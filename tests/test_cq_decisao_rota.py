"""D4: rotas do resultado e da decisão do CQ com a camada de dados substituída (a de verdade está em
tests/db/test_cq_resultado.py): o plano com o resultado, a prévia que não grava, cada folha numa transação (uma recusa
não desfaz as outras), as cargas da etapa aberta e os papéis."""

from contextlib import contextmanager

import pytest
from feixe.core.dados import ErroDados
from feixe.core.dados import cargas as dc
from feixe.core.dados import cq as dq
from feixe.core.dados import fluxos as df
from feixe.server.api import Contexto, criar_roteador

SUP = {"papeis": ["supervisor"], "uf": "DF", "perfis": [{"cod_projeto": 5, "papel": "supervisor"}]}


@pytest.fixture
def montar(monkeypatch):
    ch = {"chamadas": [], "eventos": [], "tx": 0}

    def plano(ex, uf, id_plano):
        ch["chamadas"].append(("plano", uf, id_plano))
        if id_plano == 404:
            raise ErroDados("plano de CQ não encontrado na sua unidade", 404)
        return {"id": id_plano, "resultado": "reprovado", "frase": "Comissão: 3 não conformes, aceita até 2"}

    def previa_cq(ex, uf, ids, decisao):
        ch["chamadas"].append(("previa", uf, ids, decisao))
        return {"itens": [{"id_lote": i, "erro": None} for i in ids]}

    def decidir_cq(ex, uf, id_lote, decisao, obs, forcar=False, expor=False):
        ch["chamadas"].append(("decidir", uf, id_lote, decisao, obs, forcar, expor))
        if id_lote == 2:
            raise ErroDados("2534-1: reprovada no CQ; para aprovar assim mesmo, confirme o aviso")
        nova = None if id_lote == 3 else 100 + id_lote
        return {"id_lote": id_lote, "folha_revisao": f"F{id_lote}", "resultado": "reprovado",
                "id_lote_etapa_nova": nova, "proxima": "Revisão"}  # fmt: skip

    def preparar(ex, uf, ids):
        ch["chamadas"].append(("preparar", uf, ids))
        return {"geradas": [{"id_lote_etapa": i, "gravadas": 10} for i in ids], "iniciadas": [], "avisos": []}

    monkeypatch.setattr(dq, "plano", plano)
    monkeypatch.setattr(df, "previa_cq", previa_cq)
    monkeypatch.setattr(df, "decidir_cq", decidir_cq)
    monkeypatch.setattr(dc, "preparar", preparar)

    def fazer(eu):
        @contextmanager
        def tx():
            ch["tx"] += 1
            yield object()

        ctx = Contexto(transacao=tx, publicar=lambda e, d: ch["eventos"].append((e, d)))
        ctx._eu = eu
        return criar_roteador(ctx), ch

    return fazer


def test_plano_com_resultado(montar):
    r, ch = montar(SUP)
    status, obj = r.despachar("GET", "/api/cq_planos/7", {}, None)
    assert status == 200 and obj["resultado"] == "reprovado" and ch["chamadas"] == [("plano", "DF", 7)]
    assert r.despachar("GET", "/api/cq_planos/404", {}, None)[0] == 404
    assert r.despachar("GET", "/api/cq_planos/x", {}, None)[0] == 400


def test_previa_nao_grava_nem_publica(montar):
    r, ch = montar(SUP)
    status, obj = r.despachar("POST", "/api/lotes/cq_decisao", {}, {"lotes": [1, 2], "decisao": "aprovar"})
    assert status == 200 and [i["id_lote"] for i in obj["itens"]] == [1, 2]
    assert ch["chamadas"] == [("previa", "DF", [1, 2], "aprovar")] and ch["eventos"] == []


def test_cada_folha_na_sua_transacao(montar):
    r, ch = montar(SUP)
    corpo = {"lotes": [1, 2, 3], "decisao": "nova_revisao", "observacao": "reprovadas", "previa": False,
             "expor_ocorrencias": True}  # fmt: skip
    status, obj = r.despachar("POST", "/api/lotes/cq_decisao", {}, corpo)
    assert status == 200
    assert [d["id_lote"] for d in obj["decididas"]] == [1, 3]
    assert obj["erros"] == [
        {"id_lote": 2, "erro": "2534-1: reprovada no CQ; para aprovar assim mesmo, confirme o aviso"}
    ]
    # A folha 3 decidiu sem abrir etapa (fim do fluxo); a 1 abriu a revisão, e as cargas dela saem em seguida.
    assert obj["abertas"] == [{"id_lote": 1, "id_lote_etapa": 101, "etapa": "Revisão"}]
    assert ("preparar", "DF", [101]) in ch["chamadas"] and obj["preparo"]["geradas"][0]["gravadas"] == 10
    decidir = [c for c in ch["chamadas"] if c[0] == "decidir"]
    assert [c[2] for c in decidir] == [1, 2, 3] and all(c[6] is True for c in decidir)
    assert ch["tx"] == 4  # três folhas, uma transação cada, e a das cargas
    assert ("lote", {"acao": "cq_nova_revisao", "ids": [1, 3]}) in ch["eventos"]


def test_recusas_e_papeis(montar):
    r, ch = montar(SUP)
    assert r.despachar("POST", "/api/lotes/cq_decisao", {}, {"lotes": [], "decisao": "aprovar"})[0] == 400
    corpo = {"lotes": [1], "decisao": "aprovar", "observacao": " ", "previa": False}
    assert r.despachar("POST", "/api/lotes/cq_decisao", {}, corpo)[0] == 200  # a observação é opcional
    corpo = {"lotes": [1], "decisao": "talvez", "observacao": "x", "previa": False}
    assert r.despachar("POST", "/api/lotes/cq_decisao", {}, corpo)[0] == 400
    r, _ = montar({"papeis": ["apm"], "uf": "DF", "perfis": []})
    assert r.despachar("POST", "/api/lotes/cq_decisao", {}, {"lotes": [1], "decisao": "aprovar"})[0] == 403
    assert r.despachar("GET", "/api/cq_planos/7", {}, None)[0] == 403
