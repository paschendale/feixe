"""Barra do Feixe dentro do QGIS: guia o usuário na ordem do trabalho, só com ícones.

Da esquerda para a direita: 1. conectar (o ponto diz o estado da conexão; a dica diz conta e modo), 2. carregar
camadas (o clique carrega; a seta troca o modo de trabalho: Executar, Avaliar ou Supervisionar), 3. abrir o Feixe no
navegador (o ícone tem a seta de link externo), 4. próxima carga, 5. pular carga, 6. concluir carga. Depois, só para
quem tem amostras de CQ (D3c): próxima amostra, conforme, não conforme e registrar ocorrência; só com ocorrência
esperando a ciência, Ciente; e, só para quem está com uma folha na correção de inspeção (D5), próxima ocorrência e
tratada. Tudo o mais vive no painel web; a barra é Qt puro e deve continuar pequena.

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
    QActionGroup,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QToolBar,
    QToolButton,
)

from ..core.ambiente import Ambiente
from . import regras

PASTA_ICONES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "icones")

# Modos de trabalho (D-101): cada um liga o seu subgrupo no grupo Feixe e desliga o outro, sem recarregar.
MODOS: List[Tuple[str, str, str, str]] = [
    (
        "execucao",
        "Executar",
        "modo_execucao",
        "Mostra só o subgrupo Execução: Minhas cargas e Meus lotes, para trabalhar sobre a imagem.",
    ),
    (
        "cq",
        "Avaliar",
        "modo_cq",
        "Só para quem tem amostras de CQ. Mostra só o subgrupo Controle de qualidade: as amostras e as ocorrências "
        "de cada elemento.",
    ),
    (
        "supervisao",
        "Supervisionar",
        "modo_supervisao",
        "Só supervisor. Mostra só o subgrupo Supervisão: cargas por responsável, cargas a atribuir e lotes.",
    ),
]

ESTADOS = {
    "conectado": ("#3FA45B", "Conectado"),
    "fora": ("#F0A040", "Sem a CCAR (offline)"),
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
    camadas = pyqtSignal()
    modo = pyqtSignal(str)
    conta = pyqtSignal()
    sincronizar = pyqtSignal()
    proxima = pyqtSignal()
    pular = pyqtSignal()
    concluir = pyqtSignal()
    proxima_amostra = pyqtSignal()
    conforme = pyqtSignal()
    nao_conforme = pyqtSignal()
    ocorrencia = pyqtSignal()
    ciente = pyqtSignal()
    proxima_ocorrencia = pyqtSignal()
    tratada = pyqtSignal()

    # Atalhos padrão (livres no QGIS 3.40: o QGIS não usa Alt+Shift). Configuráveis no QGIS.
    ATALHOS: Dict[str, str] = {
        "conectar": "Alt+Shift+U",
        "verificar": "Alt+Shift+V",
        "camadas": "Alt+Shift+L",
        "modo_execucao": "Alt+Shift+E",
        "modo_cq": "Alt+Shift+Q",
        "modo_supervisao": "Alt+Shift+S",
        "abrir": "Alt+Shift+F",
        "proxima": "Alt+Shift+N",
        "pular": "Alt+Shift+P",
        "concluir": "Alt+Shift+C",
        "proxima_amostra": "Alt+Shift+M",
        "conforme": "Alt+Shift+K",
        "nao_conforme": "Alt+Shift+X",
        "ocorrencia": "Alt+Shift+O",
        "ciente": "Alt+Shift+I",
        "proxima_ocorrencia": "Alt+Shift+J",
        "tratada": "Alt+Shift+T",
    }

    TEXTO_SINCRONIZAR = (
        "Envia o que você fez e traz da CCAR as suas cargas, a sua fila e os lotes da UF. O Feixe testa a "
        "conexão sozinho a cada minuto."
    )

    def __init__(self, amb: Ambiente, parent=None):
        super().__init__("Feixe", parent)
        self.setObjectName("FeixeBarra")  # o QGIS lembra posição e visibilidade pelo nome
        self.setIconSize(QSize(20, 20))
        self.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.amb = amb
        self._dicas: Dict[QAction, Tuple[str, str]] = {}
        self._estado = ("sem_conta", "", None)
        self._sincronizacao = ""

        # 1. Conectar: clique abre usuário e senha. "Sincronizar agora" fica no menu Complementos > Feixe e no atalho
        # (o nome do objeto continua "verificar", para não perder o atalho que a pessoa já configurou).
        self.acao_conta = self._acao("conectar", "conectar", "Conectar ao Feixe", "", self.conta)
        self.acao_verificar = self._acao(
            "verificar", "verificar", "Sincronizar agora", self.TEXTO_SINCRONIZAR, self.sincronizar,
        )  # fmt: skip
        self.addAction(self.acao_conta)

        # 2. Camadas: o clique carrega (ou recarrega) o grupo Feixe; a seta troca o modo de trabalho.
        self.acao_camadas = self._acao(
            "camadas", "camadas", "Carregar as camadas do Feixe",
            "Monta o grupo Feixe no projeto com as camadas do seu papel, organizadas por tarefa: Execução, Controle de "
            "qualidade (quem avalia) e Supervisão (supervisor). Carregar de novo relê o banco e substitui o grupo. Na "
            "seta, troque o modo.",
            self.camadas,
        )  # fmt: skip
        self.acoes_modo: Dict[str, QAction] = {}
        grupo_modos = QActionGroup(self)
        grupo_modos.setExclusive(True)
        for chave, nome, ic, texto in MODOS:
            a = self._acao(f"modo_{chave}", ic, nome, texto, lambda _=False, m=chave: self.modo.emit(m))
            a.setCheckable(True)
            grupo_modos.addAction(a)
            self.acoes_modo[chave] = a
        self.bt_camadas = self._botao(self.acao_camadas, [self.acao_camadas, None, *self.acoes_modo.values()])

        # 3. Abrir o painel no navegador (o ícone tem a seta de link externo).
        self.acao_painel = self._acao(
            "abrir", "abrir", "Abrir o Feixe no navegador",
            "Abre o painel do Feixe no navegador padrão: lotes, fluxos, equipe e atribuição.", self.abrir_painel,
        )  # fmt: skip
        self.addAction(self.acao_painel)
        self.separador_execucao = self.addSeparator()

        # 4 e 5. Ações de alta frequência (B2). As de CQ entram na fase D, antes da âncora.
        self.acao_proxima = self._acao(
            "proxima", "proxima", "Próxima carga",
            "Vai para a sua carga pendente mais próxima da atual: ela vira a carga atual (contorno magenta em Minhas "
            "cargas) e o mapa a enquadra.", self.proxima,
        )  # fmt: skip
        self.acao_concluir = self._acao(
            "concluir", "concluir", "Concluir carga",
            "Conclui a carga atual (contorno magenta) e já passa para a próxima. Se você selecionou outra em Minhas "
            "cargas, conclui a selecionada.", self.concluir,
        )  # fmt: skip
        self.acao_pular = self._acao(
            "pular", "pular", "Pular carga",
            "Deixa a carga atual para depois e vai para a próxima. Ela volta quando acabarem as outras deste lote, "
            "ou quando você reabrir o QGIS.", self.pular,
        )  # fmt: skip
        self.addAction(self.acao_proxima)
        self.addAction(self.acao_pular)
        self.addAction(self.acao_concluir)

        # CQ (D3c): só aparecem para quem tem o que fazer (`mostrar_cq`), na barra e no menu Complementos > Feixe.
        self.acoes_cq: Dict[str, QAction] = {
            "proxima_amostra": self._acao(
                "proxima_amostra", "proxima_amostra", "Próxima amostra",
                "Vai para a sua próxima amostra de CQ pendente: ela vira a amostra atual (contorno magenta em "
                "Amostras, com o elemento no rótulo), a camada do elemento dela liga e o mapa dá zoom nela.",
                self.proxima_amostra,
            ),
            "conforme": self._acao(
                "conforme", "conforme", "Conforme",
                "Avalia a amostra atual (ou a selecionada em Amostras) como conforme e já vai para a próxima.",
                self.conforme,
            ),
            "nao_conforme": self._acao(
                "nao_conforme", "nao_conforme", "Não conforme",
                "Avalia a amostra atual (ou a selecionada) como não conforme, com uma observação curta opcional, e já "
                "vai para a próxima.", self.nao_conforme,
            ),
            "ocorrencia": self._acao(
                "ocorrencia", "ocorrencia", "Registrar ocorrência",
                "Liga a ferramenta de ponto: clique dentro da amostra para registrar a ocorrência ali, com uma "
                "anotação. Fica ligada para a próxima; Esc ou outra ferramenta desliga.", self.ocorrencia,
            ),
            "ciente": self._acao(
                "ciente", "ciente", "Ciente",
                "Dá ciência da ocorrência selecionada em Ocorrências para ciência (ou da primeira, sem seleção): o "
                "avaliador encontrou isto numa carga sua.", self.ciente,
            ),
            # Correção de inspeção (D5): só para quem está com uma folha na correção aberta.
            "proxima_ocorrencia": self._acao(
                "proxima_ocorrencia", "proxima_ocorrencia", "Próxima ocorrência",
                "Vai para a próxima ocorrência por tratar do lote na correção de inspeção: ela vira a ocorrência "
                "atual (pino maior em Ocorrências pendentes) e o mapa a mostra, sem mudar a escala.",
                self.proxima_ocorrencia,
            ),
            "tratada": self._acao(
                "tratada", "tratada", "Tratada",
                "Marca a ocorrência atual (ou a selecionada em Ocorrências pendentes) como tratada e já vai para a "
                "próxima. Na última, o lote terminou e o supervisor decide o próximo passo.", self.tratada,
            ),
        }  # fmt: skip
        self.acao_ocorrencia = self.acoes_cq["ocorrencia"]
        self.acao_ocorrencia.setCheckable(True)
        self.separador_cq = self.addSeparator()
        for a in self.acoes_cq.values():
            self.addAction(a)
        self.mostrar_cq({})
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
        return [self.acao_conta, self.acao_verificar, self.acao_camadas, *self.acoes_modo.values(),
                self.acao_painel, self.acao_proxima, self.acao_pular, self.acao_concluir,
                *self.acoes_cq.values()]  # fmt: skip

    def mostrar_cq(self, estado: Optional[Dict], modo: Optional[str] = None) -> Dict[str, bool]:
        """Mostra as ações do CQ conforme o estado (amostras e ocorrências para ciência) e o modo (as do avaliador só no
        modo Avaliar), por `regras.acoes_visiveis`. A ação escondida some também do menu e o atalho dela não
        dispara."""
        vis = regras.acoes_visiveis(estado, modo)
        for chave, a in self.acoes_cq.items():
            a.setVisible(vis[chave])
        execucao = {"proxima": self.acao_proxima, "pular": self.acao_pular, "concluir": self.acao_concluir}
        for chave, a in execucao.items():
            a.setVisible(vis[chave])
        self.separador_execucao.setVisible(any(vis.values()))
        self.separador_cq.setVisible(any(vis[c] for c in self.acoes_cq) and any(vis[c] for c in execucao))
        return vis

    def mostrar_modo(self, chave: Optional[str]) -> None:
        """Marca no menu o modo ligado (None: grupo Feixe ausente)."""
        for k, a in self.acoes_modo.items():
            a.setChecked(k == chave)

    # --- estado ---------------------------------------------------------------------------------
    def mostrar_estado(self, estado: str, conta: str = "", detalhe: Optional[str] = None, pendentes: int = 0) -> None:
        """Pinta o botão de conectar: verde conectado, laranja sem a CCAR, cinza sem usuário e senha."""
        cor, situacao = ESTADOS[estado]
        self.acao_conta.setIcon(icone_com_ponto("conectar", cor))
        linhas = [f"<span style='color:{cor}'>●</span> {situacao}" + (f" como <b>{conta}</b>" if conta else "")]
        linhas.append(f"Modo: <b>{self.amb.rotulo}</b> · banco {self.amb.descricao_banco}")
        if detalhe:
            linhas.append(detalhe)
        if self._sincronizacao:
            linhas.append(self._sincronizacao)
        if estado == "fora":
            linhas.append(
                "Minhas cargas continuam funcionando: o que você fizer fica guardado e vai quando a conexão voltar."
            )
        if pendentes:
            linhas.append(f"{pendentes} alteração a enviar" if pendentes == 1 else f"{pendentes} alterações a enviar")
        clique = "trocar de usuário" if estado != "sem_conta" else "informar usuário e senha"
        linhas.append(f"Clique para {clique}.")
        self._dicas[self.acao_conta] = ("Conectar ao Feixe", "<br>".join(linhas))
        self._atualizar_dica(self.acao_conta)

    def mostrar_sincronizacao(self, texto: str) -> None:
        """Última sincronização ("Sincronizado às 14:05", "Sincronizando…") na dica de Sincronizar agora e de Conectar
        (a de Conectar é refeita no próximo `mostrar_estado`)."""
        self._sincronizacao = texto
        self._dicas[self.acao_verificar] = ("Sincronizar agora", f"{texto}<br>{self.TEXTO_SINCRONIZAR}")
        self._atualizar_dica(self.acao_verificar)


def pedir_observacao(parent=None) -> Optional[str]:
    """Não conforme: observação curta opcional. None = cancelou (nada é avaliado); texto vazio = sem observação."""
    texto, ok = QInputDialog.getText(parent, "Não conforme", "Observação (opcional):", QLineEdit.Normal, "")
    return texto.strip() if ok else None


def pedir_anotacao(parent=None, elemento: str = "", folha: str = "") -> Optional[str]:
    """Registrar ocorrência: a anotação (o que está errado ali). None = cancelou (nada é registrado)."""
    onde = " · ".join(p for p in (elemento, folha) if p)
    texto, ok = QInputDialog.getMultiLineText(
        parent, "Registrar ocorrência", f"Anotação{f' ({onde})' if onde else ''}:", ""
    )
    return texto.strip() if ok else None


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
