"""A5: o espelho por dblink commitado corresponde ao catálogo atual da CCAR.

A aplicação do espelho e a comparação de contagens ficam em scripts/db/testar_espelho.sh, porque instalam o
espelho de verdade no banco da GGC de dev (fora de transação).
"""

from __future__ import annotations

import os

import pytest
from scripts.db.gerar_espelho import gerar, ler_catalogo

from tests.db.conftest import RAIZ, url

pytestmark = pytest.mark.db


def test_espelho_dblink_atualizado(psycopg2):
    caminho = os.path.join(RAIZ, "feixe", "db", "ggc", "002_foreign_tables_dblink.sql")
    with open(caminho, encoding="utf-8") as f:
        commitado = f.read()
    assert commitado == gerar(ler_catalogo(url("FEIXE_CCAR"))), (
        "rode scripts/db/gerar_espelho.py e commite feixe/db/ggc/002_foreign_tables_dblink.sql"
    )
