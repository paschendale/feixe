"""Barra do Feixe dentro do QGIS (como no protótipo): marca, carregar camadas, as ações de alta frequência e o estado.

Tudo o mais vive no painel web. A barra é Qt puro e deve continuar pequena. A seta do botão da marca abre o menu com
abrir o painel, camadas e usuário e senha (o mesmo menu fica em Complementos > Feixe).
"""

from __future__ import annotations

import os

from qgis.PyQt.QtCore import QSize, Qt, pyqtSignal
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import (
    QAction,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QToolBar,
    QToolButton,
)

from ..core.ambiente import Ambiente

PASTA_ICONES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "icones")


def icone(nome: str) -> QIcon:
    return QIcon(os.path.join(PASTA_ICONES, f"{nome}.svg"))


class BarraFeixe(QToolBar):
    abrir_painel = pyqtSignal()
    camadas = pyqtSignal()
    conta = pyqtSignal()
    sincronizar = pyqtSignal()
    proxima = pyqtSignal()
    concluir = pyqtSignal()

    def __init__(self, amb: Ambiente, parent=None):
        super().__init__("Feixe", parent)
        self.setObjectName("FeixeBarra")  # o QGIS lembra posição e visibilidade pelo nome
        self.setIconSize(QSize(20, 20))
        self.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)

        self.acao_painel = QAction(icone("feixe"), "Abrir o Feixe", self)
        self.acao_painel.triggered.connect(self.abrir_painel)
        self.acao_camadas = QAction(icone("camadas"), "Carregar camadas do Feixe", self)
        self.acao_camadas.triggered.connect(self.camadas)
        self.acao_conta = QAction("Usuário e senha…", self)
        self.acao_conta.triggered.connect(self.conta)

        self.menu = QMenu(self)
        self.menu.addAction(self.acao_painel)
        self.menu.addAction(self.acao_camadas)
        self.menu.addSeparator()
        self.menu.addAction(self.acao_conta)
        marca = QToolButton(self)
        marca.setDefaultAction(self.acao_painel)
        marca.setMenu(self.menu)
        marca.setPopupMode(QToolButton.MenuButtonPopup)
        marca.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.addWidget(marca)

        camadas = QToolButton(self)
        camadas.setDefaultAction(self.acao_camadas)
        camadas.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.addWidget(camadas)

        # Ações de alta frequência (B2): próxima carga e concluir a selecionada. As de CQ entram na fase D.
        self.acao_proxima = QAction(icone("proxima"), "Próxima carga", self)
        self.acao_proxima.setToolTip("Seleciona e enquadra a sua carga pendente mais próxima")
        self.acao_proxima.triggered.connect(self.proxima)
        self.acao_concluir = QAction(icone("concluir"), "Concluir carga", self)
        self.acao_concluir.setToolTip("Conclui a carga selecionada em Minhas cargas e passa para a próxima")
        self.acao_concluir.triggered.connect(self.concluir)
        self.addAction(self.acao_proxima)
        self.addAction(self.acao_concluir)
        self._ancora_acoes = self.addSeparator()

        # Selo do ambiente só fora da produção, para ninguém confundir dev ou homologação com o banco de verdade.
        if not amb.producao:
            selo = QLabel(f" {amb.rotulo} ")
            selo.setStyleSheet(f"color:white;font-weight:bold;border-radius:3px;padding:1px 4px;background:{amb.cor}")
            selo.setToolTip(f"Este Feixe usa o banco {amb.descricao_banco}")
            self.addWidget(selo)

        self.estado = QToolButton(self)
        self.estado.setAutoRaise(True)
        self.estado.clicked.connect(self.sincronizar)
        self.addWidget(self.estado)
        self.mostrar_estado(False, "não verificado")

    def adicionar_acao(self, acao: QAction) -> None:
        """Ação de alta frequência, antes do separador do estado."""
        self.insertAction(self._ancora_acoes, acao)

    def mostrar_estado(self, online: bool, detalhe: str, pendentes: int = 0) -> None:
        """Bolinha verde (online) ou laranja (sem a CCAR), com as alterações locais pendentes ao lado."""
        cor = "#4CC26F" if online else "#F0A040"
        self.estado.setText("●" + (f" {pendentes}" if pendentes else ""))
        self.estado.setStyleSheet(f"QToolButton {{ color: {cor}; font-size: 14px; }}")
        situacao = "Conectado à CCAR" if online else "Fora da rede da CCAR"
        self.estado.setToolTip(f"{situacao} · {detalhe}" + (f" · {pendentes} alterações locais" if pendentes else ""))


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
