"""D3a: rotas do CQ da execução sobre um workspace de verdade (o cenário de tests/sync/test_cq_execucao.py) e a das
ocorrências da folha para o supervisor, com a camada de dados da CCAR substituída (a de verdade é testada contra o
banco em tests/sync/test_cq_sync.py)."""

from contextlib import contextmanager

import pytest
from feixe.core.dados import cq as dq
from feixe.server.api import Contexto, criar_roteador
from feixe.sync.workspace import Workspace

from tests.sync.conftest import USUARIO, popular
from tests.sync.test_cq_execucao import cq  # noqa: F401 - fixture


@pytest.fixture
def ws(tmp_path):
    w = Workspace.abrir("dev", USUARIO, "DF", raiz=str(tmp_path))
    popular(w)
    with w.transacao() as ex:
        ex.definir_meta("ultima_sincronizacao", "2026-11-24T12:00:00.000000Z")
    yield w
    w.fechar()


@pytest.fixture
def montar(ws):
    chamadas = {"qgis": [], "eventos": [], "acordar": []}

    def fazer(papeis):
        @contextmanager
        def tx():
            yield object()

        ctx = Contexto(
            transacao=tx,
            publicar=lambda e, d: chamadas["eventos"].append((e, d)),
            qgis=lambda nome, *a: chamadas["qgis"].append(nome),
            workspace=lambda: ws,
            acordar=chamadas["acordar"].append,
        )
        ctx._eu = {"papeis": papeis, "uf": "DF", "perfis": []}
        return criar_roteador(ctx), chamadas

    return fazer


def test_amostras_e_avaliar(montar, cq):  # noqa: F811
    r, ch = montar(["avaliador"])
    status, obj = r.despachar("GET", "/api/amostras", {"situacao": "pendente"}, None)
    assert status == 200 and [a["id"] for a in obj["itens"]] == [9001, 9002, 9009]
    assert r.despachar("GET", "/api/amostras", {"situacao": "talvez"}, None)[0] == 400
    status, obj = r.despachar("POST", "/api/amostras/9001", {}, {"status": 0, "observacao": "faltou"})
    assert status == 200 and obj["carga"]["concluido"] is True and obj["proxima"]["amostra"]["id"] == 9002
    assert {e for e, _ in ch["eventos"]} >= {"carga", "cq"} and ch["qgis"] == ["cargas_mudaram"]
    assert ch["acordar"] == [None]
    assert r.despachar("POST", "/api/amostras/9001", {}, {"status": 3})[0] == 400
    assert r.despachar("POST", "/api/amostras/9001", {}, {"status": True})[0] == 400
    assert r.despachar("POST", "/api/amostras/9003", {}, {"status": 1})[0] == 403
    assert r.despachar("POST", "/api/amostras/9009", {}, {"status": 1})[0] == 409
    r, _ = montar(["consulta"])
    assert r.despachar("GET", "/api/amostras", {}, None)[0] == 403


def test_ocorrencia_registrar_editar_ciente_e_apagar(montar, cq):  # noqa: F811
    r, ch = montar(["avaliador", "apm"])
    status, obj = r.despachar(
        "POST", "/api/inspecoes", {}, {"x": -47.89, "y": -15.79, "id_carga_trabalho": 4001, "anotacao": "trecho"}
    )
    assert status == 200 and obj["ocorrencia"]["minha"] and obj["amostra"]["ocorrencias"] == 1
    u = obj["ocorrencia"]["uuid"]
    assert r.despachar("POST", "/api/inspecoes", {}, {"x": -47.89, "id_carga_trabalho": 4001})[0] == 400
    status, obj = r.despachar("POST", f"/api/inspecoes/{u}", {}, {"anotacao": "outro trecho"})
    assert status == 200 and obj["ocorrencia"]["anotacao"] == "outro trecho"
    assert r.despachar("POST", f"/api/inspecoes/{u}", {}, {"x": -47.8})[0] == 400  # ponto sem y
    assert r.despachar("POST", "/api/inspecoes/nao-e-uuid", {}, {"anotacao": "x"})[0] == 400
    status, obj = r.despachar("GET", "/api/inspecoes", {"id_lote": "1"}, None)
    assert status == 200 and {o["uuid"] for o in obj["itens"]} == {u, cq["autor"]}
    status, obj = r.despachar("POST", f"/api/inspecoes/{cq['autor']}/ciente", {}, None)
    assert status == 200 and obj["ocorrencia"]["ciente_por"] == USUARIO
    assert r.despachar("POST", f"/api/inspecoes/{cq['outro']}/ciente", {}, None)[0] == 403
    status, obj = r.despachar("DELETE", f"/api/inspecoes/{u}", {}, None)
    assert status == 200 and obj["apagada"] == u
    assert r.despachar("DELETE", f"/api/inspecoes/{cq['autor']}", {}, None)[0] == 403
    assert [e for e, _ in ch["eventos"]].count("cq") == 4


def test_ocorrencias_da_folha_para_o_supervisor(montar, monkeypatch):
    visto = {}

    def falso(ex, uf, id_lote):
        visto.update(uf=uf, id_lote=id_lote)
        return {"id_lote": id_lote, "itens": [], "total": 0, "pendentes": 0, "sem_ciente": 0}

    monkeypatch.setattr(dq, "ocorrencias_do_lote", falso)
    r, _ = montar(["supervisor"])
    status, obj = r.despachar("GET", "/api/lotes/5/ocorrencias", {}, None)
    assert status == 200 and obj["id_lote"] == 5 and visto == {"uf": "DF", "id_lote": 5}
    r, _ = montar(["apm"])
    assert r.despachar("GET", "/api/lotes/5/ocorrencias", {}, None)[0] == 403
