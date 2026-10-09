"""Acesso ao PostgreSQL a partir de uma conexão PostGIS cadastrada no QGIS.

A senha vem do Authentication Manager do QGIS no momento da conexão e não é guardada pelo plugin.
Cada thread abre a própria conexão (psycopg2 não compartilha conexões entre threads).
"""

from __future__ import annotations

import socket
from typing import Optional

import psycopg2
import psycopg2.extras
from qgis.core import QgsApplication, QgsDataSourceUri, QgsProviderRegistry


def conexoes_postgis() -> list:
    """Nomes das conexões PostGIS cadastradas no QGIS."""
    meta = QgsProviderRegistry.instance().providerMetadata("postgres")
    return sorted(meta.connections().keys())


def uri_da_conexao(nome: str) -> QgsDataSourceUri:
    meta = QgsProviderRegistry.instance().providerMetadata("postgres")
    conns = meta.connections()
    if nome not in conns:
        raise LookupError(f"Conexão PostGIS '{nome}' não existe no QGIS")
    uri = QgsDataSourceUri(conns[nome].uri())
    if uri.authConfigId():
        # expande usuário/senha guardados no Authentication Manager
        itens = QgsApplication.authManager().updateDataSourceUriItems([], uri.authConfigId(), "postgres")
        for item in itens or []:
            chave, _, valor = item.partition("=")
            if chave == "user":
                uri.setUsername(valor.strip("'"))
            elif chave == "password":
                uri.setPassword(valor.strip("'"))
    return uri


def conninfo(nome: str) -> str:
    uri = uri_da_conexao(nome)
    partes = {
        "host": uri.host(),
        "port": uri.port() or "5432",
        "dbname": uri.database(),
        "user": uri.username(),
        "password": uri.password(),
        "connect_timeout": "5",
        "application_name": "feixe",
    }
    if uri.sslMode() not in (QgsDataSourceUri.SslPrefer, QgsDataSourceUri.SslDisable, None):
        partes["sslmode"] = "require"
    return " ".join(f"{k}='{v}'" for k, v in partes.items() if v not in (None, ""))


def conectar(nome: str):
    conn = psycopg2.connect(conninfo(nome))
    conn.autocommit = False
    return conn


def host_porta(nome: str) -> tuple:
    uri = uri_da_conexao(nome)
    return uri.host(), int(uri.port() or 5432)


def alcancavel(host: str, porta: int, timeout: float = 2.0) -> bool:
    """Teste barato de rede: o banco responde TCP? Usado para decidir online/offline sem autenticar."""
    try:
        with socket.create_connection((host, porta), timeout=timeout):
            return True
    except OSError:
        return False


def testar(nome: str) -> dict:
    """Testa a conexão e devolve usuário, versão do servidor e se o schema do feixe existe."""
    try:
        conn = conectar(nome)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "erro": str(e).strip()}
    try:
        with conn, conn.cursor() as cur:
            cur.execute("SELECT current_user, version(), current_database()")
            usuario, versao, banco = cur.fetchone()
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
            "usuario": usuario,
            "banco": banco,
            "versao_servidor": versao.split(",")[0],
            "schema_feixe": tem_schema,
            "versao_schema": versao_schema,
        }
    finally:
        conn.close()


def consultar(nome: str, sql: str, params=None) -> list:
    """Executa um SELECT com conexão própria e devolve linhas como dicionários."""
    conn = conectar(nome)
    try:
        with conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()
