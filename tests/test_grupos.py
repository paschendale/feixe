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


def test_plano_execucao_cq_sempre_em_subgrupo_e_so_o_primeiro_elemento_ligado():
    from feixe.core.dados.local.grupos import plano_execucao

    elementos = [{"id_atividade": 6, "elemento": "Comissão"}, {"id_atividade": 5, "elemento": "Omissão"}]
    cq = {"chave": "cq-1", "rotulo": "CQ · Hidrografia", "fase": "cq", "atividades": [5, 6], "elementos": elementos}
    prod = {"chave": "a-1", "rotulo": "Aquisição BC100 - Hidrografia", "fase": "aquisicao", "atividades": [1]}
    so_cq = plano_execucao([cq])
    assert so_cq == [{"tipo": "cq", "rotulo": "CQ · Hidrografia", "atividades": [5, 6], "elementos": [
        {"id_atividade": 6, "elemento": "Comissão", "visivel": True},
        {"id_atividade": 5, "elemento": "Omissão", "visivel": False},
    ]}]  # fmt: skip
    # Uma atividade de produção só: sem subgrupo intermediário e sem filtro de atividade (D-102).
    assert plano_execucao([prod]) == [{"tipo": "producao", "rotulo": None, "atividades": None, "correcoes": False}]
    # Produção e CQ: cada uma no seu subgrupo; a revisão com "incluir correções" ganha Correções a fazer.
    dois = plano_execucao([dict(prod, expor_ocorrencias=True), cq])
    assert [(p["tipo"], p["rotulo"], p["atividades"]) for p in dois] == [
        ("producao", "Aquisição BC100 - Hidrografia", [1]), ("cq", "CQ · Hidrografia", [5, 6]),
    ]  # fmt: skip
    assert dois[0]["correcoes"] is True
    # Ninguém com carga aberta: Minhas cargas vazia, para a barra ter onde mostrar a próxima.
    assert plano_execucao([]) == [{"tipo": "producao", "rotulo": None, "atividades": None, "correcoes": False}]
