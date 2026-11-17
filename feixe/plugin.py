"""Ponto de entrada do plugin: barra do Feixe, servidor local, estado online/offline e ponte com o QGIS."""

from __future__ import annotations

import os
import threading

from qgis.core import Qgis, QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsProject, QgsRectangle
from qgis.PyQt.QtCore import QObject, QTimer, QUrl, pyqtSignal
from qgis.PyQt.QtGui import QDesktopServices
from qgis.PyQt.QtWidgets import QLabel, QMessageBox

from .core import ambiente as ambmod
from .core import camadas, config, db, dispatch, log
from .core.dados import ErroDados
from .core.dados import cargas as cargas_dados
from .core.dados import lotes as lotes_dados
from .core.versao import raiz_plugin, versao_plugin
from .server.api import Contexto, ErroApi, criar_roteador
from .server.http import ServidorLocal
from .server.rotas import camadas as rotas_camadas
from .server.rotas import cargas as rotas_cargas
from .server.sse import Broker
from .ui.barra import BarraFeixe, DialogoCredenciais
from .ui.ferramentas import FerramentaFolha, SemSelecao, selecao_wkt


class _Sinais(QObject):
    estado_mudou = pyqtSignal(dict)


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
            "previa_cargas": self.previa_cargas,
            "selecao_cargas": camadas.cargas_selecionadas,
            "cargas_geradas": self.cargas_geradas,
            "selecao_wkt": self.selecao_wkt,
            "cargas_mudaram": self.cargas_mudaram,
        }
        self.barra = None
        self.rotulo_status = None
        self.ferramenta_folha = None
        # Cargas puladas, por passagem (id_lote_etapa), na ordem em que foram puladas. Só na memória (D-102): voltam
        # quando o QGIS reabre ou quando acabam as não puladas da folha.
        self.puladas = {}
        self._passagem_atual = (None, None)  # (id_lote_etapa, id_lote) da carga atual
        self.sinais = _Sinais()
        self.estado = {"online": False, "usuario": None, "detalhe": "não verificado"}
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
        self.barra.sincronizar.connect(self.verificar_rede)
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
        self.iniciar_servidor()
        self.verificar_rede()
        self._timer.start()
        if config.credenciais(self.amb) is None:
            QTimer.singleShot(500, self.pedir_credenciais)  # primeiro uso: pede usuário e senha

    def unload(self):
        self._timer.stop()
        if self.servidor:
            self.servidor.parar()
            self.servidor = None
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
            publicar=self.broker.publicar,
            qgis=self.acao_qgis,
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
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self.iface.mainWindow(), "Feixe", f"Não foi possível guardar a credencial:\n{e}")
            return
        if self.ctx:
            self.ctx.esquecer_eu()
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
        }

    def verificar_rede(self):
        """Checagem barata (TCP) em thread própria; o resultado volta pela thread principal via sinal."""

        def rodar():
            ok = db.alcancavel(self.amb)
            detalhe = f"{self.amb.descricao_banco} {'responde' if ok else 'não responde'}"
            self.sinais.estado_mudou.emit({"online": ok, "detalhe": detalhe})

        threading.Thread(target=rodar, name="feixe-rede", daemon=True).start()

    def _publicar_estado(self, novo: dict):
        self.estado.update(novo)
        if self.barra:
            cred = config.credenciais(self.amb)
            estado = "sem_conta" if not cred else ("conectado" if self.estado["online"] else "fora")
            self.barra.mostrar_estado(estado, cred[0] if cred else "")
        self.broker.publicar("estado", self.estado)

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

    def _executar(self, fn, *args):
        """Roda uma ação da barra pelo mesmo caminho da API; recusa vira aviso na barra de mensagens."""
        try:
            return fn(self.ctx, *args)
        except (ErroApi, ErroDados) as e:
            self.iface.messageBar().pushMessage("Feixe", e.mensagem, Qgis.Warning, 6)
        except Exception as e:  # noqa: BLE001
            log.erro(f"{getattr(fn, '__name__', fn)}: {e}")
            self.iface.messageBar().pushMessage("Feixe", f"Não deu certo: {e}", Qgis.Critical, 8)
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
        try:
            with self.ctx.tx() as ex:
                carga = cargas_dados.uma(ex, int(id_carga))
        except Exception as e:  # noqa: BLE001
            self.iface.messageBar().pushMessage("Feixe", f"Não deu certo: {e}", Qgis.Critical, 8)
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
    def ligar_ferramenta_folhas(self):
        """Liga o clique no mapa: cada folha clicada vai para o painel pelo evento qgis {acao: folha}."""
        canvas = self.iface.mapCanvas()
        if self.ferramenta_folha is None:
            self.ferramenta_folha = FerramentaFolha(canvas, self._folha_clicada)
        canvas.setMapTool(self.ferramenta_folha)
        self.iface.mainWindow().activateWindow()
        self.iface.messageBar().pushMessage(
            "Feixe",
            "Clique nas folhas no mapa para mandá-las ao painel. Troque de ferramenta para parar.",
            Qgis.Info,
            6,
        )

    def _folha_clicada(self, x, y):
        try:
            with db.transacao(self.amb) as ex:
                folha = lotes_dados.folha_no_ponto(ex, x, y)
        except Exception as e:  # noqa: BLE001
            self.iface.messageBar().pushMessage("Feixe", f"Não deu para ler a folha: {e}", Qgis.Warning, 6)
            return
        if folha is None:
            self.iface.messageBar().pushMessage("Feixe", "Nenhuma folha 1:100.000 neste ponto.", Qgis.Info, 3)
            return
        self.broker.publicar("qgis", {"acao": "folha", "folha": folha})
        self.iface.messageBar().pushMessage("Feixe", f"Folha {folha['cd_mi']} enviada ao painel.", Qgis.Success, 2)

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
