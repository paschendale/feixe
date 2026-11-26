"""B7: rotas do catálogo. Todos leem; só o gerente cria e altera (D-87)."""

from contextlib import contextmanager

import pytest
from feixe.core.dados import referencias as dr
from feixe.server.api import Contexto, criar_roteador


@pytest.fixture
def montar(monkeypatch):
    ch = {"criadas": [], "alteradas": [], "eventos": []}
    monkeypatch.setattr(dr, "atividades", lambda ex, i=None: [])
    monkeypatch.setattr(dr, "criar_atividade", lambda ex, a: ch["criadas"].append(a) or {"id": 1, **a})
    monkeypatch.setattr(dr, "alterar_atividade", lambda ex, i, m: ch["alteradas"].append((i, m)) or {"id": i, **m})

    def fazer(papeis):
        @contextmanager
        def tx():
            yield object()

        ctx = Contexto(transacao=tx, publicar=lambda e, d: ch["eventos"].append(e))
        ctx._eu = {"papeis": papeis, "uf": "DF", "perfis": []}
        return criar_roteador(ctx), ch

    return fazer


def test_so_gerente_cria_e_altera(montar):
    for papel in ("supervisor", "operador"):
        r, _ = montar([papel])
        assert r.despachar("GET", "/api/atividades", {}, None)[0] == 200
        assert r.despachar("POST", "/api/atividades", {}, {"nome": "x"})[0] == 403
        assert r.despachar("PATCH", "/api/atividades/1", {}, {"nome": "x"})[0] == 403
    r, ch = montar(["gerente"])
    corpo = {"nome": "Aquisição BC100 - LML", "grade_nivel": "2500", "id_tema": 3, "estranho": 1, "ativo": True}
    assert r.despachar("POST", "/api/atividades", {}, corpo)[0] == 200
    assert ch["criadas"] == [{"nome": "Aquisição BC100 - LML", "grade_nivel": 2500, "id_tema": 3, "ativo": True}]
    assert r.despachar("PATCH", "/api/atividades/7", {}, {"grade_nivel": None})[0] == 200
    assert ch["alteradas"] == [(7, {"grade_nivel": None})] and ch["eventos"] == ["atividade", "atividade"]
    assert r.despachar("PATCH", "/api/atividades/7", {}, {"grade_nivel": "cinco"})[0] == 400
