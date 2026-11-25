"""B2/C3: rotas de minhas cargas. A execução roda sobre um workspace de verdade (o cenário de tests/sync/conftest.py);
a supervisão, com a camada de dados da CCAR substituída (a de verdade é testada em tests/db/). Concluir não tem rota:
é da barra do Feixe, que chama `rotas.cargas.concluir` pelo mesmo `Contexto`."""

import socket
import time
from contextlib import contextmanager

import pytest
from feixe.core.dados import cargas as dc
from feixe.server.api import PREPARANDO, SEM_CCAR, Contexto, ErroApi, criar_roteador
from feixe.server.rotas import cargas as rc
from feixe.sync.sincronizar import Sincronizacao
from feixe.sync.trabalhador import Trabalhador
from feixe.sync.workspace import Workspace

from tests.sync.conftest import USUARIO, popular


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

    def fazer(papeis, com_qgis=True, workspace=None, online=None):
        @contextmanager
        def tx():
            yield object()

        ctx = Contexto(
            transacao=tx,
            publicar=lambda e, d: chamadas["eventos"].append((e, d)),
            qgis=(lambda nome, *a: chamadas["qgis"].append(nome)) if com_qgis else None,
            workspace=lambda: workspace or ws,
            acordar=chamadas["acordar"].append,
            online=online,
        )
        ctx._eu = {"papeis": papeis, "uf": "DF", "perfis": []}
        chamadas["ctx"] = ctx
        return criar_roteador(ctx), chamadas

    return fazer


def _outbox(ws):
    with ws.leitura() as ex:
        return ex.pendentes()


def test_concluir_grava_no_workspace_acorda_a_sincronizacao_e_avisa(montar, ws):
    _, ch = montar(["apm"])
    obj = rc.concluir(ch["ctx"], 1001)
    assert obj["carga"]["id"] == 1001 and obj["carga"]["concluido"] is True
    assert obj["progresso"] == {"id_lote_etapa": 11, "folha_revisao": "2534-1", "total": 3, "concluidas": 1}
    (item,) = _outbox(ws)
    assert item["tabela"] == "carga_trabalho" and item["campos"]["concluido"] is True
    assert ch["acordar"] == [None]  # com o debounce do trabalhador
    assert ch["eventos"][0][0] == "carga" and ch["qgis"] == ["cargas_mudaram"]


def test_recusa_de_desfazer_volta_como_409(montar):
    r, _ = montar(["apm"])
    status, obj = r.despachar("POST", "/api/cargas/1001/desfazer", {}, None)
    assert status == 409 and "não está concluída" in obj["erro"]


def test_proxima_foca_no_qgis_e_sem_pendente_devolve_nulo(montar):
    r, ch = montar(["apm"])
    status, obj = r.despachar("POST", "/api/cargas/proxima", {}, {"referencia": 1001})
    assert status == 200 and obj["carga"]["id"] == 1002 and ch["qgis"] == ["focar_carga"]
    status, obj = r.despachar("POST", "/api/cargas/proxima", {}, {"referencia": 1001, "id_lote": 77})
    assert status == 200 and obj == {"carga": None, "progresso": None}


def test_sem_qgis_concluir_funciona_e_zoom_nao(montar):
    r, ch = montar(["apm"], com_qgis=False)
    assert rc.concluir(ch["ctx"], 1001)["carga"]["concluido"] is True
    assert r.despachar("POST", "/api/cargas/1001/zoom", {}, None)[0] == 503


def test_lista_resumo_e_por_dia_do_workspace(montar):
    r, ch = montar(["apm"])
    status, obj = r.despachar("GET", "/api/cargas", {"situacao": "pendente", "lote_etapa": "11"}, None)
    assert status == 200 and [c["id"] for c in obj["itens"]] == [1001, 1002, 1003]
    assert r.despachar("GET", "/api/cargas", {"situacao": "talvez"}, None)[0] == 400
    assert r.despachar("GET", "/api/cargas", {"lote_etapa": "x"}, None)[0] == 400
    assert r.despachar("GET", "/api/cargas/resumo", {}, None)[1]["pendentes"] == 4
    rc.concluir(ch["ctx"], 1001)
    por_dia = r.despachar("GET", "/api/painel/execucao", {"fuso": "America/Sao_Paulo"}, None)[1]["por_dia"]
    assert sum(d["n"] for d in por_dia) == 1
    r, _ = montar(["consulta"])
    assert r.despachar("POST", "/api/cargas/1001/desfazer", {}, None)[0] == 403


