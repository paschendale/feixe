"""Cargas de trabalho: leituras e escritas das rotas. Recebe um `Executor` (ver o pacote)."""

from __future__ import annotations

from typing import Dict, List, Optional

from . import ErroDados, Executor

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


# --- Minhas cargas (B2) ----------------------------------------------------------------------------------------------
# "Minhas" = responsavel = current_user: a conta conectada é a do usuário, como na vw_carga_trabalho.

_CAMPOS = (
    "c.id, c.uuid::text AS uuid, c.id_lote_etapa, le.id_lote, "
    "mapcartacomp.f_rotulo(l.tipo, l.nome, le.revisao) AS folha_revisao, t.nome AS tema, fe.nome AS etapa, "
    "at.nome AS atividade, c.geocodigo, c.concluido, c.concluido_em, le.situacao AS situacao_etapa, "
    "ST_XMin(c.geom) AS xmin, ST_YMin(c.geom) AS ymin, ST_XMax(c.geom) AS xmax, ST_YMax(c.geom) AS ymax"
)
_JUNCOES = (
    "FROM mapcartacomp.carga_trabalho c "
    "JOIN mapcartacomp.lote_etapa le ON le.id = c.id_lote_etapa "
    "JOIN mapcartacomp.lote l ON l.id = le.id_lote "
    "JOIN mapcartacomp.tema t ON t.id = l.id_tema "
    "JOIN mapcartacomp.fluxo_etapa fe ON fe.id = le.id_fluxo_etapa "
    "JOIN mapcartacomp.atividade at ON at.id = c.id_atividade "
)
ABERTAS = ("pendente", "em_andamento")
JANELA_DESFAZER_HORAS = 24


def minhas(ex: Executor, id_lote_etapa: Optional[int] = None, concluido: Optional[bool] = None, limite: int = 1000):
    sql = f"SELECT {_CAMPOS} {_JUNCOES} WHERE c.responsavel = current_user"
    params: list = []
    if id_lote_etapa is not None:
        sql += " AND c.id_lote_etapa = %s"
        params.append(id_lote_etapa)
    if concluido is not None:
        sql += " AND c.concluido = %s"
        params.append(concluido)
    sql += " ORDER BY folha_revisao, c.concluido, c.concluido_em DESC, c.id LIMIT %s"
    params.append(limite)
    return ex.todos(sql, tuple(params))


def uma(ex: Executor, id_carga: int) -> Optional[Dict]:
    return ex.um(f"SELECT {_CAMPOS}, c.responsavel {_JUNCOES} WHERE c.id = %s", (id_carga,))


def resumo(ex: Executor) -> Dict:
    """Frase-resumo e progresso por passagem (D-72): o que concluí, desde quando, e o que falta em quais folhas.

    Entram as passagens abertas em que tenho carga e as encerradas em que ainda tenho carga pendente.
    """
    total = ex.um(
        "SELECT count(*) FILTER (WHERE concluido) AS concluidas, min(concluido_em) AS desde, "
        "count(*) FILTER (WHERE NOT concluido) AS pendentes "
        "FROM mapcartacomp.carga_trabalho WHERE responsavel = current_user"
    )
    passagens = ex.todos(
        "SELECT le.id AS id_lote_etapa, le.id_lote, "
        "mapcartacomp.f_rotulo(l.tipo, l.nome, le.revisao) AS folha_revisao, "
        "t.nome AS tema, fe.nome AS etapa, le.situacao, count(*) AS total, "
        "count(*) FILTER (WHERE c.concluido) AS concluidas, max(c.concluido_em) AS ultima_conclusao "
        f"{_JUNCOES}WHERE c.responsavel = current_user "
        "GROUP BY le.id, le.id_lote, l.tipo, l.nome, le.revisao, t.nome, fe.nome, le.situacao "
        "HAVING le.situacao IN ('pendente', 'em_andamento') OR bool_or(NOT c.concluido) "
        "ORDER BY count(*) FILTER (WHERE NOT c.concluido) = 0, folha_revisao"
    )
    pendentes_abertas = [p for p in passagens if p["total"] > p["concluidas"]]
    return {
        "concluidas": total["concluidas"],
        "desde": total["desde"],
        "pendentes": sum(p["total"] - p["concluidas"] for p in pendentes_abertas),
        "folhas_pendentes": len(pendentes_abertas),
        "passagens": passagens,
    }


