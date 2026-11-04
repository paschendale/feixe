"""feixe.core.papeis: identidade e papéis só pelo SGBC e por usuario_feixe."""

from __future__ import annotations

import pytest
from feixe.core import papeis


def _conta(**kw):
    base = {
        "cod_usuario": 10,
        "nom_contausuario": "u_1234567",
        "nom_usuario": "Fulana de Tal",
        "num_siape": 1234567,
        "dsc_lotacao": "DF",
        "ind_contaativa": True,
        "ind_contasistema": False,
        "ind_contasuper": False,
    }
    base.update(kw)
    return base


@pytest.mark.parametrize(
    "mudanca,esperado",
    [
        ({}, True),
        ({"ind_contaativa": False}, False),
        ({"ind_contaativa": None}, False),
        ({"ind_contasistema": True}, False),
        ({"ind_contasuper": True}, False),
        ({"ind_contasistema": None, "ind_contasuper": None}, True),
    ],
)
def test_elegibilidade(mudanca, esperado):
    assert papeis.elegivel(_conta(**mudanca)) is esperado


def test_conta_inexistente_nao_e_elegivel():
    assert papeis.elegivel(None) is False


@pytest.mark.parametrize(
    "lotacao,uf",
    [("DF", "DF"), (" go ", "GO"), ("RJ", "RJ"), (None, None), ("", None), ("CCAR", None), ("D1", None)],
)
def test_uf_da_lotacao(lotacao, uf):
    assert papeis.uf_da_lotacao(lotacao) == uf


def test_papel_por_perfil_do_sgbc():
    assert {p: papeis.papel_do_perfil(p) for p in "SOVCI"} == {
        "S": "supervisor",
        "O": "apm",
        "V": "avaliador",
        "C": "consulta",
        "I": None,
    }


def test_montar_com_perfis_e_gerente():
    perfis = [
        {"cod_projeto": 5, "projeto": "BC100", "perfil": "S"},
        {"cod_projeto": 2, "projeto": "BC250", "perfil": "O"},
        {"cod_projeto": 7, "projeto": "RJ25", "perfil": "I"},
    ]
    eu = papeis.montar("u_1234567", _conta(), perfis, {"equipe": "GGC-DF", "gerente": True, "ativo": True})
    assert eu["nome"] == "Fulana de Tal" and eu["uf"] == "DF" and eu["elegivel"]
    assert eu["papeis"] == ["gerente", "supervisor", "apm"]
    assert eu["papel"] == "gerente" and eu["papel_rotulo"] == "Gerente"
    assert eu["equipe"] == "GGC-DF"
    assert [p["papel"] for p in eu["perfis"]] == ["supervisor", "apm", None]


def test_gbc_e_lotacao_rj_como_qualquer_outra():
    eu = papeis.montar("u_1", _conta(dsc_lotacao="RJ"), [{"cod_projeto": 5, "projeto": "BC100", "perfil": "O"}], None)
    assert eu["uf"] == "RJ" and eu["papel"] == "apm" and eu["gerente"] is False and eu["equipe"] is None


def test_uf_nula_continua_identificada():
    eu = papeis.montar("u_2", _conta(dsc_lotacao=None), [{"cod_projeto": 5, "projeto": "BC100", "perfil": "V"}], None)
    assert eu["uf"] is None and eu["lotacao"] is None and eu["papel"] == "avaliador" and eu["nome"] == "Fulana de Tal"


def test_conta_inelegivel_nao_recebe_papel():
    eu = papeis.montar(
        "postgres",
        _conta(nom_usuario="postgres", ind_contasistema=True),
        [{"cod_projeto": 5, "projeto": "BC100", "perfil": "S"}],
        {"equipe": None, "gerente": True, "ativo": True},
    )
    assert eu["elegivel"] is False and eu["papeis"] == [] and eu["papel"] is None and eu["gerente"] is False
    assert eu["papel_rotulo"] == "Sem papel" and eu["perfis"][0]["perfil"] == "S"


def test_usuario_feixe_inativo_nao_da_gerente():
    eu = papeis.montar("u_1", _conta(), [], {"equipe": "X", "gerente": True, "ativo": False})
    assert eu["gerente"] is False and eu["equipe"] is None and eu["papel"] is None


def test_conta_fora_do_sgbc():
    eu = papeis.montar("alguem", None, [], None)
    assert eu["cadastrada"] is False and eu["nome"] == "alguem" and eu["uf"] is None and eu["elegivel"] is False


def test_carregar_usa_current_user_e_nao_consulta_roles():
    chamadas = []

    def consultar(sql, params):
        chamadas.append((sql, params))
        if sql == papeis.SQL_CONTA_ATUAL:
            return [{"conta": "u_1234567"}]
        if sql == papeis.SQL_USUARIO:
            return [_conta()]
        if sql == papeis.SQL_PERFIS:
            assert params == (10,)
            return [{"cod_projeto": 5, "projeto": "BC100", "perfil": "S"}]
        if sql == papeis.SQL_FEIXE:
            return [{"equipe": "GGC-DF", "gerente": False, "ativo": True}]
        raise AssertionError(sql)

    eu = papeis.carregar(consultar)
    assert eu["conta"] == "u_1234567" and eu["papel"] == "supervisor" and eu["equipe"] == "GGC-DF"
    for sql, _ in chamadas:
        assert "pg_roles" not in sql and "pg_auth_members" not in sql and "pg_has_role" not in sql
