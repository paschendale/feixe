"""B4: gerar cargas pela grade estatística (prévia, gravar, recusas, folhas vizinhas). Transações desfeitas."""

from __future__ import annotations

import psycopg2.extras
import pytest
from feixe.core.dados import ErroDados, ExecutorPg
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


def _recusa(ex, fn, *args):
    ex.cur.execute("SAVEPOINT s")
    with pytest.raises(ErroDados) as e:
        fn(ex, *args)
    ex.cur.execute("ROLLBACK TO SAVEPOINT s")
    return e.value


def _cargas(ex, le):
    return ex.todos("SELECT geocodigo FROM mapcartacomp.carga_trabalho WHERE id_lote_etapa = %s", (le,))


def test_previa_nao_grava_e_gravar_cria_as_celulas_da_folha(amb):
    cen, ex = amb
    le = cen.passagem("aquisicao")
    previa = dc.gerar_pela_grade(ex, le, True)
    assert 105 <= previa["celulas"] <= 130 and previa["gravadas"] == 0  # 2534 em 5 km: 112 (D-79)
    assert previa["previa"][0]["geocodigo"].startswith("5KME") and previa["previa"][0]["wkt"].startswith("MULTIPOLYGON")
    assert _cargas(ex, le) == []
    r = dc.gerar_pela_grade(ex, le, False)
    assert r["gravadas"] == previa["celulas"]
    cargas = _cargas(ex, le)
    assert {c["geocodigo"] for c in cargas} == {c["geocodigo"] for c in previa["previa"]}
    assert ex.um(
        "SELECT bool_and(responsavel IS NULL AND NOT concluido) AS ok FROM mapcartacomp.carga_trabalho "
        "WHERE id_lote_etapa = %s",
        (le,),
    )["ok"]
    assert "já tem cargas" in _recusa(ex, dc.gerar_pela_grade, le, False).mensagem


def test_folhas_vizinhas_nao_dividem_celula(amb):
    cen, ex = amb
    le = cen.passagem("aquisicao")
    vizinha = ex.um("SELECT id_articulacao_scn AS id FROM mapcartctrl.v_articulacao_scn_100000 WHERE cd_mi = '2535'")
    lote = dl.criar_folhas(ex, "DF", cen.fluxo, [vizinha["id"]])["criados"][0]["id_lote"]
    le2 = ex.um("SELECT id FROM mapcartacomp.lote_etapa WHERE id_lote = %s", (lote,))["id"]
    dc.gerar_pela_grade(ex, le, False)
    dc.gerar_pela_grade(ex, le2, False)
    a, b = {c["geocodigo"] for c in _cargas(ex, le)}, {c["geocodigo"] for c in _cargas(ex, le2)}
    assert a and b and not (a & b)


def test_recusas(amb):
    cen, ex = amb
    encerrada = cen.passagem("aquisicao", "concluida")
    assert "encerrada" in _recusa(ex, dc.gerar_pela_grade, encerrada, True).mensagem
    cq = cen.passagem("cq")  # etapa de CQ: amostra, não grade
    assert "exatamente uma atividade" in _recusa(ex, dc.gerar_pela_grade, cq, True).mensagem
    le = cen.passagem("aquisicao", instancia=2)
    assert _recusa(ex, dc.gerar_pela_grade, le, True, "GO").status == 404
