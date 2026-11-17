"""D-103: leituras do painel (Início e Supervisão), pela camada de dados. Numa UF sem dados (GO), para os números
serem só os do cenário. Transações desfeitas, nos dois bancos (9.6 e 17)."""

from __future__ import annotations

import pytest
from feixe.core.dados import ErroDados
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

    # Aberta a próxima e ainda não iniciada (a etapa atual do lote continua na concluída, pelo status nacional), a
    # folha já não espera ninguém (D-105): sai de Esperando, a listagem mostra a etapa aberta e é para ela que gerar e
    # atribuir cargas apontam; a gaveta não sugere abrir outra.
    df.nova_passagem(ex, "GO", lote, e["revisao"], OBS)
    nova = _aberta(ex, lote)
    assert ex.um("SELECT id_lote_etapa_atual AS a FROM mapcartacomp.lote WHERE id = %s", (lote,))["a"] != nova
    assert dp.esperando(ex, "GO") == []
    item = next(x for x in dl.listar(ex, "GO") if x["id"] == lote)
    assert (item["id_lote_etapa_atual"], item["situacao"], item["etapa"]) == (nova, "pendente", "E revisao")
    assert dl.um(ex, lote)["id_lote_etapa_atual"] == nova
    assert df.estado(ex, lote)["sugestao"] is None

    # Na última etapa do fluxo, não há próxima: é o grupo "fim do fluxo".
    df.acao(ex, "GO", nova, "iniciar", OBS)
    df.acao(ex, "GO", _aberta(ex, lote), "concluir", OBS)
    (g,) = dp.esperando(ex, "GO")
    assert g["id_proxima"] is None and g["proxima"] is None
    assert [p["conta"] for p in dl.um(ex, lote)["pessoas"]] == []


def test_execucao_por_dia(amb):  # noqa: F811
    _, ex = amb
    r = dp.execucao(ex, "America/Sao_Paulo")
    assert isinstance(r["por_dia"], list) and all({"dia", "n"} <= d.keys() for d in r["por_dia"])


def test_abrir_proximas_em_lote(amb):  # noqa: F811
    cen, ex = amb
    fluxo = df.criar(ex, "GO", 5, cen.tema, "GO lote", [
        _etapa("aquisicao", conta=True, repetivel=False, atividades=[cen.ativ["aquisicao"]]),
        _etapa("revisao", conta=True, obrigatoria=False),
    ])  # fmt: skip
    a, e = _folha(ex, "GO", fluxo, "2535")
    b, _ = _folha(ex, "GO", fluxo, "2536")
    for lote in (a, b):
        df.acao(ex, "GO", _aberta(ex, lote), "iniciar", OBS)
    df.acao(ex, "GO", _aberta(ex, a), "concluir", OBS)  # só a folha a está esperando

    r = df.abrir_proximas(ex, "GO", [a, b, -1], "em lote")
    assert [x["id_lote"] for x in r["abertas"]] == [a]
    assert {x["id_lote"]: x["erro"] for x in r["erros"]}.keys() == {b, -1}
    assert "aberta" in next(x["erro"] for x in r["erros"] if x["id_lote"] == b)
    le = _aberta(ex, a)
    passagem = ex.um("SELECT id_fluxo_etapa, instancia, situacao FROM mapcartacomp.lote_etapa WHERE id = %s", (le,))
    assert (passagem["id_fluxo_etapa"], passagem["instancia"], passagem["situacao"]) == (e["revisao"], 1, "pendente")
    h = df.historico(ex, a)[0]
    assert (h["acao"], h["observacao"]) == ("abrir", "em lote")

    # Outra UF não abre; observação vazia é recusada como na gaveta.
    assert df.acao(ex, "GO", le, "iniciar", OBS)["revisao_atual"] == 2  # conta revisão, como pela gaveta
    df.acao(ex, "GO", le, "concluir", OBS)
    assert df.abrir_proximas(ex, "DF", [a], "x")["erros"][0]["erro"].startswith("lote não encontrado")
    with pytest.raises(ErroDados):
        df.abrir_proximas(ex, "GO", [a], "  ")
