"""B7: pré-seed do catálogo e regras de cadastro de temas e atividades. Transações desfeitas, nos dois bancos."""

from __future__ import annotations

import psycopg2.extras
import pytest
from feixe.core.dados import ErroDados, ExecutorPg
from feixe.core.dados import referencias as dr

from tests.db.migracoes import aplicar
from tests.db.test_regras import Cenario

pytestmark = pytest.mark.db


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


def test_pre_seed_das_atividades_do_bc100(amb):
    _, ex = amb
    por_nome = {a["nome"]: a for a in dr.atividades(ex) if a["projeto"] == "BC100"}
    assert por_nome["Aquisição BC100 - Hidrografia"]["grade_nivel"] == 5000
    assert por_nome["Aquisição BC100 - Áreas densamente edificadas"]["grade_nivel"] == 2500
    assert por_nome["Aquisição BC100 - LML"]["grade_nivel"] == 2500
    cq = [a for n, a in por_nome.items() if n.startswith("CQ BC100")]
    assert len(cq) == 7 and all(a["medida"] and a["grade_nivel"] == 5000 for a in cq)
    assert "CQ BC100 - Áreas densamente edificadas - Acurácia Temporal" in por_nome
    acuracia = next(e for e in dr.elementos_cq(ex) if e["nome"] == "Acurácia Temporal")
    assert acuracia["nucleo"] is False
    assert {t["nome"] for t in dr.temas(ex)} >= {"Hidrografia", "Áreas densamente edificadas", "LML"}


def _nova(cen, **kw):
    base = {"cod_projeto": 5, "id_tema": cen.tema, "fase": "aquisicao", "nome": "teste nova", "geracao": "grade",
            "grade_nivel": 2500}  # fmt: skip
    return {**base, **kw}


def test_criar_atividade_e_validacoes(amb):
    cen, ex = amb
    a = dr.criar_atividade(ex, _nova(cen))
    assert (a["grade_nivel"], a["ativo"], a["em_uso"]) == (2500, True, False)
    assert "já existe" in _recusa(ex, dr.criar_atividade, _nova(cen)).mensagem
    assert _recusa(ex, dr.criar_atividade, _nova(cen, nome="x", grade_nivel=4000)).status == 400
    assert _recusa(ex, dr.criar_atividade, _nova(cen, nome="x", grade_nivel=None)).status == 400
    assert "medida" in _recusa(ex, dr.criar_atividade, _nova(cen, nome="x", fase="cq")).mensagem
    medida = next(e["id"] for e in dr.elementos_cq(ex) if e["nome"] == "Omissão")
    cq = dr.criar_atividade(ex, _nova(cen, nome="teste CQ", fase="cq", geracao="amostra_area", grade_nivel=5000,
                                      id_medidadequalidade=medida))  # fmt: skip
    assert cq["medida"] == "Omissão"


def test_alterar_atividade_em_uso(amb):
    cen, ex = amb
    usada = cen.ativ["aquisicao"]  # está numa etapa do fluxo ativo do cenário
    a = dr.alterar_atividade(ex, usada, {"nome": "teste renomeada", "geracao": "grade", "grade_nivel": 5000})
    assert (a["nome"], a["grade_nivel"]) == ("teste renomeada", 5000)
    assert "fluxo ativo" in _recusa(ex, dr.alterar_atividade, usada, {"ativo": False}).mensagem
    assert "não mudam" in _recusa(ex, dr.alterar_atividade, usada, {"fase": "revisao"}).mensagem
    livre = dr.criar_atividade(ex, _nova(cen, nome="teste livre"))
    assert dr.alterar_atividade(ex, livre["id"], {"fase": "revisao", "ativo": False})["ativo"] is False


def test_temas(amb):
    cen, ex = amb
    t = dr.criar_tema(ex, " Vegetação ")
    assert t["nome"] == "Vegetação"
    assert "já existe" in _recusa(ex, dr.criar_tema, "vegetação").mensagem
    assert "atividades ativas" in _recusa(ex, dr.alterar_tema, cen.tema, None, False).mensagem
    assert dr.alterar_tema(ex, t["id"], "Vegetação nativa", False) == {
        "id": t["id"],
        "nome": "Vegetação nativa",
        "ativo": False,
    }
