"""Barra do Feixe dentro do QGIS: guia o usuário na ordem do trabalho, só com ícones.

Da esquerda para a direita: 1. conectar (o ponto diz o estado da conexão; a dica diz conta e modo), 2. carregar
camadas (todas no clique; por módulo na seta, como as ferramentas do QGIS), 3. abrir o Feixe no navegador (o ícone
tem a seta de link externo), 4. próxima carga, 5. concluir carga. Tudo o mais vive no painel web; a barra é Qt
puro e deve continuar pequena.

Toda ação tem nome próprio (objectName) e é registrada no QGIS pelo plugin, com atalho padrão que a pessoa troca em
Configurações > Atalhos de teclado. A dica de cada botão mostra o atalho em uso.
"""

from __future__ import annotations

import os
from typing import Dict, List, Optional, Tuple

from qgis.PyQt.QtCore import QSize, Qt, pyqtSignal
from qgis.PyQt.QtGui import QColor, QIcon, QPainter, QPixmap
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

# Módulos de camadas que dá para carregar sozinhos (a ordem é a do grupo Feixe no projeto).
MODULOS: List[Tuple[str, str, str, str]] = [
    ("minhas", "Minhas cargas", "modulo_minhas", "As suas cargas, pendentes e concluídas, com o estilo do DF."),
    (
        "equipe",
        "Cargas da equipe",
        "modulo_equipe",
        "Só supervisor: cargas por responsável (uma cor por pessoa) e cargas disponíveis, das etapas abertas.",
    ),
    ("folhas", "Folhas", "modulo_folhas", "Uma camada por tema com as folhas da unidade, etapa e responsável."),
]

ESTADOS = {
    "conectado": ("#3FA45B", "Conectado"),
    "fora": ("#F0A040", "Sem resposta da CCAR"),
    "sem_conta": ("#9AA0A6", "Usuário e senha não configurados"),
}


def icone(nome: str) -> QIcon:
    return QIcon(os.path.join(PASTA_ICONES, f"{nome}.svg"))


def icone_com_ponto(nome: str, cor: str, lado: int = 40) -> QIcon:
    """Ícone com um ponto de estado no canto de baixo à direita (verde, laranja ou cinza)."""
    pm = icone(nome).pixmap(lado, lado)
    if pm.isNull():
        pm = QPixmap(lado, lado)
        pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    r = lado * 0.42
    p.setPen(QColor("white"))
    p.setBrush(QColor(cor))
    p.drawEllipse(int(lado - r - 1), int(lado - r - 1), int(r), int(r))
    p.end()
    return QIcon(pm)


def _dica(titulo: str, texto: str, atalho: str = "") -> str:
    atalho = f" <span style='color:gray'>({atalho})</span>" if atalho else ""
    return f"<b>{titulo}</b>{atalho}<br>{texto}"


