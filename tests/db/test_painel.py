"""D-103: leituras do painel (Início e Supervisão), pela camada de dados. Numa UF sem dados (GO), para os números
serem só os do cenário. Transações desfeitas, nos dois bancos (9.6 e 17)."""

from __future__ import annotations

import pytest
from feixe.core.dados import fluxos as df
from feixe.core.dados import lotes as dl
from feixe.core.dados import painel as dp

from tests.db.test_fluxo import OBS, _aberta, _etapa, _folha, amb  # noqa: F401

pytestmark = pytest.mark.db


def test_atividade_em_producao_e_esperando(amb):  # noqa: F811
    cen, ex = amb
    fluxo = df.criar(ex, "GO", 5, cen.tema, "GO painel", [
        _etapa("aquisicao", conta=True, repetivel=False, atividades=[cen.ativ["aquisicao"]]),
        _etapa("revisao", conta=True, obrigatoria=False),
    ])  # fmt: skip
    lote, e = _folha(ex, "GO", fluxo)
    df.acao(ex, "GO", _aberta(ex, lote), "iniciar", OBS)

    s = dp.supervisao(ex, "GO")
    grupo = next(g for g in s["grupos"] if cen.ativ["aquisicao"] in g["atividades"])
    assert grupo["chave"] == f"a-{cen.ativ['aquisicao']}" and grupo["lotes"] == [lote]
    assert {"id_lote": lote}.items() <= next(x for x in s["lotes"] if x["id_lote"] == lote).items()
    assert s["status"].get("EM_PRODUCAO") == 1
    assert dp.esperando(ex, "GO") == []

    # Concluída a etapa, a folha sai da produção e espera o supervisor abrir a próxima.
    df.acao(ex, "GO", _aberta(ex, lote), "concluir", OBS)
    assert all(lote not in g["lotes"] for g in dp.supervisao(ex, "GO")["grupos"])
    (g,) = dp.esperando(ex, "GO")
    assert (g["id_proxima"], [f["id_lote"] for f in g["folhas"]]) == (e["revisao"], [lote])

    # Na última etapa do fluxo, não há próxima: é o grupo "fim do fluxo".
    df.nova_passagem(ex, "GO", lote, e["revisao"], OBS)
    df.acao(ex, "GO", _aberta(ex, lote), "iniciar", OBS)
    df.acao(ex, "GO", _aberta(ex, lote), "concluir", OBS)
    (g,) = dp.esperando(ex, "GO")
    assert g["id_proxima"] is None and g["proxima"] is None
    assert [p["conta"] for p in dl.um(ex, lote)["pessoas"]] == []


def test_execucao_por_dia(amb):  # noqa: F811
    _, ex = amb
    r = dp.execucao(ex, "America/Sao_Paulo")
    assert isinstance(r["por_dia"], list) and all({"dia", "n"} <= d.keys() for d in r["por_dia"])