def test_workspace_vazio_mostra_preparando_e_pede_o_pull(montar, tmp_path):
    vazio = Workspace.abrir("dev", USUARIO, "DF", raiz=str(tmp_path / "novo"))
    try:
        r, ch = montar(["apm"], workspace=vazio)
        status, obj = r.despachar("GET", "/api/cargas/resumo", {}, None)
        assert status == 200 and obj["preparando"] is True and obj["passagens"] == []
        assert r.despachar("GET", "/api/cargas", {}, None)[1] == {"itens": [], "preparando": True}
        assert 0 in ch["acordar"]  # a sincronização vai já, sem debounce
        with pytest.raises(ErroApi) as e:
            rc.concluir(ch["ctx"], 1001)
        assert (e.value.status, e.value.mensagem) == (409, PREPARANDO)
    finally:
        vazio.fechar()


def test_supervisao_sem_a_ccar_responde_na_hora_com_a_mensagem_certa(montar):
    r, ch = montar(["supervisor", "apm"], online=lambda: False)
    status, obj = r.despachar("GET", "/api/equipe", {}, None)
    assert status == 503 and obj["erro"] == SEM_CCAR
    # A execução continua: o workspace não depende da CCAR.
    assert rc.concluir(ch["ctx"], 1001)["carga"]["concluido"] is True


def test_escrita_da_supervisao_acorda_a_sincronizacao(montar, monkeypatch):
    monkeypatch.setattr(dc, "descartar", lambda *a, **k: {"tiradas": 2, "ficaram": 0, "lote_etapas": [21]})
    r, ch = montar(["supervisor"])
    assert r.despachar("POST", "/api/cargas/descartar", {}, {"ids": [2001, 2002]})[0] == 200
    assert ch["acordar"] == [None]
    r.despachar("GET", "/api/cargas", {}, None)  # leitura não acorda
    assert ch["acordar"] == [None]


def test_identidade_guardada_abre_a_execucao_offline():
    psycopg2 = pytest.importorskip("psycopg2")

    def consultar(sql, params=None):
        raise psycopg2.OperationalError("could not connect to server")

    guardado = {"conta": USUARIO, "papeis": ["apm"], "uf": "DF"}
    ctx = Contexto(consultar=consultar, eu_guardado=lambda: guardado)
    status, eu = criar_roteador(ctx).despachar("GET", "/api/eu", {}, None)
    assert status == 200 and eu["papeis"] == ["apm"] and eu["offline"] is True
    assert ctx._eu is None  # não fica guardada: quando a CCAR voltar, vale a de lá
    # Sem identidade guardada, a falha de conexão vira a mensagem de "precisa da CCAR".
    status, obj = criar_roteador(Contexto(consultar=consultar)).despachar("GET", "/api/eu", {}, None)
    assert status == 503 and obj["erro"] == SEM_CCAR


def _porta_fechada() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    porta = s.getsockname()[1]
    s.close()
    return porta


def test_offline_concluir_responde_na_hora_e_a_pendencia_aparece_no_estado(ws):
    """Com a porta da CCAR fechada, concluir pela API grava no workspace e volta na hora; a thread de segundo plano
    tenta sincronizar, fica offline, e o estado mostra a pendência."""
    porta = _porta_fechada()

    def alcancavel():
        try:
            socket.create_connection(("127.0.0.1", porta), timeout=1).close()
            return True
        except OSError:
            return False

    @contextmanager
    def remota():
        raise AssertionError("offline: não deveria abrir conexão")
        yield  # pragma: no cover

    sinc = Sincronizacao(lambda: ws, remota, alcancavel=alcancavel)
    sinc.usar(ws)
    trab = Trabalhador(sinc.sincronizar, atraso=0.05).iniciar()
    try:
        ctx = Contexto(
            status=lambda: {"sincronizacao": sinc.estado()},
            workspace=lambda: ws,
            acordar=trab.acordar,
            online=lambda: sinc.online,
        )
        ctx._eu = {"papeis": ["apm"], "uf": "DF", "perfis": []}
        r = criar_roteador(ctx)
        t0 = time.monotonic()
        assert rc.concluir(ctx, 1001)["carga"]["concluido"] is True and time.monotonic() - t0 < 0.5
        fim = time.monotonic() + 3
        while trab.rodadas == 0 and time.monotonic() < fim:
            time.sleep(0.02)
        est = r.despachar("GET", "/api/status", {}, None)[1]["sincronizacao"]
        assert est["online"] is False and est["ultimo_estado"] == "offline" and est["pendentes"] == 1
        # Offline, a próxima conclusão continua imediata.
        t0 = time.monotonic()
        rc.concluir(ctx, 1002)
        assert time.monotonic() - t0 < 0.5
    finally:
        trab.parar()


