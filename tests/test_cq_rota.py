"""D2: rotas dos planos de CQ com a camada de dados substituída (a de verdade está em tests/db/test_cq_plano.py)."""

from contextlib import contextmanager

import pytest
from feixe.core.dados import ErroDados
from feixe.core.dados import cq as dq
from feixe.server.api import Contexto, criar_roteador

SUP = {"papeis": ["supervisor"], "uf": "DF", "perfis": [{"cod_projeto": 5, "papel": "supervisor"}]}


@pytest.fixture
def montar(monkeypatch):
    ch = {"chamadas": [], "eventos": []}

    def planos(ex, uf, le):
        ch["chamadas"].append(("planos", uf, le))
        return {"id_lote_etapa": le, "planos": [], "sem_plano": []}

    def criar_plano(ex, uf, le, ativ, nivel, lqa, fracao=None, previa=False, refazer=False, semente=None):
        ch["chamadas"].append(("criar", uf, le, ativ, nivel, lqa, fracao, previa, refazer, semente))
        if lqa == 3:
            raise ErroDados("LQA 3,0% fora do Quadro 6 do manual.", 400)
        return {"id_lote_etapa": le, "id_atividade": ativ, "N": 112, "n": 20, "ac": 2, "previa": previa}

    monkeypatch.setattr(dq, "planos", planos)
    monkeypatch.setattr(dq, "criar_plano", criar_plano)

    def fazer(eu):
        @contextmanager
        def tx():
            yield object()

        ctx = Contexto(transacao=tx, publicar=lambda e, d: ch["eventos"].append(e))
        ctx._eu = eu
        return criar_roteador(ctx), ch

    return fazer


def test_lista_os_planos_da_passagem(montar):
    r, ch = montar(SUP)
    assert r.despachar("GET", "/api/lote_etapas/7/cq_planos", {}, None)[0] == 200
    assert ch["chamadas"] == [("planos", "DF", 7)]


def test_previa_nao_publica_e_gravar_publica(montar):
    r, ch = montar(SUP)
    corpo = {"id_atividade": 3, "nivel": "II", "lqa": 4, "previa": True}
    status, obj = r.despachar("POST", "/api/lote_etapas/7/cq_plano", {}, corpo)
    assert status == 200 and obj["previa"] and ch["eventos"] == []
    corpo = {"id_atividade": 3, "nivel": "III", "lqa": "2,5", "fracao_critica": 2.5, "refazer": True, "semente": 9}
    status, obj = r.despachar("POST", "/api/lote_etapas/7/cq_plano", {}, corpo)
    assert status == 200 and not obj["previa"]
    assert ch["chamadas"] == [
        ("criar", "DF", 7, 3, "II", 4, None, True, False, None),
        ("criar", "DF", 7, 3, "III", "2,5", 2.5, False, True, 9),
    ]
    assert ch["eventos"] == ["carga", "lote"]


def test_recusas_e_papeis(montar):
    r, ch = montar(SUP)
    # A recusa do manual volta como 400 com a mensagem; nada é publicado.
    status, obj = r.despachar("POST", "/api/lote_etapas/7/cq_plano", {}, {"id_atividade": 3, "nivel": "II", "lqa": 3})
    assert status == 400 and "Quadro 6" in obj["erro"] and ch["eventos"] == []
    assert r.despachar("POST", "/api/lote_etapas/7/cq_plano", {}, {"nivel": "II", "lqa": 4})[0] == 400
    corpo = {"id_atividade": 3, "nivel": "II", "lqa": 4, "previa": "sim"}
    assert r.despachar("POST", "/api/lote_etapas/7/cq_plano", {}, corpo)[0] == 400
    # A rota do plano não cai na das ações da etapa (/api/lote_etapas/{id}/{acao}).
    assert r.despachar("POST", "/api/lote_etapas/x/cq_plano", {}, {})[0] == 400
    r, _ = montar({**SUP, "papeis": ["avaliador"]})
    assert r.despachar("GET", "/api/lote_etapas/7/cq_planos", {}, None)[0] == 403
    assert r.despachar("POST", "/api/lote_etapas/7/cq_plano", {}, {"id_atividade": 3})[0] == 403
