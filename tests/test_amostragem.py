"""feixe.core.cq.amostragem: Quadros 5 e 6 do manual do IBGE (p. 36-37), casos tirados diretamente dos quadros."""

from __future__ import annotations

from decimal import Decimal

import pytest
from feixe.core.cq import amostragem
from feixe.core.cq.amostragem import ErroAmostragem, calcular, letra_codigo, plano


# Quadro 5, incluindo os limites das faixas de N.
@pytest.mark.parametrize(
    "N, nivel, letra",
    [
        (100, "II", "F"),  # exemplo do backlog
        (2, "I", "A"),
        (8, "III", "B"),
        (9, "III", "C"),
        (150, "II", "F"),
        (151, "II", "G"),
        (500, "I", "F"),
        (501, "I", "G"),
        (10000, "I", "J"),
        (10001, "I", "K"),
        (500000, "II", "P"),
        (500001, "III", "R"),
        (2000, "i", "H"),  # nível em minúsculas
        (116, 2, "F"),  # nível como número; ~116 células de 5 km numa folha
    ],
)
def test_letra_codigo(N, nivel, letra):
    assert letra_codigo(N, nivel) == letra


# Quadro 6, células com valor: o Ac vem da própria linha.
@pytest.mark.parametrize(
    "letra, lqa, n, ac",
    [
        ("F", 4.0, 20, 2),  # backlog
        ("H", "4,0", 50, 5),  # backlog
        ("F", "2,5", 20, 1),  # LQA do DF
        ("K", 2.5, 125, 7),
        ("A", 6.5, 2, 0),
        ("A", 25, 2, 1),
        ("G", "0,4", 32, 0),
        ("R", 0.65, 2000, 21),
        ("J", "15", 80, 21),
    ],
)
def test_plano_celula_com_valor(letra, lqa, n, ac):
    p = plano(letra, lqa)
    assert (p.letra_ac, p.n, p.ac) == (letra, n, ac)


# Setas, regra do Quadro 9 (p. 40): n da linha da letra; só o Ac vem do primeiro plano na direção da seta.
@pytest.mark.parametrize(
    "letra, lqa, n, letra_ac, ac",
    [
        ("C", "4,0", 5, "B", 0),  # seta para cima (Quadro 9: C, n=5, Ac=0)
        ("D", "4,0", 8, "E", 1),  # seta para baixo (Quadro 9: D, n=8, Ac=1)
        ("A", "4,0", 2, "B", 0),  # Quadro 9: A, n=2, Ac=0
        ("N", "4,0", 500, "M", 21),  # Quadro 9: N, n=500, Ac=21
        ("E", "2,5", 13, "F", 1),  # seta para baixo, LQA do DF
        ("D", "2,5", 8, "C", 0),  # seta para cima, LQA do DF
        ("A", "0,4", 2, "G", 0),  # várias setas para baixo em sequência
        ("H", "0,4", 50, "G", 0),
        ("J", "0,4", 80, "K", 1),
        ("A", 15, 2, "B", 1),
        ("R", 25, 2000, "H", 21),  # várias setas para cima em sequência
        ("J", 25, 80, "H", 21),
        ("R", "1,0", 2000, "Q", 21),
    ],
)
def test_plano_setas(letra, lqa, n, letra_ac, ac):
    p = plano(letra, lqa)
    assert (p.letra, p.n, p.letra_ac, p.ac) == (letra, n, letra_ac, ac)


# Quadro 9 do manual (p. 40): plano de um lote da BC100, nível II, LQA 4%. (N, letra, Ac, n, método).
QUADRO_9 = [
    (1, None, 0, 1, "completa"),
    (8, "A", 0, 2, "amostral"),
    (16, "C", 0, 5, "amostral"),
    (35, "D", 1, 8, "amostral"),
    (121, "F", 2, 20, "amostral"),
    (150, "F", 2, 20, "amostral"),
    (4, "A", 0, 2, "amostral"),
    (143, "F", 2, 20, "amostral"),
    (48, "D", 1, 8, "amostral"),
    (6483, "L", 14, 200, "amostral"),
    (78, "E", 1, 13, "amostral"),
    (180, "G", 3, 32, "amostral"),
    (12, "B", 0, 3, "amostral"),
    (19, "C", 0, 5, "amostral"),
    (20, "C", 0, 5, "amostral"),
    (2, "A", 0, 2, "completa"),
    (6, "A", 0, 2, "amostral"),
    (71238, "N", 21, 500, "amostral"),
    (8073, "L", 14, 200, "amostral"),
    (642, "J", 7, 80, "amostral"),
    (372, "H", 5, 50, "amostral"),
    (1270, "K", 10, 125, "amostral"),
    (38631, "N", 21, 500, "amostral"),
    (1531, "K", 10, 125, "amostral"),
    (312, "H", 5, 50, "amostral"),
    (3, "A", 0, 2, "amostral"),
    (100, "F", 2, 20, "amostral"),
    (33, "D", 1, 8, "amostral"),
    (852, "J", 7, 80, "amostral"),
    (31, "D", 1, 8, "amostral"),
    (85425, "N", 21, 500, "amostral"),
]


