#!/usr/bin/env python3
"""Gera feixe/db/ggc/002_foreign_tables_dblink.sql (espelho por dblink) a partir do catálogo do mapcartacomp da CCAR.

A variante postgres_fdw não precisa disto (IMPORT FOREIGN SCHEMA lê as colunas sozinho); a de dblink precisa da
lista de colunas e tipos de cada tabela. Rode depois de toda migração que mude colunas e commite o arquivo gerado:

    python3 scripts/db/gerar_espelho.py "<conexão da CCAR de dev>" > feixe/db/ggc/002_foreign_tables_dblink.sql

O teste tests/db/test_espelho.py falha se o arquivo commitado estiver diferente do que o catálogo gera.
"""

from __future__ import annotations

import sys

# As mesmas da variante postgres_fdw (002_foreign_tables_fdw.sql), na mesma ordem.
OBJETOS = [
    "schema_version", "tema", "fase", "atividade", "fluxo", "fluxo_etapa", "usuario_feixe", "calendario", "lote",
    "lote_etapa", "lote_etapa_hist", "carga_trabalho", "cq_plano", "cq_amostra", "cq_inspecao", "sync_log",
    "ctrl_lote_etapa", "ctrl_lote",
]  # fmt: skip

CABECALHO = """\
-- GGC 002 (variante dblink): mapcartacomp da CCAR como views somente leitura sobre dblink no banco da GGC.
-- Compatível com PostgreSQL 9.6. Idempotente. Requer 001_server_dblink.sql.
-- ARQUIVO GERADO por scripts/db/gerar_espelho.py a partir do catálogo da CCAR: não editar à mão.
--
-- Diferente da variante postgres_fdw, aqui os filtros não descem para a CCAR: cada consulta traz a tabela inteira
-- (o que a conta do mapeamento enxerga). Prefira postgres_fdw quando a DBA puder escolher.

CREATE SCHEMA IF NOT EXISTS mapcartacomp;

COMMENT ON SCHEMA mapcartacomp IS
    'Feixe: espelho somente leitura do mapcartacomp da CCAR (views sobre dblink). Não escrever aqui.';

DROP VIEW IF EXISTS mapcartacomp.vw_carga_trabalho, mapcartacomp.vw_cq_amostra, mapcartacomp.vw_cq_amostra_all,
    mapcartacomp.vw_cq_inspecao;
"""

SQL_COLUNAS = """
SELECT c.relname, a.attname, format_type(a.atttypid, a.atttypmod)
  FROM pg_attribute a
  JOIN pg_class c ON c.oid = a.attrelid
  JOIN pg_namespace n ON n.oid = c.relnamespace
 WHERE n.nspname = 'mapcartacomp' AND c.relname = ANY(%s) AND a.attnum > 0 AND NOT a.attisdropped
 ORDER BY c.relname, a.attnum
"""


def gerar(colunas: dict) -> str:
    partes = [CABECALHO]
    for obj in reversed(OBJETOS):
        partes.append(f"DROP VIEW IF EXISTS mapcartacomp.{obj};")
    for obj in OBJETOS:
        cols = colunas[obj]
        nomes = ", ".join(n for n, _ in cols)
        defs = ",\n           ".join(f"{n} {t}" for n, t in cols)
        partes.append(
            f"\nCREATE VIEW mapcartacomp.{obj} AS\n"
            f"    SELECT * FROM dblink('feixe_ccar_dblink', 'SELECT {nomes} FROM mapcartacomp.{obj}')\n"
            f"        AS t ({defs});"
        )
    return "\n".join(partes) + "\n"


def ler_catalogo(conninfo: str) -> dict:
    import psycopg2

    conn = psycopg2.connect(conninfo)
    try:
        with conn.cursor() as cur:
            cur.execute(SQL_COLUNAS, (OBJETOS,))
            colunas = {}
            for rel, nome, tipo in cur.fetchall():
                colunas.setdefault(rel, []).append((nome, tipo))
    finally:
        conn.close()
    faltam = [o for o in OBJETOS if o not in colunas]
    if faltam:
        raise SystemExit(f"objetos ausentes no mapcartacomp: {', '.join(faltam)}")
    return colunas


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    sys.stdout.write(gerar(ler_catalogo(argv[0])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
