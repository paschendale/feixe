"""Leituras agregadas do painel no navegador: o Início por papel e as abas da Supervisão (D-103).

Atividade em produção segue o mesmo corte dos subgrupos do QGIS (D-102, `grupos`): atividade da etapa aberta de um
lote (pendente ou em andamento, no máximo uma por lote; D-105); as de CQ de um tema ficam num grupo só. Assim o painel
e as camadas contam a mesma história.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from . import Executor
from . import fluxos as df
from .grupos import _agrupar

_ABERTAS = "('pendente', 'em_andamento')"


def _membros(ex: Executor, uf: Optional[str]) -> List[Dict]:
    """Lote x atividade das etapas atuais e abertas da UF, com o que o agrupamento precisa."""
    return ex.todos(
        "SELECT l.id AS id_lote, t.id AS id_tema, t.nome AS tema, fe.fase, f.ordem AS ordem_fase, "
        "a.id AS id_atividade, a.nome AS atividade FROM mapcartacomp.lote l "
        "JOIN mapcartacomp.lote_etapa le ON le.id_lote = l.id "
        "JOIN mapcartacomp.fluxo_etapa fe ON fe.id = le.id_fluxo_etapa "
        "JOIN mapcartacomp.fase f ON f.codigo = fe.fase "
        "JOIN mapcartacomp.fluxo_etapa_atividade fa ON fa.id_fluxo_etapa = fe.id "
        "JOIN mapcartacomp.atividade a ON a.id = fa.id_atividade "
        "JOIN mapcartacomp.tema t ON t.id = l.id_tema "
        f"WHERE le.situacao IN {_ABERTAS} AND (%s::text IS NULL OR l.uf = %s)",
        (uf, uf),
    )


def _cargas(ex: Executor, uf: Optional[str]) -> List[Dict]:
    """Cargas das etapas atuais e abertas, por atividade, lote e responsável (nulo = a atribuir)."""
    return ex.todos(
        "SELECT c.id_atividade, le.id_lote, c.responsavel, coalesce(u.nom_usuario::text, c.responsavel) AS nome, "
        "count(*) AS total, count(*) FILTER (WHERE c.concluido) AS concluidas, "
        "count(*) FILTER (WHERE c.concluido AND c.concluido_em > now() - interval '7 days') AS concluidas_7d, "
        "max(c.concluido_em) AS ultima "
        "FROM mapcartacomp.carga_trabalho c "
        "JOIN mapcartacomp.lote_etapa le ON le.id = c.id_lote_etapa "
        "JOIN mapcartacomp.lote l ON l.id = le.id_lote "
        "LEFT JOIN mapcartctrl.t_usuario u ON u.nom_contausuario = c.responsavel "
        f"WHERE le.situacao IN {_ABERTAS} AND (%s::text IS NULL OR l.uf = %s) GROUP BY 1, 2, 3, 4",
        (uf, uf),
    )


def _chave(fase: str, id_tema: int, id_atividade: int) -> str:
    return f"cq-{id_tema}" if fase == "cq" else f"a-{id_atividade}"


def _mais_recente(a, b):
    return b if a is None or (b is not None and b > a) else a


def supervisao(ex: Executor, uf: Optional[str]) -> Dict:
    """Atividades em produção com folhas, pessoas e o andamento das cargas; o detalhe de cada lote (para a tabela
    Folhas) e de cada pessoa (para a Equipe); e o status nacional da unidade."""
    membros = _membros(ex, uf)
    grupos = _agrupar(membros)
    fase_da_atividade = {m["id_atividade"]: (m["fase"], m["id_tema"]) for m in membros}
    por_chave = {g["chave"]: g for g in grupos}
    for g in grupos:
        g.update(lotes=set(), pessoas=set(), total=0, concluidas=0, com_alguem=0, a_atribuir=0, concluidas_7d=0)
    for m in membros:
        por_chave[_chave(m["fase"], m["id_tema"], m["id_atividade"])]["lotes"].add(m["id_lote"])

    # Folha na fila de alguém já tem destino: as cargas a atribuir dela contam como "na fila", não como sem dono.
    fila = {
        r["id_lote"]: r["nome"]
        for r in ex.todos(
            "SELECT le.id_lote, coalesce(u.nom_usuario::text, f.responsavel) AS nome FROM mapcartacomp.fila_folha f "
            "JOIN mapcartacomp.lote_etapa le ON le.id = f.id_lote_etapa "
            "LEFT JOIN mapcartctrl.t_usuario u ON u.nom_contausuario = f.responsavel "
            f"WHERE f.atribuida_em IS NULL AND le.situacao IN {_ABERTAS} AND (%s::text IS NULL OR f.uf = %s)",
            (uf, uf),
        )
    }
    for g in grupos:
        g["na_fila"] = 0
    lotes: Dict[int, Dict] = {}
    pessoas: Dict[str, Dict] = {}
    for c in _cargas(ex, uf):
        fase, id_tema = fase_da_atividade.get(c["id_atividade"], (None, None))
        g = por_chave.get(_chave(fase, id_tema, c["id_atividade"])) if fase else None
        pendentes = c["total"] - c["concluidas"]
        if g:
            g["total"] += c["total"]
            g["concluidas"] += c["concluidas"]
            g["concluidas_7d"] += c["concluidas_7d"]
            if c["responsavel"]:
                g["com_alguem"] += pendentes
                g["pessoas"].add(c["responsavel"])
            elif c["id_lote"] in fila:
                g["na_fila"] += pendentes
            else:
                g["a_atribuir"] += pendentes
        lote = lotes.setdefault(c["id_lote"], {"responsaveis": {}, "a_atribuir": 0, "na_fila": 0, "ultima": None})
        lote["ultima"] = _mais_recente(lote["ultima"], c["ultima"])
        if c["responsavel"]:
            lote["responsaveis"][c["responsavel"]] = c["nome"]
            p = pessoas.setdefault(
                c["responsavel"],
                {"conta": c["responsavel"], "nome": c["nome"], "pendentes": 0, "concluidas_7d": 0, "ultima": None,
                 "grupos": set(), "lotes": set()},
            )  # fmt: skip
            p["pendentes"] += pendentes
            p["concluidas_7d"] += c["concluidas_7d"]
            p["ultima"] = _mais_recente(p["ultima"], c["ultima"])
            if g and pendentes:
                p["grupos"].add(g["chave"])
                p["lotes"].add(c["id_lote"])
        elif c["id_lote"] in fila:
            lote["na_fila"] += pendentes
        else:
            lote["a_atribuir"] += pendentes

    for g in grupos:
        g["lotes"] = sorted(g["lotes"])
        g["pessoas"] = len(g["pessoas"])
    iniciadas = {
        r["id_lote"]: r["iniciada_em"]
        for r in ex.todos(
            "SELECT l.id AS id_lote, coalesce(le.iniciada_em, le.criado_em) AS iniciada_em FROM mapcartacomp.lote l "
            "JOIN mapcartacomp.lote_etapa le ON le.id_lote = l.id "
            f"WHERE le.situacao IN {_ABERTAS} AND (%s::text IS NULL OR l.uf = %s)",
            (uf, uf),
        )
    }
    detalhe_lotes = [
        {"id_lote": i, "responsaveis": sorted(d["responsaveis"].values()), "a_atribuir": d["a_atribuir"],
         "na_fila": d["na_fila"], "fila_de": fila.get(i), "ultima": d["ultima"], "iniciada_em": iniciadas.get(i)}
        for i, d in lotes.items()
    ]  # fmt: skip
    for i, inicio in iniciadas.items():
        if i not in lotes:
            detalhe_lotes.append(
                {
                    "id_lote": i,
                    "responsaveis": [],
                    "a_atribuir": 0,
                    "na_fila": 0,
                    "fila_de": fila.get(i),
                    "ultima": None,
                    "iniciada_em": inicio,
                }
            )
    for p in pessoas.values():
        p["grupos"] = sorted(p["grupos"])
        p["lotes"] = sorted(p["lotes"])
    status = ex.todos(
        "SELECT status_nacional, count(*) AS n FROM mapcartacomp.lote WHERE (%s::text IS NULL OR uf = %s) GROUP BY 1",
        (uf, uf),
    )
    return {
        "grupos": grupos,
        "lotes": detalhe_lotes,
        "pessoas": sorted(pessoas.values(), key=lambda p: p["nome"]),
        "status": {r["status_nacional"]: r["n"] for r in status},
    }


def esperando(ex: Executor, uf: str) -> List[Dict]:
    """Folhas cuja última etapa terminou (concluída ou pulada, ou em andamento com todas as cargas concluídas) e que só
    andam quando o supervisor abrir a próxima.

    Agrupadas pela decisão: tema, etapa que terminou e a próxima do fluxo (nula = fim do fluxo). Folha já CONCLUIDA
    para a CCAR fica de fora.
    """
    linhas = ex.todos(
        "SELECT l.id AS id_lote, mapcartacomp.f_rotulo(l.tipo, l.nome, le.revisao) AS folha_revisao, "
        "l.id_tema, t.nome AS tema, fe.id AS id_etapa, fe.nome AS etapa, le.situacao, "
        "coalesce(le.concluida_em, le.atualizado_em) AS desde, l.id_fluxo, fl.nome AS fluxo, "
        "n.id AS id_proxima, n.nome AS proxima "
        "FROM mapcartacomp.lote l "
        f"JOIN mapcartacomp.lote_etapa le ON le.id = {df._ULTIMA} "
        "JOIN mapcartacomp.fluxo_etapa fe ON fe.id = le.id_fluxo_etapa "
        "JOIN mapcartacomp.fluxo fl ON fl.id = l.id_fluxo "
        "JOIN mapcartacomp.tema t ON t.id = l.id_tema "
        "LEFT JOIN LATERAL (SELECT x.id, x.nome FROM mapcartacomp.fluxo_etapa x WHERE x.id_fluxo = l.id_fluxo "
        "AND x.ordem > fe.ordem ORDER BY x.ordem LIMIT 1) n ON true "
        f"WHERE le.situacao NOT IN {_ABERTAS} AND l.status_nacional <> 'CONCLUIDA' AND l.uf = %s "
        "AND NOT EXISTS (SELECT 1 FROM mapcartacomp.lote_etapa x WHERE x.id_lote = l.id "
        f"AND x.situacao IN {_ABERTAS}) "
        "ORDER BY t.nome, fe.ordem, folha_revisao",
        (uf,),
    )
    # E as que terminaram as cargas (D-109): etapa em andamento com todas as cargas concluídas. Para o supervisor é a
    # mesma decisão; abrir a próxima conclui a etapa (`fluxos.avancar`).
    linhas += ex.todos(
        "SELECT l.id AS id_lote, mapcartacomp.f_rotulo(l.tipo, l.nome, le.revisao) AS folha_revisao, "
        "l.id_tema, t.nome AS tema, fe.id AS id_etapa, fe.nome AS etapa, le.situacao, "
        "(SELECT max(c.concluido_em) FROM mapcartacomp.carga_trabalho c WHERE c.id_lote_etapa = le.id) AS desde, "
        "l.id_fluxo, fl.nome AS fluxo, n.id AS id_proxima, n.nome AS proxima "
        "FROM mapcartacomp.lote l "
        "JOIN mapcartacomp.lote_etapa le ON le.id_lote = l.id AND le.situacao = 'em_andamento' "
        "JOIN mapcartacomp.fluxo_etapa fe ON fe.id = le.id_fluxo_etapa "
        "JOIN mapcartacomp.fluxo fl ON fl.id = l.id_fluxo "
        "JOIN mapcartacomp.tema t ON t.id = l.id_tema "
        "LEFT JOIN LATERAL (SELECT x.id, x.nome FROM mapcartacomp.fluxo_etapa x WHERE x.id_fluxo = l.id_fluxo "
        "AND x.ordem > fe.ordem ORDER BY x.ordem LIMIT 1) n ON true "
        "WHERE l.uf = %s AND fe.fase <> 'envio_gcq' "
        "AND EXISTS (SELECT 1 FROM mapcartacomp.carga_trabalho c WHERE c.id_lote_etapa = le.id) "
        "AND NOT EXISTS (SELECT 1 FROM mapcartacomp.carga_trabalho c WHERE c.id_lote_etapa = le.id "
        "AND NOT c.concluido) ORDER BY t.nome, fe.ordem, folha_revisao",
        (uf,),
    )
    grupos: Dict[tuple, Dict] = {}
    for r in linhas:
        g = grupos.setdefault(
            (r["id_tema"], r["id_etapa"], r["id_proxima"]),
            {"tema": r["tema"], "etapa": r["etapa"], "fluxo": r["fluxo"], "id_proxima": r["id_proxima"],
             "proxima": r["proxima"], "folhas": [], "desde": None, "ate": None},
        )  # fmt: skip
        g["folhas"].append(
            {
                "id_lote": r["id_lote"],
                "folha_revisao": r["folha_revisao"],
                "situacao": r["situacao"],
                "desde": r["desde"],
            }
        )
        if r["desde"] is not None:
            g["desde"] = r["desde"] if g["desde"] is None else min(g["desde"], r["desde"])
            g["ate"] = r["desde"] if g["ate"] is None else max(g["ate"], r["desde"])
    # Fim do fluxo por último: é outra decisão (encerrar a folha), não abrir a próxima.
    return sorted(grupos.values(), key=lambda g: (g["id_proxima"] is None, -len(g["folhas"])))


def execucao(ex: Executor, fuso: str, dias: int = 14) -> Dict:
    """Minhas conclusões por dia (no fuso de quem olha), para as barras do Início e de Execução."""
    linhas = ex.todos(
        "SELECT (c.concluido_em AT TIME ZONE %s)::date AS dia, count(*) AS n FROM mapcartacomp.carga_trabalho c "
        "WHERE c.responsavel = current_user AND c.concluido "
        "AND c.concluido_em > now() - (%s || ' days')::interval GROUP BY 1 ORDER BY 1",
        (fuso, str(dias + 1)),
    )
    return {"por_dia": [{"dia": r["dia"].isoformat(), "n": r["n"]} for r in linhas]}
