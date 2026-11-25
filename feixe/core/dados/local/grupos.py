"""Subgrupos da execução nas camadas do QGIS, sobre o workspace (C4, D-102).

As camadas da execução leem o workspace (online ou offline), então os subgrupos também saem dele: as atividades das
cargas da pessoa em passagens abertas, agrupadas como na CCAR (as de CQ de um tema num subgrupo só). A supervisão
continua na CCAR (`core/dados/grupos.py`).
"""

from __future__ import annotations

from typing import Dict, List

from ..grupos import _agrupar
from . import SQL_ABERTAS


def execucao(ex) -> List[Dict]:
    return _agrupar(
        ex.todos(
            "SELECT DISTINCT t.id AS id_tema, t.nome AS tema, fe.fase, f.ordem AS ordem_fase, a.id AS id_atividade, "
            "a.nome AS atividade FROM carga_trabalho c "
            "JOIN lote_etapa le ON le.id = c.id_lote_etapa "
            "JOIN lote l ON l.id = le.id_lote "
            "JOIN fluxo_etapa fe ON fe.id = le.id_fluxo_etapa "
            "JOIN fase f ON f.codigo = fe.fase "
            "JOIN atividade a ON a.id = c.id_atividade "
            "JOIN tema t ON t.id = l.id_tema "
            f"WHERE c.responsavel = ? AND le.situacao IN {SQL_ABERTAS}",
            (ex.usuario,),
        )
    )
