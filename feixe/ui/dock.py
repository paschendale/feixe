"""Dock mínimo dentro do QGIS: selo do ambiente, estado da conexão e as ações de alta frequência.

Tudo o mais vive na interface web. Este dock é Qt puro e deve continuar pequeno.
"""

from __future__ import annotations

from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDockWidget,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..core import config as cfgmod


class DockFeixe(QDockWidget):
    abrir_painel = pyqtSignal()
    testar_conexao = pyqtSignal()
    sincronizar = pyqtSignal()
    configurar = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__("Feixe", parent)
        self.setObjectName("FeixeDock")
        self.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 8, 8, 8)
        self.selo = QLabel("")
        self.selo.setAlignment(Qt.AlignCenter)
        self.selo.setStyleSheet("padding:4px;border-radius:4px;color:white;font-weight:bold")
        self.estado = QLabel("sem conexão configurada")
        self.estado.setWordWrap(True)
        lay.addWidget(self.selo)
        lay.addWidget(self.estado)
        linha = QHBoxLayout()
        self.bt_painel = QPushButton("Abrir painel")
        self.bt_painel.clicked.connect(self.abrir_painel)
        self.bt_sync = QPushButton("Sincronizar")
        self.bt_sync.setEnabled(False)
        self.bt_sync.clicked.connect(self.sincronizar)
        linha.addWidget(self.bt_painel)
        linha.addWidget(self.bt_sync)
        lay.addLayout(linha)
        linha2 = QHBoxLayout()
        self.bt_testar = QPushButton("Testar conexão")
        self.bt_testar.clicked.connect(self.testar_conexao)
        self.bt_config = QPushButton("Configurações")
        self.bt_config.clicked.connect(self.configurar)
        linha2.addWidget(self.bt_testar)
        linha2.addWidget(self.bt_config)
        lay.addLayout(linha2)
        lay.addStretch()
        self.setWidget(w)

    def mostrar_ambiente(self, cfg: cfgmod.Config) -> None:
        self.selo.setText(cfg.rotulo_ambiente.upper())
        self.selo.setStyleSheet(
            f"padding:4px;border-radius:4px;color:white;font-weight:bold;background:{cfg.cor_ambiente}"
        )

    def mostrar_estado(self, texto: str) -> None:
        self.estado.setText(texto)


class DialogoConfig(QDialog):
    def __init__(self, cfg: cfgmod.Config, conexoes: list, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Feixe: configurações")
        self.cfg = cfg
        form = QFormLayout(self)
        self.cb_ambiente = QComboBox()
        for chave, (rotulo, _) in cfgmod.AMBIENTES.items():
            self.cb_ambiente.addItem(rotulo, chave)
        self.cb_ambiente.setCurrentIndex(list(cfgmod.AMBIENTES).index(cfg.ambiente))
        form.addRow("Ambiente", self.cb_ambiente)
        self.cb_conexoes = {}
        for chave, (rotulo, _) in cfgmod.AMBIENTES.items():
            cb = QComboBox()
            cb.addItem("(nenhuma)", "")
            for nome in conexoes:
                cb.addItem(nome, nome)
            atual = cfg.conexoes.get(chave, "")
            idx = cb.findData(atual)
            cb.setCurrentIndex(idx if idx >= 0 else 0)
            self.cb_conexoes[chave] = cb
            form.addRow(f"Conexão PostGIS ({rotulo})", cb)
        ajuda = QLabel("As conexões vêm do cadastro PostGIS do QGIS. Guarde a senha no Authentication Manager.")
        ajuda.setWordWrap(True)
        form.addRow(ajuda)
        botoes = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        botoes.accepted.connect(self.accept)
        botoes.rejected.connect(self.reject)
        form.addRow(botoes)

    def resultado(self) -> cfgmod.Config:
        self.cfg.ambiente = self.cb_ambiente.currentData()
        self.cfg.conexoes = {k: cb.currentData() for k, cb in self.cb_conexoes.items()}
        return self.cfg
