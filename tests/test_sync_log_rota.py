"""C5: rotas dos conflitos de sincronização (puro). O supervisor lê a CCAR com a camada de dados substituída (a de
verdade é testada em tests/sync/test_conflitos.py, `db`); quem executa lê o `sync_log` do workspace."""

import datetime as dt
import json
from contextlib import contextmanager

import pytest
from feixe.core.dados import sync_log as sl
from feixe.server.api import Contexto, criar_roteador
from feixe.sync.workspace import Workspace

from tests.sync.conftest import USUARIO, popular

UTC = dt.timezone.utc


@pytest.fixture
def ws(tmp_path):
    w = Workspace.abrir("dev", USUARIO, "DF", raiz=str(tmp_path))
    popular(w)
    with w.transacao() as ex:
        ex.definir_meta("ultima_sincronizacao", "2026-11-24T12:00:00.000000Z")
    yield w
    w.fechar()


@pytest.fixture
def montar(ws, monkeypatch):
    chamadas = []
    monkeypatch.setattr(sl, "listar", lambda ex, uf, **f: chamadas.append((uf, f)) or {"itens": [], "total": 0})
    monkeypatch.setattr(sl, "contagem", lambda ex, uf, dias: chamadas.append((uf, dias)) or {"total": 0})

    def fazer(papeis, uf="DF"):
        @contextmanager
        def tx():
            yield object()

        ctx = Contexto(transacao=tx, workspace=lambda: ws)
        ctx._eu = {"papeis": papeis, "uf": uf, "perfis": []}
        return criar_roteador(ctx), chamadas

    return fazer


def test_supervisor_filtra_na_sua_uf_e_por_padrao_ve_conflitos_e_recusas(montar):
    r, ch = montar(["supervisor"])
    assert r.despachar("GET", "/api/sync_log", {}, None)[0] == 200
    uf, f = ch[-1]
    assert uf == "DF" and f["resultados"] == ["conflito_vencido", "conflito_perdido", "recusado"]
    assert f["desde"] is None and f["pagina"] == 1 and f["por_pagina"] == sl.POR_PAGINA
    q = {"resultado": "conflito_*", "desde": "2026-11-01", "ate": "2026-11-24", "pessoa": " ana ", "folha": "2534",
         "pagina": "2", "por_pagina": "999", "fuso": "America/Sao_Paulo"}  # fmt: skip
    assert r.despachar("GET", "/api/sync_log", q, None)[0] == 200
    _, f = ch[-1]
    assert f["resultados"] == ["conflito_vencido", "conflito_perdido"]
    assert f["pessoa"] == "ana" and f["folha"] == "2534" and f["pagina"] == 2 and f["por_pagina"] == sl.MAX_POR_PAGINA
    # O período vale no fuso de quem olha, com o último dia inteiro.
    assert f["desde"].astimezone(UTC) == dt.datetime(2026, 11, 1, 3, tzinfo=UTC)
    assert f["ate"].astimezone(UTC) == dt.datetime(2026, 11, 25, 3, tzinfo=UTC)
    assert r.despachar("GET", "/api/sync_log", {"resultado": "recusado"}, None)[0] == 200
    assert ch[-1][1]["resultados"] == ["recusado"]


@pytest.mark.parametrize(
    "q",
    [
        {"resultado": "aplicado"},
        {"resultado": "conflito_*,erro"},
        {"desde": "24/11/2026"},
        {"desde": "2026-11-24", "ate": "2026-11-01"},
        {"pagina": "0"},
        {"fuso": "x; drop"},
    ],
)
def test_filtros_invalidos_dao_400(montar, q):
    r, ch = montar(["supervisor"])
    assert r.despachar("GET", "/api/sync_log", q, None)[0] == 400
    assert ch == []


def test_so_supervisor_ve_os_conflitos_da_unidade(montar):
    for papeis in (["apm"], ["avaliador"], ["gerente"], []):
        r, ch = montar(papeis)
        assert r.despachar("GET", "/api/sync_log", {}, None)[0] == 403
        assert r.despachar("GET", "/api/sync_log/contagem", {}, None)[0] == 403
        assert ch == []
    r, ch = montar(["supervisor"], uf=None)
    assert r.despachar("GET", "/api/sync_log", {}, None)[0] == 403


def test_contagem_dos_ultimos_dias(montar):
    r, ch = montar(["supervisor"])
    assert r.despachar("GET", "/api/sync_log/contagem", {}, None)[0] == 200
    assert r.despachar("GET", "/api/sync_log/contagem", {"dias": "30"}, None)[0] == 200
    assert ch == [("DF", 7), ("DF", 30)]
    assert r.despachar("GET", "/api/sync_log/contagem", {"dias": "0"}, None)[0] == 400


