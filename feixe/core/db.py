"""Acesso ao PostgreSQL: banco do ambiente chumbado + credencial do Authentication Manager.

Conexões reaproveitadas (D-104): abrir uma conexão custa 3 a 4 idas e voltas na rede (TCP, SSL, autenticação), e da
GGC até a CCAR cada ida e volta passa de 100 ms. Por isso as transações pegam uma conexão ociosa do `_Pool` e a
devolvem no fim, em vez de abrir e fechar a cada requisição. Uma conexão só serve a uma transação por vez; a que
quebra (rede caiu, banco reiniciou) é descartada. A credencial lida do Authentication Manager fica em memória até
`esquecer()` (troca de usuário e senha), que também fecha as conexões ociosas.
"""

from __future__ import annotations

import contextlib
import socket
import threading
import time
from contextlib import contextmanager
from typing import Iterator, Optional

import psycopg2
import psycopg2.extensions
import psycopg2.extras

from . import config
from .ambiente import Ambiente
from .dados import ExecutorPg


class SemCredencial(Exception):
    pass


def conninfo(amb: Ambiente, usuario: str = None, senha: str = None, timeout_conexao: int = 10) -> str:
    if usuario is None:
        cred = _credencial(amb)
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
        "connect_timeout": str(int(timeout_conexao)),
        "application_name": "feixe",
        # Conexão ociosa que a rede derrubou é percebida e fechada pelo libpq, em vez de travar na próxima consulta.
        "keepalives": "1",
        "keepalives_idle": "30",
        "keepalives_interval": "10",
        "keepalives_count": "3",
    }
    return " ".join(f"{k}='{v}'" for k, v in partes.items() if v not in (None, ""))


_cred_cache: dict = {}


def _credencial(amb: Ambiente):
    """Credencial do Authentication Manager, lida uma vez (cada leitura decifra a configuração)."""
    if amb.nome not in _cred_cache:
        cred = config.credenciais(amb)
        if not cred:
            return None
        _cred_cache[amb.nome] = cred
    return _cred_cache[amb.nome]


class _Pool:
    """Conexões ociosas por conninfo. Pequeno de propósito: o painel faz poucas requisições ao mesmo tempo."""

    MAX_OCIOSAS = 6
    MAX_IDADE_OCIOSA = 300  # segundos: depois disso, fecha em vez de reaproveitar
    CONFERIR_DEPOIS = 30  # ociosa há mais que isso: um SELECT 1 antes de usar (uma ida e volta, não três ou quatro)

    def __init__(self):
        self._trava = threading.Lock()
        self._ociosas: dict = {}  # conninfo -> [(conn, devolvida_em)]

    def pegar(self, info: str):
        agora = time.monotonic()
        with self._trava:
            fila = self._ociosas.get(info, [])
            while fila:
                conn, quando = fila.pop()
                if conn.closed or agora - quando > self.MAX_IDADE_OCIOSA:
                    _fechar(conn)
                    continue
                break
            else:
                conn = None
        if conn is not None and agora - quando > self.CONFERIR_DEPOIS and not _viva(conn):
            _fechar(conn)
            conn = None
        if conn is not None:
            return conn
        conn = psycopg2.connect(info)
        conn.autocommit = False
        return conn

    def devolver(self, info: str, conn) -> None:
        if conn.closed or conn.get_transaction_status() != psycopg2.extensions.TRANSACTION_STATUS_IDLE:
            _fechar(conn)
            return
        with self._trava:
            fila = self._ociosas.setdefault(info, [])
            if len(fila) < self.MAX_OCIOSAS:
                fila.append((conn, time.monotonic()))
                return
        _fechar(conn)

    def fechar_tudo(self) -> None:
        with self._trava:
            todas = [c for fila in self._ociosas.values() for c, _ in fila]
            self._ociosas.clear()
        for c in todas:
            _fechar(c)


def _viva(conn) -> bool:
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
        conn.rollback()
        return True
    except Exception:  # noqa: BLE001
        return False


def _fechar(conn) -> None:
    with contextlib.suppress(Exception):
        conn.close()


_pool = _Pool()


def esquecer() -> None:
    """Troca de credencial ou plugin descarregado: esquece a credencial guardada e fecha as conexões ociosas."""
    _cred_cache.clear()
    _pool.fechar_tudo()


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
    """Executa um SELECT numa conexão do pool e devolve linhas como dicionários."""
    with transacao(amb) as ex:
        return ex.todos(sql, params)


@contextmanager
def transacao(amb: Ambiente, usuario: str = None, senha: str = None, timeout_conexao: int = 10) -> Iterator[ExecutorPg]:
    """Transação numa conexão do pool, com a credencial do usuário: commit ao sair, rollback em qualquer erro.

    Uma conexão ociosa que a rede derrubou falha já na primeira consulta; nesse caso a requisição devolve o erro e a
    conexão é descartada, e a próxima abre uma nova. `timeout_conexao` (segundos) mais curto para a sincronização,
    que não pode deixar a pessoa esperando quando a CCAR não responde."""
    info = conninfo(amb, usuario, senha, timeout_conexao)
    conn = _pool.pegar(info)
    try:
        with conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            yield ExecutorPg(cur)
    except (psycopg2.OperationalError, psycopg2.InterfaceError):
        _fechar(conn)
        raise
    finally:
        _pool.devolver(info, conn)