# --- C4: edição pela camada Minhas cargas (tabela de atributos, formulário) -----------------------------------------


def _ctx_edicao(ws, eventos=None, acordar=None):
    ctx = Contexto(
        workspace=lambda: ws,
        publicar=lambda e, d: (eventos if eventos is not None else []).append((e, d)),
        acordar=(acordar if acordar is not None else []).append,
    )
    ctx._eu = {"papeis": ["apm"], "uf": "DF", "perfis": []}
    return ctx


def test_editar_pela_camada_passa_pelas_regras_e_pela_outbox(ws):
    eventos, acordar = [], []
    r = rc.editar(_ctx_edicao(ws, eventos, acordar), {1001: True, 1002: False, 3001: True, 1009: True, 999: True})
    assert r["feitas"] == [{"id": 1001, "concluido": True, "folha_revisao": "2534-1"}]  # 1002 já estava pendente
    assert {x["id"]: x["motivo"] for x in r["recusadas"]} == {
        3001: "a etapa desta folha já foi encerrada pelo supervisor",
        1009: "esta carga não está atribuída a você",
        999: "carga não encontrada",
    }
    assert r["progresso"]["concluidas"] == 1 and r["fila"] is None
    (item,) = _outbox(ws)
    assert item["campos"]["concluido"] is True and item["campos"]["concluido_em"]  # a hora vai explícita
    assert [e for e, _ in eventos] == ["carga"] and acordar  # o painel fica sabendo; a sincronização acorda
    ok, avisos = rc.mensagens_edicao(r)
    assert ok == ["Carga concluída · 2534-1 · 1/3"]
    assert avisos[0] == (
        "Carga 3001 da 2536-1: A etapa desta folha já foi encerrada pelo supervisor. A mudança foi desfeita."
    )


def test_editar_a_ultima_pendente_puxa_a_fila_e_desfazer_tem_janela(ws):
    import datetime as dt

    r = rc.editar(_ctx_edicao(ws), {1001: True, 1002: True, 1003: True})
    assert len(r["feitas"]) == 3 and r["fila"]["folha_revisao"] == "2535-0" and r["fila"]["atribuidas"] == 2
    ok, _ = rc.mensagens_edicao(r)
    assert ok[0] == "3 cargas concluídas · 2534-1 · 3/3" and "2535-0 (2 cargas)" in ok[1]
    antiga = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=30)
    with ws.transacao() as ex:
        u = ex.um("SELECT uuid FROM carga_trabalho WHERE id = 1001")["uuid"]
        ex.atualizar("carga_trabalho", u, {"concluido_em": antiga})
    r = rc.editar(_ctx_edicao(ws), {1001: False, 1002: False})
    assert [f["id"] for f in r["feitas"]] == [1002]
    assert r["recusadas"] == [
        {"id": 1001, "folha_revisao": "2534-1", "motivo": "só dá para desfazer até 24 horas depois de concluir"}
    ]
    assert rc.mensagens_edicao(r)[0] == ["Conclusão desfeita · 2534-1 · 2/3"]


def test_editar_com_o_workspace_preparando_e_recusado(ws):
    from feixe.server.api import ErroApi

    with ws.transacao() as ex:
        ex.executar("DELETE FROM meta WHERE chave = 'ultima_sincronizacao'")
    with pytest.raises(ErroApi) as e:
        rc.editar(_ctx_edicao(ws), {1001: True})
    assert e.value.status == 409 and _outbox(ws) == []
