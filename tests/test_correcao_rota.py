"""D5: rotas da correção de inspeção sobre um workspace de verdade (o cenário de tests/sync/test_correcao_execucao.py):
tratar e desmarcar, a próxima ocorrência levando o QGIS até ela, o painel da Execução › Correção e a próxima carga
deixando a carga da folha de fora."""

from tests.sync.test_correcao_execucao import corr  # noqa: F401 - fixture
from tests.test_cq_execucao_rota import montar, ws  # noqa: F401 - fixtures


def test_tratar_desmarcar_e_recusas(montar, corr):  # noqa: F811
    r, ch = montar(["operador"])
    status, obj = r.despachar("POST", f"/api/inspecoes/{corr['r2']}/tratar", {}, {"tratado": True})
    assert status == 200 and obj["ocorrencia"]["tratado"] is True and obj["proxima"]["uuid"] == corr["r1"]
    assert obj["progresso"]["tratadas"] == 2 and ch["acordar"] == [None]
    assert {e for e, _ in ch["eventos"]} >= {"carga", "cq"} and ch["qgis"] == ["cargas_mudaram"]
    status, obj = r.despachar("POST", f"/api/inspecoes/{corr['r1']}/tratar", {}, None)  # sem corpo: marca
    assert status == 200 and obj["progresso"]["pendentes"] == 0 and obj["proxima"] is None
    status, obj = r.despachar("POST", f"/api/inspecoes/{corr['r1']}/tratar", {}, {"tratado": False})
    assert status == 200 and obj["ocorrencia"]["tratado"] is False and obj["progresso"]["pendentes"] == 1
    assert r.despachar("POST", f"/api/inspecoes/{corr['r1']}/tratar", {}, {"tratado": "sim"})[0] == 400
    assert r.despachar("POST", f"/api/inspecoes/{corr['outra_folha']}/tratar", {}, None)[0] == 403
    assert r.despachar("POST", "/api/inspecoes/nao-e-uuid/tratar", {}, None)[0] == 400
    r, _ = montar(["consulta"])
    assert r.despachar("POST", f"/api/inspecoes/{corr['r1']}/tratar", {}, None)[0] == 403


def test_proxima_ocorrencia_painel_e_proxima_carga(montar, corr):  # noqa: F811
    r, ch = montar(["operador"])
    status, obj = r.despachar("POST", "/api/inspecoes/proxima", {}, {"id_lote": 1})
    assert status == 200 and obj["ocorrencia"]["uuid"] in (corr["r1"], corr["r2"])
    assert obj["progresso"]["folha_revisao"] == "2534-2" and ch["qgis"] == ["focar_ocorrencia"]
    status, obj = r.despachar("POST", "/api/inspecoes/proxima", {}, {"id_lote": 2})
    assert status == 200 and obj == {"ocorrencia": None, "progresso": None}
    status, obj = r.despachar("GET", "/api/painel/execucao", {}, None)
    (f,) = obj["correcao"]
    assert f["total"] == 3 and f["tratadas"] == 1 and f["so_folha"] is True
    assert {o["avaliador"] for o in f["ocorrencias"]} == {"u_aval"}  # sem a CCAR, a conta
    status, obj = r.despachar("POST", "/api/cargas/proxima", {}, {})
    assert status == 200 and obj["carga"]["id"] != 6001
