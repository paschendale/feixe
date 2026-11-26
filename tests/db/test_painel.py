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

    # Outra UF não abre; a observação é opcional.
    assert df.acao(ex, "GO", le, "iniciar", OBS)["revisao_atual"] == 2  # conta revisão, como pela gaveta
    df.acao(ex, "GO", le, "concluir", OBS)
    assert df.abrir_proximas(ex, "DF", [a], "x")["erros"][0]["erro"].startswith("lote não encontrado")
    df.acao(ex, "GO", _aberta(ex, b), "concluir", "  ")
    assert df.historico(ex, b)[0]["acao"] == "concluir" and df.historico(ex, b)[0]["observacao"] is None


def test_depois_de_pular_a_seguinte_e_a_que_vem_depois_da_pulada(amb):  # noqa: F811
    # D-107: a etapa atual ignora as puladas (dirige o status nacional); contar a partir dela reabria a etapa pulada.
    cen, ex = amb
    fluxo = df.criar(ex, "GO", 5, cen.tema, "GO pular", [
        _etapa("aquisicao", conta=True, repetivel=False, atividades=[cen.ativ["aquisicao"]]),
        _etapa("revisao", conta=True, obrigatoria=False),
        _etapa("correcao_topologica"),
    ])  # fmt: skip
    a, e = _folha(ex, "GO", fluxo, "2537")
    df.acao(ex, "GO", _aberta(ex, a), "iniciar", OBS)
    df.acao(ex, "GO", _aberta(ex, a), "concluir", OBS)
    assert df.abrir_proximas(ex, "GO", [a], OBS)["abertas"][0]["etapa"] == "E revisao"
    estado = df.acao(ex, "GO", _aberta(ex, a), "pular", OBS)
    assert estado["sugestao"]["id"] == e["correcao_topologica"]

    grupo = next(g for g in dp.esperando(ex, "GO") if any(f["id_lote"] == a for f in g["folhas"]))
    assert (grupo["etapa"], grupo["id_proxima"]) == ("E revisao", e["correcao_topologica"])
    assert grupo["folhas"][0]["situacao"] == "pulada"

    r = df.abrir_proximas(ex, "GO", [a], OBS)
    assert [x["etapa"] for x in r["abertas"]] == ["E correcao_topologica"], r
    status = ex.um("SELECT status_nacional FROM mapcartacomp.lote WHERE id = %s", (a,))["status_nacional"]
    assert status == "EM_PRODUCAO"


def test_encerrar_a_folha_no_fim_do_fluxo(amb):  # noqa: F811
    # D-153 (P-26): a última etapa do fluxo terminou e não há seguinte; o supervisor encerra e a folha fica CONCLUIDA.
    cen, ex = amb
    fluxo = df.criar(ex, "GO", 5, cen.tema, "GO fim", [
        _etapa("aquisicao", conta=True, repetivel=False, atividades=[cen.ativ["aquisicao"]]),
        _etapa("revisao", conta=True, obrigatoria=False),
    ])  # fmt: skip
    a, e = _folha(ex, "GO", fluxo, "2535")
    b, _ = _folha(ex, "GO", fluxo, "2536")
    for lote in (a, b):
        df.acao(ex, "GO", _aberta(ex, lote), "iniciar", OBS)
        df.acao(ex, "GO", _aberta(ex, lote), "concluir", OBS)
    df.nova_passagem(ex, "GO", a, e["revisao"], OBS)
    df.acao(ex, "GO", _aberta(ex, a), "iniciar", OBS)
    df.acao(ex, "GO", _aberta(ex, a), "concluir", OBS)

    status = lambda lote: ex.um("SELECT status_nacional AS s FROM mapcartacomp.lote WHERE id = %s", (lote,))["s"]  # noqa: E731
    assert status(a) == "EM_PRODUCAO"
    p = {i["id_lote"]: i for i in df.encerrar(ex, "GO", [a, b], None, previa=True)["itens"]}
    assert p[a]["erro"] is None and "abra a próxima etapa" in p[b]["erro"]  # b ainda tem a revisão no fluxo
    assert status(a) == "EM_PRODUCAO"  # a prévia não muda nada

    r = df.encerrar(ex, "GO", [a, b], "", previa=False)
    assert [x["id_lote"] for x in r["encerradas"]] == [a] and [x["id_lote"] for x in r["erros"]] == [b]
    assert status(a) == "CONCLUIDA" and df.historico(ex, a)[0]["acao"] == "encerrar"
    assert "já está concluído" in df.encerrar(ex, "GO", [a], None, previa=True)["itens"][0]["erro"]
    assert dl.um(ex, a)["status_nacional"] == "CONCLUIDA"

    # Abrir outra etapa depois reabre a folha: a etapa atual muda e o encerramento fica no histórico.
    df.nova_passagem(ex, "GO", a, e["revisao"], OBS)
    df.acao(ex, "GO", _aberta(ex, a), "iniciar", OBS)
    assert status(a) == "EM_PRODUCAO"
