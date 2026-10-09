"""Acesso ao PostgreSQL: banco do ambiente chumbado + credencial do Authentication Manager.

Cada thread abre a própria conexão (psycopg2 não compartilha conexões entre threads).
"""

from __future__ import annotations

import socket
from typing import Optional

import psycopg2
import psycopg2.extras

from . import config
from .ambiente import Ambiente


class SemCredencial(Exception):
    pass


def conninfo(amb: Ambiente, usuario: str = None, senha: str = None) -> str:
    if usuario is None:
        cred = config.credenciais(amb)
        if not cred:
            raise SemCredencial("usuário e senha ainda não configurados")
        usuario, senha = cred
    partes = {
        "host": amb.host,
        "port": amb.porta,
        "dbname": amb.banco,
        "user": usuario,
        "password": senha,
        "sslmode": amb.sslmode,
        "connect_timeout": "5",
        "application_name": "feixe",
    }
    return " ".join(f"{k}='{v}'" for k, v in partes.items() if v not in (None, ""))


def conectar(amb: Ambiente, usuario: str = None, senha: str = None):
    conn = psycopg2.connect(conninfo(amb, usuario, senha))
    conn.autocommit = False
    return conn


def alcancavel(amb: Ambiente, timeout: float = 2.0) -> bool:
    """Teste barato de rede: o banco responde TCP? Decide online/offline sem autenticar."""
    try:
        with socket.create_connection((amb.host, amb.porta), timeout=timeout):
            return True
    except OSError:
        return False


def testar(amb: Ambiente, usuario: str = None, senha: str = None) -> dict:
    """Testa a conexão e devolve usuário, versão do servidor e se o schema do feixe existe."""
    try:
        conn = conectar(amb, usuario, senha)
    except SemCredencial as e:
        return {"ok": False, "erro": str(e), "sem_credencial": True}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "erro": str(e).strip()}
    try:
        with conn, conn.cursor() as cur:
            cur.execute("SELECT current_user, version(), current_database()")
            usuario_db, versao, banco = cur.fetchone()
            cur.execute("SELECT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'mapcartacomp')")
            tem_schema = cur.fetchone()[0]
            versao_schema: Optional[int] = None
            if tem_schema:
                cur.execute(
                    "SELECT EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE n.nspname = 'mapcartacomp' AND c.relname = 'schema_version')"
                )
                if cur.fetchone()[0]:
                    cur.execute("SELECT max(versao) FROM mapcartacomp.schema_version")
                    versao_schema = cur.fetchone()[0]
        return {
            "ok": True,
            "usuario": usuario_db,
            "banco": banco,
            "versao_servidor": versao.split(",")[0],
            "schema_feixe": tem_schema,
            "versao_schema": versao_schema,
        }
    finally:
        conn.close()


def consultar(amb: Ambiente, sql: str, params=None) -> list:
    """Executa um SELECT com conexão própria e devolve linhas como dicionários."""
    conn = conectar(amb)
    try:
        with conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()
