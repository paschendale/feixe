"""Ponto de entrada do plugin: dock, servidor local, estado online/offline e ponte com o QGIS."""

from __future__ import annotations

import os
import threading

from qgis.core import Qgis, QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsProject, QgsRectangle
from qgis.PyQt.QtCore import QObject, Qt, QTimer, QUrl, pyqtSignal
from qgis.PyQt.QtGui import QDesktopServices, QIcon
from qgis.PyQt.QtWidgets import QAction, QMessageBox

from .core import ambiente as ambmod
from .core import camadas, config, db, dispatch, log
from .core.versao import raiz_plugin, versao_plugin
from .server.api import Contexto, ErroApi, criar_roteador
from .server.http import ServidorLocal
from .server.rotas import camadas as rotas_camadas
from .server.sse import Broker
from .ui.dock import DialogoCredenciais, DockFeixe


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
            "montar_camadas": lambda eu, responsaveis: camadas.montar(
                self.amb, config.authcfg_id(self.amb), eu, responsaveis
            ),
        }
        self.dock = None
        self.acao = None
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
        self.dock = DockFeixe(self.amb, self.iface.mainWindow())
        self.dock.abrir_painel.connect(self.abrir_painel)
        self.dock.conta.connect(self.pedir_credenciais)
        self.dock.camadas.connect(self.montar_camadas)
        self.iface.addDockWidget(Qt.RightDockWidgetArea, self.dock)
        self.acao = QAction(QIcon(os.path.join(raiz_plugin(), "icon.svg")), "Feixe", self.iface.mainWindow())
        self.acao.triggered.connect(self.abrir_painel)
        self.iface.addToolBarIcon(self.acao)
        self.iface.addPluginToMenu("&Feixe", self.acao)
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
        if self.acao:
            self.iface.removePluginMenu("&Feixe", self.acao)
            self.iface.removeToolBarIcon(self.acao)
        if self.dock:
            self.iface.removeDockWidget(self.dock)
            self.dock.deleteLater()
            self.dock = None
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
        if self.dock:
            icone = "●" if self.estado["online"] else "○"
            situacao = "online" if self.estado["online"] else "offline"
            self.dock.mostrar_estado(f"{icone} {situacao} · {self.estado['detalhe']}")
            self.dock.bt_sync.setEnabled(bool(self.estado["online"]))
        self.broker.publicar("estado", self.estado)

    def _aplicar_estado(self, novo: dict):
        self._publicar_estado(novo)

    # --- QGIS ----------------------------------------------------------------------------------
    def montar_camadas(self):
        """Botão do dock: o mesmo caminho da rota POST /api/camadas/montar."""
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
        resumo = ", ".join(f"{c['nome']} ({c['feicoes']})" for c in r["camadas"])
        self.iface.messageBar().pushMessage("Feixe", f"Camadas montadas: {resumo}", Qgis.Success, 5)

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
