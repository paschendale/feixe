"""Aplica as migrações de feixe/db/ccar dentro da transação de uma conexão de teste, sem confirmar."""

from __future__ import annotations

import glob
import os

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DIR_CCAR = os.path.join(RAIZ, "feixe", "db", "ccar")


def arquivos(ate: int = 999) -> list:
    saida = []
    for caminho in sorted(glob.glob(os.path.join(DIR_CCAR, "[0-9][0-9][0-9]_*.sql"))):
        if int(os.path.basename(caminho)[:3]) <= ate:
            saida.append(caminho)
    return saida


def aplicar(conn, ate: int = 999, vezes: int = 1) -> None:
    """Executa o SQL cru de cada migração (sem passar por schema_version). Com vezes=2 prova a idempotência do SQL."""
    with conn.cursor() as cur:
        cur.execute("SET LOCAL client_min_messages = warning")
        for _ in range(vezes):
            for caminho in arquivos(ate):
                with open(caminho, encoding="utf-8") as f:
                    cur.execute(f.read())
