from feixe.server.api import Contexto, Roteador, criar_roteador


def test_roteador_parametros_e_metodos():
    r = Roteador()

    @r.rota("GET", "/api/x/{id}")
    def _x(req):
        return 200, {"id": req.params["id"], "q": req.query.get("q")}

    assert r.despachar("GET", "/api/x/42", {"q": "a"}, None) == (200, {"id": "42", "q": "a"})
    assert r.despachar("POST", "/api/x/42", {}, None)[0] == 405
    assert r.despachar("GET", "/api/nada", {}, None)[0] == 404


def test_rotas_sem_banco_respondem_503():
    r = criar_roteador(Contexto(status=lambda: {"online": False}))
    assert r.despachar("GET", "/api/status", {}, None) == (200, {"online": False})
    assert r.despachar("GET", "/api/eu", {}, None)[0] == 503


def test_busca_de_folhas_pela_camada_de_dados():
    from contextlib import contextmanager

    from feixe.core.dados import Executor

    chamadas = []

    class Falso(Executor):
        def todos(self, sql, params=None):
            chamadas.append((sql, params))
            return [{"id": 1, "cd_mi": "2534", "xmin": -48.0, "ymin": -16.0, "xmax": -47.5, "ymax": -15.5}]

    @contextmanager
    def tx():
        yield Falso()

    ctx = Contexto(transacao=tx)
    ctx._eu = {"papeis": ["supervisor"], "uf": "DF", "perfis": []}
    r = criar_roteador(ctx)
    status, obj = r.despachar("GET", "/api/folhas", {"q": "25", "limite": "5"}, None)
    assert status == 200 and obj["itens"][0]["cd_mi"] == "2534"
    assert chamadas[-1][1] == ("%25%", "%25%", "%25%", "25", "25%", "25%", 5)
    assert r.despachar("GET", "/api/folhas", {"limite": "5000"}, None)[0] == 200 and chamadas[-1][1] == (1000,)
    ctx._eu = {"papeis": ["apm"], "uf": "DF", "perfis": []}
    assert r.despachar("GET", "/api/folhas", {}, None)[0] == 403


def test_erro_inesperado_vira_500():
    def consultar(sql, params):
        raise RuntimeError("boom")

    r = criar_roteador(Contexto(consultar=consultar))
    status, obj = r.despachar("GET", "/api/eu", {}, None)
    assert status == 500 and "boom" in obj["erro"]


def test_eu_com_consultar_falso():
    """GET /api/eu monta identidade e papel só com o SGBC e usuario_feixe; nenhuma consulta a roles do banco."""
    from feixe.core import papeis

    vistos = []

    def consultar(sql, params):
        vistos.append(sql)
        if sql == papeis.SQL_CONTA_ATUAL:
            return [{"conta": "u_7654321"}]
        if sql == papeis.SQL_USUARIO:
            return [
                {
                    "cod_usuario": 42,
                    "nom_contausuario": "u_7654321",
                    "nom_usuario": "Beltrano",
                    "num_siape": 7654321,
                    "dsc_lotacao": None,
                    "ind_contaativa": True,
                    "ind_contasistema": False,
                    "ind_contasuper": False,
                }
            ]
        if sql == papeis.SQL_PERFIS:
            return [{"cod_projeto": 5, "projeto": "BC100", "perfil": "S"}]
        if sql == papeis.SQL_FEIXE:
            return []
        raise AssertionError(sql)

    status, eu = criar_roteador(Contexto(consultar=consultar)).despachar("GET", "/api/eu", {}, None)
    assert status == 200
    assert eu["conta"] == "u_7654321" and eu["nome"] == "Beltrano"
    assert eu["uf"] is None and eu["papel"] == "supervisor" and eu["papel_rotulo"] == "Supervisor"
    assert eu["gerente"] is False and eu["equipe"] is None
    assert not any("pg_roles" in s or "pg_auth_members" in s or "pg_has_role" in s for s in vistos)


def test_eu_sem_banco():
    assert criar_roteador(Contexto()).despachar("GET", "/api/eu", {}, None)[0] == 503
