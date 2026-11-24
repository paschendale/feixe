"""B2/C3: rotas de minhas cargas. A execução roda sobre um workspace de verdade (o cenário de tests/sync/conftest.py);
a supervisão, com a camada de dados da CCAR substituída (a de verdade é testada em tests/db/)."""

import socket
import time
from contextlib import contextmanager

import pytest
from feixe.core.dados import ErroDados
from feixe.core.dados import cargas as dc
from feixe.server.api import PREPARANDO, SEM_CCAR, Contexto, criar_roteador
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
        return criar_roteador(ctx), chamadas

    return fazer


def _outbox(ws):
    with ws.leitura() as ex:
        return ex.pendentes()


def test_concluir_grava_no_workspace_acorda_a_sincronizacao_e_avisa(montar, ws):
    r, ch = montar(["apm"])
    status, obj = r.despachar("POST", "/api/cargas/1001/concluir", {}, None)
    assert status == 200 and obj["carga"]["id"] == 1001 and obj["carga"]["concluido"] is True
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
    r, _ = montar(["apm"], com_qgis=False)
    assert r.despachar("POST", "/api/cargas/1001/concluir", {}, None)[0] == 200
    assert r.despachar("POST", "/api/cargas/1001/zoom", {}, None)[0] == 503


def test_lista_resumo_e_por_dia_do_workspace(montar):
    r, _ = montar(["apm"])
    status, obj = r.despachar("GET", "/api/cargas", {"situacao": "pendente", "lote_etapa": "11"}, None)
    assert status == 200 and [c["id"] for c in obj["itens"]] == [1001, 1002, 1003]
    assert r.despachar("GET", "/api/cargas", {"situacao": "talvez"}, None)[0] == 400
    assert r.despachar("GET", "/api/cargas", {"lote_etapa": "x"}, None)[0] == 400
    assert r.despachar("GET", "/api/cargas/resumo", {}, None)[1]["pendentes"] == 4
    r.despachar("POST", "/api/cargas/1001/concluir", {}, None)
    por_dia = r.despachar("GET", "/api/painel/execucao", {"fuso": "America/Sao_Paulo"}, None)[1]["por_dia"]
    assert sum(d["n"] for d in por_dia) == 1
    r, _ = montar(["consulta"])
    assert r.despachar("POST", "/api/cargas/1001/concluir", {}, None)[0] == 403


def test_workspace_vazio_mostra_preparando_e_pede_o_pull(montar, tmp_path):
    vazio = Workspace.abrir("dev", USUARIO, "DF", raiz=str(tmp_path / "novo"))
    try:
        r, ch = montar(["apm"], workspace=vazio)
        status, obj = r.despachar("GET", "/api/cargas/resumo", {}, None)
        assert status == 200 and obj["preparando"] is True and obj["passagens"] == []
        assert r.despachar("GET", "/api/cargas", {}, None)[1] == {"itens": [], "preparando": True}
        assert 0 in ch["acordar"]  # a sincronização vai já, sem debounce
        assert r.despachar("POST", "/api/cargas/1001/concluir", {}, None) == (409, {"erro": PREPARANDO})
    finally:
        vazio.fechar()


def test_supervisao_sem_a_ccar_responde_na_hora_com_a_mensagem_certa(montar):
    r, _ = montar(["supervisor", "apm"], online=lambda: False)
    status, obj = r.despachar("GET", "/api/equipe", {}, None)
    assert status == 503 and obj["erro"] == SEM_CCAR
    # A execução continua: o workspace não depende da CCAR.
    assert r.despachar("POST", "/api/cargas/1001/concluir", {}, None)[0] == 200


def test_escrita_da_supervisao_acorda_a_sincronizacao(montar, monkeypatch):
    monkeypatch.setattr(dc, "atribuir", lambda *a, **k: {"atribuidas": 2, "ja_estavam": 0, "fora": 0})
    r, ch = montar(["supervisor"])
    assert r.despachar("POST", "/api/cargas/atribuir", {}, {"responsavel": USUARIO, "ids": [2001, 2002]})[0] == 200
    assert ch["acordar"] == [None]
    r.despachar("GET", "/api/cargas", {}, None)  # leitura não acorda
    assert ch["acordar"] == [None]


def test_identidade_guardada_abre_a_execucao_offline():
    import psycopg2

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
        status, _ = r.despachar("POST", "/api/cargas/1001/concluir", {}, None)
        assert status == 200 and time.monotonic() - t0 < 0.5
        fim = time.monotonic() + 3
        while trab.rodadas == 0 and time.monotonic() < fim:
            time.sleep(0.02)
        est = r.despachar("GET", "/api/status", {}, None)[1]["sincronizacao"]
        assert est["online"] is False and est["ultimo_estado"] == "offline" and est["pendentes"] == 1
        # Offline, a próxima conclusão continua imediata.
        t0 = time.monotonic()
        assert r.despachar("POST", "/api/cargas/1002/concluir", {}, None)[0] == 200
        assert time.monotonic() - t0 < 0.5
    finally:
        trab.parar()


def test_gerar_varias_passagens_com_recusa_de_uma(montar, monkeypatch):
    def gerar(ex, le, previa, uf):
        if le == 2:
            raise ErroDados("2535-0: esta etapa já tem cargas")
        r = {"id_lote_etapa": le, "folha_revisao": "2534-0", "celulas": 112, "gravadas": 0 if previa else 112}
        return {**r, "previa": [{"geocodigo": "5KME1N1", "wkt": "MULTIPOLYGON EMPTY"}]} if previa else r

    monkeypatch.setattr(dc, "gerar_pela_grade", gerar)
    r, ch = montar(["supervisor"])
    status, obj = r.despachar("POST", "/api/cargas/gerar", {}, {"lote_etapas": [1, 2], "previa": True})
    assert status == 200 and [x["celulas"] for x in obj["resultados"]] == [112] and "previa" not in obj["resultados"][0]
    assert obj["erros"] == [{"id_lote_etapa": 2, "erro": "2535-0: esta etapa já tem cargas"}]
    assert ch["qgis"] == ["previa_cargas"] and ch["eventos"] == []
    status, obj = r.despachar("POST", "/api/cargas/gerar", {}, {"lote_etapas": [1], "previa": False})
    assert obj["resultados"][0]["gravadas"] == 112 and [e for e, _ in ch["eventos"]] == ["carga", "lote"]
    assert r.despachar("POST", "/api/cargas/gerar", {}, {"lote_etapas": []})[0] == 400
    r, _ = montar(["apm"])
    assert r.despachar("POST", "/api/cargas/gerar", {}, {"lote_etapas": [1]})[0] == 403
