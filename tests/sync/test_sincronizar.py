"""C2: `Sincronizacao` sem banco: offline e erro viram resultado, uma de cada vez, e o estado lê o workspace."""

from __future__ import annotations

import contextlib
import threading

from feixe.server.api import Contexto, criar_roteador
from feixe.sync.sincronizar import Sincronizacao, hora_local


def _sinc(ws, remota, alcancavel=lambda: True, terminou=None):
    return Sincronizacao(lambda: ws, remota, alcancavel=alcancavel, ao_terminar=terminou)


def test_sem_rede_vira_offline_sem_abrir_conexao(ws):
    abertas = []
    terminou = []
    s = _sinc(ws, lambda: abertas.append(1), alcancavel=lambda: False, terminou=terminou.append)
    r = s.sincronizar()
    assert r["estado"] == "offline" and r["pull"] is None and not abertas
    assert terminou and terminou[0]["online"] is False and terminou[0]["ultimo_estado"] == "offline"


def test_queda_no_meio_vira_offline_e_erro_vira_erro(ws):
    rede = {"ok": True}

    @contextlib.contextmanager
    def caiu():
        rede["ok"] = False
        raise ConnectionResetError("a conexão caiu")
        yield  # pragma: no cover

    assert _sinc(ws, caiu, alcancavel=lambda: rede["ok"]).sincronizar()["estado"] == "offline"

    @contextlib.contextmanager
    def senha_errada():
        raise RuntimeError("autenticação falhou")
        yield  # pragma: no cover

    r = _sinc(ws, senha_errada).sincronizar()
    assert r["estado"] == "erro" and "autenticação" in r["mensagem"]


def test_uma_de_cada_vez(ws):
    entrou, solta = threading.Event(), threading.Event()

    @contextlib.contextmanager
    def lenta():
        entrou.set()
        solta.wait(5)
        raise RuntimeError("fim")
        yield  # pragma: no cover

    s = _sinc(ws, lenta)
    t = threading.Thread(target=s.sincronizar)
    t.start()
    assert entrou.wait(5)
    assert s.sincronizar()["estado"] == "em_andamento" and s.estado()["em_andamento"] is True
    solta.set()
    t.join(5)
    assert s.estado()["em_andamento"] is False


def test_estado_le_pendencias_e_ultima_sincronizacao(ws):
    s = _sinc(ws, None)
    assert s.estado()["pendentes"] is None  # nenhum workspace aberto ainda
    s.usar(ws)
    with ws.transacao() as ex:
        ex.atualizar("carga_trabalho", ex.um("SELECT uuid FROM carga_trabalho WHERE id = 1001")["uuid"],
                     {"concluido": True})  # fmt: skip
        ex.definir_meta("ultima_sincronizacao", "2026-11-24T17:05:00.000000Z")
    e = s.estado()
    assert e["pendentes"] == 1 and e["ultima_sincronizacao"] == "2026-11-24T17:05:00.000000Z"
    assert hora_local(e["ultima_sincronizacao"]) is not None and hora_local(None) is None


def test_rota_sincronizar_devolve_o_resultado():
    r = criar_roteador(Contexto(sincronizar=lambda: {"estado": "offline", "pull": None}))
    assert r.despachar("POST", "/api/sincronizar", {}, None) == (200, {"estado": "offline", "pull": None})


def test_aviso_de_rede_so_na_troca():
    from feixe.sync.sincronizar import OFFLINE, aviso_de_rede

    assert aviso_de_rede(None, True) is None  # abriu com a CCAR respondendo: nada a dizer
    assert aviso_de_rede(None, False) == OFFLINE  # abriu sem rede: avisa uma vez
    assert aviso_de_rede(False, False, 3) is None and aviso_de_rede(True, True) is None  # o QTimer não repete
    assert aviso_de_rede(True, False, 2) == OFFLINE
    assert aviso_de_rede(False, True, 0) == "A conexão com a CCAR voltou."
    assert aviso_de_rede(False, True, 1) == "A conexão com a CCAR voltou: enviando 1 alteração guardada."
    assert aviso_de_rede(False, True, 4) == "A conexão com a CCAR voltou: enviando 4 alterações guardadas."
    assert aviso_de_rede(True, None) is None