def progresso(ex: Executor, id_lote_etapa: int) -> Dict:
    """Minhas cargas concluídas / total numa passagem: o "35/93" da barra de status."""
    return ex.um(
        "SELECT le.id AS id_lote_etapa, mapcartacomp.f_rotulo(l.tipo, l.nome, le.revisao) AS folha_revisao, "
        "count(c.id) AS total, count(c.id) FILTER (WHERE c.concluido) AS concluidas "
        "FROM mapcartacomp.lote_etapa le JOIN mapcartacomp.lote l ON l.id = le.id_lote "
        "LEFT JOIN mapcartacomp.carga_trabalho c ON c.id_lote_etapa = le.id AND c.responsavel = current_user "
        "WHERE le.id = %s GROUP BY le.id, l.tipo, l.nome, le.revisao",
        (id_lote_etapa,),
    )


def _minha_para_mudar(ex: Executor, id_carga: int) -> Dict:
    linha = ex.um(
        "SELECT c.id, c.id_lote_etapa, c.concluido, c.responsavel = current_user AS minha, le.situacao, "
        f"c.concluido_em > now() - interval '{JANELA_DESFAZER_HORAS} hours' AS recente "
        "FROM mapcartacomp.carga_trabalho c JOIN mapcartacomp.lote_etapa le ON le.id = c.id_lote_etapa "
        "WHERE c.id = %s FOR UPDATE OF c",
        (id_carga,),
    )
    if not linha:
        raise ErroDados("carga não encontrada", 404)
    if not linha["minha"]:
        raise ErroDados("esta carga não está atribuída a você", 403)
    if linha["situacao"] not in ABERTAS:
        raise ErroDados("a etapa desta folha já foi encerrada pelo supervisor")
    return linha


def concluir(ex: Executor, id_carga: int) -> Dict:
    """Conclui uma carga minha. Concluir de novo não faz nada (o clique duplo não vira erro)."""
    linha = _minha_para_mudar(ex, id_carga)
    if not linha["concluido"]:
        ex.executar("UPDATE mapcartacomp.carga_trabalho SET concluido = true WHERE id = %s", (id_carga,))
    return {"carga": uma(ex, id_carga), "progresso": progresso(ex, linha["id_lote_etapa"])}


def desfazer(ex: Executor, id_carga: int) -> Dict:
    """Desfaz a conclusão de uma carga minha, até 24 horas depois de concluir."""
    linha = _minha_para_mudar(ex, id_carga)
    if not linha["concluido"]:
        raise ErroDados("esta carga não está concluída")
    if not linha["recente"]:
        raise ErroDados(f"só dá para desfazer até {JANELA_DESFAZER_HORAS} horas depois de concluir")
    ex.executar("UPDATE mapcartacomp.carga_trabalho SET concluido = false WHERE id = %s", (id_carga,))
    return {"carga": uma(ex, id_carga), "progresso": progresso(ex, linha["id_lote_etapa"])}


def proxima(ex: Executor, referencia: Optional[int] = None) -> Optional[Dict]:
    """Minha próxima carga pendente: a mais próxima da referência (a carga selecionada ou a última que concluí),
    de preferência na mesma passagem. Só em passagens abertas. Nenhuma pendente: None."""
    return ex.um(
        "WITH r AS (SELECT id_lote_etapa, ST_Centroid(geom) AS g FROM mapcartacomp.carga_trabalho WHERE id = "
        "coalesce(%s, (SELECT id FROM mapcartacomp.carga_trabalho WHERE responsavel = current_user AND concluido "
        "ORDER BY concluido_em DESC NULLS LAST LIMIT 1))) "
        f"SELECT {_CAMPOS} {_JUNCOES}LEFT JOIN r ON true "
        "WHERE c.responsavel = current_user AND NOT c.concluido AND le.situacao IN ('pendente', 'em_andamento') "
        "AND c.id <> coalesce(%s, -1) "
        "ORDER BY (c.id_lote_etapa = r.id_lote_etapa) DESC NULLS LAST, ST_Distance(ST_Centroid(c.geom), r.g) "
        "NULLS LAST, folha_revisao, c.id LIMIT 1",
        (referencia, referencia),
    )
