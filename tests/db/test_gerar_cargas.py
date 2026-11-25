"""B4/D-109: as cargas pela grade estatística, geradas ao preparar a passagem (células da folha, folhas vizinhas).
Transações desfeitas."""

from __future__ import annotations

import psycopg2.extras
import pytest
from feixe.core.dados import ExecutorPg
from feixe.core.dados import cargas as dc
from feixe.core.dados import lotes as dl

from tests.db.migracoes import aplicar
from tests.db.test_regras import Cenario

pytestmark = pytest.mark.db


@pytest.fixture
def amb(banco):
    aplicar(banco)
    with banco.cursor() as cur, banco.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as dcur:
        cen = Cenario(cur)
        # A aquisição do cenário passa a gerar cargas pela grade de 5 km.
        cur.execute(
            "UPDATE mapcartacomp.atividade SET geracao = 'grade', grade_nivel = 5000 WHERE id = %s",
            (cen.ativ["aquisicao"],),
        )
        yield cen, ExecutorPg(dcur)


def _cargas(ex, le):
    return ex.todos("SELECT geocodigo FROM mapcartacomp.carga_trabalho WHERE id_lote_etapa = %s", (le,))


def test_preparar_cria_as_celulas_da_folha_e_nao_duplica(amb):
    cen, ex = amb
    le = cen.passagem("aquisicao")
    (g,) = dc.preparar(ex, "DF", [le])["geradas"]
    assert g["id_lote_etapa"] == le and 105 <= g["gravadas"] <= 130  # 2534 em 5 km: 112 (D-79)
    cargas = _cargas(ex, le)
    assert len(cargas) == g["gravadas"] == len({c["geocodigo"] for c in cargas})
    assert all(c["geocodigo"].startswith("5KME") for c in cargas)
    assert ex.um(
        "SELECT bool_and(responsavel IS NULL AND NOT concluido) AS ok FROM mapcartacomp.carga_trabalho "
        "WHERE id_lote_etapa = %s",
        (le,),
    )["ok"]
    assert dc.preparar(ex, "DF", [le])["geradas"] == [] and len(_cargas(ex, le)) == g["gravadas"]


def test_folhas_vizinhas_nao_dividem_celula(amb):
    cen, ex = amb
    le = cen.passagem("aquisicao")
    vizinha = ex.um("SELECT id_articulacao_scn AS id FROM mapcartctrl.v_articulacao_scn_100000 WHERE cd_mi = '2535'")
    lote = dl.criar_folhas(ex, "DF", cen.fluxo, [vizinha["id"]])["criados"][0]["id_lote"]
    le2 = ex.um("SELECT id FROM mapcartacomp.lote_etapa WHERE id_lote = %s", (lote,))["id"]
    dc.preparar(ex, "DF", [le, le2])
    a, b = {c["geocodigo"] for c in _cargas(ex, le)}, {c["geocodigo"] for c in _cargas(ex, le2)}
    assert a and b and not (a & b)


def test_passagem_encerrada_ou_de_outra_uf_fica_como_esta(amb):
    cen, ex = amb
    encerrada = cen.passagem("aquisicao", "concluida")
    le = cen.passagem("aquisicao", instancia=2)
    assert dc.preparar(ex, "DF", [encerrada]) == {"geradas": [], "iniciadas": [], "avisos": []}
    assert dc.preparar(ex, "GO", [le]) == {"geradas": [], "iniciadas": [], "avisos": []}
    assert _cargas(ex, encerrada) == [] and _cargas(ex, le) == []
