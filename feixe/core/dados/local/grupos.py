"""Subgrupos da execução nas camadas do QGIS, sobre o workspace (C4, D-102, D3c).

As camadas da execução leem o workspace (online ou offline), então os subgrupos também saem dele: as atividades das
cargas da pessoa em passagens abertas, agrupadas como na CCAR (as de CQ de um tema num subgrupo só). A supervisão
continua na CCAR (`core/dados/grupos.py`).

Aqui fica também o que a montagem precisa decidir sem o QGIS (D3c), para os testes puros: o plano dos subgrupos da
execução (`plano_execucao`), os filtros das camadas do CQ (SQL do SQLite, aplicados pelo OGR como `subsetString`) e o
estado do CQ que a barra usa para mostrar as ações (`estado_cq`).
"""

from __future__ import annotations

from typing import Dict, List, Optional

from ..grupos import _agrupar
from . import SQL_ABERTAS

EU = "(SELECT valor FROM meta WHERE chave = 'usuario')"  # a conta do workspace, sem citar nada no filtro
_ABERTA = f"(SELECT id FROM lote_etapa WHERE situacao IN {SQL_ABERTAS})"


def _em(ids: List[int]) -> str:
    return ", ".join(str(int(i)) for i in ids) or "NULL"


def execucao(ex) -> List[Dict]:
    """Subgrupos da execução. Os de CQ trazem `elementos` (uma camada de amostras e uma de ocorrências por atividade,
    pelo elemento de qualidade); os de produção, `expor_ocorrencias` (tenho carga numa passagem aberta planejada com
    "incluir correções a serem feitas": a camada Correções a fazer)."""
    grupos = _agrupar(
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
    ids = sorted({i for g in grupos for i in g["atividades"]})
    nomes = {
        r["id"]: r["elemento"] or r["nome"]
        for r in ex.todos(f"SELECT id, nome, elemento FROM atividade WHERE id IN ({_em(ids)})")
    }
    expostas = {
        r["id_atividade"]
        for r in ex.todos(
            "SELECT DISTINCT c.id_atividade FROM carga_trabalho c JOIN lote_etapa le ON le.id = c.id_lote_etapa "
            f"WHERE c.responsavel = ? AND le.situacao IN {SQL_ABERTAS} AND le.expor_ocorrencias",
            (ex.usuario,),
        )
    }
    for g in grupos:
        if g["fase"] == "cq":
            g["elementos"] = sorted(
                ({"id_atividade": i, "elemento": nomes.get(i) or f"atividade {i}"} for i in g["atividades"]),
                key=lambda e: (e["elemento"].lower(), e["id_atividade"]),
            )
        else:
            g["expor_ocorrencias"] = any(i in expostas for i in g["atividades"])
    return grupos


def plano_execucao(grupos: List[Dict]) -> List[Dict]:
    """O que a Execução monta, subgrupo por subgrupo, na ordem dos grupos.

    - Produção: Minhas cargas e Minhas folhas (e Correções a fazer, com `expor_ocorrencias`). Com um grupo só, sem
      subgrupo intermediário e sem filtro de atividade (`rotulo` e `atividades` None), como no D-102.
    - CQ (D3c): sempre num subgrupo "CQ · tema", com Ocorrências e Amostras por elemento (uma atividade por medida) e
      Minhas folhas; só o primeiro elemento vem ligado.
    - Ninguém com carga aberta: Minhas cargas e Minhas folhas vazias, para a barra ter onde mostrar a próxima.
    """
    if not grupos:
        return [{"tipo": "producao", "rotulo": None, "atividades": None, "correcoes": False}]
    varios = len(grupos) > 1
    plano = []
    for g in grupos:
        if g.get("fase") == "cq":
            elementos = [dict(e, visivel=i == 0) for i, e in enumerate(g.get("elementos") or [])]
            plano.append({"tipo": "cq", "rotulo": g["rotulo"], "atividades": g["atividades"], "elementos": elementos})
        else:
            plano.append(
                {"tipo": "producao", "rotulo": g["rotulo"] if varios else None,
                 "atividades": g["atividades"] if varios else None, "correcoes": bool(g.get("expor_ocorrencias"))}
            )  # fmt: skip
    return plano


# --- filtros das camadas do CQ (SQLite, `subsetString` do OGR) -------------------------------------------------------


def filtro_amostras(id_atividade: int) -> str:
    """Cargas de CQ minhas, da atividade (um elemento), em passagens abertas."""
    return (
        f"responsavel = {EU} AND id_cq_plano IS NOT NULL AND id_atividade = {int(id_atividade)} "
        f"AND id_lote_etapa IN {_ABERTA}"
    )


def filtro_ocorrencias(id_atividade: int) -> str:
    """Ocorrências nas minhas amostras da atividade, em passagens abertas (as que registrei e as de outro avaliador na
    mesma amostra, se houver)."""
    return (
        "id_carga_trabalho IN (SELECT c.id FROM carga_trabalho c WHERE c.responsavel = "
        f"{EU} AND c.id_cq_plano IS NOT NULL AND c.id_atividade = {int(id_atividade)} AND c.id_lote_etapa IN {_ABERTA})"
    )


# Para ciência (D-66): apontam uma carga minha (sou quem fez a carga avaliada) e ainda sem ciência, de qualquer
# passagem (a ciência vale com a passagem encerrada).
FILTRO_CIENCIA = f"ciente_em IS NULL AND id_carga_avaliada IN (SELECT id FROM carga_trabalho WHERE responsavel = {EU})"


def filtro_correcoes(atividades: Optional[List[int]] = None) -> str:
    """Lista de correção (D-66, `expor_ocorrencias`): as não tratadas das folhas em que tenho carga numa passagem
    aberta planejada com "incluir correções a serem feitas" (e da atividade do subgrupo, se houver)."""
    extra = f" AND c.id_atividade IN ({_em(atividades)})" if atividades else ""
    return (
        "NOT tratado AND id_lote IN (SELECT le.id_lote FROM lote_etapa le WHERE le.expor_ocorrencias "
        f"AND le.situacao IN {SQL_ABERTAS} AND EXISTS (SELECT 1 FROM carga_trabalho c WHERE c.id_lote_etapa = le.id "
        f"AND c.responsavel = {EU}{extra}))"
    )


# --- estado do CQ para a barra ----------------------------------------------------------------------------------------


def estado_cq(ex) -> Dict[str, int]:
    """Quantas amostras tenho em passagens abertas (e quantas pendentes) e quantas ocorrências esperam a minha ciência:
    a barra mostra as ações do avaliador e o Ciente só para quem tem o que fazer."""
    a = ex.um(
        "SELECT count(*) AS n, coalesce(sum(CASE WHEN a.status IS NULL THEN 1 ELSE 0 END), 0) AS pendentes "
        "FROM carga_trabalho c JOIN cq_amostra a ON a.id_carga_trabalho = c.id "
        f"JOIN lote_etapa le ON le.id = c.id_lote_etapa WHERE c.responsavel = ? AND le.situacao IN {SQL_ABERTAS}",
        (ex.usuario,),
    )
    c = ex.um(
        "SELECT count(*) AS n FROM cq_inspecao WHERE ciente_em IS NULL "
        "AND id_carga_avaliada IN (SELECT id FROM carga_trabalho WHERE responsavel = ?)",
        (ex.usuario,),
    )
    return {"amostras": int(a["n"]), "pendentes": int(a["pendentes"]), "ciencia": int(c["n"])}


def cargas_cq_pendentes(ex) -> List[int]:
    """As minhas cargas de CQ pendentes: "Próxima carga" (produção) as deixa de fora; andam por "Próxima amostra"."""
    return [
        r["id"]
        for r in ex.todos(
            "SELECT id FROM carga_trabalho WHERE responsavel = ? AND NOT concluido AND id_cq_plano IS NOT NULL",
            (ex.usuario,),
        )
    ]


def e_cq(ex, id_lote_etapa: Optional[int]) -> bool:
    """A passagem é de CQ? (o texto da barra de status fala de amostras)."""
    if id_lote_etapa is None:
        return False
    r = ex.um(
        "SELECT fe.fase FROM lote_etapa le JOIN fluxo_etapa fe ON fe.id = le.id_fluxo_etapa WHERE le.id = ?",
        (id_lote_etapa,),
    )
    return bool(r) and r["fase"] == "cq"
