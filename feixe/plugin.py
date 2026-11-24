"""Ponto de entrada do plugin: barra do Feixe, servidor local, estado online/offline e ponte com o QGIS."""

from __future__ import annotations

import json
import os
import threading

from qgis.core import Qgis, QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsProject, QgsRectangle
from qgis.PyQt.QtCore import QObject, QTimer, QUrl, pyqtSignal
from qgis.PyQt.QtGui import QDesktopServices
from qgis.PyQt.QtWidgets import QLabel, QMessageBox

from .core import ambiente as ambmod
from .core import camadas, config, db, dispatch, log
from .core.dados import ErroDados
from .core.versao import raiz_plugin, versao_plugin
from .server.api import Contexto, ErroApi, criar_roteador
from .server.http import ServidorLocal
from .server.rotas import camadas as rotas_camadas
from .server.rotas import cargas as rotas_cargas
from .server.sse import Broker
from .sync import workspace as wsmod
from .sync.sincronizar import Sincronizacao, hora_local
from .sync.trabalhador import Trabalhador
from .ui.barra import BarraFeixe, DialogoCredenciais
from .ui.ferramentas import FerramentaFolha, SemSelecao, selecao_wkt


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
            "montar_camadas": lambda eu, responsaveis, supervisao, execucao: camadas.montar(
                self.amb, config.authcfg_id(self.amb), eu, responsaveis, supervisao, execucao
            ),
            "focar_carga": self.focar_carga,
            "ferramenta_folhas": self.ligar_ferramenta_folhas,
            "marcar_folhas": self.marcar_folhas,
            "fim_folhas": self.fim_folhas,
            "previa_cargas": self.previa_cargas,
            "selecao_cargas": camadas.cargas_selecionadas,
            "cargas_geradas": self.cargas_geradas,
            "selecao_wkt": self.selecao_wkt,
            "cargas_mudaram": self.cargas_mudaram,
        }
        self.barra = None
        self.rotulo_status = None
        self.ferramenta_folha = None
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
        self._abrir_workspace_gravado()
        self.iniciar_servidor()
        self.trabalhador.iniciar()
        self.verificar_rede()
        self._timer.start()
        if config.credenciais(self.amb) is None:
            QTimer.singleShot(500, self.pedir_credenciais)  # primeiro uso: pede usuário e senha

    def unload(self):
        self._timer.stop()
        self.trabalhador.parar()
        self.fim_folhas()
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
        self.sinais.sincronizacao_mudou.emit(est)

    def _aplicar_sincronizacao(self, est):
        self.sincronizacao = est
        if est.get("online") is not None:
            self.estado["online"] = est["online"]
        self._publicar_estado({})
        if est.get("mudou"):
            # As camadas do QGIS ainda leem a CCAR (o GPKG é do C4): o que o push levou passa a aparecer nelas.
            camadas.recarregar_cargas()
        for aviso in est.get("avisos") or []:
            self.iface.messageBar().pushMessage("Feixe", aviso, Qgis.Warning, 10)

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
            return [i for ids in self.puladas.values() for i in ids]

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
        """Faz dela a carga atual (contorno magenta) sem mudar a escala de quem trabalha: se ela já está inteira na
        tela, o mapa não se move; senão, centraliza nela. Depois pisca a carga para chamar o olho (D-102)."""
        camadas.definir_atual(carga["id"])
        self._passagem_atual = (carga.get("id_lote_etapa"), carga.get("id_lote"))
        canvas = self.iface.mapCanvas()
        destino = canvas.mapSettings().destinationCrs()
        ret = QgsRectangle(carga["xmin"], carga["ymin"], carga["xmax"], carga["ymax"])
        origem = QgsCoordinateReferenceSystem("EPSG:4674")
        if origem != destino:
            ret = QgsCoordinateTransform(origem, destino, QgsProject.instance()).transformBoundingBox(ret)
        if not canvas.extent().contains(ret):
            canvas.setCenter(ret.center())
            canvas.refresh()
        camada = camadas.camada_com_carga(carga["id"])
        if camada is not None:
            f = next(camada.getFeatures(f'"id_carga_trabalho" = {int(carga["id"])}'), None)
            if f is not None:
                canvas.flashFeatureIds(camada, [f.id()])
        self.mostrar_progresso(progresso)

    def cargas_mudaram(self, progresso):
        camadas.recarregar_cargas()
        self.mostrar_progresso(progresso)

    def mostrar_progresso(self, progresso):
        if self.rotulo_status and progresso:
            p = progresso
            self.rotulo_status.setText(f"Feixe · {p['folha_revisao']} · {p['concluidas']}/{p['total']}")

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

    def previa_cargas(self, celulas):
        camada = camadas.mostrar_previa(celulas)
        ext = camada.extent()
        self.zoom_para(ext.xMinimum(), ext.yMinimum(), ext.xMaximum(), ext.yMaximum(), 4674)

    def cargas_geradas(self):
        camadas.remover_previa()
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
        dicas = getattr(self.iface, "actionMapTips", lambda: None)()
        if dicas is not None and not dicas.isChecked():
            dicas.trigger()  # as camadas do Feixe têm dica ao passar o mouse (D-102)
        resumo = ", ".join(f"{c['nome']} ({c['feicoes']})" for c in r["camadas"])
        self.iface.messageBar().pushMessage("Feixe", f"Camadas montadas: {resumo}", Qgis.Success, 5)
        return r

    def trocar_modo(self, chave):
        """Seta do botão de camadas: liga o subgrupo do modo (Execução ou Supervisão). Carrega antes se precisar."""
        if camadas.modo_atual() is None and self.montar_camadas() is None:
            self.barra.mostrar_modo(camadas.modo_atual())
            return
        try:
            camadas.modo(chave)
        except RuntimeError as e:
            self.iface.messageBar().pushMessage("Feixe", str(e).capitalize() + ".", Qgis.Info, 5)
        self.barra.mostrar_modo(camadas.modo_atual())

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
