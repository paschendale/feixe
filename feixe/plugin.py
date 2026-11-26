"""Ponto de entrada do plugin: barra do Feixe, servidor local, estado online/offline e ponte com o QGIS."""

from __future__ import annotations

import contextlib
import json
import os
import threading

from qgis.core import Qgis, QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsProject, QgsRectangle
from qgis.PyQt.QtCore import QObject, QTimer, QUrl, pyqtSignal
from qgis.PyQt.QtGui import QDesktopServices
from qgis.PyQt.QtWidgets import QLabel, QMessageBox

from .core import ambiente as ambmod
from .core import camadas, config, db, dispatch, edicao, log
from .core.dados import ErroDados
from .core.dados.local import cargas as lc
from .core.dados.local import cq as lq
from .core.dados.local import grupos as lgrupos
from .core.versao import raiz_plugin, versao_plugin
from .server.api import Contexto, ErroApi, criar_roteador
from .server.http import ServidorLocal
from .server.rotas import camadas as rotas_camadas
from .server.rotas import cargas as rotas_cargas
from .server.rotas import cq as rotas_cq
from .server.sse import Broker
from .sync import workspace as wsmod
from .sync.sincronizar import Sincronizacao, aviso_de_rede, hora_local
from .sync.trabalhador import Trabalhador
from .ui import regras
from .ui.barra import BarraFeixe, DialogoCredenciais, pedir_anotacao, pedir_observacao
from .ui.ferramentas import FerramentaFolha, FerramentaPonto, SemSelecao, selecao_wkt


class _Sinais(QObject):
    estado_mudou = pyqtSignal(dict)
    sincronizacao_mudou = pyqtSignal(dict)


