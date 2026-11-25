"""C5: o push gera um `conflito_perdido`, um `conflito_vencido` e um `recusado` na CCAR de dev (marcador `db`) e a
API do supervisor (`GET /api/sync_log`) devolve cada um com a carga legível, os dois valores e a frase. Mesmo cenário
e mesmas duas estações de `test_push.py`."""

from __future__ import annotations

import contextlib
import datetime as dt

import pytest
from feixe.core.dados import ExecutorPg
from feixe.core.dados.local import cargas as lc
from feixe.core.dados.local import sync_log as lsl
from feixe.server.api import Contexto, criar_roteador

from tests.sync.test_push import (  # noqa: F401 - fixtures
    EU,
    OUTRO,
    S,
    _antes,
    _enviar,
    _puxar,
    ccar,
    cen,
    extras,
    ws1,
    ws2,
)

pytestmark = pytest.mark.db


def _roteador(conn):
    @contextlib.contextmanager
    def tx():
        with conn, conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
            yield ExecutorPg(cur)

    ctx = Contexto(transacao=tx)
    ctx._eu = {"papeis": ["supervisor"], "uf": "DF", "perfis": [{"cod_projeto": 5, "papel": "supervisor"}]}
    return criar_roteador(ctx)


def _gerar(ccar, cen, ws1, ws2):  # noqa: F811
    """Perdido na carga 1, vencido na carga 0 e recusado na carga 2 (reatribuída pelo supervisor a outra pessoa)."""
    _puxar(ccar, ws1)
    _puxar(ccar, ws2)
    # Concluir nas duas pontas não é conflito (fica a mais antiga, D-133); o conflito é concluir numa e desfazer
    # na outra.
    # carga 1: a estação 1 conclui e desfaz antes; a 2 conclui depois e envia primeiro -> a 1 perde
    with ws1.transacao(_antes(31)) as ex:
        lc.concluir(ex, cen.minhas[1])
    with ws1.transacao(_antes(30)) as ex:
        lc.desfazer(ex, cen.minhas[1])
    with ws2.transacao(_antes(20)) as ex:
        lc.concluir(ex, cen.minhas[1])
    # carga 0: a 2 conclui antes e envia primeiro; a 1 conclui e desfaz depois -> a 1 vence
    with ws2.transacao(_antes(15)) as ex:
        lc.concluir(ex, cen.minhas[0])
    _enviar(ccar, ws2)
    with ws1.transacao(_antes(11)) as ex:
        lc.concluir(ex, cen.minhas[0])
    with ws1.transacao(_antes(10)) as ex:
        lc.desfazer(ex, cen.minhas[0])
    # carga 2: concluída na 1 e reatribuída na CCAR antes do envio -> recusada
    with ws1.transacao(_antes(8)) as ex:
        lc.concluir(ex, cen.minhas[2])
    cen.executar(f"UPDATE {S}.carga_trabalho SET responsavel = %s WHERE id = %s", (OUTRO, cen.minhas[2]))
    r = _enviar(ccar, ws1)
    assert r["resultados"]["conflito_perdido"] == 1, r
    assert r["resultados"]["conflito_vencido"] == 1, r
    assert r["resultados"]["recusado"] == 1, r


