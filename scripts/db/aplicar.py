#!/usr/bin/env python3
"""Aplica as migrações de feixe/db/ccar que faltam num banco e registra cada uma em mapcartacomp.schema_version.

Uso:
    python3 scripts/db/aplicar.py [--ensaio] [--role <role_dona>] <conninfo> [ate_versao]

    <conninfo>    string de conexão (URL postgresql://... ou "host=... dbname=... user=...")
    [ate_versao]  aplica só até esta versão (padrão: todas)
    --role        faz SET ROLE para a role de administração do schema antes de aplicar: quem conecta com o usuário
                  pessoal (membro dela) cria os objetos em nome dela, e não no seu. As funções SECURITY DEFINER
                  rodam como a dona, que precisa ler o mapcartctrl.
    --ensaio      aplica as migrações que faltam numa transação e desfaz tudo no fim (ROLLBACK): prova que o SQL
                  roda naquele servidor sem mudar nada. É como se verifica a compatibilidade com o PostgreSQL 9.6.

Todas as migrações pendentes rodam numa única transação: ou entram todas, ou nenhuma. Rodar de novo sem migrações
novas não faz nada. Sem a senha na conninfo, ela é pedida no terminal (ou lida de PGPASSWORD / ~/.pgpass).

Só precisa de Python 3 e psycopg2, sem psql nem bash: roda com o Python do QGIS (no Windows, o "OSGeo4W Shell"
ou `python-qgis-ltr.bat`), que já traz o psycopg2.
"""

from __future__ import annotations

import argparse
import getpass
import os
import re
import sys
from typing import List, Optional, Tuple

DIR = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "feixe", "db", "ccar"))
MIGRACAO = re.compile(r"^(\d{3})_.+\.sql$")
NOME_ROLE = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")

SQL_TEM_VERSAO = (
    "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
    "WHERE n.nspname = 'mapcartacomp' AND c.relname = 'schema_version'"
)


def migracoes(diretorio: str = DIR) -> List[Tuple[int, str]]:
    """(versão, caminho) de cada migração, em ordem."""
    saida = []
    for nome in sorted(os.listdir(diretorio)):
        m = MIGRACAO.match(nome)
        if m:
            saida.append((int(m.group(1)), os.path.join(diretorio, nome)))
    return saida


def pendentes(atual: int, ate: int, diretorio: str = DIR) -> List[Tuple[int, str]]:
    return [(v, f) for v, f in migracoes(diretorio) if atual < v <= ate]


def _conectar(conninfo: str):
    import psycopg2

    try:
        return psycopg2.connect(conninfo)
    except psycopg2.OperationalError as e:
        if "password" not in str(e).lower() or not sys.stdin.isatty():
            raise
        return psycopg2.connect(conninfo, password=getpass.getpass("senha: "))


def aplicar(
    conninfo: str, ate: int = 999999, ensaio: bool = False, role: Optional[str] = None, saida=sys.stdout
) -> int:
    conn = _conectar(conninfo)
    try:
        with conn.cursor() as cur:
            cur.execute("SET client_min_messages = warning")
            if role:
                if not NOME_ROLE.match(role):
                    raise ValueError(f"nome de role inválido: {role}")
                cur.execute(f'SET ROLE "{role}"')
            cur.execute(SQL_TEM_VERSAO)
            atual = 0
            if cur.fetchone()[0] == 1:
                cur.execute("SELECT coalesce(max(versao), 0) FROM mapcartacomp.schema_version")
                atual = cur.fetchone()[0]
            lista = pendentes(atual, ate)
            if not lista:
                conn.rollback()
                print(f"nada a aplicar: banco na versão {atual}", file=saida)
                return 0
            for v, caminho in lista:
                nome = os.path.basename(caminho)
                print(f"aplicando {nome}", file=saida)
                with open(caminho, encoding="utf-8") as f:
                    cur.execute(f.read())
                cur.execute(
                    "INSERT INTO mapcartacomp.schema_version (versao, nome) VALUES (%s, %s)", (v, nome[: -len(".sql")])
                )
        final = lista[-1][0]
        if ensaio:
            conn.rollback()
            print(f"ensaio ok: {len(lista)} migrações ({atual + 1} a {final}) aplicadas e desfeitas", file=saida)
        else:
            conn.commit()
            print(f"aplicadas {len(lista)} migrações: versão {atual} -> {final}", file=saida)
        return 0
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ensaio", action="store_true", help="aplica e desfaz no fim (ROLLBACK)")
    p.add_argument("--role", help="role de administração do schema (SET ROLE antes de aplicar)")
    p.add_argument("conninfo", help='URL postgresql://... ou "host=... dbname=... user=..."')
    p.add_argument("ate_versao", nargs="?", type=int, default=999999, help="aplica só até esta versão")
    a = p.parse_args(argv)
    try:
        return aplicar(a.conninfo, a.ate_versao, a.ensaio, a.role)
    except Exception as e:  # mensagem do banco sem traceback; nada ficou aplicado
        print(f"erro, nada foi aplicado: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
