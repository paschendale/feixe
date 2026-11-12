"""Cargas de trabalho: leituras e escritas das rotas. Recebe um `Executor` (ver o pacote)."""

from __future__ import annotations

from typing import Dict, List, Optional

from . import Executor

# Passagens atuais e abertas dos lotes (pendentes ou em andamento): é o que o supervisor está distribuindo agora. A
# passagem atual já concluída (folha esperando o supervisor andar) fica de fora.
SQL_PASSAGENS_ATUAIS = (
    "SELECT le.id FROM mapcartacomp.lote l JOIN mapcartacomp.lote_etapa le ON le.id = l.id_lote_etapa_atual "
    "WHERE le.situacao IN ('pendente', 'em_andamento')"
)


def responsaveis_atuais(ex: Executor, uf: Optional[str]) -> List[Dict]:
    """Quem tem carga nas passagens atuais dos lotes da UF, com o nome do SGBC e quantas cargas tem."""
    sql = (
        "SELECT c.responsavel AS conta, coalesce(u.nom_usuario::text, c.responsavel) AS nome, count(*) AS cargas "
        "FROM mapcartacomp.carga_trabalho c "
        "LEFT JOIN mapcartctrl.t_usuario u ON u.nom_contausuario = c.responsavel "
        f"WHERE c.responsavel IS NOT NULL AND c.id_lote_etapa IN ({SQL_PASSAGENS_ATUAIS}"
    )
    params: tuple = ()
    if uf:
        sql += " AND l.uf = %s) AND c.uf = %s"
        params = (uf, uf)
    else:
        sql += ")"
    sql += " GROUP BY c.responsavel, u.nom_usuario ORDER BY 2"
    return ex.todos(sql, params)
