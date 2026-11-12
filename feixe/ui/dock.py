"""Dock mínimo dentro do QGIS: selo do ambiente, estado da conexão e as ações de alta frequência.

Tudo o mais vive na interface web. Este dock é Qt puro e deve continuar pequeno.
"""

from __future__ import annotations

from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDockWidget,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..core.ambiente import Ambiente


class DockFeixe(QDockWidget):
    abrir_painel = pyqtSignal()
    sincronizar = pyqtSignal()
    conta = pyqtSignal()
    camadas = pyqtSignal()

    def __init__(self, amb: Ambiente, parent=None):
        super().__init__("Feixe", parent)
        self.setObjectName("FeixeDock")
        self.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 8, 8, 8)
        self.selo = QLabel(amb.rotulo.upper())
        self.selo.setAlignment(Qt.AlignCenter)
        self.selo.setStyleSheet(f"padding:4px;border-radius:4px;color:white;font-weight:bold;background:{amb.cor}")
        self.selo.setToolTip(f"Este Feixe usa o banco {amb.descricao_banco}")
        if amb.producao:
            self.selo.hide()  # em produção o selo é desnecessário; só dev e homologação precisam se destacar
        self.estado = QLabel("não verificado")
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
        self.bt_camadas = QPushButton("Camadas do Feixe")
        self.bt_camadas.setToolTip("Monta (ou remonta) o grupo Feixe com as suas cargas e as folhas")
        self.bt_camadas.clicked.connect(self.camadas)
        lay.addWidget(self.bt_camadas)
        self.bt_conta = QPushButton("Usuário e senha")
        self.bt_conta.clicked.connect(self.conta)
        lay.addWidget(self.bt_conta)
        lay.addStretch()
        self.setWidget(w)

    def mostrar_estado(self, texto: str) -> None:
        self.estado.setText(texto)


class DialogoCredenciais(QDialog):
    """Só o que o usuário precisa informar: matrícula (usuário do banco) e senha. O resto vem do build."""

    def __init__(self, amb: Ambiente, usuario_atual: str, testar, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Feixe: usuário e senha")
        self.setMinimumWidth(380)
        self._testar = testar
        self.resultado_teste = None
        form = QFormLayout(self)
        self.ed_usuario = QLineEdit(usuario_atual)
        self.ed_usuario.setPlaceholderText("u_1234567")
        self.ed_senha = QLineEdit()
        self.ed_senha.setEchoMode(QLineEdit.Password)
        form.addRow("Usuário", self.ed_usuario)
        form.addRow("Senha", self.ed_senha)
        self.msg = QLabel("Use o mesmo usuário e senha do banco de dados cartográfico.")
        self.msg.setWordWrap(True)
        form.addRow(self.msg)
        botoes = QDialogButtonBox()
        self.bt_ok = botoes.addButton("Testar e salvar", QDialogButtonBox.AcceptRole)
        botoes.addButton(QDialogButtonBox.Cancel)
        botoes.accepted.connect(self._ao_aceitar)
        botoes.rejected.connect(self.reject)
        form.addRow(botoes)

    def _ao_aceitar(self):
        usuario, senha = self.ed_usuario.text().strip(), self.ed_senha.text()
        if not usuario or not senha:
            self.msg.setText("Informe usuário e senha.")
            return
        self.bt_ok.setEnabled(False)
        self.msg.setText("Testando a conexão…")
        self.repaint()
        r = self._testar(usuario, senha)
        self.bt_ok.setEnabled(True)
        if r.get("ok"):
            self.resultado_teste = r
            self.accept()
        else:
            self.msg.setText(f"Não conectou: {r.get('erro', 'erro desconhecido')}")

    def valores(self) -> tuple:
        return self.ed_usuario.text().strip(), self.ed_senha.text()
