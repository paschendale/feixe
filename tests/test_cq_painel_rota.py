"""D3d: as rotas novas do painel do CQ sobre um workspace de verdade (cenário de tests/sync/test_cq_execucao.py), com
a CCAR substituída: o bloco de CQ e de ciência em /api/painel/execucao (nomes dos avaliadores pela CCAR, quando ela
responde), a próxima amostra da folha, o "Ciente em todas desta folha" e o "Ver no QGIS" das ocorrências."""

from contextlib import contextmanager

import pytest
from feixe.core.dados import cq as dq
from feixe.core.dados import painel as dp
from feixe.server.api import Contexto, criar_roteador
from feixe.server.rotas import painel as rp

from tests.sync.test_cq_execucao import cq  # noqa: F401 - fixture
from tests.test_cq_execucao_rota import ws  # noqa: F401 - fixture


@pytest.fixture
def montar(ws, monkeypatch):  # noqa: F811
    monkeypatch.setattr(rp, "_NOMES", {})

    def fazer(papeis, online=True):
        ch = {"qgis": [], "eventos": [], "zoom": [], "tx": 0}

        @contextmanager
        def tx():
            ch["tx"] += 1
            yield object()

        ctx = Contexto(
            transacao=tx,
            publicar=lambda e, d: ch["eventos"].append((e, d)),
            qgis=lambda nome, *a: ch["qgis"].append(nome),
            workspace=lambda: ws,
            acordar=lambda atraso=None: None,
            online=lambda: online,
            zoom_para=lambda *a: ch["zoom"].append(a),
        )
        ctx._eu = {"papeis": papeis, "uf": "DF", "perfis": []}
        return criar_roteador(ctx), ch

    return fazer


def test_painel_execucao_com_cq_e_ciencia(montar, cq, monkeypatch):  # noqa: F811
    pedidos = []
    monkeypatch.setattr(dp, "nomes", lambda ex, contas: pedidos.append(contas) or {"u_aval": "Ana Avaliadora"})
    r, ch = montar(["apm", "avaliador"])
    status, obj = r.despachar("GET", "/api/painel/execucao", {"fuso": "America/Sao_Paulo"}, None)
    assert status == 200 and "por_dia" in obj
    assert [(x["id_lote_etapa"], x["minhas"], x["total"]) for x in obj["cq"]] == [(12, 2, 3), (14, 1, 3)]
    (o,) = obj["ciencia"]["pendentes"]
    assert o["uuid"] == cq["autor"] and o["avaliador"] == "Ana Avaliadora"
    # O nome fica guardado: a segunda leitura não vai à CCAR.
    r.despachar("GET", "/api/painel/execucao", {}, None)
    assert pedidos == [["u_aval"]] and ch["tx"] == 1


def test_sem_a_ccar_fica_a_conta(montar, cq):  # noqa: F811
    r, ch = montar(["apm"], online=False)
    status, obj = r.despachar("GET", "/api/painel/execucao", {}, None)
    assert status == 200 and obj["ciencia"]["pendentes"][0]["avaliador"] == "u_aval" and ch["tx"] == 0


def test_proxima_amostra_da_folha(montar, cq):  # noqa: F811
    r, ch = montar(["avaliador"])
    status, obj = r.despachar("POST", "/api/amostras/proxima", {}, {"id_lote": 1})
    assert status == 200 and obj["carga"]["id"] == 4001 and obj["amostra"]["id"] == 9001
    assert obj["progresso"]["id_lote_etapa"] == 12 and ch["qgis"] == ["focar_amostra"]
    status, obj = r.despachar("POST", "/api/amostras/proxima", {}, {"id_lote": 2})
    assert status == 200 and obj["carga"] is None and ch["qgis"] == ["focar_amostra"]
    # A rota de avaliar ({id}) continua respondendo.
    assert r.despachar("POST", "/api/amostras/9001", {}, {"status": 1})[0] == 200


def test_ciente_em_todas_da_folha(montar, cq):  # noqa: F811
    r, ch = montar(["apm"])
    status, obj = r.despachar("POST", "/api/inspecoes/ciente", {}, {"id_lote": 1})
    assert status == 200 and obj["cientes"] == 1 and [e for e, _ in ch["eventos"]] == ["cq"]
    status, obj = r.despachar("POST", "/api/inspecoes/ciente", {}, {"id_lote": 1})
    assert status == 200 and obj["cientes"] == 0 and len(ch["eventos"]) == 1  # nada mudou: nada publicado
    assert r.despachar("POST", "/api/inspecoes/ciente", {}, {})[0] == 400
    # A ciência de uma ({uuid}/ciente) continua no seu caminho.
    assert r.despachar("POST", f"/api/inspecoes/{cq['autor']}/ciente", {}, None)[0] == 200


def test_ver_ocorrencia_no_qgis(montar, cq, monkeypatch):  # noqa: F811
    r, ch = montar(["apm"])
    status, _ = r.despachar("POST", f"/api/inspecoes/{cq['autor']}/zoom", {}, None)
    assert status == 200
    ((xmin, ymin, xmax, ymax, srid),) = ch["zoom"]
    assert xmin < -47.88 < xmax and ymin < -15.78 < ymax and srid == 4674
    # A de outra pessoa não é visível para mim (D-66): não há o que mostrar.
    assert r.despachar("POST", f"/api/inspecoes/{cq['outro']}/zoom", {}, None)[0] == 404

    item = {"uuid": "0f0e0d0c-0b0a-4000-8000-000000000001", "x": -47.5, "y": -15.5}
    monkeypatch.setattr(dq, "ocorrencias_do_lote", lambda ex, uf, id_lote: {"itens": [item]})
    r, ch = montar(["supervisor"])
    assert r.despachar("POST", f"/api/lotes/5/ocorrencias/{item['uuid']}/zoom", {}, None)[0] == 200
    assert len(ch["zoom"]) == 1
    outro = "0f0e0d0c-0b0a-4000-8000-000000000002"
    assert r.despachar("POST", f"/api/lotes/5/ocorrencias/{outro}/zoom", {}, None)[0] == 404
    r, _ = montar(["apm"])
    assert r.despachar("POST", f"/api/lotes/5/ocorrencias/{item['uuid']}/zoom", {}, None)[0] == 403


def test_trabalhar_na_amostra_e_proxima_carga_sem_amostras(montar, cq):  # noqa: F811
    r, ch = montar(["avaliador", "apm"])
    status, obj = r.despachar("POST", "/api/amostras/9001/zoom", {}, None)
    assert status == 200 and obj["carga"]["id"] == 4001 and ch["qgis"] == ["focar_amostra"]
    assert r.despachar("POST", "/api/amostras/9003/zoom", {}, None)[0] == 404  # de outro avaliador
    # "Próxima carga" na folha 2534 vai para a produção (1001), nunca para uma amostra de CQ (4001, 4002).
    status, obj = r.despachar("POST", "/api/cargas/proxima", {}, {"id_lote": 1})
    assert status == 200 and obj["carga"]["id_lote_etapa"] != 12 and ch["qgis"][-1] == "focar_carga"