@pytest.mark.parametrize("N, letra, ac, n, metodo", QUADRO_9)
def test_quadro_9(N, letra, ac, n, metodo):
    r = calcular(N, "II", "4,0")
    assert (r.letra, r.ac, r.inspecao_completa) == (letra, ac, metodo == "completa")
    if metodo == "amostral":
        assert r.n == n == r.n_quadro
    else:
        assert r.n == N


def test_setas_todas_resolvem_exceto_a_10():
    """Toda célula do Quadro 6 tem Ac, salvo A com LQA 10,0 (seta para cima na primeira linha)."""
    sem_valor = []
    for letra in amostragem.LETRAS:
        for lqa in amostragem.LQAS:
            try:
                p = plano(letra, lqa)
            except ErroAmostragem:
                sem_valor.append((letra, lqa))
                continue
            assert isinstance(p.ac, int) and p.n == amostragem.QUADRO_6[letra][0]
    assert sem_valor == [("A", "10")]


def test_calcular_backlog():
    r = calcular(100, "II", "4,0")
    assert (r.letra, r.letra_ac, r.n, r.ac, r.inspecao_completa) == ("F", "F", 20, 2, False)
    assert r.lqa == Decimal("4.0")


def test_calcular_exemplo_figura_11():
    # Manual, p. 35: N = 2000, nível I, LQA 1,5 -> 50 amostras, Ac = 2.
    r = calcular(2000, "I", 1.5)
    assert (r.letra, r.n, r.ac) == ("H", 50, 2)


def test_calcular_com_seta():
    r = calcular(16, "II", "4,0")  # C, seta para cima: Ac de B, n de C
    assert (r.letra, r.letra_ac, r.n_quadro, r.n, r.ac) == ("C", "B", 5, 5, 0)
    r = calcular(35, "II", 4)  # D, seta para baixo: Ac de E, n de D
    assert (r.letra, r.letra_ac, r.n, r.ac) == ("D", "E", 8, 1)


def test_calcular_inspecao_completa_quando_n_maior_ou_igual_a_N():
    r = calcular(2, "I", "6,5")  # A: n = 2 >= N = 2
    assert r.inspecao_completa and r.n == 2 and r.n_quadro == 2 and r.ac == 0
    r = calcular(10, "II", "2,5")  # B, n = 3 < 10: amostral, Ac de C
    assert not r.inspecao_completa and (r.letra, r.n, r.letra_ac, r.ac) == ("B", 3, "C", 0)
    r = calcular(5, "III", "0,4")  # B, n = 3 < 5: amostral, Ac de G
    assert not r.inspecao_completa and (r.n, r.letra_ac, r.ac) == (3, "G", 0)
    r = calcular(3, "III", 25)  # B, n = 3 >= 3: completa
    assert r.inspecao_completa and r.n == 3 and r.ac == 2


def test_calcular_lote_de_um_item():
    r = calcular(1, "II", 4)
    assert r.inspecao_completa and r.letra is None and r.n == 1 and r.ac == 0


@pytest.mark.parametrize("nivel", ["IV", "S-1", "", None, 0, 4, True])
def test_nivel_desconhecido(nivel):
    with pytest.raises(ErroAmostragem, match="Nível de inspeção desconhecido"):
        letra_codigo(100, nivel)


@pytest.mark.parametrize("N", [0, -5])
def test_N_nao_positivo(N):
    with pytest.raises(ErroAmostragem, match="maior que zero"):
        letra_codigo(N, "II")
    with pytest.raises(ErroAmostragem, match="maior que zero"):
        calcular(N, "II", 4)


@pytest.mark.parametrize("N", [10.5, "100", None, True])
def test_N_invalido(N):
    with pytest.raises(ErroAmostragem, match="Tamanho do lote inválido"):
        letra_codigo(N, "II")


def test_N_um_fora_do_quadro_5():
    with pytest.raises(ErroAmostragem, match="inspeção completa"):
        letra_codigo(1, "II")


@pytest.mark.parametrize("lqa", [3.0, "3,0", 0.1, 40, "100"])
def test_lqa_fora_do_quadro(lqa):
    with pytest.raises(ErroAmostragem, match="fora do Quadro 6"):
        plano("F", lqa)


@pytest.mark.parametrize("lqa", ["abc", "", None, True])
def test_lqa_invalido(lqa):
    with pytest.raises(ErroAmostragem, match="LQA inválido"):
        plano("F", lqa)


@pytest.mark.parametrize("lqa", [2.5, "2,5", "2.5", "2,50", " 2,5 % ", Decimal("2.5")])
def test_lqa_formatos(lqa):
    assert plano("F", lqa).ac == 1


@pytest.mark.parametrize("letra", ["I", "O", "S", "", None])
def test_letra_desconhecida(letra):
    with pytest.raises(ErroAmostragem, match="Letra-código desconhecida"):
        plano(letra, 4)


def test_combinacao_sem_valor():
    with pytest.raises(ErroAmostragem, match="não tem número de aceitação para a letra A com LQA 10,0%"):
        plano("A", 10)
    with pytest.raises(ErroAmostragem, match="não tem número de aceitação"):
        calcular(5, "II", "10,0")
