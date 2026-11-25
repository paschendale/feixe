"""B1/D-102/C4: POST /api/camadas/montar calcula os subgrupos por atividade e entrega tudo ao QGIS. A execução vem do
workspace (o cenário de tests/sync/conftest.py), online ou offline; a supervisão, da CCAR (aqui substituída)."""

from contextlib import contextmanager

import pytest
from feixe.core.dados import Executor
from feixe.server.api import Contexto, criar_roteador
from feixe.server.rotas.camadas import SUPERVISAO_SEM_CCAR
from feixe.sync.workspace import Workspace

from tests.sync.conftest import USUARIO, popular

_LINHA = {"id_tema": 1, "tema": "Hidrografia", "fase": "aquisicao", "ordem_fase": 1, "id_atividade": 7,
          "atividade": "Aquisição BC100 - Hidrografia", "conta": "u_1", "nome": "Fulano", "pendentes": 3,
          "concluidas": 1}  # fmt: skip
# Do workspace: as cargas abertas de u_apm são da atividade 100, na passagem 11.
EXECUCAO = [{"chave": "a-100", "rotulo": "Aquisição BC100 - Hidrografia", "id_tema": 1, "tema": "Hidrografia",
             "fase": "aquisicao", "atividades": [100]}]  # fmt: skip


class _Ex(Executor):
    def __init__(self):
        self.sqls = []

    def todos(self, sql, params=None):
        self.sqls.append((sql, params))
        return [dict(_LINHA)]


@pytest.fixture
def ws(tmp_path):
    w = Workspace.abrir("dev", USUARIO, "DF", raiz=str(tmp_path))
    popular(w)
    yield w
    w.fechar()


@pytest.fixture
def ctx_de(ws):
    def fazer(papeis_, online=None):
        ex = _Ex()
        chamadas = []
        eventos = []

        @contextmanager
        def transacao():
            yield ex

        def qgis(nome, *args):
            chamadas.append((nome, args))
            return {"modo": "execucao", "camadas": [{"nome": "Minhas cargas", "feicoes": 3}]}

        ctx = Contexto(transacao=transacao, qgis=qgis, publicar=lambda e, d: eventos.append(e),
                       workspace=lambda: ws, online=online)  # fmt: skip
        ctx._eu = {"papeis": papeis_, "uf": "DF"}
        return ctx, ex, chamadas, eventos

    return fazer


def test_supervisor_recebe_subgrupos_e_responsaveis_da_uf(ctx_de, ws):
    ctx, ex, chamadas, eventos = ctx_de(["supervisor"])
    status, obj = criar_roteador(ctx).despachar("POST", "/api/camadas/montar", {}, None)
    assert status == 200 and obj["camadas"][0]["nome"] == "Minhas cargas" and obj["avisos"] == []
    nome, (eu, responsaveis, supervisao, execucao, gpkg) = chamadas[0]
    assert nome == "montar_camadas" and responsaveis[0]["conta"] == "u_1" and gpkg == ws.caminho
    assert supervisao == [
        {"chave": "a-7", "rotulo": "Aquisição BC100 - Hidrografia", "id_tema": 1, "tema": "Hidrografia",
         "fase": "aquisicao", "atividades": [7]}
    ]  # fmt: skip
    assert execucao == EXECUCAO  # do workspace, não da CCAR
    assert [p for _, p in ex.sqls] == [("DF", "DF"), ("DF", "DF")]
    assert eventos == ["qgis"]


def test_apm_so_tem_execucao_do_workspace_e_sem_papel_recebe_403(ctx_de):
    ctx, ex, chamadas, _ = ctx_de(["apm"])
    assert criar_roteador(ctx).despachar("POST", "/api/camadas/montar", {}, None)[0] == 200
    assert ex.sqls == [] and chamadas[0][1][1] == [] and chamadas[0][1][2] is None and chamadas[0][1][3] == EXECUCAO
    ctx, _, _, _ = ctx_de([])
    assert criar_roteador(ctx).despachar("POST", "/api/camadas/montar", {}, None)[0] == 403


def test_sem_a_ccar_monta_so_a_execucao_com_aviso(ctx_de):
    """Offline: a execução monta do workspace; a supervisão fica de fora (None) e a pessoa é avisada."""
    ctx, ex, chamadas, _ = ctx_de(["supervisor"], online=lambda: False)
    status, obj = criar_roteador(ctx).despachar("POST", "/api/camadas/montar", {}, None)
    assert status == 200 and obj["avisos"] == [SUPERVISAO_SEM_CCAR]
    _, (eu, responsaveis, supervisao, execucao, _) = chamadas[0]
    assert ex.sqls == [] and supervisao is None and responsaveis == [] and execucao == EXECUCAO


def test_conexao_que_cai_no_meio_vira_o_mesmo_aviso(ctx_de):
    psycopg2 = pytest.importorskip("psycopg2")

    ctx, _, chamadas, _ = ctx_de(["supervisor"])

    @contextmanager
    def caiu():
        raise psycopg2.OperationalError("server closed the connection unexpectedly")
        yield  # pragma: no cover

    ctx._transacao = caiu
    status, obj = criar_roteador(ctx).despachar("POST", "/api/camadas/montar", {}, None)
    assert status == 200 and obj["avisos"] == [SUPERVISAO_SEM_CCAR] and chamadas[0][1][2] is None
