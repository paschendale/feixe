"""Fila de folhas no workspace (D-111, item 3): a versão local de `filas.puxar` (B8, D-106).

O supervisor planeja a fila online, na CCAR; o pull (C2) traz para o workspace os itens da fila da pessoa e as cargas
ainda sem responsável dessas folhas. Quando a pessoa conclui a última carga pendente que tem (em qualquer etapa
aberta), a próxima folha da fila é puxada aqui mesmo, na hora, online ou offline, e cada mudança vira item da outbox:
as cargas que passam para a pessoa, o item da fila marcado como atribuído e, se a passagem ainda não tinha começado,
a passagem iniciada com a linha no histórico (como o `_iniciar` do `atribuir`, D-109).

Regras da CCAR que valem aqui (D-106): só anda quando não sobrou carga pendente minha em etapa aberta; item sem nada a
atribuir é pulado e fica na fila; só as cargas a atribuir mudam de mão. O perfil da pessoa no SGBC não é conferido no
workspace (mapcartctrl não vem para o workspace): a folha só entrou na fila depois dessa conferência, no
`filas.adicionar`, e o push confere de novo. Recusa no push (perdeu o perfil, outra pessoa pegou as cargas) desfaz o
local e fica no sync_log (D-111, item 5; C3).
"""

from __future__ import annotations

from typing import Dict, Optional

from . import SQL_ABERTAS, rotulo


def puxar(ex, responsavel: str) -> Optional[Dict]:
    """Depois que `responsavel` conclui uma carga: se não sobrou pendente dele em etapa aberta, atribui a ele as cargas
    a atribuir do primeiro item da fila com algo a atribuir. Volta o que foi atribuído (mesmo formato da CCAR) ou
    None."""
    falta = ex.um(
        "SELECT count(*) AS n FROM carga_trabalho c JOIN lote_etapa le ON le.id = c.id_lote_etapa "
        f"WHERE c.responsavel = ? AND NOT c.concluido AND le.situacao IN {SQL_ABERTAS}",
        (responsavel,),
    )["n"]
    if falta:
        return None
    fila = ex.todos(
        "SELECT f.id, f.uuid, f.uf, f.id_lote_etapa, le.uuid AS uuid_lote_etapa, le.situacao, le.id_lote, "
        f"{rotulo()} AS folha_revisao, t.nome AS tema "
        "FROM fila_folha f JOIN lote_etapa le ON le.id = f.id_lote_etapa JOIN lote l ON l.id = le.id_lote "
        "LEFT JOIN tema t ON t.id = l.id_tema "
        f"WHERE f.responsavel = ? AND f.atribuida_em IS NULL AND le.situacao IN {SQL_ABERTAS} "
        "ORDER BY f.ordem, f.fid",
        (responsavel,),
    )
    for item in fila:
        livres = ex.todos(
            "SELECT uuid FROM carga_trabalho WHERE id_lote_etapa = ? AND uf = ? AND responsavel IS NULL "
            "AND NOT concluido ORDER BY id",
            (item["id_lote_etapa"], item["uf"]),
        )
        if not livres:
            continue
        for c in livres:
            ex.atualizar("carga_trabalho", c["uuid"], {"responsavel": responsavel})
        if item["situacao"] == "pendente":
            ex.atualizar("lote_etapa", item["uuid_lote_etapa"], {"situacao": "em_andamento", "iniciada_em": ex.agora})
            ex.inserir(
                "lote_etapa_hist",
                {"id_lote_etapa": item["id_lote_etapa"], "uf": item["uf"], "acao": "iniciar", "em": ex.agora,
                 "por": ex.usuario, "observacao": "Iniciada ao distribuir as cargas"},
            )  # fmt: skip
        ex.atualizar("fila_folha", item["uuid"], {"atribuida_em": ex.agora, "atribuidas": len(livres)})
        return {
            "id": item["id"],
            "id_lote": item["id_lote"],
            "id_lote_etapa": item["id_lote_etapa"],
            "folha_revisao": item["folha_revisao"],
            "tema": item["tema"],
            "atribuidas": len(livres),
        }
    return None
