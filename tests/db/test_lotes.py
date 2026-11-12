"""B3: criar folhas e lotes livres, listar e achar a folha no ponto, pela camada de dados. Transações desfeitas."""

from __future__ import annotations

import psycopg2.extras
import pytest
from feixe.core.dados import ErroDados, ExecutorPg
from feixe.core.dados import lotes as dl

from tests.db.migracoes import aplicar
from tests.db.test_regras import Cenario

pytestmark = pytest.mark.db

QUADRADO = "POLYGON((-47.9 -15.9, -47.8 -15.9, -47.8 -15.8, -47.9 -15.8, -47.9 -15.9))"
GRAVATA = "POLYGON((-47.9 -15.9, -47.8 -15.8, -47.8 -15.9, -47.9 -15.8, -47.9 -15.9))"


@pytest.fixture
def amb(banco):
    aplicar(banco)
    with banco.cursor() as cur, banco.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as dcur:
        yield Cenario(cur), ExecutorPg(dcur)


def _recusa(ex, fn, *args):
    ex.cur.execute("SAVEPOINT s")
    with pytest.raises(ErroDados) as e:
        fn(ex, *args)
    ex.cur.execute("ROLLBACK TO SAVEPOINT s")
    return e.value


def _folha(ex, mi):
    return ex.um("SELECT id_articulacao_scn AS id FROM mapcartctrl.v_articulacao_scn_100000 WHERE cd_mi = %s", (mi,))[
        "id"
    ]


def test_criar_folhas_comeca_na_primeira_etapa_e_nao_duplica(amb):
    cen, ex = amb  # o cenário já tem a 2534 neste projeto e tema
    r = dl.criar_folhas(ex, "DF", cen.fluxo, [_folha(ex, "2534"), _folha(ex, "2535")])
    assert [c["cd_mi"] for c in r["criados"]] == ["2535"]
    assert [e["cd_mi"] for e in r["existentes"]] == ["2534"]
    lote = dl.um(ex, r["criados"][0]["id_lote"])
    assert lote["tipo"] == "folha" and lote["nome"] == "2535" and lote["uf"] == "DF"
    assert [(p["etapa"], p["situacao"], p["instancia"]) for p in lote["passagens"]] == [
        ("Etapa aquisicao", "pendente", 1)
    ]
    assert lote["xmin"] is not None  # geometria vem da articulação
    assert any(x["id"] == lote["id"] for x in dl.listar(ex, "DF", cen.tema))


def test_fluxo_de_outra_uf_ou_folha_inexistente_sao_recusados(amb):
    cen, ex = amb
    assert _recusa(ex, dl.criar_folhas, "GO", cen.fluxo, [_folha(ex, "2535")]).status == 404
    assert _recusa(ex, dl.criar_folhas, "DF", cen.fluxo, [-1]).status == 404
    assert _recusa(ex, dl.criar_folhas, "DF", cen.fluxo, []).status == 400


def test_lote_livre(amb):
    cen, ex = amb
    r = dl.criar_livre(ex, "DF", cen.fluxo, " Bacia do Paranoá ", QUADRADO)
    lote = dl.um(ex, r["criados"][0]["id_lote"])
    assert (lote["tipo"], lote["nome"], len(lote["passagens"])) == ("livre", "Bacia do Paranoá", 1)
    assert "já existe" in _recusa(ex, dl.criar_livre, "DF", cen.fluxo, "Bacia do Paranoá", QUADRADO).mensagem
    assert "inválida" in _recusa(ex, dl.criar_livre, "DF", cen.fluxo, "Gravata", GRAVATA).mensagem
    assert _recusa(ex, dl.criar_livre, "DF", cen.fluxo, "Linha", "LINESTRING(-47.9 -15.9, -47.8 -15.8)").status == 400
    assert _recusa(ex, dl.criar_livre, "DF", cen.fluxo, "  ", QUADRADO).status == 400


def test_folha_no_ponto_e_fluxos(amb):
    cen, ex = amb
    c = ex.um(
        "SELECT ST_X(ST_PointOnSurface(geom)) AS x, ST_Y(ST_PointOnSurface(geom)) AS y "
        "FROM mapcartctrl.v_articulacao_scn_100000 WHERE cd_mi = '2534'"
    )
    assert dl.folha_no_ponto(ex, c["x"], c["y"])["cd_mi"] == "2534"
    assert dl.folha_no_ponto(ex, 0.0, 0.0) is None  # no mar
    f = next(f for f in dl.fluxos(ex, "DF", 5, cen.tema) if f["id"] == cen.fluxo)
    assert f["primeira_etapa"] == "Etapa aquisicao" and f["projeto"]
