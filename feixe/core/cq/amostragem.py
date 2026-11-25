"""Plano de amostragem simples por atributos, inspeção normal, pelos Quadros 5 e 6 do manual do IBGE.

Fonte: IBGE, "Avaliação da qualidade de dados geoespaciais" (Manuais técnicos em geociências), capítulo "Amostragem
aplicada a dados geoespaciais", p. 36-37 do livro. Os quadros são adaptados da ET-CQDG (DSG, 2016) e da ISO
2859-1:1999 (tabelas I e II-A).

- Quadro 5: tamanho do lote (N) + nível geral de inspeção (I, II ou III) -> letra-código.
- Quadro 6: letra-código + LQA (%) -> tamanho da amostra (n) e número de aceitação (Ac).

Setas do Quadro 6: segue-se a regra do Quadro 9 do manual (p. 40, plano de um lote da BC100 com LQA 4%), decisão
do projeto, e não a da ISO 2859-1. A letra-código e o tamanho de amostra (n) ficam os da linha da letra do Quadro 5;
da seta vem só o número de aceitação (Ac), o do primeiro plano na direção da seta, na mesma coluna de LQA. Ex.: N=35,
nível II, LQA 4,0: letra D, n=8 (linha D), Ac=1 (seta para baixo até E); N=16: letra C, n=5, Ac=0 (seta para cima
até B). Na ISO 2859-1 a letra e o n também mudariam para os da linha de destino (E com n=13; B com n=3). Toda linha do
quadro tem n próprio, então o n nunca depende da seta. A única seta sem plano no seu sentido é a da letra A com LQA
10,0 (para cima, e não há linha acima de A): essa combinação não tem Ac no quadro e é recusada com `ErroAmostragem`.

Inspeção completa: o manual (p. 39) diz que, quando o tamanho da amostra é igual ou maior que o tamanho do lote
(n >= N), faz-se a inspeção completa. Nesse caso `calcular` devolve n = N e `inspecao_completa=True`, mantendo o Ac
do plano. Lotes com N = 1 ficam abaixo da primeira faixa do Quadro 5 (2 a 8) e também são inspeção completa, como no
Quadro 9 do manual (sem letra-código, Ac = 0).

Python puro (só stdlib), para o plugin e para os testes.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import NamedTuple, Optional, Union

NIVEIS = ("I", "II", "III")

# Quadro 5: (N mínimo, N máximo ou None para "e maiores", letra no nível I, II, III).
QUADRO_5 = (
    (2, 8, "A", "A", "B"),
    (9, 15, "A", "B", "C"),
    (16, 25, "B", "C", "D"),
    (26, 50, "C", "D", "E"),
    (51, 90, "C", "E", "F"),
    (91, 150, "D", "F", "G"),
    (151, 280, "E", "G", "H"),
    (281, 500, "F", "H", "J"),
    (501, 1200, "G", "J", "K"),
    (1201, 3200, "H", "K", "L"),
    (3201, 10000, "J", "L", "M"),
    (10001, 35000, "K", "M", "N"),
    (35001, 150000, "L", "N", "P"),
    (150001, 500000, "M", "P", "Q"),
    (500001, None, "N", "Q", "R"),
)

# Quadro 6: colunas de LQA (%), na ordem do quadro.
LQAS = ("0.4", "0.65", "1.0", "1.5", "2.5", "4.0", "6.5", "10", "15", "25")
_LQAS_DEC = tuple(Decimal(x) for x in LQAS)

_B = "v"  # seta para baixo: usar o primeiro plano abaixo
_C = "^"  # seta para cima: usar o primeiro plano acima

# Quadro 6: letra -> (n, Ac em cada coluna de LQA, ou seta). Transcrito célula a célula do manual.
QUADRO_6 = {
    "A": (2, (_B, _B, _B, _B, _B, _B, 0, _C, _B, 1)),
    "B": (3, (_B, _B, _B, _B, _B, 0, _C, _B, 1, 2)),
    "C": (5, (_B, _B, _B, _B, 0, _C, _B, 1, 2, 3)),
    "D": (8, (_B, _B, _B, 0, _C, _B, 1, 2, 3, 5)),
    "E": (13, (_B, _B, 0, _C, _B, 1, 2, 3, 5, 7)),
    "F": (20, (_B, 0, _C, _B, 1, 2, 3, 5, 7, 10)),
    "G": (32, (0, _C, _B, 1, 2, 3, 5, 7, 10, 14)),
    "H": (50, (_C, _B, 1, 2, 3, 5, 7, 10, 14, 21)),
    "J": (80, (_B, 1, 2, 3, 5, 7, 10, 14, 21, _C)),
    "K": (125, (1, 2, 3, 5, 7, 10, 14, 21, _C, _C)),
    "L": (200, (2, 3, 5, 7, 10, 14, 21, _C, _C, _C)),
    "M": (315, (3, 5, 7, 10, 14, 21, _C, _C, _C, _C)),
    "N": (500, (5, 7, 10, 14, 21, _C, _C, _C, _C, _C)),
    "P": (800, (7, 10, 14, 21, _C, _C, _C, _C, _C, _C)),
    "Q": (1250, (10, 14, 21, _C, _C, _C, _C, _C, _C, _C)),
    "R": (2000, (14, 21, _C, _C, _C, _C, _C, _C, _C, _C)),
}
LETRAS = tuple(QUADRO_6)  # A..R, sem I e O, na ordem do quadro


class ErroAmostragem(ValueError):
    """Entrada fora dos quadros do manual ou combinação sem valor."""


class Plano(NamedTuple):
    """Plano de amostragem de uma letra e um LQA.

    `n` é sempre o da linha de `letra`. `letra_ac` é a linha de onde veio o Ac: igual a `letra` quando a célula tem
    valor, ou a do primeiro plano na direção da seta (só para explicar o Ac ao usuário).
    """

    letra: str
    letra_ac: str
    n: int
    ac: int


class Resultado(NamedTuple):
    """Plano completo para um lote: N, nível, LQA e o que inspecionar.

    `letra` é a do Quadro 5 (None quando N = 1, abaixo do quadro); `n_quadro` é o n da linha dessa letra no Quadro 6;
    `ac` e `letra_ac` (linha de onde o Ac veio) seguem as setas. `n` é o que se inspeciona de fato: `n_quadro`, ou N
    quando `inspecao_completa`.
    """

    N: int
    nivel: str
    lqa: Decimal
    letra: Optional[str]
    letra_ac: Optional[str]
    n_quadro: Optional[int]
    n: int
    ac: int
    inspecao_completa: bool


def normalizar_nivel(nivel: Union[str, int]) -> str:
    """Aceita "I", "ii", "III", 1, 2, 3 ou "2" e devolve o nível em romano."""
    if isinstance(nivel, bool):
        raise ErroAmostragem(f"Nível de inspeção desconhecido: {nivel!r}. Use I, II ou III.")
    if isinstance(nivel, int):
        if 1 <= nivel <= 3:
            return NIVEIS[nivel - 1]
    elif isinstance(nivel, str):
        texto = nivel.strip().upper()
        if texto in NIVEIS:
            return texto
        if texto in ("1", "2", "3"):
            return NIVEIS[int(texto) - 1]
    raise ErroAmostragem(f"Nível de inspeção desconhecido: {nivel!r}. Use I, II ou III (níveis gerais do Quadro 5).")


def normalizar_lqa(lqa: Union[str, float, int, Decimal]) -> Decimal:
    """Aceita 4, 4.0, "4,0", "2,5" ou "0.65" e devolve o LQA como uma das colunas do Quadro 6."""
    if isinstance(lqa, bool):
        raise ErroAmostragem(f"LQA inválido: {lqa!r}.")
    try:
        if isinstance(lqa, str):
            valor = Decimal(lqa.strip().replace("%", "").strip().replace(",", "."))
        elif isinstance(lqa, float):
            valor = Decimal(repr(lqa))
        else:
            valor = Decimal(lqa)
    except (InvalidOperation, ValueError, TypeError):
        raise ErroAmostragem(f"LQA inválido: {lqa!r}. Informe um número, como 4,0 ou 2,5.") from None
    for coluna in _LQAS_DEC:
        if valor == coluna:
            return coluna
    aceitos = ", ".join(x.replace(".", ",") for x in LQAS)
    raise ErroAmostragem(f"LQA {_formatar(valor)}% fora do Quadro 6 do manual. Valores aceitos: {aceitos}.")


def letra_codigo(N: int, nivel: Union[str, int]) -> str:
    """Letra-código do Quadro 5 para um lote de N itens no nível geral de inspeção dado."""
    nivel = normalizar_nivel(nivel)
    N = _validar_N(N)
    if N < 2:
        raise ErroAmostragem(f"Lote com {N} item fica abaixo do Quadro 5 (começa em 2): faça a inspeção completa.")
    coluna = NIVEIS.index(nivel)
    tamanho = N
    for minimo, maximo, *letras in QUADRO_5:
        if maximo is None or minimo <= tamanho <= maximo:
            return letras[coluna]
    raise AssertionError("Quadro 5 cobre todo N >= 2")  # pragma: no cover


def plano(letra: str, lqa: Union[str, float, int, Decimal]) -> Plano:
    """Tamanho de amostra (n) da linha da letra e número de aceitação (Ac) do Quadro 6, com o Ac seguindo as setas."""
    letra_pedida = letra.strip().upper() if isinstance(letra, str) else letra
    if letra_pedida not in QUADRO_6:
        raise ErroAmostragem(f"Letra-código desconhecida: {letra!r}. O Quadro 6 vai de A a R (sem I e O).")
    valor = normalizar_lqa(lqa)
    coluna = _LQAS_DEC.index(valor)
    i = LETRAS.index(letra_pedida)
    celula = QUADRO_6[letra_pedida][1][coluna]
    if celula in (_B, _C):
        passo = 1 if celula == _B else -1
        j = i + passo
        while 0 <= j < len(LETRAS) and QUADRO_6[LETRAS[j]][1][coluna] == celula:
            j += passo
        if not 0 <= j < len(LETRAS) or QUADRO_6[LETRAS[j]][1][coluna] in (_B, _C):
            sentido = "abaixo" if celula == _B else "acima"
            raise ErroAmostragem(
                f"O Quadro 6 não tem número de aceitação para a letra {letra_pedida} com LQA {_formatar(valor)}%: "
                f"a seta aponta para {sentido} e não há plano nessa direção. "
                "Escolha outro LQA ou outro nível de inspeção."
            )
        i = j
    n = QUADRO_6[letra_pedida][0]  # Quadro 9: o n é sempre o da linha da letra
    letra_ac = LETRAS[i]
    return Plano(letra=letra_pedida, letra_ac=letra_ac, n=n, ac=int(QUADRO_6[letra_ac][1][coluna]))


def calcular(N: int, nivel: Union[str, int], lqa: Union[str, float, int, Decimal]) -> Resultado:
    """Encadeia o Quadro 5 e o Quadro 6 e aplica a regra da inspeção completa (n >= N)."""
    nivel = normalizar_nivel(nivel)
    N = _validar_N(N)
    valor = normalizar_lqa(lqa)
    if N < 2:
        return Resultado(N, nivel, valor, None, None, None, N, 0, True)
    letra = letra_codigo(N, nivel)
    p = plano(letra, valor)
    completa = p.n >= N
    return Resultado(N, nivel, valor, letra, p.letra_ac, p.n, N if completa else p.n, p.ac, completa)


def _validar_N(N: int) -> int:
    if isinstance(N, bool) or not isinstance(N, int):
        raise ErroAmostragem(f"Tamanho do lote inválido: {N!r}. Informe um número inteiro de itens.")
    if N <= 0:
        raise ErroAmostragem(f"Tamanho do lote tem de ser maior que zero (veio {N}).")
    return N


def _formatar(valor: Decimal) -> str:
    texto = format(valor.normalize(), "f")
    if "." not in texto:
        texto += ".0"
    return texto.replace(".", ",")
