"""Subgrupos dinâmicos das camadas do Feixe no QGIS (D-102): um por atividade em produção agora.

"Em produção" = atividade da etapa aberta (pendente ou em andamento) de um lote; cada lote tem no máximo uma. Não é
a "etapa atual" do lote (`id_lote_etapa_atual`), que fica na etapa concluída até a seguinte começar, porque é ela que
dá o status nacional (D-105): uma etapa aberta e ainda não iniciada já está em produção para o supervisor. Aqui, a
supervisão: a etapa dos lotes da UF, na CCAR; a execução sai do workspace (`local/grupos.py`). As atividades de CQ de
um tema (uma por medida) ficam num subgrupo só, "CQ · tema": são as mesmas folhas e a divisão fina é da fase D.
"""

from __future__ import annotations

import unicodedata
from typing import Dict, List, Optional

from . import Executor

_ABERTAS = "('pendente', 'em_andamento')"


def _sem_acento(texto: str) -> str:
    """Para ordenar "Áreas..." junto do A, e não depois do Z."""
    return "".join(c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c)).lower()


def _agrupar(linhas: List[Dict]) -> List[Dict]:
    """Linhas (id_tema, tema, fase, ordem_fase, id_atividade, atividade) -> subgrupos com as ids das atividades."""
    grupos: Dict[str, Dict] = {}
    for r in linhas:
        if r["fase"] == "cq":
            chave, rotulo = f"cq-{r['id_tema']}", f"CQ · {r['tema']}"
        else:
            chave, rotulo = f"a-{r['id_atividade']}", r["atividade"]
        g = grupos.setdefault(
            chave,
            {"chave": chave, "rotulo": rotulo, "id_tema": r["id_tema"], "tema": r["tema"], "fase": r["fase"],
             "ordem": (_sem_acento(r["tema"]), r["ordem_fase"], _sem_acento(rotulo)), "atividades": []},
        )  # fmt: skip
        if r["id_atividade"] not in g["atividades"]:
            g["atividades"].append(r["id_atividade"])
    saida = sorted(grupos.values(), key=lambda g: g["ordem"])
    for g in saida:
        g.pop("ordem")
        g["atividades"].sort()
    return saida


def supervisao(ex: Executor, uf: Optional[str]) -> List[Dict]:
    """Subgrupos da supervisão: atividades das etapas atuais e abertas dos lotes da UF (com ou sem cargas ainda)."""
    return _agrupar(
        ex.todos(
            "SELECT DISTINCT t.id AS id_tema, t.nome AS tema, fe.fase, f.ordem AS ordem_fase, a.id AS id_atividade, "
            "a.nome AS atividade FROM mapcartacomp.lote l "
            "JOIN mapcartacomp.lote_etapa le ON le.id_lote = l.id "
            "JOIN mapcartacomp.fluxo_etapa fe ON fe.id = le.id_fluxo_etapa "
            "JOIN mapcartacomp.fase f ON f.codigo = fe.fase "
            "JOIN mapcartacomp.fluxo_etapa_atividade fa ON fa.id_fluxo_etapa = fe.id "
            "JOIN mapcartacomp.atividade a ON a.id = fa.id_atividade "
            "JOIN mapcartacomp.tema t ON t.id = l.id_tema "
            f"WHERE le.situacao IN {_ABERTAS} AND (%s::text IS NULL OR l.uf = %s)",
            (uf, uf),
        )
    )


def responsaveis(ex: Executor, uf: Optional[str]) -> List[Dict]:
    """Quem tem carga pendente nas etapas atuais e abertas da UF, por atividade, com o nome do SGBC. As cores por
    pessoa saem da lista de todas as contas (estáveis), e a legenda de cada subgrupo mostra só quem está nele."""
    return ex.todos(
        "SELECT c.id_atividade, c.responsavel AS conta, coalesce(u.nom_usuario::text, c.responsavel) AS nome, "
        "count(*) FILTER (WHERE NOT c.concluido) AS pendentes, count(*) FILTER (WHERE c.concluido) AS concluidas "
        "FROM mapcartacomp.carga_trabalho c "
        "JOIN mapcartacomp.lote_etapa le ON le.id = c.id_lote_etapa "
        "JOIN mapcartacomp.lote l ON l.id = le.id_lote "
        "LEFT JOIN mapcartctrl.t_usuario u ON u.nom_contausuario = c.responsavel "
        f"WHERE c.responsavel IS NOT NULL AND le.situacao IN {_ABERTAS} AND (%s::text IS NULL OR l.uf = %s) "
        "GROUP BY 1, 2, 3 ORDER BY 3",
        (uf, uf),
    )
