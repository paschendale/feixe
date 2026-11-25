"""B1/D-102: POST /api/camadas/montar calcula os subgrupos por atividade e entrega tudo ao QGIS."""

from contextlib import contextmanager

from feixe.core.dados import Executor
from feixe.server.api import Contexto, criar_roteador

_LINHA = {"id_tema": 1, "tema": "Hidrografia", "fase": "aquisicao", "ordem_fase": 1, "id_atividade": 7,
          "atividade": "Aquisição BC100 - Hidrografia", "conta": "u_1", "nome": "Fulano", "pendentes": 3,
          "concluidas": 1}  # fmt: skip


class _Ex(Executor):
    def __init__(self):
        self.sqls = []

    def todos(self, sql, params=None):
        self.sqls.append((sql, params))
        return [dict(_LINHA)]


def _ctx(papeis_):
    ex = _Ex()
    chamadas = []
    eventos = []

    @contextmanager
    def transacao():
        yield ex

    def qgis(nome, *args):
        chamadas.append((nome, args))
        return {"modo": "execucao", "camadas": [{"nome": "Minhas cargas", "feicoes": 3}]}

    ctx = Contexto(transacao=transacao, qgis=qgis, publicar=lambda e, d: eventos.append(e))
    ctx._eu = {"papeis": papeis_, "uf": "DF"}
    return ctx, ex, chamadas, eventos


def test_supervisor_recebe_subgrupos_e_responsaveis_da_uf():
    ctx, ex, chamadas, eventos = _ctx(["supervisor"])
    status, obj = criar_roteador(ctx).despachar("POST", "/api/camadas/montar", {}, None)
    assert status == 200 and obj["camadas"][0]["nome"] == "Minhas cargas"
    nome, (eu, responsaveis, supervisao, execucao) = chamadas[0]
    assert nome == "montar_camadas" and responsaveis[0]["conta"] == "u_1"
    assert supervisao == execucao == [
        {"chave": "a-7", "rotulo": "Aquisição BC100 - Hidrografia", "id_tema": 1, "tema": "Hidrografia",
         "fase": "aquisicao", "atividades": [7]}
    ]  # fmt: skip
    assert [p for _, p in ex.sqls] == [None, ("DF", "DF"), ("DF", "DF")]
    assert eventos == ["qgis"]


def test_apm_so_tem_execucao_e_sem_papel_recebe_403():
    ctx, ex, chamadas, _ = _ctx(["apm"])
    assert criar_roteador(ctx).despachar("POST", "/api/camadas/montar", {}, None)[0] == 200
    assert len(ex.sqls) == 1 and chamadas[0][1][1] == [] and chamadas[0][1][2] == []
    ctx, _, _, _ = _ctx([])
    assert criar_roteador(ctx).despachar("POST", "/api/camadas/montar", {}, None)[0] == 403
