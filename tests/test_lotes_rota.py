"""B3: rotas de lotes com a camada de dados substituída (a de verdade é testada em tests/db/test_lotes.py)."""

from contextlib import contextmanager

import pytest
from feixe.core.dados import lotes as dl
from feixe.server.api import Contexto, criar_roteador

SUP = {
    "papeis": ["supervisor"],
    "uf": "DF",
    "perfis": [{"cod_projeto": 5, "papel": "supervisor"}, {"cod_projeto": 2, "papel": "consulta"}],
}


@pytest.fixture
def montar(monkeypatch):
    ch = {"chamadas": [], "eventos": []}

    def criar_folhas(ex, uf, fluxo, folhas, projetos):
        ch["chamadas"].append(("folhas", uf, fluxo, folhas, list(projetos)))
        return {"tema": "Hidrografia", "criados": [{"cd_mi": "2535", "id_lote": 9}], "existentes": []}

    monkeypatch.setattr(dl, "criar_folhas", criar_folhas)
    monkeypatch.setattr(dl, "listar", lambda ex, uf, tema, status: ch["chamadas"].append(("listar", uf, tema)) or [])

    def fazer(eu):
        @contextmanager
        def tx():
            yield object()

        ctx = Contexto(transacao=tx, publicar=lambda e, d: ch["eventos"].append(e))
        ctx._eu = eu
        return criar_roteador(ctx), ch

    return fazer


def test_supervisor_cria_folhas_na_sua_uf_e_projetos(montar):
    r, ch = montar(SUP)
    status, obj = r.despachar("POST", "/api/lotes", {}, {"tipo": "folha", "id_fluxo": 1, "folhas": ["11", 12]})
    assert status == 200 and obj["criados"][0]["cd_mi"] == "2535"
    assert ch["chamadas"] == [("folhas", "DF", 1, [11, 12], [5])]
    assert ch["eventos"] == ["lote"]


def test_validacoes_e_papeis(montar):
    r, _ = montar(SUP)
    assert r.despachar("POST", "/api/lotes", {}, {"tipo": "outro", "id_fluxo": 1})[0] == 400
    assert r.despachar("POST", "/api/lotes", {}, {"tipo": "folha"})[0] == 400
    assert r.despachar("GET", "/api/lotes", {"status": "QUALQUER"}, None)[0] == 400
    r, _ = montar({**SUP, "uf": None})
    assert r.despachar("POST", "/api/lotes", {}, {"tipo": "folha", "id_fluxo": 1, "folhas": [1]})[0] == 403
    r, _ = montar({**SUP, "papeis": ["apm"]})
    assert r.despachar("POST", "/api/lotes", {}, {"tipo": "folha", "id_fluxo": 1, "folhas": [1]})[0] == 403


def test_gerente_ve_todas_as_ufs_e_supervisor_so_a_sua(montar):
    r, ch = montar({"papeis": ["gerente"], "uf": "RJ", "perfis": []})
    assert r.despachar("GET", "/api/lotes", {}, None)[0] == 200
    r, _ = montar(SUP)
    r.despachar("GET", "/api/lotes", {"tema": "3"}, None)
    assert ch["chamadas"] == [("listar", None, None), ("listar", "DF", 3)]


def test_rotas_do_fluxo(montar, monkeypatch):
    from feixe.core.dados import fluxos as df

    chamadas = []
    monkeypatch.setattr(
        df, "acao", lambda ex, uf, le, qual, obs, res: chamadas.append((uf, le, qual, obs, res)) or {"id": 3}
    )
    monkeypatch.setattr(df, "do_modelo", lambda ex, uf, p, t, nome: {"id": 9, "cod_projeto": p})
    r, ch = montar(SUP)
    corpo = {"observacao": "ok", "resultado": "aprovada"}
    assert r.despachar("POST", "/api/lote_etapas/7/gcq", {}, corpo) == (200, {"id": 3})
    assert chamadas == [("DF", 7, "gcq", "ok", "aprovada")] and ch["eventos"] == ["lote"]
    assert r.despachar("POST", "/api/lote_etapas/7/apagar", {}, corpo)[0] == 404
    novo = {"modo": "modelo", "nome": "DF LML", "cod_projeto": 5, "id_tema": 3}
    assert r.despachar("POST", "/api/fluxos", {}, novo)[0] == 200
    assert r.despachar("POST", "/api/fluxos", {}, {**novo, "cod_projeto": 2})[0] == 403  # perfil C no projeto 2
    r, _ = montar({**SUP, "papeis": ["apm"]})
    assert r.despachar("POST", "/api/lote_etapas/7/iniciar", {}, corpo)[0] == 403
