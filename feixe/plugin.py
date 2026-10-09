"""Ponto de entrada do plugin: dock, servidor local, estado online/offline e ponte com o QGIS."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading

from qgis.core import Qgis, QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsProject, QgsRectangle
from qgis.PyQt.QtCore import QObject, Qt, QTimer, QUrl, pyqtSignal
from qgis.PyQt.QtGui import QDesktopServices, QIcon
from qgis.PyQt.QtWidgets import QAction

from .core import config as cfgmod
from .core import db, dispatch, log
from .core.versao import raiz_plugin, versao_plugin
from .server.api import Contexto, criar_roteador
from .server.http import ServidorLocal
from .server.sse import Broker
from .ui.dock import DialogoConfig, DockFeixe


class _Sinais(QObject):
    estado_mudou = pyqtSignal(dict)


class FeixePlugin:
    def __init__(self, iface):
        self.iface = iface
        self.cfg = cfgmod.carregar()
        self.servidor = None
        self.broker = Broker()
        self.dock = None
        self.acao = None
        self.sinais = _Sinais()
        self.estado = {"online": False, "usuario": None, "detalhe": "não verificado"}
        self._timer = QTimer()
        self._timer.setInterval(60_000)
        self._timer.timeout.connect(self.verificar_rede)

    # --- ciclo de vida -------------------------------------------------------------------------
    def initGui(self):  # noqa: N802
        dispatch.iniciar()
        self.dock = DockFeixe(self.iface.mainWindow())
        self.dock.abrir_painel.connect(self.abrir_painel)
        self.dock.testar_conexao.connect(self.testar_conexao)
        self.dock.configurar.connect(self.configurar)
        self.dock.mostrar_ambiente(self.cfg)
        self.iface.addDockWidget(Qt.RightDockWidgetArea, self.dock)
        self.acao = QAction(QIcon(os.path.join(raiz_plugin(), "icon.svg")), "Feixe", self.iface.mainWindow())
        self.acao.triggered.connect(self.abrir_painel)
        self.iface.addToolBarIcon(self.acao)
        self.iface.addPluginToMenu("&Feixe", self.acao)
        self.sinais.estado_mudou.connect(self._aplicar_estado)
        self.iniciar_servidor()
        self.verificar_rede()
        self._timer.start()

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
        )
        pasta = os.path.join(raiz_plugin(), "web", "dist")
        self.servidor = ServidorLocal(criar_roteador(ctx), self.broker, pasta, porta=self.cfg.porta).iniciar()
        log.info(f"servidor local em {self.servidor.origem}")

    def abrir_painel(self):
        if not self.servidor:
            self.iniciar_servidor()
        url = self.servidor.url_abertura
        # Modo aplicativo do Edge/Chrome quando existir: janela sem barra de endereço, parece um programa próprio.
        for exe in ("msedge", "chrome", "google-chrome", "chromium"):
            caminho = shutil.which(exe)
            if caminho:
                try:
                    subprocess.Popen([caminho, f"--app={url}"], close_fds=True)
                    return
                except OSError:
                    break
        if sys.platform == "darwin":
            for app in ("Microsoft Edge", "Google Chrome"):
                if os.path.isdir(f"/Applications/{app}.app"):
                    try:
                        subprocess.Popen(["open", "-na", app, "--args", f"--app={url}"], close_fds=True)
                        return
                    except OSError:
                        break
        QDesktopServices.openUrl(QUrl(url))

    # --- banco e rede --------------------------------------------------------------------------
    def consultar(self, sql, params=None):
        if not self.cfg.conexao:
            raise RuntimeError("nenhuma conexão configurada para este ambiente")
        return db.consultar(self.cfg.conexao, sql, params)

    def status_api(self):
        return {
            "ambiente": self.cfg.ambiente,
            "rotulo_ambiente": self.cfg.rotulo_ambiente,
            "cor_ambiente": self.cfg.cor_ambiente,
            "conexao": self.cfg.conexao,
            "versao_plugin": versao_plugin(),
            "qgis": Qgis.QGIS_VERSION,
            "clientes_sse": self.broker.conectados,
            **self.estado,
        }

    def verificar_rede(self):
        """Checagem barata (TCP) em thread própria; o resultado volta pela thread principal via sinal."""
        nome = self.cfg.conexao
        if not nome:
            self._publicar_estado({"online": False, "usuario": None, "detalhe": "nenhuma conexão configurada"})
            return

        def rodar():
            try:
                host, porta = db.host_porta(nome)
                ok = db.alcancavel(host, porta)
                detalhe = f"{host}:{porta} {'responde' if ok else 'não responde'}"
                self.sinais.estado_mudou.emit({"online": ok, "detalhe": detalhe})
            except Exception as e:  # noqa: BLE001
                self.sinais.estado_mudou.emit({"online": False, "detalhe": str(e)})

        threading.Thread(target=rodar, name="feixe-rede", daemon=True).start()

    def testar_conexao(self):
        nome = self.cfg.conexao
        if not nome:
            self.iface.messageBar().pushMessage("Feixe", "Configure uma conexão para este ambiente.", Qgis.Warning, 5)
            return

        def rodar():
            r = db.testar(nome)
            if r.get("ok"):
                schema = "sim" if r["schema_feixe"] else "não"
                detalhe = f"{r['usuario']}@{r['banco']} · {r['versao_servidor']} · schema feixe: {schema}"
                self.sinais.estado_mudou.emit({"online": True, "usuario": r["usuario"], "detalhe": detalhe})
            else:
                self.sinais.estado_mudou.emit({"online": False, "detalhe": r.get("erro", "falha")})

        threading.Thread(target=rodar, name="feixe-teste", daemon=True).start()

    def _publicar_estado(self, novo: dict):
        self.estado.update(novo)
        if self.dock:
            icone = "●" if self.estado["online"] else "○"
            self.dock.mostrar_estado(
                f"{icone} {'online' if self.estado['online'] else 'offline'} · {self.estado['detalhe']}"
            )
            self.dock.bt_sync.setEnabled(bool(self.estado["online"]))
        self.broker.publicar("estado", self.estado)

    def _aplicar_estado(self, novo: dict):
        self._publicar_estado(novo)

    # --- QGIS ----------------------------------------------------------------------------------
    def zoom_para(self, xmin, ymin, xmax, ymax, srid=4674):
        canvas = self.iface.mapCanvas()
        origem = QgsCoordinateReferenceSystem(f"EPSG:{srid}")
        destino = canvas.mapSettings().destinationCrs()
        ret = QgsRectangle(xmin, ymin, xmax, ymax)
        if origem != destino:
            ret = QgsCoordinateTransform(origem, destino, QgsProject.instance()).transformBoundingBox(ret)
        canvas.setExtent(ret)
        canvas.refresh()

    def configurar(self):
        try:
            conexoes = db.conexoes_postgis()
        except Exception as e:  # noqa: BLE001
            log.aviso(f"não foi possível listar conexões: {e}")
            conexoes = []
        dlg = DialogoConfig(self.cfg, conexoes, self.iface.mainWindow())
        if dlg.exec_():
            self.cfg = dlg.resultado()
            cfgmod.salvar(self.cfg)
            self.dock.mostrar_ambiente(self.cfg)
            self.broker.publicar("configuracao", {"ambiente": self.cfg.ambiente})
            self.verificar_rede()