def test_api_do_supervisor_mostra_os_dois_lados(ccar, cen, ws1, ws2):  # noqa: F811 - fixtures de test_push
    _gerar(ccar, cen, ws1, ws2)
    rot = _roteador(ccar)
    status, obj = rot.despachar("GET", "/api/sync_log", {"pessoa": EU, "fuso": "America/Sao_Paulo"}, None)
    assert status == 200, obj
    itens = {i["alvo"]["id_carga"]: i for i in obj["itens"]}
    assert set(itens) == set(cen.minhas) and obj["total"] == 3
    assert all(i["resultado"] != "aplicado" for i in obj["itens"])

    perdido = itens[cen.minhas[1]]
    assert perdido["resultado"] == "conflito_perdido" and perdido["vencedor"] == "servidor"
    assert perdido["alvo"]["folha"] == "PA" and perdido["alvo"]["etapa"] == "Aquisição"
    assert perdido["alvo"]["atividade"].startswith("teste push")
    assert perdido["enviado_por"]["nome"] == f"Teste {EU}"
    conc = next(v for v in perdido["valores"] if v["campo"] == "concluido")
    assert conc["local"] == "pendente" and conc["servidor"] == "concluída"
    assert perdido["servidor"]["origem_em"] == "acao"
    assert "concluiu a carga e depois desfez a conclusão" in perdido["frase"]
    assert "tinha concluído a carga" in perdido["frase"] and "ficou a conclusão, das " in perdido["frase"]
    assert "(chegou à CCAR" in perdido["frase"]  # a ação de 30 min atrás só chegou agora

    vencido = itens[cen.minhas[0]]
    assert vencido["resultado"] == "conflito_vencido" and vencido["vencedor"] == "local"
    assert vencido["descartado"] == "servidor" and vencido["servidor"]["por"]["conta"] == EU
    assert "em outro computador" in vencido["frase"] and "ficou o desfazer, das " in vencido["frase"]

    recusado = itens[cen.minhas[2]]
    assert recusado["resultado"] == "recusado" and "não está mais atribuída" in recusado["motivo"]
    assert recusado["alvo"]["responsavel_atual"]["conta"] == OUTRO
    assert f"A carga está com {OUTRO}" in recusado["frase"] and "tinha reatribuído a carga" in recusado["frase"]

    # Filtros: só os conflitos; folha que não existe; o contador.
    status, obj = rot.despachar("GET", "/api/sync_log", {"pessoa": EU, "resultado": "conflito_*"}, None)
    assert status == 200 and {i["resultado"] for i in obj["itens"]} == {"conflito_vencido", "conflito_perdido"}
    status, obj = rot.despachar("GET", "/api/sync_log", {"pessoa": EU, "folha": "nao-existe-xyz"}, None)
    assert status == 200 and obj["itens"] == []
    status, obj = rot.despachar("GET", "/api/sync_log", {"pessoa": EU, "por_pagina": "2", "pagina": "2"}, None)
    assert status == 200 and len(obj["itens"]) == 1 and obj["total"] == 3
    status, obj = rot.despachar("GET", "/api/sync_log/contagem", {}, None)
    assert status == 200 and obj["conflitos"] >= 2 and obj["recusas"] >= 1

    # Quem executa vê as próprias recusas e conflitos perdidos no workspace, sem o nome do colega.
    with ws1.leitura() as ex:
        meus = lsl.meus(ex, dt.timezone.utc)["itens"]
    assert {m["resultado"] for m in meus} == {"conflito_perdido", "recusado"}
    assert all(OUTRO not in m["frase"] and "Teste" not in m["frase"] for m in meus)
    rec = next(m for m in meus if m["resultado"] == "recusado")
    assert rec["frase"].startswith("Você concluiu a carga") and rec["alvo"]["folha"] == "PA"


def test_linha_apagada_continua_legivel(ccar, cen, ws1):  # noqa: F811
    """Carga descartada na CCAR enquanto estava suja: a recusa ainda diz de que folha e etapa era (o `ref` do push)."""
    _puxar(ccar, ws1)
    with ws1.transacao() as ex:
        lc.concluir(ex, cen.minhas[0])
    uuid_ = cen.linha("carga_trabalho", cen.minhas[0])["uuid"]
    cen.executar(f"DELETE FROM {S}.carga_trabalho WHERE id = %s", (cen.minhas[0],))
    assert _enviar(ccar, ws1)["resultados"]["recusado"] == 1
    status, obj = _roteador(ccar).despachar("GET", "/api/sync_log", {"pessoa": EU}, None)
    assert status == 200
    (item,) = [i for i in obj["itens"] if i["uuid"] == str(uuid_)]
    assert item["alvo"]["existe"] is False and item["alvo"]["id_carga"] == cen.minhas[0]
    assert item["alvo"]["folha"] == "PA" and item["alvo"]["etapa"] == "Aquisição"
    assert "não existe mais" in item["frase"]


def test_consultas_rodam_no_96():
    """A leitura do supervisor no PostgreSQL 9.6 da GGC, com as migrações e um registro de cada tipo numa transação
    desfeita no fim."""
    import json

    import psycopg2
    from feixe.core.dados import sync_log as sl

    from tests.db.conftest import url
    from tests.db.migracoes import aplicar

    conn = psycopg2.connect(url("FEIXE_GGC"))
    try:
        aplicar(conn)
        with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
            ex = ExecutorPg(cur)
            d = {"local": {"valores": {"concluido": True}, "por": EU, "em": "2026-11-24T12:00:00+00:00"},
                 "ref": {"id": 1, "folha": "2534-1", "id_lote_etapa": None}}  # fmt: skip
            for res in ("conflito_perdido", "conflito_vencido", "recusado", "aplicado"):
                cur.execute(
                    f"INSERT INTO {S}.sync_log (usuario, uf, tabela, uuid, operacao, resultado, detalhe) "
                    "VALUES (%s, 'DF', 'carga_trabalho', %s::uuid, 'update', %s, %s::jsonb)",
                    (EU, "00000000-0000-4000-8000-000000000001", res, json.dumps(d)),
                )
            r = sl.listar(ex, "DF", pessoa=EU, folha="2534")
            assert r["total"] == 3 and r["itens"][0]["alvo"]["folha"] == "2534-1"
            assert sl.contagem(ex, "DF")["total"] >= 3
    finally:
        conn.rollback()
        conn.close()