class BarraFeixe(QToolBar):
    abrir_painel = pyqtSignal()
    camadas = pyqtSignal(object)  # None = todas; senão a lista de módulos
    conta = pyqtSignal()
    sincronizar = pyqtSignal()
    proxima = pyqtSignal()
    concluir = pyqtSignal()

    # Atalhos padrão (livres no QGIS 3.40: o QGIS não usa Alt+Shift). Configuráveis no QGIS.
    ATALHOS: Dict[str, str] = {
        "conectar": "Alt+Shift+U",
        "verificar": "Alt+Shift+V",
        "camadas": "Alt+Shift+L",
        "camadas_minhas": "Alt+Shift+1",
        "camadas_equipe": "Alt+Shift+2",
        "camadas_folhas": "Alt+Shift+3",
        "abrir": "Alt+Shift+F",
        "proxima": "Alt+Shift+N",
        "concluir": "Alt+Shift+C",
    }

    def __init__(self, amb: Ambiente, parent=None):
        super().__init__("Feixe", parent)
        self.setObjectName("FeixeBarra")  # o QGIS lembra posição e visibilidade pelo nome
        self.setIconSize(QSize(20, 20))
        self.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.amb = amb
        self._dicas: Dict[QAction, Tuple[str, str]] = {}
        self._estado = ("sem_conta", "", None)

        # 1. Conectar: clique abre usuário e senha. "Verificar a conexão agora" fica no menu Complementos > Feixe e
        # no atalho; o Feixe já verifica sozinho a cada minuto.
        self.acao_conta = self._acao("conectar", "conectar", "Conectar ao Feixe", "", self.conta)
        self.acao_verificar = self._acao(
            "verificar", "verificar", "Verificar a conexão agora",
            "Testa de novo se a CCAR responde. O Feixe já verifica sozinho a cada minuto.", self.sincronizar,
        )  # fmt: skip
        self.addAction(self.acao_conta)

        # 2. Camadas: clique carrega todas; a seta carrega um módulo.
        self.acao_camadas = self._acao(
            "camadas", "camadas", "Carregar as camadas do Feixe",
            "Monta o grupo Feixe no projeto com todas as camadas do seu papel. Carregar de novo substitui, não "
            "duplica. Na seta, carregue só um módulo.", lambda: self.camadas.emit(None),
        )  # fmt: skip
        self.acoes_modulo: Dict[str, QAction] = {}
        for chave, nome, ic, texto in MODULOS:
            a = self._acao(f"camadas_{chave}", ic, nome, texto + " Substitui só este módulo no grupo Feixe.",
                           lambda _=False, m=chave: self.camadas.emit([m]))  # fmt: skip
            self.acoes_modulo[chave] = a
        self.bt_camadas = self._botao(self.acao_camadas, [self.acao_camadas, None, *self.acoes_modulo.values()])

        # 3. Abrir o painel no navegador (o ícone tem a seta de link externo).
        self.acao_painel = self._acao(
            "abrir", "abrir", "Abrir o Feixe no navegador",
            "Abre o painel do Feixe no navegador padrão: folhas, fluxos, equipe e atribuição.", self.abrir_painel,
        )  # fmt: skip
        self.addAction(self.acao_painel)
        self.addSeparator()

        # 4 e 5. Ações de alta frequência (B2). As de CQ entram na fase D, antes da âncora.
        self.acao_proxima = self._acao(
            "proxima", "proxima", "Próxima carga",
            "Seleciona e enquadra a sua carga pendente mais próxima da última que você concluiu.", self.proxima,
        )  # fmt: skip
        self.acao_concluir = self._acao(
            "concluir", "concluir", "Concluir carga",
            "Conclui a carga selecionada na camada Minhas cargas e já passa para a próxima.", self.concluir,
        )  # fmt: skip
        self.addAction(self.acao_proxima)
        self.addAction(self.acao_concluir)
        self._ancora_acoes = self.addSeparator()
        self._ancora_acoes.setVisible(False)
        self.mostrar_estado("sem_conta")

    # --- montagem -------------------------------------------------------------------------------
    def _acao(self, chave: str, ic: str, titulo: str, texto: str, ao_disparar) -> QAction:
        a = QAction(icone(ic), titulo, self)
        a.setObjectName(f"feixe_{chave}")
        a.setShortcut(self.ATALHOS.get(chave, ""))
        a.setShortcutContext(Qt.ApplicationShortcut)
        a.triggered.connect(ao_disparar)
        self._dicas[a] = (titulo, texto)
        a.changed.connect(lambda a=a: self._atualizar_dica(a))  # atalho trocado no QGIS: a dica acompanha
        self._atualizar_dica(a)
        return a

    def _botao(self, padrao: QAction, menu: List[Optional[QAction]]) -> QToolButton:
        bt = QToolButton(self)
        bt.setDefaultAction(padrao)
        m = QMenu(bt)
        m.setToolTipsVisible(True)
        for a in menu:
            if a is None:
                m.addSeparator()
            else:
                m.addAction(a)
        bt.setMenu(m)
        bt.setPopupMode(QToolButton.MenuButtonPopup)
        bt.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.addWidget(bt)
        return bt

    def _atualizar_dica(self, a: QAction) -> None:
        titulo, texto = self._dicas[a]
        a.setToolTip(_dica(titulo, texto, a.shortcut().toString()))  # o Qt só emite changed se o texto mudar

    def todas_acoes(self) -> List[QAction]:
        """Para o plugin registrar no QGIS (atalhos configuráveis) e no menu Complementos > Feixe."""
        return [self.acao_conta, self.acao_verificar, self.acao_camadas, *self.acoes_modulo.values(),
                self.acao_painel, self.acao_proxima, self.acao_concluir]  # fmt: skip

    def adicionar_acao(self, acao: QAction) -> None:
        """Ação de alta frequência nova (fases seguintes), depois de concluir carga."""
        self.insertAction(self._ancora_acoes, acao)

    # --- estado ---------------------------------------------------------------------------------
    def mostrar_estado(self, estado: str, conta: str = "", detalhe: Optional[str] = None, pendentes: int = 0) -> None:
        """Pinta o botão de conectar: verde conectado, laranja sem a CCAR, cinza sem usuário e senha."""
        cor, situacao = ESTADOS[estado]
        self.acao_conta.setIcon(icone_com_ponto("conectar", cor))
        linhas = [f"<span style='color:{cor}'>●</span> {situacao}" + (f" como <b>{conta}</b>" if conta else "")]
        linhas.append(f"Modo: <b>{self.amb.rotulo}</b> · banco {self.amb.descricao_banco}")
        if detalhe:
            linhas.append(detalhe)
        if pendentes:
            linhas.append(f"{pendentes} alterações locais a enviar")
        clique = "trocar de usuário" if estado != "sem_conta" else "informar usuário e senha"
        linhas.append(f"Clique para {clique}.")
        self._dicas[self.acao_conta] = ("Conectar ao Feixe", "<br>".join(linhas))
        self._atualizar_dica(self.acao_conta)


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
