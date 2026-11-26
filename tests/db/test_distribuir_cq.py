"""D-147: distribuir as amostras de CQ de várias folhas juntas, por proporção entre avaliadores. Transações desfeitas,
nos dois bancos."""

from __future__ import annotations

import uuid

import psycopg2.extras
import pytest
from feixe.core.dados import ErroDados, ExecutorPg
from feixe.core.dados import cargas as dc
from feixe.core.dados import distribuir_cq as dd

from tests.db.migracoes import aplicar
from tests.db.test_atribuir import _conta
from tests.db.test_regras import Cenario

pytestmark = pytest.mark.db


@pytest.fixture
def amb(banco):
    aplicar(banco)
    with banco.cursor() as cur, banco.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as dcur:
        cen = Cenario(cur)
        cur.execute(
            "UPDATE mapcartacomp.atividade SET geracao = 'amostra_area', grade_nivel = 5000 WHERE id = ANY(%s)",
            (list(cen.ativ_cq.values()),),
        )
        cur.execute(
            "UPDATE mapcartacomp.fluxo_etapa SET nivel_inspecao = 'I', lqa = 4 WHERE id = %s", (cen.etapa["cq"],)
        )
        for conta in ("t_ana", "t_bia", "t_caio"):
            _conta(cur, conta, perfil="V")
        _conta(cur, "t_apm", perfil="O")
        yield cen, ExecutorPg(dcur)


def _outra_folha(cen, mi):
    cen.cur.execute(
        "INSERT INTO mapcartacomp.lote (uuid, cod_projeto, id_tema, id_fluxo, uf, tipo, id_articulacao_scn, nome) "
        "SELECT %s, 5, %s, %s, 'DF', 'folha', id_articulacao_scn, %s FROM mapcartctrl.v_articulacao_scn_100000 "
        "WHERE cd_mi = %s RETURNING id",
        (str(uuid.uuid4()), cen.tema, cen.fluxo, mi, mi),
    )
    return cen.cur.fetchone()[0]


def _cq(cen, ex, lote):
    cen.lote = lote
    le = cen.passagem("cq")
    dc.preparar(ex, "DF", [le])
    return le


def _donos(ex, les):
    return ex.todos(
        "SELECT c.responsavel, p.id_atividade, count(*) AS n FROM mapcartacomp.carga_trabalho c "
        "JOIN mapcartacomp.cq_plano p ON p.id = c.id_cq_plano WHERE c.id_lote_etapa = ANY(%s) "
        "GROUP BY 1, 2 ORDER BY 2, 1",
        (les,),
    )


