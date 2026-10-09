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
    assert r.despachar("GET", "/api/folhas", {}, None)[0] == 503
    assert r.despachar("POST", "/api/folhas/1/zoom", {}, None)[0] == 503
    assert r.despachar("POST", "/api/sincronizar", {}, None)[0] == 501


def test_folhas_consulta_e_zoom():
    chamadas = []

    def consultar(sql, params):
        chamadas.append((sql, params))
        return [{"id": 1, "cd_mi": "2534", "xmin": -48.0, "ymin": -16.0, "xmax": -47.5, "ymax": -15.5}]

    zooms = []
    ctx = Contexto(consultar=consultar, zoom_para=lambda *a: zooms.append(a))
    r = criar_roteador(ctx)
    status, obj = r.despachar("GET", "/api/folhas", {"q": "25", "limite": "5"}, None)
    assert status == 200 and obj["itens"][0]["cd_mi"] == "2534"
    assert chamadas[-1][1] == ("%25%", "%25%", "%25%", 5)
    status, obj = r.despachar("POST", "/api/folhas/1/zoom", {}, None)
    assert status == 200 and zooms == [(-48.0, -16.0, -47.5, -15.5, 4674)]


def test_erro_inesperado_vira_500():
    def consultar(sql, params):
        raise RuntimeError("boom")

    r = criar_roteador(Contexto(consultar=consultar))
    status, obj = r.despachar("GET", "/api/folhas", {}, None)
    assert status == 500 and "boom" in obj["erro"]
