"""A1: migração v1 de mapcartacomp. Roda nos dois bancos de dev (PostgreSQL 17 da CCAR e 9.6 da GGC).

Na CCAR o schema está aplicado de verdade; na GGC (9.6) só em ensaio, numa transação desfeita, para provar a
compatibilidade sem criar nada lá. Os testes que conferem o modelo aplicam as migrações numa transação desfeita.
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

from tests.db.conftest import RAIZ, url
from tests.db.migracoes import aplicar, arquivos

APLICAR = os.path.join(RAIZ, "scripts", "db", "aplicar.py")
VERSAO_ESPERADA = int(os.path.basename(arquivos()[-1])[:3])

TABELAS = {
    "schema_version", "tema", "fase", "atividade", "fluxo", "fluxo_etapa", "fluxo_etapa_atividade", "cq_elemento",
    "usuario_feixe", "calendario", "lote", "lote_etapa", "lote_etapa_hist", "carga_trabalho", "cq_plano", "cq_amostra",
    "cq_inspecao", "sync_log",
}  # fmt: skip

# Tabelas sincronizadas com o workspace local: uuid do plugin, uf e auditoria.
SINCRONIZADAS = ["lote", "lote_etapa", "lote_etapa_hist", "carga_trabalho", "cq_plano", "cq_amostra", "cq_inspecao"]
AUDITORIA = {"criado_em": "timestamp with time zone", "criado_por": "text",
             "atualizado_em": "timestamp with time zone", "atualizado_por": "text"}  # fmt: skip


def _rodar(*args) -> str:
    r = subprocess.run([sys.executable, APLICAR, *args], capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stderr
    return r.stdout


def _colunas(cur, tabela: str) -> dict:
    cur.execute(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_schema = 'mapcartacomp' AND table_name = %s",
        (tabela,),
    )
    return dict(cur.fetchall())


def _catalogo(cur) -> list:
    """Retrato do schema: colunas, restrições e índices. Serve para provar que reaplicar não muda nada."""
    cur.execute(
        """
        SELECT 'col', table_name || '.' || column_name || ':' || data_type || ':' || is_nullable
          FROM information_schema.columns WHERE table_schema = 'mapcartacomp'
        UNION ALL
        SELECT 'con', conrelid::regclass::text || ':' || conname || ':' || pg_get_constraintdef(oid)
          FROM pg_constraint WHERE connamespace = 'mapcartacomp'::regnamespace
        UNION ALL
        SELECT 'idx', indexrelid::regclass::text FROM pg_index i JOIN pg_class c ON c.oid = i.indrelid
         WHERE c.relnamespace = 'mapcartacomp'::regnamespace
        UNION ALL
        SELECT 'fase', codigo || ':' || status_nacional FROM mapcartacomp.fase
        ORDER BY 1, 2
        """
    )
    return cur.fetchall()


@pytest.mark.db
def test_aplicar_na_ccar_e_idempotente(psycopg2):
    ccar = url("FEIXE_CCAR")
    _rodar(ccar)
    assert _rodar(ccar).startswith("nada a aplicar")
    conn = psycopg2.connect(ccar)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT max(versao), count(*) FROM mapcartacomp.schema_version")
            assert cur.fetchone() == (VERSAO_ESPERADA, VERSAO_ESPERADA)
    finally:
        conn.close()


@pytest.mark.db
def test_aplicar_ensaio_no_96(psycopg2):
    """O ensaio aplica tudo no 9.6 e desfaz: o banco da GGC termina sem nada do Feixe."""
    ggc = url("FEIXE_GGC")
    sql_objetos = (
        "SELECT c.relname, c.relkind FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = 'mapcartacomp' ORDER BY 1"
    )
    conn = psycopg2.connect(ggc)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT split_part(version(), ' ', 2)")
            assert cur.fetchone()[0].startswith("9.6")
            cur.execute(sql_objetos)
            antes = cur.fetchall()
            saida = _rodar("--ensaio", ggc)
            assert f"ensaio ok: {VERSAO_ESPERADA} migrações (1 a {VERSAO_ESPERADA})" in saida
            cur.execute(sql_objetos)
            assert cur.fetchall() == antes
    finally:
        conn.close()


@pytest.mark.db
def test_sql_reaplicado_nao_muda_o_catalogo(banco):
    aplicar(banco)
    with banco.cursor() as cur:
        antes = _catalogo(cur)
    aplicar(banco, vezes=2)
    with banco.cursor() as cur:
        assert _catalogo(cur) == antes


@pytest.mark.db
def test_tabelas_e_colunas(banco):
    aplicar(banco)
    with banco.cursor() as cur:
        cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'mapcartacomp'")
        assert {r[0] for r in cur.fetchall()} >= TABELAS
        for tabela in SINCRONIZADAS:
            cols = _colunas(cur, tabela)
            assert cols.get("uuid") == "uuid", tabela
            assert cols.get("uf") == "character", tabela
            for nome, tipo in AUDITORIA.items():
                assert cols.get(nome) == tipo, f"{tabela}.{nome}"
        cur.execute(
            "SELECT g.f_table_name, g.type, g.srid FROM public.geometry_columns g "
            "JOIN information_schema.tables t ON t.table_schema = g.f_table_schema AND t.table_name = g.f_table_name "
            "WHERE g.f_table_schema = 'mapcartacomp' AND t.table_type = 'BASE TABLE'"
        )
        geoms = {r[0]: (r[1], r[2]) for r in cur.fetchall()}
        assert geoms == {
            "lote": ("MULTIPOLYGON", 4674),
            "carga_trabalho": ("MULTIPOLYGON", 4674),
            "cq_inspecao": ("POINT", 4674),
        }


@pytest.mark.db
def test_chaves_estrangeiras(banco):
    aplicar(banco)
    with banco.cursor() as cur:
        cur.execute(
            """
            SELECT c.conrelid::regclass::text, c.confrelid::regclass::text
              FROM pg_constraint c
             WHERE c.contype = 'f' AND c.connamespace = 'mapcartacomp'::regnamespace
            """
        )
        fks = set(cur.fetchall())
    esperadas = {
        ("mapcartacomp.atividade", "mapcartctrl.t_projeto"),
        ("mapcartacomp.fluxo", "mapcartctrl.t_projeto"),
        ("mapcartacomp.lote", "mapcartctrl.t_projeto"),
        ("mapcartacomp.lote", "mapcartctrl.t_articulacao_scn"),
        ("mapcartacomp.usuario_feixe", "mapcartctrl.t_usuario"),
        ("mapcartacomp.cq_elemento", "mapcartctrl.t_qua_medidadequalidade"),
        ("mapcartacomp.atividade", "mapcartacomp.cq_elemento"),
        ("mapcartacomp.fluxo_etapa_atividade", "mapcartacomp.fluxo_etapa"),
        ("mapcartacomp.fluxo_etapa_atividade", "mapcartacomp.atividade"),
        ("mapcartacomp.cq_plano", "mapcartacomp.atividade"),
        ("mapcartacomp.carga_trabalho", "mapcartacomp.atividade"),
        ("mapcartacomp.lote", "mapcartacomp.fluxo"),
        ("mapcartacomp.lote", "mapcartacomp.lote_etapa"),
        ("mapcartacomp.lote_etapa", "mapcartacomp.lote"),
        ("mapcartacomp.lote_etapa", "mapcartacomp.fluxo_etapa"),
        ("mapcartacomp.carga_trabalho", "mapcartacomp.lote_etapa"),
        ("mapcartacomp.carga_trabalho", "mapcartacomp.cq_plano"),
        ("mapcartacomp.cq_plano", "mapcartacomp.lote_etapa"),
        ("mapcartacomp.cq_amostra", "mapcartacomp.cq_plano"),
        ("mapcartacomp.cq_amostra", "mapcartacomp.carga_trabalho"),
        ("mapcartacomp.cq_inspecao", "mapcartacomp.lote"),
        ("mapcartacomp.cq_inspecao", "mapcartacomp.carga_trabalho"),
        ("mapcartacomp.cq_inspecao", "mapcartacomp.lote_etapa"),
    }
    assert esperadas <= fks, esperadas - fks


@pytest.mark.db
def test_seed_de_fase(banco):
    aplicar(banco)
    with banco.cursor() as cur:
        cur.execute("SELECT codigo, status_nacional FROM mapcartacomp.fase ORDER BY ordem")
        assert cur.fetchall() == [
            ("aquisicao", "EM_PRODUCAO"),
            ("revisao", "EM_PRODUCAO"),
            ("cq", "EM_CQ"),
            ("correcao_inspecao", "EM_PRODUCAO"),
            ("correcao_topologica", "EM_PRODUCAO"),
            ("envio_gcq", "ENTREGUE_GCQ"),
            ("outra", "EM_PRODUCAO"),
        ]


@pytest.mark.db
def test_folha_unica_por_projeto_e_tema(banco, psycopg2):
    """A mesma folha entra uma vez por projeto + tema, mas pode aparecer em vários temas."""
    aplicar(banco)
    with banco.cursor() as cur:
        cur.execute("SELECT id_articulacao_scn FROM mapcartctrl.t_articulacao_scn LIMIT 1")
        folha = cur.fetchone()[0]
        cur.execute("INSERT INTO mapcartacomp.tema (nome) VALUES ('t_a'), ('t_b') RETURNING id")
        ta, tb = (r[0] for r in cur.fetchall())
        ids = []
        for t in (ta, tb):
            cur.execute(
                "INSERT INTO mapcartacomp.fluxo (cod_projeto, id_tema, uf, nome) VALUES (5, %s, 'DF', 'f') "
                "RETURNING id",
                (t,),
            )
            ids.append((t, cur.fetchone()[0]))
        sql = (
            "INSERT INTO mapcartacomp.lote (uuid, cod_projeto, id_tema, id_fluxo, uf, tipo, id_articulacao_scn, nome) "
            "VALUES (md5(random()::text)::uuid, 5, %s, %s, 'DF', 'folha', %s, 'x')"
        )
        for t, f in ids:
            cur.execute(sql, (t, f, folha))
        cur.execute("SAVEPOINT s")
        with pytest.raises(psycopg2.IntegrityError):
            cur.execute(sql, (ids[0][0], ids[0][1], folha))
        cur.execute("ROLLBACK TO SAVEPOINT s")
        # Fluxo de outro tema é recusado (FK composta lote -> fluxo).
        with pytest.raises(psycopg2.IntegrityError):
            cur.execute(sql.replace("'folha', %s", "'livre', NULL"), (ta, ids[1][1]))


def test_executor_pg_le_e_escreve_na_transacao(banco):
    """O executor da camada de dados sobre um cursor de dicionários (B0)."""
    import psycopg2.extras
    from feixe.core.dados import ExecutorPg

    with banco.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        ex = ExecutorPg(cur)
        ex.executar("CREATE TEMP TABLE t_b0 (x int)")
        assert ex.executar("INSERT INTO t_b0 VALUES (1), (2)") == 2
        assert ex.um("SELECT sum(x) AS s FROM t_b0") == {"s": 2 + 1}
        assert ex.um("SELECT x FROM t_b0 WHERE x > 5") is None