def _registrar(ws, resultado, detalhe, uuid_=None, tabela="carga_trabalho"):
    with ws.transacao() as ex:
        if uuid_ is None:
            uuid_ = ex.um("SELECT uuid FROM carga_trabalho WHERE id = 1001")["uuid"]
        ex.registrar_log(tabela, uuid_, "update", resultado, detalhe)


def test_quem_executa_ve_as_proprias_recusas_e_conflitos_perdidos_sem_colegas(montar, ws):
    agora = dt.datetime.now(UTC)
    acao = (agora - dt.timedelta(minutes=40)).isoformat()
    srv = (agora - dt.timedelta(minutes=20)).isoformat()
    base = {"itens": ["k1"], "local": {"valores": {"concluido": True}, "por": USUARIO, "em": acao}, "desvio_s": 0}
    colega = {"por": "u_colega", "em": srv, "origem_em": "acao"}
    perdido = {**base, "descartado": "local", "servidor": {"valores": {"concluido": True}, **colega}}
    _registrar(ws, "conflito_perdido", perdido)
    motivo = "a etapa deste lote foi encerrada pelo supervisor"
    _registrar(ws, "recusado", {**base, "itens": ["k2"], "motivo": motivo,
                                "servidor": {"valores": {"concluido": False}, **colega}})  # fmt: skip
    _registrar(ws, "recusado", {"itens": ["k2"], "repetido": True})  # repetição: não aparece de novo
    _registrar(ws, "aplicado", {**base, "itens": ["k3"]})
    _registrar(ws, "conflito_vencido", {**base, "itens": ["k4"]})
    r, _ = montar(["apm"])
    status, obj = r.despachar("GET", "/api/sync_log/meus", {"fuso": "UTC"}, None)
    assert status == 200
    assert [i["resultado"] for i in obj["itens"]] == ["recusado", "conflito_perdido"]
    texto = json.dumps(obj, ensure_ascii=False)
    assert "u_colega" not in texto
    rec, perd = obj["itens"]
    assert rec["alvo"]["folha"] == "2534-1" and rec["alvo"]["id"] == 1001  # resolvida no workspace
    assert rec["frase"].startswith("Você concluiu a carga") and "encerrada pelo supervisor" in rec["frase"]
    assert "na CCAR, a carga tinha mudado" in perd["frase"] and perd["frase"].endswith("ficou o que estava na CCAR.")


def test_frase_do_supervisor_com_duas_pessoas():
    tz, hoje = UTC, dt.date(2026, 11, 24)
    d = {
        "local": {"valores": {"concluido": True, "concluido_em": "2026-11-24T09:12:00Z"}, "por": "ana",
                  "em": "2026-11-24T09:12:00+00:00"},
        "servidor": {"valores": {"concluido": False, "concluido_em": None}, "por": "bruno",
                     "em": "2026-11-24T12:40:00+00:00", "origem_em": "atualizado_em"},
        "descartado": "local", "desvio_s": 0,
    }  # fmt: skip
    nomes = {"ana": "Ana Lima", "bruno": "Bruno Melo"}
    em = dt.datetime(2026, 11, 24, 13, 0, tzinfo=UTC)
    f = sl.frase("conflito_perdido", "carga_trabalho", "update", d, em, nomes, tz, hoje, "ana")
    assert f == (
        "Ana Lima concluiu a carga às 09:12 (chegou à CCAR às 13:00); Bruno Melo tinha alterado a carga às 12:40; "
        "ficou a alteração de Bruno Melo, das 12:40."
    )
    v = sl.valores(d, tz, nomes)
    assert v[0] == {"campo": "concluido", "rotulo": "Situação", "local": "concluída", "servidor": "pendente",
                    "igual": False}  # fmt: skip
    d2 = {**d, "juntados": [{"campos": {"concluido": True}}, {"campos": {"concluido": False}}],
          "local": {**d["local"], "valores": {"concluido": False}}}  # fmt: skip
    f2 = sl.frase("conflito_vencido", "carga_trabalho", "update", d2, em, nomes, tz, dt.date(2026, 11, 25), "ana")
    assert f2.startswith("Ana Lima concluiu a carga e depois desfez a conclusão em 24/11 às 09:12")
    assert f2.endswith("ficou o desfazer de Ana Lima, de 24/11 às 09:12.")