def test_varias_pessoas_na_mesma_folha_por_proporcao(amb):
    cen, ex = amb
    a = cen.lote
    # Quem executou a folha (carga na aquisição) não avalia: regra fixa.
    aq = cen.passagem("aquisicao", "concluida")
    le_a = _cq(cen, ex, a)
    cen.cur.execute(
        "INSERT INTO mapcartacomp.carga_trabalho (uuid, id_lote_etapa, id_atividade, responsavel, concluido, geom) "
        "SELECT %s, %s, %s, 't_caio', true, geom FROM mapcartacomp.carga_trabalho WHERE id_lote_etapa = %s LIMIT 1",
        (str(uuid.uuid4()), aq, cen.ativ["aquisicao"], le_a),
    )
    b = _outra_folha(cen, "2535")
    le_b = _cq(cen, ex, b)

    s = dd.sugestao(ex, "DF", [a, b])
    assert [f["folha_revisao"][:4] for f in s["folhas"]] == ["2534", "2535"] and s["origem"] == "nenhuma"
    pessoas = {p["conta"]: p for p in s["pessoas"]}
    # Quem executou uma das folhas só fica fora dela: avalia a outra.
    assert pessoas["t_caio"]["motivo"] is None and [f[:4] for f in pessoas["t_caio"]["nao_avalia"]] == ["2534"]
    assert "avaliador (V)" in pessoas["t_apm"]["motivo"]
    assert pessoas["t_ana"]["motivo"] is None and not any(p["peso"] for p in s["pessoas"])  # ninguém marcado
    so_caio = dd.distribuir(ex, "DF", [a, b], {"t_caio": 1}, previa=True)
    n_a = sum(1 for _ in ex.todos("SELECT 1 FROM mapcartacomp.carga_trabalho WHERE id_lote_etapa = %s", (le_a,)))
    assert [(x["folha_revisao"][:4], x["amostras"]) for x in so_caio["sem_avaliador"]] == [("2534", n_a)]
    assert so_caio["pessoas"][0]["total"] == s["total"] - n_a and so_caio["excluidos"][0]["conta"] == "t_caio"
    # Com outra pessoa junto, a 2534 vai toda para ela, e o caio fica com a parte dele na 2535.
    caio_ana = dd.distribuir(ex, "DF", [a, b], {"t_caio": 1, "t_ana": 1}, previa=True)
    assert caio_ana["sem_avaliador"] == [] and sum(x["total"] for x in caio_ana["pessoas"]) == s["total"]
    # Só com a 2534, ele não pode avaliar nada: o servidor recusa.
    with pytest.raises(ErroDados, match="próprio trabalho"):
        dd.distribuir(ex, "DF", [a], {"t_caio": 1}, previa=True)

    # Prévia não muda nada; 3 para 1, as amostras das duas folhas juntas e cada elemento repartido.
    p = dd.distribuir(ex, "DF", [a, b], {"t_ana": 3, "t_bia": 1}, previa=True)
    assert p["movidas"] == s["total"] and not any(d["responsavel"] for d in _donos(ex, [le_a, le_b]))
    r = dd.distribuir(ex, "DF", [a, b], {"t_ana": 3, "t_bia": 1}, previa=False)
    assert r["pessoas"] == p["pessoas"]
    for e in s["elementos"]:
        n = {d["responsavel"]: d["n"] for d in _donos(ex, [le_a, le_b]) if d["id_atividade"] == e["id_atividade"]}
        assert set(n) == {"t_ana", "t_bia"} and n["t_ana"] + n["t_bia"] == e["amostras"]
        assert abs(n["t_ana"] - 3 * e["amostras"] / 4) < 1
    # As amostras das duas folhas se juntam em blocos contínuos (folha, grade): a ana fica com a 2534 e a bia com o
    # fim da 2535, que se divide entre as duas. A etapa começou nas duas, sem fila.
    assert {d["responsavel"] for d in _donos(ex, [le_a])} == {"t_ana"}
    assert {d["responsavel"] for d in _donos(ex, [le_b])} == {"t_ana", "t_bia"}
    for le in (le_a, le_b):
        assert ex.um("SELECT situacao FROM mapcartacomp.lote_etapa WHERE id = %s", (le,))["situacao"] == "em_andamento"
    assert (
        ex.um("SELECT count(*) AS n FROM mapcartacomp.fila_folha WHERE id_lote_etapa = ANY(%s)", ([le_a, le_b],))["n"]
        == 0
    )

    # Redistribuir: abre com a divisão atual; a ana avaliou duas, sai da divisão e as pendentes dela vão para a bia.
    assert dd.sugestao(ex, "DF", [a, b])["origem"] == "atual"
    feitas = [
        x["id"]
        for x in ex.todos(
            "SELECT id FROM mapcartacomp.carga_trabalho WHERE id_lote_etapa = %s AND responsavel = 't_ana' "
            "ORDER BY id LIMIT 2",
            (le_a,),
        )
    ]
    ex.executar("UPDATE mapcartacomp.carga_trabalho SET concluido = true, concluido_em = now() WHERE id = ANY(%s)",
                (feitas,))  # fmt: skip
    dd.distribuir(ex, "DF", [a, b], {"t_bia": 1}, previa=False)
    donos = ex.todos(
        "SELECT responsavel, concluido, count(*) AS n FROM mapcartacomp.carga_trabalho "
        "WHERE id_lote_etapa = ANY(%s) GROUP BY 1, 2 ORDER BY 1, 2",
        ([le_a, le_b],),
    )
    assert [(d["responsavel"], d["concluido"]) for d in donos] == [("t_ana", True), ("t_bia", False)]

    # A equipe é lembrada: a próxima folha de CQ da mesma etapa abre com a divisão da última distribuída.
    c = _outra_folha(cen, "2536")
    _cq(cen, ex, c)
    s2 = dd.sugestao(ex, "DF", [c])
    assert s2["origem"] == "ultima" and s2["origem_folha"][:4] in ("2534", "2535")
    pesos = {p["conta"]: p["peso"] for p in s2["pessoas"] if p["peso"]}
    assert set(pesos) <= {"t_ana", "t_bia"} and sum(pesos.values()) == s2["total"]


def test_folha_fora_do_cq_fica_de_fora_com_o_motivo(amb):
    cen, ex = amb
    cen.passagem("aquisicao")
    s = dd.sugestao(ex, "DF", [cen.lote])
    assert s["folhas"] == [] and "etapa de CQ" in s["fora"][0]["motivo"]
    with pytest.raises(ErroDados, match="amostras"):
        dd.distribuir(ex, "DF", [cen.lote], {"t_ana": 1}, previa=True)
