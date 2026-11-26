"""D-158: andamento de uma célula da grade estatística a partir das cargas antigas que a cobrem (sem banco)."""

from __future__ import annotations

import datetime

from scripts.db.migrar_df import transferir

D1 = datetime.datetime(2026, 10, 1, 10, tzinfo=datetime.timezone.utc)
D2 = datetime.datetime(2026, 10, 5, 15, tzinfo=datetime.timezone.utc)


def p(area, concluido, resp=None, em=None):
    return {"area": area, "concluido": concluido, "responsavel": resp, "concluido_em": em}


def test_celula_toda_coberta_por_concluidas_fica_concluida_com_a_ultima_data():
    t = transferir(100, [p(60, True, "u_a", D1), p(40, True, "u_b", D2)])
    assert t["concluido"] and t["cobertura"] == 1.0
    assert t["concluido_em"] == D2
    assert t["responsavel"] == "u_a"  # quem tem mais área concluída, não quem concluiu por último


def test_limiar_decide_a_cobertura_parcial():
    pedacos = [p(55, True, "u_a", D1), p(45, False, "u_b")]
    assert transferir(100, pedacos, 0.5)["concluido"]
    assert not transferir(100, pedacos, 0.6)["concluido"]


def test_exatamente_no_limiar_conta_como_concluida():
    assert transferir(100, [p(50, True, "u_a", D1), p(50, False)], 0.5)["concluido"]


def test_pendente_fica_com_quem_tem_mais_area_pendente():
    t = transferir(100, [p(30, True, "u_a", D1), p(45, False, "u_b"), p(25, False, "u_c")])
    assert not t["concluido"] and t["concluido_em"] is None
    assert t["responsavel"] == "u_b"


def test_pendente_sem_responsavel_fica_disponivel():
    t = transferir(100, [p(20, True, "u_a", D1), p(80, False, None)])
    assert not t["concluido"] and t["responsavel"] is None


def test_soma_das_areas_do_mesmo_responsavel():
    t = transferir(100, [p(30, False, "u_a"), p(30, False, "u_a"), p(40, False, "u_b")])
    assert t["responsavel"] == "u_a"


def test_celula_sem_carga_antiga_fica_pendente_e_disponivel():
    t = transferir(100, [])
    assert t == {"concluido": False, "concluido_em": None, "responsavel": None, "cobertura": 0.0}


def test_cobertura_nao_passa_de_um_com_sobreposicao():
    assert transferir(100, [p(80, True, "u_a", D1), p(80, True, "u_a", D1)])["cobertura"] == 1.0


def test_concluida_sem_data_de_origem():
    t = transferir(100, [p(100, True, "u_a", None)])
    assert t["concluido"] and t["concluido_em"] is None
