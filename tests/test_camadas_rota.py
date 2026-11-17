"""B1: POST /api/camadas/montar consulta os responsáveis só para supervisor e entrega tudo ao QGIS."""

from contextlib import contextmanager

from feixe.core.dados import Executor
from feixe.server.api import Contexto, criar_roteador


class _Ex(Executor):
    def __init__(self):
        self.sqls = []

    def todos(self, sql, params=None):
        self.sqls.append((sql, params))
        return [{"conta": "u_1", "nome": "Fulano", "cargas": 3}]


def _ctx(papeis_):
    ex = _Ex()
    chamadas = []
    eventos = []

    @contextmanager
    def transacao():
        yield ex

    def qgis(nome, *args):
        chamadas.append((nome, args))
        return {"camadas": [{"nome": "Minhas cargas", "feicoes": 3}]}

    ctx = Contexto(transacao=transacao, qgis=qgis, publicar=lambda e, d: eventos.append(e))
    ctx._eu = {"papeis": papeis_, "uf": "DF"}
    return ctx, ex, chamadas, eventos


def test_supervisor_recebe_responsaveis_da_uf():
    ctx, ex, chamadas, eventos = _ctx(["supervisor"])
    status, obj = criar_roteador(ctx).despachar("POST", "/api/camadas/montar", {}, None)
    assert status == 200 and obj["camadas"][0]["nome"] == "Minhas cargas"
    nome, (eu, responsaveis, temas, modulos) = chamadas[0]
    assert nome == "montar_camadas" and responsaveis[0]["conta"] == "u_1" and modulos is None
    assert ex.sqls[0][1] == ("DF",) and ex.sqls[1][1] == ("DF", "DF")
    assert eventos == ["qgis"]


def test_apm_nao_consulta_responsaveis_e_sem_papel_recebe_403():
    ctx, ex, chamadas, _ = _ctx(["apm"])
    assert criar_roteador(ctx).despachar("POST", "/api/camadas/montar", {}, None)[0] == 200
    assert len(ex.sqls) == 1 and chamadas[0][1][1] == []  # só os temas
    ctx, _, _, _ = _ctx([])
    assert criar_roteador(ctx).despachar("POST", "/api/camadas/montar", {}, None)[0] == 403


def test_um_modulo_so_consulta_o_que_precisa():
    ctx, ex, chamadas, _ = _ctx(["supervisor"])
    r = criar_roteador(ctx)
    assert r.despachar("POST", "/api/camadas/montar", {}, {"modulos": ["minhas"]})[0] == 200
    assert ex.sqls == [] and chamadas[0][1][3] == ["minhas"]
    assert r.despachar("POST", "/api/camadas/montar", {}, {"modulos": ["folhas"]})[0] == 200
    assert len(ex.sqls) == 1 and chamadas[1][1][1] == []  # só os temas, sem responsáveis


def test_modulo_equipe_so_para_supervisor_e_modulo_desconhecido():
    ctx, _, chamadas, _ = _ctx(["apm"])
    r = criar_roteador(ctx)
    assert r.despachar("POST", "/api/camadas/montar", {}, {"modulos": ["equipe"]})[0] == 403
    assert r.despachar("POST", "/api/camadas/montar", {}, {"modulos": ["xyz"]})[0] == 400
    assert r.despachar("POST", "/api/camadas/montar", {}, {"modulos": []})[0] == 400
    assert chamadas == []
