"""Testes contra os bancos de dev (marcador `db`). Leem FEIXE_CCAR e FEIXE_GGC do ambiente ou do `.dev.env` na raiz.

Sem `.dev.env` (ex.: no CI) ou sem psycopg2, os testes são pulados. `make test` não os roda; use `make test-db`.
"""

from __future__ import annotations

import os

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _ler_dev_env() -> dict:
    caminho = os.path.join(RAIZ, ".dev.env")
    valores = {}
    if os.path.isfile(caminho):
        with open(caminho, encoding="utf-8") as f:
            for linha in f:
                linha = linha.strip()
                if linha and not linha.startswith("#") and "=" in linha:
                    k, v = linha.split("=", 1)
                    valores[k.strip()] = v.strip().strip("'\"")
    return valores


_ENV = _ler_dev_env()


def url(nome: str) -> str:
    valor = os.environ.get(nome) or _ENV.get(nome)
    if not valor:
        pytest.skip(f"{nome} não definido (.dev.env ausente)")
    return valor


def pytest_collection_modifyitems(items):
    for item in items:
        if "tests/db/" in str(item.fspath).replace(os.sep, "/"):
            item.add_marker(pytest.mark.db)


@pytest.fixture(scope="session")
def psycopg2():
    return pytest.importorskip("psycopg2")


@pytest.fixture(params=["FEIXE_CCAR", "FEIXE_GGC"], ids=["ccar17", "ggc96"])
def banco(request, psycopg2):
    """Conexão a cada banco de dev, numa transação que é desfeita no fim do teste."""
    conn = psycopg2.connect(url(request.param))
    conn.autocommit = False
    try:
        yield conn
    finally:
        conn.rollback()
        conn.close()
