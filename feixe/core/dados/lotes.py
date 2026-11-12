"""Lotes (folhas e lotes livres): leituras e escritas das rotas. Recebe um `Executor` (ver o pacote)."""

from __future__ import annotations

from typing import Dict, List, Optional

from . import Executor


def temas_com_lotes(ex: Executor, uf: Optional[str]) -> List[Dict]:
    """Temas que têm lote na UF (todas as UFs se nula), com quantos lotes, em ordem de nome."""
    sql = (
        "SELECT t.id, t.nome, count(*) AS lotes FROM mapcartacomp.tema t "
        "JOIN mapcartacomp.lote l ON l.id_tema = t.id"
        + (" WHERE l.uf = %s" if uf else "")
        + " GROUP BY t.id, t.nome ORDER BY t.nome"
    )
    return ex.todos(sql, (uf,) if uf else ())
