"""D-102: subgrupos por atividade em produção; as de CQ de um tema ficam juntas; ordem por tema sem acento."""

from feixe.core.dados.grupos import _agrupar


def _l(id_tema, tema, fase, ordem, id_atividade, atividade):
    return {"id_tema": id_tema, "tema": tema, "fase": fase, "ordem_fase": ordem, "id_atividade": id_atividade,
            "atividade": atividade}  # fmt: skip


def test_cq_agrupado_por_tema_e_ordem_sem_acento():
    g = _agrupar([
        _l(3, "LML", "aquisicao", 1, 15, "Aquisição BC100 - LML"),
        _l(2, "Áreas densamente edificadas", "cq", 3, 12, "CQ ADE - Comissão"),
        _l(2, "Áreas densamente edificadas", "cq", 3, 11, "CQ ADE - Omissão"),
        _l(1, "Hidrografia", "aquisicao", 1, 1, "Aquisição BC100 - Hidrografia"),
        _l(1, "Hidrografia", "cq", 3, 5, "CQ Hidro - Omissão"),
    ])  # fmt: skip
    assert [(x["rotulo"], x["atividades"]) for x in g] == [
        ("CQ · Áreas densamente edificadas", [11, 12]),
        ("Aquisição BC100 - Hidrografia", [1]),
        ("CQ · Hidrografia", [5]),
        ("Aquisição BC100 - LML", [15]),
    ]