class FeixePlugin:
    def __init__(self, iface):
        self.iface = iface
        self.amb = None
        self.erro_ambiente = None
        try:
            self.amb = ambmod.carregar()
        except ambmod.AmbienteInvalido as e:
            self.erro_ambiente = str(e)
        self.servidor = None
        self.ctx = None
        self.broker = Broker()
        # Ações que as rotas pedem ao QGIS, por nome; cada item da fase B registra as suas. Rodam na thread principal.
        self.acoes_qgis = {
            "montar_camadas": self._montar_no_qgis,
            "focar_carga": self.focar_carga,
            "ferramenta_folhas": self.ligar_ferramenta_folhas,
            "marcar_folhas": self.marcar_folhas,
            "fim_folhas": self.fim_folhas,
            "selecao_cargas": camadas.cargas_selecionadas,
            "cargas_geradas": self.cargas_geradas,
            "selecao_wkt": self.selecao_wkt,
            "cargas_mudaram": self.cargas_mudaram,
            "focar_amostra": self.focar_amostra,
            "focar_ocorrencia": self.focar_ocorrencia,
        }
        self.barra = None
        self.rotulo_status = None
        self.ferramenta_folha = None
        self.ferramenta_ponto = None  # Registrar ocorrência (D3c)
        # Diálogos mínimos do CQ, trocáveis nos testes (headless não abre diálogo).
        self.pedir_observacao = lambda atual="": pedir_observacao(self.iface.mainWindow(), atual)
        self.pedir_anotacao = lambda elemento="", folha="": pedir_anotacao(self.iface.mainWindow(), elemento, folha)
        self._cq = None  # último estado do CQ visto pela barra (amostras, pendentes, ciência)
        self._malha = None  # {no_feixe, escolhidas} da malha de escolher folhas, enquanto ela está no mapa
        # Cargas puladas, por passagem (id_lote_etapa), na ordem em que foram puladas. Só na memória (D-102): voltam
        # quando o QGIS reabre ou quando acabam as não puladas da folha.
        self.puladas = {}
        self._passagem_atual = (None, None)  # (id_lote_etapa, id_lote) da carga atual
        self.sinais = _Sinais()
        self.estado = {"online": False, "usuario": None, "detalhe": "não verificado"}
        # Sincronização (C2, C3): push e pull do workspace da conta. A execução lê e grava no workspace, e uma thread
        # de segundo plano (`Trabalhador`) sincroniza depois de cada escrita (com debounce), a cada minuto (o QTimer
        # de rede a acorda) e no primeiro uso. O resultado volta à barra pela thread principal, via sinal, e ao painel
        # pelo SSE.
        self._ws = None
        self._ws_trava = threading.RLock()
        self.sinc = Sincronizacao(
            abrir_workspace=self.workspace,
            remota=lambda: db.transacao(self.amb, timeout_conexao=5),
            alcancavel=lambda: db.alcancavel(self.amb),
            ao_terminar=self._sincronizacao_terminou,
            ao_comecar=lambda est: self.broker.publicar("sincronizacao", est),
        )
        self.trabalhador = Trabalhador(self._sincronizar_fundo)
        self.sincronizacao = {}
        self._rede = None  # última notícia de online/offline já avisada (C4): avisa só na troca
        # Camadas Minhas cargas do workspace com a edição ligada à outbox (C4): id -> (camada, funções ligadas).
        self._edicao = {}
        self._timer = QTimer()
        self._timer.setInterval(60_000)
        self._timer.timeout.connect(self.verificar_rede)

    # --- ciclo de vida -------------------------------------------------------------------------
    def initGui(self):  # noqa: N802
        if self.amb is None:
            log.erro(self.erro_ambiente)
            self.iface.messageBar().pushMessage("Feixe", self.erro_ambiente, Qgis.Critical, 0)
            return
        dispatch.iniciar()
        self.barra = BarraFeixe(self.amb, self.iface.mainWindow())
        self.barra.abrir_painel.connect(self.abrir_painel)
        self.barra.conta.connect(self.pedir_credenciais)
        self.barra.camadas.connect(self.montar_camadas)
        self.barra.modo.connect(self.trocar_modo)
        self.barra.sincronizar.connect(self.sincronizar_agora)
        self.barra.proxima.connect(self.proxima_carga)
        self.barra.pular.connect(self.pular_carga)
        self.barra.concluir.connect(self.concluir_carga)
        self.barra.proxima_amostra.connect(self.proxima_amostra)
        self.barra.conforme.connect(lambda: self.avaliar_amostra(None, 1))
        self.barra.nao_conforme.connect(lambda: self.nao_conforme(None))
        self.barra.ocorrencia.connect(self.ligar_ferramenta_ocorrencia)
        self.barra.ciente.connect(lambda: self.ciente(None))
        self.barra.proxima_ocorrencia.connect(self.proxima_ocorrencia)
        self.barra.tratada.connect(lambda: self.tratar(None, True))
        self.iface.addToolBar(self.barra)
        self.barra.show()  # se a pessoa escondeu a barra, abrir o QGIS de novo a traz de volta
        # Atalhos configuráveis em Configurações > Atalhos de teclado (o QGIS aplica o que a pessoa salvou).
        for acao in self.barra.todas_acoes():
            self.iface.registerMainWindowAction(acao, self.barra.ATALHOS.get(acao.objectName()[len("feixe_") :], ""))
            self.iface.addPluginToMenu("&Feixe", acao)
        # Texto do Feixe na barra de status do QGIS (no protótipo: "Feixe · 2534-1 · 35/93" com a carga atual).
        self.rotulo_status = QLabel("Feixe")
        self.iface.statusBarIface().addPermanentWidget(self.rotulo_status, 0)
        self.sinais.estado_mudou.connect(self._aplicar_estado)
        self.sinais.sincronizacao_mudou.connect(self._aplicar_sincronizacao)
        # Edição pela tabela de atributos e pelo formulário (C4): toda camada Minhas cargas do workspace que entra no
        # projeto (ao montar, ou ao abrir um projeto salvo com o grupo Feixe) passa a gravar pela outbox.
        QgsProject.instance().layersAdded.connect(self._ligar_edicao)
        self._ligar_edicao(list(QgsProject.instance().mapLayers().values()))
        # A barra do avaliador acompanha o grupo Controle de qualidade: ligar e desligar na árvore, tirar o grupo ou as
        # camadas, e abrir, criar ou fechar projeto (que não emitem visibilityChanged).
        for sinal in self._sinais_da_barra():
            sinal.connect(self._mostrar_barra_cq_depois)
        self._abrir_workspace_gravado()
        self.iniciar_servidor()
        self._atualizar_cq()  # as ações do CQ na barra, pelo workspace gravado (offline também)
        self.trabalhador.iniciar()
        self.verificar_rede()
        self._timer.start()
        if config.credenciais(self.amb) is None:
            QTimer.singleShot(500, self.pedir_credenciais)  # primeiro uso: pede usuário e senha

    def unload(self):
        self._timer.stop()
        with contextlib.suppress(TypeError):  # o initGui parou antes de ligar (ambiente inválido)
            QgsProject.instance().layersAdded.disconnect(self._ligar_edicao)
        for sinal in self._sinais_da_barra():
            with contextlib.suppress(TypeError):
                sinal.disconnect(self._mostrar_barra_cq_depois)
        self._desligar_edicao()
        self.trabalhador.parar()
        self.fim_folhas()
        if self.ferramenta_ponto is not None and self.iface.mapCanvas().mapTool() is self.ferramenta_ponto:
            self.iface.actionPan().trigger()
        if self.servidor:
            self.servidor.parar()
            self.servidor = None
        db.esquecer()  # fecha as conexões guardadas no pool
        self._fechar_workspace()
        if self.barra:
            for acao in self.barra.todas_acoes():
                self.iface.unregisterMainWindowAction(acao)
                self.iface.removePluginMenu("&Feixe", acao)
            self.iface.mainWindow().removeToolBar(self.barra)
            self.barra.deleteLater()
            self.barra = None
        if self.rotulo_status:
            self.iface.statusBarIface().removeWidget(self.rotulo_status)
            self.rotulo_status.deleteLater()
            self.rotulo_status = None
        dispatch.encerrar()

    def _montar_no_qgis(self, eu, responsaveis, supervisao, execucao, gpkg):
        """A montagem pedida pela barra ou pelo painel: o grupo Feixe e, junto, as ações do CQ na barra."""
        r = camadas.montar(self.amb, config.authcfg_id(self.amb), eu, responsaveis, supervisao, execucao, gpkg)
        self._atualizar_cq()
        return r

    # --- servidor local ------------------------------------------------------------------------
    def iniciar_servidor(self):
        ctx = Contexto(
            status=self.status_api,
            consultar=self.consultar,
            zoom_para=lambda xmin, ymin, xmax, ymax, srid: dispatch.na_thread_principal(
                self.zoom_para, xmin, ymin, xmax, ymax, srid
            ),
            transacao=lambda: db.transacao(self.amb),
            sincronizar=self.sinc.sincronizar,
            publicar=self.broker.publicar,
            qgis=self.acao_qgis,
            workspace=self.workspace,
            acordar=self.trabalhador.acordar,
            online=lambda: self.sinc.online,
            eu_guardado=self._eu_guardado,
            guardar_eu=self._guardar_eu,
        )
        self.ctx = ctx
        pasta = os.path.join(raiz_plugin(), "web", "dist")
        self.servidor = ServidorLocal(criar_roteador(ctx), self.broker, pasta).iniciar()
        log.info(f"servidor local em {self.servidor.origem}")

    def abrir_painel(self):
        if config.credenciais(self.amb) is None:
            self.pedir_credenciais()
            if config.credenciais(self.amb) is None:
                return
        if not self.servidor:
            self.iniciar_servidor()
        QDesktopServices.openUrl(QUrl(self.servidor.url_abertura))

    # --- credenciais ---------------------------------------------------------------------------
    def pedir_credenciais(self):
        atual = config.credenciais(self.amb)
        dlg = DialogoCredenciais(
            self.amb,
            atual[0] if atual else "",
            testar=lambda u, s: db.testar(self.amb, u, s),
            parent=self.iface.mainWindow(),
        )
        if not dlg.exec_():
            return
        usuario, senha = dlg.valores()
        try:
            config.salvar_credenciais(self.amb, usuario, senha)
            db.esquecer()
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self.iface.mainWindow(), "Feixe", f"Não foi possível guardar a credencial:\n{e}")
            return
        if self.ctx:
            self.ctx.esquecer_eu()
        self._fechar_workspace()  # outra conta, outro workspace
        self.sinc.marcar_rede(True)  # a credencial acabou de ser testada contra a CCAR
        self.trabalhador.acordar(0)
        r = dlg.resultado_teste or {}
        schema = "sim" if r.get("schema_feixe") else "não"
        self._publicar_estado(
            {
                "online": True,
                "usuario": r.get("usuario", usuario),
                "detalhe": f"{r.get('usuario', usuario)}@{r.get('banco', self.amb.banco)} · schema feixe: {schema}",
            }
        )
        self.iface.messageBar().pushMessage("Feixe", f"Conectado como {usuario}.", Qgis.Success, 4)

    # --- banco e rede --------------------------------------------------------------------------
    def consultar(self, sql, params=None):
        return db.consultar(self.amb, sql, params)

    def status_api(self):
        cred = config.credenciais(self.amb)
        return {
            "ambiente": self.amb.nome,
            "rotulo_ambiente": self.amb.rotulo,
            "cor_ambiente": self.amb.cor,
            "banco": self.amb.descricao_banco,
            "credencial": bool(cred),
            "versao_plugin": versao_plugin(),
            "qgis": Qgis.QGIS_VERSION,
            "clientes_sse": self.broker.conectados,
            **self.estado,
            "sincronizacao": self.sinc.estado(),
        }

    # --- workspace e sincronização (C2) ----------------------------------------------------------
    def workspace(self):
        """O workspace da conta conectada, aberto uma vez. Se o arquivo já existe, abre com a UF gravada nele (sem
        banco: a execução funciona offline); senão, com a UF da lotação no SGBC (precisa da CCAR, uma vez). Lotação
        trocada no SGBC recria o workspace na próxima vez que a identidade vier da CCAR (`_guardar_eu`)."""
        cred = config.credenciais(self.amb)
        if not cred:
            raise RuntimeError("usuário e senha ainda não configurados")
        with self._ws_trava:  # as threads do servidor HTTP e a da sincronização pedem ao mesmo tempo
            if self._ws is not None and self._ws.usuario == cred[0]:
                return self._ws
            self._fechar_workspace()
            uf = wsmod.uf_gravada(wsmod.caminho(self.amb.nome, cred[0]))
            if not uf:
                uf = (self.ctx.eu() if self.ctx else {}).get("uf")  # pode abrir o workspace (_guardar_eu)
                if self._ws is not None and self._ws.usuario == cred[0]:
                    return self._ws
            if not uf:
                raise RuntimeError("a conta não tem UF de lotação no SGBC: sem ela não há escopo para sincronizar")
            self._ws = wsmod.Workspace.abrir(self.amb.nome, cred[0], uf)
            self.sinc.usar(self._ws)
            return self._ws

    def _guardar_eu(self, eu):
        """A identidade veio da CCAR: fica no workspace (meta), para a execução abrir offline com os mesmos papéis.
        UF diferente da do workspace (lotação mudou) reabre, e o workspace é recriado levando a outbox (D-114)."""
        cred = config.credenciais(self.amb)
        if not cred or eu.get("conta") != cred[0] or not eu.get("uf"):
            return
        with self._ws_trava:
            if self._ws is not None and (self._ws.uf != eu["uf"] or self._ws.usuario != cred[0]):
                self._fechar_workspace()
            if self._ws is None:
                self._ws = wsmod.Workspace.abrir(self.amb.nome, cred[0], eu["uf"])
                self.sinc.usar(self._ws)
            with self._ws.transacao() as ex:
                ex.definir_meta("eu", json.dumps(eu, ensure_ascii=False, default=str))

    def _eu_guardado(self):
        """A identidade guardada no workspace da conta. Só abre um workspace que já existe (pela UF gravada): sem ele
        não há o que ler, e ir ao banco aqui seria pedir à CCAR que não respondeu."""
        cred = config.credenciais(self.amb)
        if not cred:
            return None
        if self._ws is None and not wsmod.uf_gravada(wsmod.caminho(self.amb.nome, cred[0])):
            return None
        try:
            ws = self.workspace()
        except Exception:  # noqa: BLE001 - sem workspace, sem identidade guardada
            return None
        with ws.leitura() as ex:
            texto = ex.meta("eu")
        return json.loads(texto) if texto else None

    def _abrir_workspace_gravado(self):
        """Ao abrir o QGIS: se a conta já tem workspace, abre com a UF gravada nele, sem ir ao banco, para o estado
        (pendências, última sincronização) aparecer mesmo offline."""
        cred = config.credenciais(self.amb)
        if not cred:
            return
        caminho = wsmod.caminho(self.amb.nome, cred[0])
        uf = wsmod.uf_gravada(caminho)
        if not uf:
            return
        try:
            self._ws = wsmod.Workspace.abrir(self.amb.nome, cred[0], uf)
            self.sinc.usar(self._ws)
        except Exception as e:  # noqa: BLE001
            log.erro(f"workspace: {e}")

    def _fechar_workspace(self):
        self.sinc.usar(None)
        if self._ws is not None:
            self._ws.fechar()
            self._ws = None

    def sincronizar_agora(self):
        """Botão da barra: a thread de segundo plano sincroniza já; o resultado volta pelo sinal."""
        if config.credenciais(self.amb) is None:
            self.pedir_credenciais()
            return
        if not self.servidor:
            self.iniciar_servidor()
        self.trabalhador.acordar(0)

    def _sincronizar_fundo(self):
        """Na thread do `Trabalhador`: sem conta configurada, nada a fazer."""
        if config.credenciais(self.amb) is None:
            return {"estado": "sem_conta"}
        r = self.sinc.sincronizar()
        if r["estado"] == "erro":
            log.erro(f"sincronizar: {r.get('mensagem')}")
        return r

    def _sincronizacao_terminou(self, est):
        """Na thread que sincronizou: o painel fica sabendo pelo SSE e a barra pela thread principal. Se algo mudou
        (o push aplicou, o pull trouxe linhas), as telas recarregam pelos eventos de sempre."""
        self.broker.publicar("sincronizacao", est)
        if est.get("mudou"):
            self.broker.publicar("carga", {"sincronizacao": True})
            self.broker.publicar("lote", {"sincronizacao": True})
            self.broker.publicar("cq", {"sincronizacao": True})
        self.sinais.sincronizacao_mudou.emit(est)

    def _aplicar_sincronizacao(self, est):
        self.sincronizacao = est
        if est.get("online") is not None:
            self.estado["online"] = est["online"]
        self._publicar_estado({})
        self._avisar_rede(est.get("online"))
        if est.get("mudou"):
            # O push levou e o pull trouxe: as camadas do workspace mostram o que veio da CCAR (outra pessoa, o
            # supervisor, a recusa que desfez o local) e as da supervisão, o que o push gravou lá.
            camadas.recarregar_cargas()
            self._atualizar_cq()
        for aviso in est.get("avisos") or []:
            self.iface.messageBar().pushMessage("Feixe", aviso, Qgis.Warning, 10)

    def _avisar_rede(self, online):
        """Na troca de online para offline e de volta, um aviso só, na barra de mensagens e no painel (sem repetir a
        cada minuto do QTimer nem a cada sincronização)."""
        if online is None:
            return
        aviso = aviso_de_rede(self._rede, online, self.sincronizacao.get("pendentes") or 0)
        self._rede = online
        if aviso is None:
            return
        self.iface.messageBar().pushMessage("Feixe", aviso, Qgis.Info if online else Qgis.Warning, 6 if online else 12)
        self.broker.publicar("rede", {"online": online, "texto": aviso})

    def verificar_rede(self):
        """Checagem barata (TCP) em thread própria; o resultado volta pela thread principal via sinal."""

        def rodar():
            ok = db.alcancavel(self.amb)
            detalhe = f"{self.amb.descricao_banco} {'responde' if ok else 'não responde'}"
            self.sinc.marcar_rede(ok)
            self.sinais.estado_mudou.emit({"online": ok, "detalhe": detalhe})
            self.sinais.sincronizacao_mudou.emit(self.sinc.estado())
            # O periódico: a cada minuto (e ao abrir o QGIS) a thread de segundo plano sincroniza. Offline, ela só
            # testa a rede e volta; as pendências esperam.
            self.trabalhador.acordar(0)

        threading.Thread(target=rodar, name="feixe-rede", daemon=True).start()

    def _publicar_estado(self, novo: dict):
        self.estado.update(novo)
        if self.barra:
            cred = config.credenciais(self.amb)
            estado = "sem_conta" if not cred else ("conectado" if self.estado["online"] else "fora")
            self.barra.mostrar_sincronizacao(self._texto_sincronizacao())
            pendentes = self.sincronizacao.get("pendentes") or 0
            self.barra.mostrar_estado(estado, cred[0] if cred else "", pendentes=pendentes)
        self.broker.publicar("estado", self.estado)

    def _texto_sincronizacao(self) -> str:
        est = self.sincronizacao or {}
        if est.get("em_andamento"):
            return "Sincronizando…"
        hora = hora_local(est.get("ultima_sincronizacao"))
        texto = f"Sincronizado às {hora}" if hora else "Ainda não sincronizado"
        if est.get("ultimo_estado") == "offline":
            texto += " · a última tentativa ficou sem a CCAR"
        elif est.get("ultimo_estado") == "erro":
            texto += f" · a última tentativa falhou: {est.get('mensagem')}"
        return texto

    def _aplicar_estado(self, novo: dict):
        self._publicar_estado(novo)
        self._avisar_rede(novo.get("online"))

    # --- barra: próxima carga e concluir carga (B2) ---------------------------------------------
    def _pronto(self) -> bool:
        if config.credenciais(self.amb) is None:
            self.pedir_credenciais()
            if config.credenciais(self.amb) is None:
                return False
        if not self.servidor:
            self.iniciar_servidor()
        return True

    def _executar(self, fn, *args, falhou=None):
        """Roda uma ação da barra pelo mesmo caminho da API; recusa vira aviso na barra de mensagens (e um item em
        `falhou`, para quem precisa separar "deu errado" de "voltou nada")."""
        try:
            return fn(self.ctx, *args)
        except (ErroApi, ErroDados) as e:
            self.iface.messageBar().pushMessage("Feixe", e.mensagem, Qgis.Warning, 6)
        except Exception as e:  # noqa: BLE001
            log.erro(f"{getattr(fn, '__name__', fn)}: {e}")
            self.iface.messageBar().pushMessage("Feixe", f"Não deu certo: {e}", Qgis.Critical, 8)
        if falhou is not None:
            falhou.append(True)
        return None

    def _para_execucao(self) -> bool:
        """Garante as camadas e o modo executar: quem pede uma carga está executando."""
        if not self._pronto():
            return False
        if camadas.camada_minhas() is None and self.montar_camadas() is None:
            return False
        if camadas.modo_atual() != "execucao":
            self.trocar_modo("execucao")
        return True

    def _proxima(self, referencia, id_lote=None):
        """Próxima carga, deixando de fora as puladas. Se acabaram as não puladas da folha atual, as puladas dela
        voltam à rotação antes de passar para outra folha."""

        def excluir():
            # As amostras de CQ andam por "Próxima amostra", e a carga da folha na correção de inspeção, por
            # "Próxima ocorrência" (D5): nenhuma das duas por "Próxima carga".
            return [i for ids in self.puladas.values() for i in ids] + self._ler(lgrupos.fora_da_producao, [])

        le, lote = self._passagem_atual
        if id_lote is None and self.puladas.get(le):
            r = self._executar(rotas_cargas.proxima, referencia, excluir(), lote)
            if r is None or r["carga"] is not None:
                return r
            self.puladas.pop(le)
        return self._executar(rotas_cargas.proxima, referencia, excluir(), id_lote)

    def proxima_carga(self):
        if not self._para_execucao():
            return
        r = self._proxima(camadas.carga_selecionada() or camadas.carga_atual())
        if r is not None and r["carga"] is None:
            self.iface.messageBar().pushMessage("Feixe", "Você não tem carga pendente.", Qgis.Info, 5)

    def concluir_carga(self):
        """Conclui a carga selecionada em Minhas cargas (escolha à mão) ou, sem seleção, a carga atual, e passa para a
        próxima, como no protótipo."""
        if not self._pronto():
            return
        id_carga = camadas.carga_selecionada() or camadas.carga_atual()
        if id_carga is None:
            self.iface.messageBar().pushMessage(
                "Feixe", "Nenhuma carga atual: use Próxima carga ou selecione uma em Minhas cargas.", Qgis.Info, 6
            )
            return
        r = self._executar(rotas_cargas.concluir, id_carga)
        if r is None:
            return
        for ids in self.puladas.values():
            if id_carga in ids:
                ids.remove(id_carga)
        p = r["progresso"]
        f = r.get("fila")
        if f:
            self.iface.messageBar().pushMessage(
                "Feixe",
                f"Folha {p['folha_revisao']} concluída. A próxima da sua fila é a {f['folha_revisao']} "
                f"({f['atribuidas']} cargas), já atribuída a você.",
                Qgis.Success,
                8,
            )
        else:
            self.iface.messageBar().pushMessage(
                "Feixe", f"Carga concluída · {p['folha_revisao']} · {p['concluidas']}/{p['total']}", Qgis.Success, 3
            )
        self._proxima(id_carga)

    def pular_carga(self, id_carga=None):
        """Deixa a carga para depois: ela volta no fim da fila da folha (ou quando o QGIS reabre). Só na memória."""
        if not self._para_execucao():
            return
        id_carga = id_carga or camadas.carga_selecionada() or camadas.carga_atual()
        if id_carga is None:
            self.iface.messageBar().pushMessage(
                "Feixe", "Nenhuma carga atual para pular: use Próxima carga.", Qgis.Info, 5
            )
            return
        falhou = []
        carga = self._executar(rotas_cargas.uma, int(id_carga), falhou=falhou)
        if falhou:
            return
        if carga is None or carga["concluido"]:
            self.iface.messageBar().pushMessage("Feixe", "Só dá para pular carga pendente.", Qgis.Info, 5)
            return
        fila = self.puladas.setdefault(carga["id_lote_etapa"], [])
        if carga["id"] not in fila:
            fila.append(carga["id"])
        self._passagem_atual = (carga["id_lote_etapa"], carga["id_lote"])
        r = self._proxima(carga["id"])
        if r is not None and r["carga"] is None:
            fila.remove(carga["id"])
            self.iface.messageBar().pushMessage(
                "Feixe", "Esta é a única carga pendente que você tem: não há para onde pular.", Qgis.Info, 5
            )
        elif r is not None:
            self.iface.messageBar().pushMessage(
                "Feixe", f"Carga pulada: volta depois das outras da {carga['folha_revisao']}.", Qgis.Info, 4
            )

    # --- ações das camadas (formulário, identificar, clique direito) ----------------------------------------------
    def trabalhar_em(self, id_carga):
        if self._para_execucao():
            self._executar(rotas_cargas.focar, int(id_carga))

    def proxima_na_folha(self, id_lote):
        if not self._para_execucao():
            return
        r = self._proxima(camadas.carga_atual(), int(id_lote))
        if r is not None and r["carga"] is None:
            self.iface.messageBar().pushMessage("Feixe", "Você não tem carga pendente nesta folha.", Qgis.Info, 5)

    def abrir_folha(self, id_lote):
        """Abre o painel na gaveta da folha (ações de fluxo, histórico, atribuir)."""
        if not self._pronto():
            return
        QDesktopServices.openUrl(QUrl(f"{self.servidor.url_abertura}#/supervisao/folhas/{int(id_lote)}"))

    def focar_carga(self, carga, progresso):
        """Faz dela a carga atual (contorno magenta), o mapa vai até ela, na extensão dela (D-148), e pisca."""
        if camadas.camada_com_amostra(carga["id"]) is not None:
            # Uma carga de CQ (o painel pede "focar_carga" também para a amostra): vira a amostra atual.
            self.focar_amostra(carga, progresso)
            return
        camadas.definir_atual(carga["id"])
        self._passagem_atual = (carga.get("id_lote_etapa"), carga.get("id_lote"))
        self._enquadrar(carga, camadas.camada_com_carga(carga["id"]))
        self.mostrar_progresso(progresso, False)

    def _enquadrar(self, carga, camada):
        """Zoom na extensão da carga (ou da amostra), com uma folga de 10% em volta, e pisca (D-148; antes, no D-102,
        o mapa só centralizava, sem mudar a escala)."""
        canvas = self.iface.mapCanvas()
        destino = canvas.mapSettings().destinationCrs()
        ret = QgsRectangle(carga["xmin"], carga["ymin"], carga["xmax"], carga["ymax"])
        origem = QgsCoordinateReferenceSystem("EPSG:4674")
        if origem != destino:
            ret = QgsCoordinateTransform(origem, destino, QgsProject.instance()).transformBoundingBox(ret)
        ret.scale(1.1)
        canvas.setExtent(ret)
        canvas.refresh()
        if camada is not None:
            f = next(camada.getFeatures(f'"id" = {int(carga["id"])}'), None)
            if f is not None:
                canvas.flashFeatureIds(camada, [f.id()])

    def cargas_mudaram(self, progresso, so_workspace=False):
        """Uma rota mudou cargas: na execução (`so_workspace`), as camadas do workspace mostram já, online ou offline;
        na supervisão (na CCAR), todas releem."""
        camadas.recarregar_cargas(so_workspace)
        self.mostrar_progresso(progresso)
        self._atualizar_cq()

    # --- CQ: amostras, ocorrências e ciência (D3c) ----------------------------------------------------------------
    # Tudo pelo workspace (D-140), com as funções de `core/dados/local/cq.py` e as rotas de `server/rotas/cq.py`: a
    # barra e as ações das camadas fazem o mesmo que o painel. Cada escrita relê só as camadas do workspace e acorda a
    # sincronização. Na thread principal (a barra, as ações e o `ctx.qgis` chegam todos por ela).
    def _ler(self, fn, padrao=None, *args):
        """Leitura do workspace já aberto (sem abrir nada nem ir à CCAR: serve à barra, a qualquer momento)."""
        if self._ws is None:
            return padrao
        try:
            with self._ws.leitura() as ex:
                return fn(ex, *args)
        except Exception as e:  # noqa: BLE001 - o workspace ainda não preparado não impede a barra
            log.erro(f"{getattr(fn, '__name__', fn)}: {e}")
            return padrao

    def _atualizar_cq(self):
        """A barra mostra as ações do CQ só para quem tem o que fazer; ocorrências para ciência que chegaram (pela
        sincronização) ganham a camada, ligada, e um aviso que diz o que fazer."""
        est = self._ler(lgrupos.estado_cq, {}) or {}
        antes, self._cq = self._cq, est
        self._mostrar_barra_cq()
        if est.get("correcao") and antes is not None and not antes.get("correcao"):
            self.iface.messageBar().pushMessage(
                "Feixe",
                f"Chegou uma folha para a correção de inspeção ({est.get('correcao_pendentes') or 0} ocorrências por "
                "tratar). Use Próxima ocorrência na barra do Feixe.",
                Qgis.Info,
                10,
            )
        n = est.get("ciencia") or 0
        if not n:
            return
        nova = camadas.garantir_ciencia()
        if not nova and not (antes or {}).get("ciencia"):
            camadas.ligar(camadas.camada_ciencia())
        if antes is not None and n > (antes.get("ciencia") or 0):
            self.iface.messageBar().pushMessage(
                "Feixe",
                f"{'Chegou 1 ocorrência' if n == 1 else f'Há {n} ocorrências'} do CQ numa carga sua, na camada "
                "Ocorrências para ciência. Leia e marque Ciente (barra do Feixe).",
                Qgis.Info,
                10,
            )

    @staticmethod
    def _sinais_da_barra():
        projeto = QgsProject.instance()
        raiz = projeto.layerTreeRoot()
        return [raiz.visibilityChanged, raiz.addedChildren, raiz.removedChildren, projeto.cleared,
                projeto.readProject, projeto.layersRemoved]  # fmt: skip

    def _mostrar_barra_cq_depois(self, *_):
        """Depois que a árvore termina de mudar (a remoção de um grupo emite vários sinais seguidos)."""
        QTimer.singleShot(0, self._mostrar_barra_cq)

    def _mostrar_barra_cq(self, *_):
        """As ações do avaliador aparecem só com o grupo Controle de qualidade ligado (modo Avaliar, D-148): ao trocar
        o modo pela barra e também ao ligar ou desligar o grupo à mão na árvore de camadas."""
        if self.barra:
            modo = camadas.modo_atual()
            self.barra.mostrar_cq(self._cq or {}, modo)
            self.barra.mostrar_modo(modo)

    def _para_cq(self) -> bool:
        """Garante as camadas e o modo avaliar para quem avalia; sem amostras, diz e não segue."""
        if not self._pronto():
            return False
        if not camadas.camadas_amostras() and self.montar_camadas() is None:
            return False
        if not camadas.camadas_amostras():
            self.iface.messageBar().pushMessage(
                "Feixe", "Você não tem amostras de CQ em passagens abertas.", Qgis.Info, 5
            )
            return False
        if camadas.modo_atual() != "cq":
            self.trocar_modo("cq")
        return True

    @staticmethod
    def _proxima_amostra(ctx, referencia):
        ctx.exigir_pronto()
        with ctx.leitura() as ex:
            r = lq.proxima(ex, referencia)
            progresso = lc.progresso(ex, r["carga"]["id_lote_etapa"]) if r else None
        if r:
            ctx.qgis("focar_amostra", r["carga"], progresso)
        return {"carga": r["carga"] if r else None, "amostra": r["amostra"] if r else None, "progresso": progresso}

    def proxima_amostra(self):
        if not self._para_cq():
            return None
        r = self._executar(self._proxima_amostra, camadas.amostra_selecionada() or camadas.amostra_atual())
        if r is not None and r["carga"] is None:
            self.iface.messageBar().pushMessage(
                "Feixe", f"Nenhuma amostra pendente. {regras.FIM_DAS_AMOSTRAS}", Qgis.Info, 8
            )
        return r

    def focar_amostra(self, carga, progresso):
        """Faz dela a amostra atual (contorno magenta em Amostras, com o elemento no rótulo), zoom nela e pisca."""
        camadas.definir_amostra_atual(carga["id"])
        camada = camadas.camada_com_amostra(carga["id"])
        camadas.ligar_elemento(camada)
        self._enquadrar(carga, camada)
        self.mostrar_progresso(progresso, True)

    def trabalhar_na_amostra(self, id_carga):
        """Ação da camada Amostras: esta vira a amostra atual."""
        if not self._para_cq():
            return
        r = self._executar(rotas_cargas.uma, int(id_carga))
        if r is not None:
            progresso = self._ler(lc.progresso, None, r["id_lote_etapa"])
            self.focar_amostra(r, progresso)

    @staticmethod
    def _avaliar(ctx, id_carga, status, observacao):
        with ctx.leitura() as ex:
            a = lq.amostra_da_carga(ex, id_carga)
        if a is None:
            raise ErroDados("esta carga não é uma amostra de CQ", 404)
        return rotas_cq.avaliar(ctx, a["id"], status, observacao)

    def avaliar_amostra(self, id_carga=None, status=1, observacao=lq._NADA):
        """Conforme e Não conforme (barra e ação da camada): avalia a amostra atual, ou a selecionada, ou a da ação, e
        já vai para a próxima (D-136); na última, diz que acabou e o que vem depois."""
        if not self._para_cq():
            return None
        id_carga = id_carga or camadas.amostra_selecionada() or camadas.amostra_atual()
        if id_carga is None:
            self.iface.messageBar().pushMessage(
                "Feixe", "Nenhuma amostra atual: use Próxima amostra ou selecione uma em Amostras.", Qgis.Info, 6
            )
            return None
        r = self._executar(self._avaliar, int(id_carga), int(status), observacao)
        if r is None:
            return None
        self.iface.messageBar().pushMessage("Feixe", regras.mensagem_avaliada(r), Qgis.Success, 6)
        prox = r.get("proxima")
        if prox and prox.get("carga"):
            self.focar_amostra(prox["carga"], self._ler(lc.progresso, None, prox["carga"]["id_lote_etapa"]))
        else:
            camadas.definir_amostra_atual(None)
            self.mostrar_progresso(r.get("progresso"), True)
        return r

    def nao_conforme(self, id_carga=None):
        """Não conforme com uma observação curta opcional (diálogo mínimo; cancelar não avalia)."""
        if not self._para_cq():
            return None
        id_carga = id_carga or camadas.amostra_selecionada() or camadas.amostra_atual()
        atual = self._ler(lq.amostra_da_carga, None, int(id_carga)) if id_carga else None
        obs = self.pedir_observacao((atual or {}).get("observacao") or "")
        if obs is None:
            return None
        return self.avaliar_amostra(id_carga, 0, obs)

    def ligar_ferramenta_ocorrencia(self):
        """Barra: liga (ou desliga, se já ligada) a ferramenta de ponto para registrar ocorrências."""
        canvas = self.iface.mapCanvas()
        if self.ferramenta_ponto is not None and canvas.mapTool() is self.ferramenta_ponto:
            self.iface.actionPan().trigger()
            return
        if not self._para_cq():
            if self.barra:
                self.barra.acao_ocorrencia.setChecked(False)
            return
        if self.ferramenta_ponto is None:
            self.ferramenta_ponto = FerramentaPonto(
                canvas, self.ocorrencia_no_ponto, lambda: self.iface.actionPan().trigger()
            )
            if self.barra:
                self.ferramenta_ponto.setAction(self.barra.acao_ocorrencia)
        canvas.setMapTool(self.ferramenta_ponto)
        self.iface.messageBar().pushMessage(
            "Feixe",
            "Clique dentro da amostra para registrar a ocorrência no ponto. Arrastar move o mapa; Esc desliga.",
            Qgis.Info,
            6,
        )

    def ocorrencia_no_ponto(self, x, y):
        """Clique da ferramenta (SIRGAS 2000 geográfico): o ponto vai na amostra atual, se cai nela, ou na amostra sob
        o clique; fora de todas as minhas, recusa com o motivo. A anotação vem de um diálogo mínimo."""
        id_carga = camadas.amostra_no_ponto(x, y)
        if id_carga is None:
            self.iface.messageBar().pushMessage("Feixe", regras.FORA_DAS_AMOSTRAS, Qgis.Warning, 8)
            return None
        a = self._ler(lq.amostra_da_carga, None, id_carga) or {}
        anotacao = self.pedir_anotacao(a.get("elemento") or "", a.get("folha_revisao") or "")
        if anotacao is None:
            return None
        r = self._executar(rotas_cq.registrar_ocorrencia, x, y, id_carga, anotacao or None)
        if r is None:
            return None
        camadas.definir_amostra_atual(id_carga)
        self.iface.messageBar().pushMessage("Feixe", regras.mensagem_ocorrencia(r), Qgis.Success, 6)
        return r

    @staticmethod
    def _ciente(ctx, uuid):
        return rotas_cq.ciente(ctx, uuid)

    def ciente(self, uuid=None):
        """Ciente (barra e ação da camada) na ocorrência selecionada em Ocorrências para ciência. Sem seleção, não dá
        ciência às cegas: seleciona e mostra a primeira, para a pessoa ler e confirmar."""
        if not self._pronto():
            return None
        uuid = uuid or camadas.ocorrencia_selecionada("ocorrencias_ciencia")
        if uuid is None:
            camada = camadas.camada_ciencia()
            f = next(camada.getFeatures(), None) if camada is not None else None
            if f is None:
                self.iface.messageBar().pushMessage(
                    "Feixe", "Nenhuma ocorrência esperando a sua ciência.", Qgis.Info, 5
                )
                return None
            camada.selectByIds([f.id()])
            p = f.geometry().asPoint()
            self._enquadrar({"id": f["id"] or 0, "xmin": p.x(), "ymin": p.y(), "xmax": p.x(), "ymax": p.y()}, None)
            self.iface.mapCanvas().flashFeatureIds(camada, [f.id()])
            anotacao = f["anotacao"] if f["anotacao"] not in (None, "") else "(sem anotação)"
            self.iface.messageBar().pushMessage(
                "Feixe",
                f"Ocorrência de {f['elemento']}: {anotacao}. Leia no mapa e clique Ciente de novo para registrar.",
                Qgis.Info,
                10,
            )
            return None
        r = self._executar(self._ciente, str(uuid))
        if r is None:
            return None
        restantes = (self._cq or {}).get("ciencia") or 0
        self.iface.messageBar().pushMessage(
            "Feixe", regras.mensagem_ciente(r["ocorrencia"], restantes), Qgis.Success, 6
        )
        return r

    # --- correção de inspeção (D5) --------------------------------------------------------------------------------
    # Pelo workspace, como o CQ (D-140): quem está com a folha na correção varre as ocorrências da folha (todas as
    # revisões) e marca cada uma como tratada; a carga da folha conclui com a última e a folha vai para o supervisor.
    def _para_correcao(self) -> bool:
        """Garante as camadas da correção e o modo executar; sem folha na correção, diz e não segue."""
        if not self._pronto():
            return False
        papeis = ("correcao_pendentes", "correcao_tratadas")
        precisa = not camadas.camadas_do_papel(*papeis) and (self._cq or {}).get("correcao")
        if precisa and self.montar_camadas() is None:
            return False
        if camadas.modo_atual() not in (None, "execucao"):
            self.trocar_modo("execucao")
        if not (self._ler(lgrupos.estado_cq, {}) or {}).get("correcao"):
            self.iface.messageBar().pushMessage(
                "Feixe", "Você não está com nenhuma folha na correção de inspeção.", Qgis.Info, 5
            )
            return False
        return True

    def proxima_ocorrencia(self):
        if not self._para_correcao():
            return None
        ref = camadas.ocorrencia_selecionada("correcao_pendentes") or camadas.ocorrencia_atual()
        r = self._executar(rotas_cq.proxima_ocorrencia, ref, None)
        if r is not None and r["ocorrencia"] is None:
            self.iface.messageBar().pushMessage(
                "Feixe", f"Nenhuma ocorrência por tratar. {regras.FIM_DA_CORRECAO}", Qgis.Info, 8
            )
        return r

    def focar_ocorrencia(self, o, progresso, avisar=True):
        """Faz dela a ocorrência atual (pino maior em Ocorrências pendentes), sem mudar a escala, pisca e diz o que
        corrigir ali."""
        camadas.definir_ocorrencia_atual(o["uuid"])
        x, y = o["x"], o["y"]
        self._enquadrar({"id": 0, "xmin": x, "ymin": y, "xmax": x, "ymax": y}, None)
        camada = camadas.camada_com_ocorrencia(o["uuid"])
        if camada is not None:
            f = next(camada.getFeatures(f"\"uuid\" = '{o['uuid']}'"), None)
            if f is not None:
                self.iface.mapCanvas().flashFeatureIds(camada, [f.id()])
        self.mostrar_progresso(progresso, False)
        if avisar:
            self.iface.messageBar().pushMessage("Feixe", regras.mensagem_ocorrencia_atual(o, progresso), Qgis.Info, 8)

    def trabalhar_na_ocorrencia(self, uuid):
        """Ação da camada Ocorrências pendentes: esta vira a ocorrência atual."""
        if not self._para_correcao():
            return
        with contextlib.suppress(Exception):
            o = self._ler(lq.ocorrencia, None, str(uuid))
            if o is not None:
                self.focar_ocorrencia(o, self._ler(lq.progresso_correcao, None, o["id_lote"]))

    def tratar(self, uuid=None, tratado=True):
        """Tratada (barra e ação da camada) na ocorrência atual ou na selecionada; Desfazer tratada (ação da camada
        Ocorrências tratadas). Marcar já leva à próxima (D-136); a última diz que a folha terminou e quem decide."""
        if not self._para_correcao():
            return None
        uuid = uuid or camadas.ocorrencia_selecionada("correcao_pendentes") or camadas.ocorrencia_atual()
        if uuid is None:
            self.iface.messageBar().pushMessage(
                "Feixe", "Nenhuma ocorrência atual: use Próxima ocorrência ou selecione uma em Ocorrências pendentes.",
                Qgis.Info, 6,
            )  # fmt: skip
            return None
        r = self._executar(rotas_cq.tratar, str(uuid), bool(tratado))
        if r is None:
            return None
        self.iface.messageBar().pushMessage("Feixe", regras.mensagem_tratada(r), Qgis.Success, 8)
        prox = r.get("proxima")
        if tratado and prox:
            self.focar_ocorrencia(prox, self._ler(lq.progresso_correcao, None, prox["id_lote"]), False)
        else:
            if tratado:
                camadas.definir_ocorrencia_atual(None)
            self.mostrar_progresso(r.get("progresso"), False)
        return r

    # --- edição pela tabela de atributos e pelo formulário (C4) ---------------------------------------------------
    def _ligar_edicao(self, novas):
        for camada in novas:
            if not camadas.editavel_pelo_feixe(camada) or camada.id() in self._edicao:
                continue
            ligada = lambda *_, c=camada: self._antes_de_gravar(c)  # noqa: E731 - com ou sem o stopEditing do sinal
            # Fora da edição a camada volta a acompanhar o workspace (em edição, as recargas passam por ela).
            parou = lambda: QTimer.singleShot(0, lambda: camadas.recarregar_cargas(so_workspace=True))  # noqa: E731
            camada.beforeCommitChanges.connect(ligada)
            camada.editingStopped.connect(parou)
            id_camada = camada.id()
            camada.willBeDeleted.connect(lambda i=id_camada: self._edicao.pop(i, None))
            self._edicao[id_camada] = (camada, ligada, parou)

    def _desligar_edicao(self):
        for camada, ligada, parou in list(self._edicao.values()):
            with contextlib.suppress(TypeError, RuntimeError):  # a camada já foi apagada
                camada.beforeCommitChanges.disconnect(ligada)
                camada.editingStopped.disconnect(parou)
        self._edicao.clear()

    def _antes_de_gravar(self, camada):
        """O QGIS vai gravar a edição de Minhas cargas: a mudança sai do buffer (o OGR não grava nada) e vai pelo
        caminho da barra, com as regras e a outbox (`core/edicao.py`)."""
        if camadas.papel(camada) == "ocorrencias":
            self._antes_de_gravar_ocorrencias(camada)
            return
        desejadas, outras = edicao.ler(camada)
        if not edicao.esvaziar(camada):
            log.erro("edição de Minhas cargas: o buffer não esvaziou; o workspace vai recusar a gravação do OGR")
        if outras:
            self.iface.messageBar().pushMessage(
                "Feixe",
                "Em Minhas cargas só a situação (Concluída) muda pelo QGIS; as outras mudanças foram desfeitas.",
                Qgis.Info,
                8,
            )
        r = None
        if desejadas and self._pronto():
            r = self._executar(rotas_cargas.editar, desejadas)
        if r is not None:
            feito, avisos = rotas_cargas.mensagens_edicao(r)
            if feito:
                self.iface.messageBar().pushMessage("Feixe", " ".join(feito), Qgis.Success, 5)
            for aviso in avisos:
                self.iface.messageBar().pushMessage("Feixe", aviso, Qgis.Warning, 10)
        # Depois do commit (a camada ainda está no meio dele): as camadas do workspace mostram o que ficou valendo.
        QTimer.singleShot(0, lambda: self._depois_de_gravar(camada, r))

    @staticmethod
    def _editar_ocorrencia(ctx, uuid, anotacao):
        """Sem tocar no QGIS: a camada está no meio do commit (quem chama recarrega depois)."""
        ctx.exigir_pronto()
        with ctx.local() as ex:
            r = lq.editar(ex, uuid, anotacao)
        ctx.publicar("cq", {"ocorrencia": uuid})
        return r

    def _antes_de_gravar_ocorrencias(self, camada):
        """Ocorrências do avaliador (D3c): só a anotação muda pelo QGIS, e vai por `lq.editar` (só a própria, com a
        passagem de CQ aberta); o resto sai do buffer com aviso."""
        desejadas, outras = edicao.ler(camada, "anotacao", "uuid", edicao.texto)
        if not edicao.esvaziar(camada):
            log.erro("edição de ocorrências: o buffer não esvaziou; o workspace vai recusar a gravação do OGR")
        if outras:
            self.iface.messageBar().pushMessage(
                "Feixe",
                "Nas ocorrências só a anotação muda pelo QGIS; as outras mudanças foram desfeitas. Para um ponto novo, "
                "use Registrar ocorrência na barra do Feixe.",
                Qgis.Info,
                8,
            )
        feitas = 0
        if desejadas and self._pronto():
            for uuid, anotacao in desejadas.items():
                if self._executar(self._editar_ocorrencia, uuid, anotacao) is not None:
                    feitas += 1
        if feitas:
            texto = "Anotação gravada." if feitas == 1 else f"{feitas} anotações gravadas."
            self.iface.messageBar().pushMessage("Feixe", texto, Qgis.Success, 4)
        QTimer.singleShot(0, lambda: self._depois_de_gravar(camada, None))

    def _depois_de_gravar(self, camada, r):
        camadas.recarregar_cargas(so_workspace=True)
        if camada.isEditable():
            # "Salvar edição" sem sair da edição: o buffer está vazio e a camada pode reler a situação; a junção (a
            # folha e o progresso) acerta quando a edição termina.
            camada.dataProvider().reloadData()
            camada.triggerRepaint()
        if r and r.get("progresso"):
            self.mostrar_progresso(r["progresso"])

    def mostrar_progresso(self, progresso, cq=None):
        """Barra de status: "Feixe · 2534-1 · 35/93" nas cargas, "Feixe · CQ 2534-1 · 7/20 amostras" no CQ (sem
        `cq`, pela fase da passagem) e "Feixe · Correção 2534-3 · 12/40 tratadas" na correção (`regras.texto_status`
        pelo andamento)."""
        if self.rotulo_status and progresso:
            if cq is None:
                cq = bool(self._ler(lgrupos.e_cq, False, progresso.get("id_lote_etapa")))
            self.rotulo_status.setText(regras.texto_status(progresso, cq))

    # --- ferramentas de mapa do supervisor (B3, B4) ---------------------------------------------
    def ligar_ferramenta_folhas(self, folhas, no_feixe, escolhidas):
        """Carrega a malha de folhas 1:100.000 com o estado de cada uma e liga a ferramenta de escolher no mapa."""
        canvas = self.iface.mapCanvas()
        vazio = not any(c.isValid() for c in QgsProject.instance().mapLayers().values())
        self._malha = {"no_feixe": no_feixe, "escolhidas": set(escolhidas)}
        malha = camadas.mostrar_malha(folhas, no_feixe, escolhidas)
        if vazio:  # projeto em branco: mostrar o país, senão a malha cai fora da tela
            canvas.setDestinationCrs(malha.crs())
            canvas.setExtent(malha.extent())
            canvas.refresh()
        if self.ferramenta_folha is None:
            self.ferramenta_folha = FerramentaFolha(canvas, self._folha_clicada, self._retangulo_folhas)
        canvas.setMapTool(self.ferramenta_folha)
        self.iface.mainWindow().activateWindow()
        self.iface.messageBar().pushMessage(
            "Feixe",
            "Clique numa folha para escolher ou tirar; Ctrl ou Shift e arraste para escolher as folhas de um "
            "retângulo. Arrastar sem tecla move o mapa.",
            Qgis.Info,
            8,
        )

    def marcar_folhas(self, no_feixe, escolhidas):
        self._malha = {"no_feixe": no_feixe, "escolhidas": set(escolhidas)}
        camadas.marcar_malha(no_feixe, escolhidas)

    def fim_folhas(self):
        camadas.remover_malha()
        self._malha = None
        canvas = self.iface.mapCanvas()
        if self.ferramenta_folha is not None and canvas.mapTool() is self.ferramenta_folha:
            self.iface.actionPan().trigger()

    def _mudar_escolhidas(self, adicionar, tirar):
        """Muda a malha na hora (sem esperar o painel) e manda a mudança para o painel, que guarda a lista."""
        if self._malha is not None:
            self._malha["escolhidas"] |= {f["id"] for f in adicionar}
            self._malha["escolhidas"] -= set(tirar)
            camadas.marcar_malha(self._malha["no_feixe"], sorted(self._malha["escolhidas"]))
        self.broker.publicar("qgis", {"acao": "folhas", "adicionar": adicionar, "tirar": tirar})

    @staticmethod
    def _so_id(f):
        return {"id": f["id"], "cd_mi": f["cd_mi"], "nm_carta": f["nm_carta"]}

    def _folha_clicada(self, x, y):
        from qgis.core import QgsGeometry, QgsPointXY

        achadas = camadas.folhas_da_malha(QgsGeometry.fromPointXY(QgsPointXY(x, y)))
        if not achadas:
            self.iface.messageBar().pushMessage("Feixe", "Nenhuma folha 1:100.000 neste ponto.", Qgis.Info, 3)
            return
        f = achadas[0]
        if f["estado"] == camadas.ESCOLHIDA:
            self._mudar_escolhidas([], [f["id"]])
        elif f["estado"] == camadas.NO_FEIXE:
            self.iface.messageBar().pushMessage("Feixe", f"A folha {f['cd_mi']} já está {f['rotulo']}.", Qgis.Info, 4)
        else:
            self._mudar_escolhidas([self._so_id(f)], [])

    def _retangulo_folhas(self, retangulo):
        from qgis.core import QgsGeometry

        tocadas = camadas.folhas_da_malha(QgsGeometry.fromRect(retangulo), so_cobertas=True)
        novas = [self._so_id(f) for f in tocadas if f["estado"] == camadas.LIVRE]
        ja = [f["cd_mi"] for f in tocadas if f["estado"] == camadas.NO_FEIXE]
        if novas:
            self._mudar_escolhidas(novas, [])
        partes = [f"{len(novas)} folha(s) escolhida(s)"] + ([f"{len(ja)} já no Feixe, deixadas de fora"] if ja else [])
        self.iface.messageBar().pushMessage("Feixe", "; ".join(partes) + ".", Qgis.Info, 4)

    def cargas_geradas(self):
        camadas.recarregar_cargas()

    def selecao_wkt(self):
        try:
            return selecao_wkt(self.iface.activeLayer())
        except SemSelecao as e:
            raise ErroApi(400, str(e)) from None

    # --- QGIS ----------------------------------------------------------------------------------
    def montar_camadas(self):
        """Botão da barra: o mesmo caminho da rota POST /api/camadas/montar."""
        if config.credenciais(self.amb) is None:
            self.pedir_credenciais()
            if config.credenciais(self.amb) is None:
                return
        if not self.servidor:
            self.iniciar_servidor()
        try:
            r = rotas_camadas.montar(self.ctx)
        except ErroApi as e:
            self.iface.messageBar().pushMessage("Feixe", e.mensagem, Qgis.Warning, 6)
            return
        except Exception as e:  # noqa: BLE001
            log.erro(f"montar camadas: {e}")
            self.iface.messageBar().pushMessage("Feixe", f"Não foi possível montar as camadas: {e}", Qgis.Critical, 8)
            return
        self.barra.mostrar_modo(r.get("modo"))
        for aviso in r.get("avisos") or []:
            self.iface.messageBar().pushMessage("Feixe", aviso, Qgis.Warning, 10)
        dicas = getattr(self.iface, "actionMapTips", lambda: None)()
        if dicas is not None and not dicas.isChecked():
            dicas.trigger()  # as camadas do Feixe têm dica ao passar o mouse (D-102)
        resumo = ", ".join(f"{c['nome']} ({c['feicoes']})" for c in r["camadas"])
        self.iface.messageBar().pushMessage("Feixe", f"Camadas montadas: {resumo}", Qgis.Success, 5)
        return r

    def trocar_modo(self, chave):
        """Seta do botão de camadas: liga o subgrupo do modo (Execução, Controle de qualidade ou Supervisão). Carrega
        antes se precisar."""
        if camadas.modo_atual() is None and self.montar_camadas() is None:
            self.barra.mostrar_modo(camadas.modo_atual())
            return
        try:
            camadas.modo(chave)
        except RuntimeError as e:
            self.iface.messageBar().pushMessage("Feixe", str(e).capitalize() + ".", Qgis.Info, 5)
        self._mostrar_barra_cq()

    def acao_qgis(self, nome, *args):
        """Ponte das rotas para o QGIS: despacha a ação registrada para a thread principal e espera o resultado."""
        fn = self.acoes_qgis.get(nome)
        if fn is None:
            raise KeyError(f"ação do QGIS desconhecida: {nome}")
        return dispatch.na_thread_principal(fn, *args)

    def zoom_para(self, xmin, ymin, xmax, ymax, srid=4674):
        canvas = self.iface.mapCanvas()
        origem = QgsCoordinateReferenceSystem(f"EPSG:{srid}")
        destino = canvas.mapSettings().destinationCrs()
        ret = QgsRectangle(xmin, ymin, xmax, ymax)
        if origem != destino:
            ret = QgsCoordinateTransform(origem, destino, QgsProject.instance()).transformBoundingBox(ret)
        canvas.setExtent(ret)
        canvas.refresh()
