"""C1: criação, conferência e recriação do workspace; outbox e sync_log; GeoPackage válido; concorrência."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import threading

import pytest
from feixe.sync import esquema
from feixe.sync.geometria import wkb_ponto
from feixe.sync.workspace import Workspace, WorkspaceRecusado, caminho, iso_exato

from tests.sync.conftest import USUARIO, VERSAO, carga


def test_cria_na_pasta_do_ambiente_e_usuario(tmp_path):
    with Workspace.abrir("dev", USUARIO, "DF", raiz=str(tmp_path)) as ws:
        assert ws.caminho == os.path.join(str(tmp_path), "dev", USUARIO, "workspace.gpkg")
        assert ws.caminho == caminho("dev", USUARIO, str(tmp_path))
        with ws.leitura() as ex:
            meta = {r["chave"]: r["valor"] for r in ex.todos("SELECT * FROM meta")}
            assert ex.um("PRAGMA journal_mode")["journal_mode"] == "wal"
            assert ex.um("PRAGMA application_id")["application_id"] == 0x47504B47
            tabelas = {r["name"] for r in ex.todos("SELECT name FROM sqlite_master WHERE type = 'table'")}
        assert meta["ambiente"] == "dev" and meta["usuario"] == USUARIO and meta["uf"] == "DF"
        assert meta["versao_esquema"] == str(esquema.VERSAO)
        esperadas = set(esquema.TABELAS) | {"meta", "outbox", "sync_log", "gpkg_contents", "gpkg_geometry_columns"}
        assert esperadas <= tabelas
        assert {
            "lote",
            "lote_etapa",
            "carga_trabalho",
            "fila_folha",
            "cq_plano",
            "cq_amostra",
            "cq_inspecao",
        } <= esperadas
        assert not any("rtree" in t for t in tabelas)


def test_reabrir_mantem_os_dados(ws):
    ws.fechar()
    with Workspace.abrir("dev", USUARIO, "DF", path=ws.caminho) as w2, w2.leitura() as ex:
        assert ex.um("SELECT count(*) AS n FROM carga_trabalho")["n"] == 7


def test_outro_ambiente_e_outro_usuario_sao_recusados(ws):
    ws.fechar()
    with pytest.raises(WorkspaceRecusado, match="ambiente 'dev'"):
        Workspace.abrir("homologacao", USUARIO, "DF", path=ws.caminho)
    with pytest.raises(WorkspaceRecusado, match="usuário 'u_apm'"):
        Workspace.abrir("dev", "u_outro", "DF", path=ws.caminho)
    # Copiado para a pasta de outro usuário, também não serve.
    destino = caminho("dev", "u_outro", os.path.dirname(os.path.dirname(os.path.dirname(ws.caminho))))
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    shutil.copy(ws.caminho, destino)
    with pytest.raises(WorkspaceRecusado):
        Workspace.abrir("dev", "u_outro", "DF", raiz=os.path.dirname(os.path.dirname(os.path.dirname(ws.caminho))))


def test_arquivo_que_nao_e_workspace_e_recusado(tmp_path):
    p = tmp_path / "qualquer.gpkg"
    sqlite3.connect(str(p)).execute("CREATE TABLE x (a)").connection.commit()
    with pytest.raises(WorkspaceRecusado, match="não é um workspace"):
        Workspace.abrir("dev", USUARIO, "DF", path=str(p))


def test_esquema_mais_novo_e_recusado(ws):
    with ws.transacao() as ex:
        ex.definir_meta("versao_esquema", str(esquema.VERSAO + 1))
    ws.fechar()
    with pytest.raises(WorkspaceRecusado, match="mais novo"):
        Workspace.abrir("dev", USUARIO, "DF", path=ws.caminho)


@pytest.mark.parametrize("motivo", ["esquema", "uf"])
def test_esquema_velho_ou_outra_uf_recria_levando_outbox_e_sync_log(ws, motivo):
    with ws.transacao() as ex:
        uuid = ex.um("SELECT uuid FROM carga_trabalho WHERE id = 1001")["uuid"]
        ex.atualizar("carga_trabalho", uuid, {"concluido": True, "concluido_em": ex.agora})
        ex.registrar_log("carga_trabalho", uuid, "update", "aplicado")
        if motivo == "esquema":
            ex.definir_meta("versao_esquema", "0")
    ws.fechar()
    uf = "DF" if motivo == "esquema" else "GO"
    with Workspace.abrir("dev", USUARIO, uf, path=ws.caminho) as w2, w2.leitura() as ex:
        assert ex.um("SELECT count(*) AS n FROM carga_trabalho")["n"] == 0  # cache: volta no próximo pull
        itens = ex.pendentes()
        assert [(i["tabela"], i["uuid"], i["operacao"]) for i in itens] == [("carga_trabalho", uuid, "update")]
        assert ex.um("SELECT count(*) AS n FROM sync_log")["n"] == 1
        assert ex.meta("versao_esquema") == str(esquema.VERSAO) and ex.meta("uf") == uf
    assert os.path.exists(ws.caminho + ".anterior")


def test_esquema_1_migra_a_outbox_com_chave_e_acao(ws):
    """Workspace da versão 1 (outbox sem `chave` e `acao`): a migração acrescenta as colunas sem perder itens."""
    with ws.transacao() as ex:
        uuid = ex.um("SELECT uuid FROM carga_trabalho WHERE id = 1001")["uuid"]
        ex.atualizar("carga_trabalho", uuid, {"concluido": True})
    conn = ws.conn
    conn.execute("BEGIN IMMEDIATE")
    conn.execute(
        "CREATE TABLE outbox_v1 AS SELECT id, tabela, uuid, operacao, campos, hora, versao_base, tentativas, erro "
        "FROM outbox"
    )
    conn.execute("DROP TABLE outbox")
    conn.execute("ALTER TABLE outbox_v1 RENAME TO outbox")
    conn.execute("UPDATE meta SET valor = '1' WHERE chave = 'versao_esquema'")
    conn.execute("COMMIT")
    ws.fechar()
    with Workspace.abrir("dev", USUARIO, "DF", path=ws.caminho) as w2, w2.leitura() as ex:
        (item,) = ex.pendentes()
        assert item["uuid"] == uuid and item["chave"] and item["acao"] == item["hora"]
        assert ex.um("SELECT count(*) AS n FROM carga_trabalho")["n"] > 0  # migrou, não recriou
        assert ex.meta("versao_esquema") == str(esquema.VERSAO)


def test_gravar_uma_carga_poe_a_linha_na_outbox(ws):
    with ws.transacao() as ex:
        antes = ex.um("SELECT uuid, versao_base, sujo FROM carga_trabalho WHERE id = 1001")
        assert antes["sujo"] == 0 and antes["versao_base"] == "2026-11-20T12:00:00.123456Z"
        ex.atualizar("carga_trabalho", antes["uuid"], {"concluido": True, "concluido_em": ex.agora})
        hora = ex.agora_iso
        hora_exata = iso_exato(ex.agora)
    with ws.leitura() as ex:
        linha = ex.um("SELECT concluido, concluido_em, sujo, versao_base, atualizado_por FROM carga_trabalho "
                      "WHERE id = 1001")  # fmt: skip
        item = ex.um("SELECT * FROM outbox")
    assert linha == {"concluido": 1, "concluido_em": hora, "sujo": 1, "versao_base": antes["versao_base"],
                     "atualizado_por": USUARIO}  # fmt: skip
    assert item["tabela"] == "carga_trabalho" and item["uuid"] == antes["uuid"] and item["operacao"] == "update"
    assert json.loads(item["campos"]) == {"concluido": True, "concluido_em": hora}
    assert item["hora"] == hora_exata and item["versao_base"] == antes["versao_base"]


def test_escrita_que_falha_nao_deixa_linha_nem_outbox(ws):
    with pytest.raises(RuntimeError), ws.transacao() as ex:
        uuid = ex.um("SELECT uuid FROM carga_trabalho WHERE id = 1001")["uuid"]
        ex.atualizar("carga_trabalho", uuid, {"concluido": True})
        raise RuntimeError("queda no meio")
    with ws.leitura() as ex:
        assert ex.um("SELECT concluido FROM carga_trabalho WHERE id = 1001")["concluido"] == 0
        assert ex.pendentes() == []


def test_inserir_linha_local_sem_id_e_confirmar_no_push(ws):
    with ws.transacao() as ex:
        u = ex.inserir("cq_inspecao", {"id_lote": 1, "id_carga_trabalho": 1001, "elemento": "Omissão",
                                       "geom": wkb_ponto(-47.9, -15.8),
                                       "responsavel": USUARIO})  # fmt: skip
        linha = ex.um("SELECT id, uf, sujo, cx, cy FROM cq_inspecao WHERE uuid = ?", (u,))
        assert linha == {"id": None, "uf": "DF", "sujo": 1, "cx": -47.9, "cy": -15.8}
        (item,) = ex.pendentes()
        assert item["operacao"] == "insert" and item["campos"]["elemento"] == "Omissão"
        assert item["campos"]["geom"].startswith("0101000000")  # WKB em hexadecimal
        # O C3 confirma: a linha ganha o id da CCAR e a versão do servidor, e fica limpa.
        ex.confirmar(item["id"], "aplicado", id_remoto=77, versao_remota=VERSAO)
        assert ex.um("SELECT id, sujo, versao_base FROM cq_inspecao WHERE uuid = ?", (u,)) == {
            "id": 77, "sujo": 0, "versao_base": "2026-11-20T12:00:00.123456Z"}  # fmt: skip
        assert ex.pendentes() == []
        assert ex.um("SELECT resultado FROM sync_log")["resultado"] == "aplicado"


def test_gravar_remoto_atualiza_pela_chave_sem_outbox(ws):
    with ws.transacao() as ex:
        c = carga(1001, 11, USUARIO, -47.90, -15.80, concluido=True, concluido_em=VERSAO)
        c["uuid"] = ex.um("SELECT uuid FROM carga_trabalho WHERE id = 1001")["uuid"]
        assert ex.gravar_remoto("carga_trabalho", c) == "update"
        assert ex.um("SELECT count(*) AS n FROM carga_trabalho")["n"] == 7
        assert ex.pendentes() == []
        ex.marcar_pull("carga_trabalho", VERSAO)
        assert ex.ultimo_pull("carga_trabalho") == "2026-11-20T12:00:00.123456Z"


def test_campo_fora_do_espelho_e_recusado(ws):
    with pytest.raises(ValueError, match="fora do espelho"), ws.transacao() as ex:
        ex.atualizar("carga_trabalho", "x", {"inventado": 1})
    with pytest.raises(ValueError, match="não é tabela do espelho"), ws.transacao() as ex:
        ex.atualizar("tema", "x", {"nome": "y"})


def test_threads_escrevendo_ao_mesmo_tempo(ws):
    """Servidor HTTP e sincronização ao mesmo tempo, cada um com o seu Workspace do mesmo arquivo."""
    outro = Workspace.abrir("dev", USUARIO, "DF", path=ws.caminho)
    with ws.leitura() as ex:
        uuids = [r["uuid"] for r in ex.todos("SELECT uuid FROM carga_trabalho")]
    erros = []

    def escrever(w, n):
        try:
            for i in range(n):
                with w.transacao() as ex:
                    ex.atualizar("carga_trabalho", uuids[i % len(uuids)], {"concluido": i % 2 == 0})
        except Exception as e:  # noqa: BLE001
            erros.append(e)

    ts = [threading.Thread(target=escrever, args=(w, 40)) for w in (ws, outro, ws, outro)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    outro.fechar()
    assert erros == []
    with ws.leitura() as ex:
        assert len(ex.pendentes()) == 160


@pytest.mark.skipif(shutil.which("ogrinfo") is None, reason="ogrinfo (GDAL) não instalado")
def test_e_um_geopackage_que_o_ogr_abre(ws):
    ws.fechar()
    saida = subprocess.run(
        ["ogrinfo", "-ro", "-q", ws.caminho, "carga_trabalho", "-where", "id = 1001"],
        capture_output=True, text=True, check=True,
    ).stdout  # fmt: skip
    assert "MULTIPOLYGON (((-47.9 -15.8,-47.85 -15.8,-47.85 -15.75,-47.9 -15.75,-47.9 -15.8)))" in saida
    assert "concluido (Integer(Boolean)) = 0" in saida
    resumo = subprocess.run(["ogrinfo", "-ro", "-so", ws.caminho, "carga_trabalho"], capture_output=True, text=True,
                            check=True).stdout  # fmt: skip
    assert "Geometry: Multi Polygon" in resumo and "Feature Count: 7" in resumo and "4674" in resumo
    alertas = subprocess.run(["ogrinfo", "-ro", "-q", ws.caminho, "carga_trabalho"], capture_output=True,
                             text=True, check=True).stderr  # fmt: skip
    assert "Warning" not in alertas and "ERROR" not in alertas


# --- C4: só o plugin escreve; views das camadas da execução ---------------------------------------------------------


def _por_fora(ws):
    """Outra conexão ao arquivo, como a do OGR quando o QGIS grava a edição de uma camada."""
    conn = sqlite3.connect(ws.caminho, timeout=5, isolation_level=None)
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE carga_trabalho SET concluido = 1 WHERE id = 1001",
        "DELETE FROM carga_trabalho WHERE id = 1001",
        "INSERT INTO carga_trabalho (uuid, concluido) VALUES ('x', 0)",
        "UPDATE lote_etapa SET situacao = 'concluida' WHERE id = 11",
        "UPDATE tema SET nome = 'x'",
    ],
)
def test_escrita_por_fora_do_plugin_e_recusada_no_arquivo(ws, sql):
    conn = _por_fora(ws)
    try:
        with pytest.raises(sqlite3.IntegrityError, match="só muda pelas ações do Feixe"):
            conn.execute(sql)
        assert conn.execute("SELECT plugin FROM controle_escrita").fetchone() == (0,)
        assert conn.execute("SELECT count(*) FROM carga_trabalho").fetchone() == (7,)  # ler continua livre
    finally:
        conn.close()
    with ws.leitura() as ex:
        assert ex.pendentes() == [] and ex.um("SELECT concluido FROM carga_trabalho WHERE id = 1001")["concluido"] == 0


def test_o_interruptor_so_vale_dentro_da_transacao_do_plugin(ws):
    """O pull (`gravar_remoto`) e a execução (`atualizar`) gravam; depois do COMMIT, e de um ROLLBACK, a outra conexão
    continua recusada."""
    with ws.transacao() as ex:
        ex.gravar_remoto("carga_trabalho", carga(1004, 11, USUARIO, -47.5, -15.8))
        uuid = ex.um("SELECT uuid FROM carga_trabalho WHERE id = 1004")["uuid"]
        ex.atualizar("carga_trabalho", uuid, {"concluido": True})
    with pytest.raises(RuntimeError), ws.transacao() as ex:
        ex.atualizar("carga_trabalho", uuid, {"concluido": False})
        raise RuntimeError("falha no meio")
    conn = _por_fora(ws)
    try:
        assert conn.execute("SELECT plugin FROM controle_escrita").fetchone() == (0,)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE carga_trabalho SET concluido = 0 WHERE id = 1004")
    finally:
        conn.close()
    with ws.leitura() as ex:
        assert ex.um("SELECT concluido FROM carga_trabalho WHERE id = 1004")["concluido"] == 1
        assert len(ex.pendentes()) == 1


def test_views_das_camadas_da_execucao(ws):
    with ws.transacao() as ex:
        uuid = ex.um("SELECT uuid FROM carga_trabalho WHERE id = 1002")["uuid"]
        ex.atualizar("carga_trabalho", uuid, {"concluido": True})
    with ws.leitura() as ex:
        info = {r["id"]: r for r in ex.todos(f"SELECT * FROM {esquema.VW_CARGA_INFO}")}
        folhas = ex.todos(f"SELECT * FROM {esquema.VW_MINHAS_FOLHAS} ORDER BY id_lote")
        registradas = {r["table_name"]: r["data_type"] for r in ex.todos("SELECT * FROM gpkg_contents")}
    assert sorted(info) == [1001, 1002, 1003, 3001]  # só as minhas (1009 é de outra pessoa; 2001 e 2002, de ninguém)
    assert info[1002] == {
        "id": 1002, "id_lote": 1, "folha_revisao": "2534-1", "tema": "Hidrografia", "etapa": "Aquisição",
        "atividade": "Aquisição BC100 - Hidrografia", "situacao_etapa": "em_andamento", "minhas_na_folha": 3,
        "minhas_concluidas_na_folha": 1,
    }  # fmt: skip
    # Só as folhas com passagem aberta em que tenho carga: a 2536 está encerrada, a 2535 ainda não é minha.
    assert [(f["id_lote"], f["folha_revisao"], f["situacao"]) for f in folhas] == [(1, "2534-1", "em_andamento")]
    assert registradas[esquema.VW_CARGA_INFO] == "attributes" and registradas[esquema.VW_MINHAS_FOLHAS] == "features"


def test_esquema_2_ganha_os_gatilhos_e_as_views_sem_recriar(ws):
    with ws.transacao() as ex:
        uuid = ex.um("SELECT uuid FROM carga_trabalho WHERE id = 1001")["uuid"]
        ex.atualizar("carga_trabalho", uuid, {"concluido": True})
    conn = ws.conn
    conn.execute("BEGIN IMMEDIATE")
    for nome, tipo in conn.execute(
        "SELECT name, type FROM sqlite_master WHERE type IN ('trigger', 'view') OR name = 'controle_escrita'"
    ).fetchall():
        conn.execute(f"DROP {tipo.upper()} {nome}")
    conn.execute("DELETE FROM gpkg_geometry_columns WHERE table_name LIKE 'vw_%'")
    conn.execute("DELETE FROM gpkg_contents WHERE table_name LIKE 'vw_%'")
    conn.execute("UPDATE meta SET valor = '2' WHERE chave = 'versao_esquema'")
    conn.execute("COMMIT")
    ws.fechar()
    with Workspace.abrir("dev", USUARIO, "DF", path=ws.caminho) as w2:
        with w2.leitura() as ex:
            assert len(ex.pendentes()) == 1  # migrou, não recriou
            assert ex.meta("versao_esquema") == str(esquema.VERSAO)
            gatilhos = ex.um("SELECT count(*) AS n FROM sqlite_master WHERE type = 'trigger'")["n"]
            assert gatilhos == 3 * len(esquema.TABELAS)
            assert ex.um(f"SELECT count(*) AS n FROM {esquema.VW_CARGA_INFO}")["n"] == 4
        conn = _por_fora(w2)
        try:
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute("UPDATE carga_trabalho SET concluido = 0 WHERE id = 1001")
        finally:
            conn.close()
