"""Minhas cargas sobre o workspace (D-111): a execução, que antes do C3 lia e gravava na CCAR (B2, D-94, D-102).

Regras, as mesmas da CCAR (D-94): minhas = `responsavel` = a conta do workspace; concluir em etapa encerrada pelo
supervisor é recusado; concluir de novo não faz nada; desfazer só pelo responsável e até 24 h depois de concluir.
`concluido_em` vai explícito (a hora da ação), para a conclusão offline chegar à CCAR com a hora real (o gatilho
`t10_concluido_em` guarda a hora que vier).
"""

from __future__ import annotations

import datetime as dt
import math
from typing import Dict, List, Optional

from .. import ErroDados
from . import SQL_ABERTAS, converter, data, rotulo

JANELA_DESFAZER_HORAS = 24

_CAMPOS = (
    "c.id, c.uuid, c.id_lote_etapa, le.id_lote, "
    f"{rotulo()} AS folha_revisao, t.nome AS tema, fe.nome AS etapa, "
    "at.nome AS atividade, c.geocodigo, c.concluido, c.concluido_em, le.situacao AS situacao_etapa, "
    "c.xmin, c.ymin, c.xmax, c.ymax"
)
# Referências com LEFT JOIN: offline, uma referência que ainda não veio no pull não pode sumir com a carga.
_JUNCOES = (
    "FROM carga_trabalho c "
    "JOIN lote_etapa le ON le.id = c.id_lote_etapa "
    "JOIN lote l ON l.id = le.id_lote "
    "LEFT JOIN tema t ON t.id = l.id_tema "
    "LEFT JOIN fluxo_etapa fe ON fe.id = le.id_fluxo_etapa "
    "LEFT JOIN atividade at ON at.id = c.id_atividade "
)


def _carga(linha: Optional[Dict]) -> Optional[Dict]:
    if linha is not None:
        linha.pop("cx", None)
        linha.pop("cy", None)
    return converter(linha, datas=("concluido_em",), bools=("concluido",))


def minhas(ex, id_lote_etapa: Optional[int] = None, concluido: Optional[bool] = None, limite: int = 1000):
    sql = f"SELECT {_CAMPOS} {_JUNCOES} WHERE c.responsavel = ?"
    params: list = [ex.usuario]
    if id_lote_etapa is not None:
        sql += " AND c.id_lote_etapa = ?"
        params.append(id_lote_etapa)
    if concluido is not None:
        sql += " AND c.concluido = ?"
        params.append(1 if concluido else 0)
    sql += " ORDER BY folha_revisao, c.concluido, c.concluido_em DESC, c.id LIMIT ?"
    params.append(limite)
    return [_carga(r) for r in ex.todos(sql, tuple(params))]


def uma(ex, id_carga: int) -> Optional[Dict]:
    return _carga(ex.um(f"SELECT {_CAMPOS}, c.responsavel {_JUNCOES} WHERE c.id = ?", (id_carga,)))


def resumo(ex) -> Dict:
    """Frase-resumo e progresso por passagem (D-72): as abertas em que tenho carga e as encerradas em que ainda tenho
    carga pendente."""
    total = ex.um(
        "SELECT min(concluido_em) AS desde FROM carga_trabalho WHERE responsavel = ? AND concluido", (ex.usuario,)
    )
    concluidas = ex.um("SELECT count(*) AS n FROM carga_trabalho WHERE responsavel = ? AND concluido", (ex.usuario,))[
        "n"
    ]
    passagens = ex.todos(
        "SELECT le.id AS id_lote_etapa, le.id_lote, "
        f"{rotulo()} AS folha_revisao, t.nome AS tema, fe.nome AS etapa, le.situacao, count(*) AS total, "
        "sum(CASE WHEN c.concluido THEN 1 ELSE 0 END) AS concluidas, max(c.concluido_em) AS ultima_conclusao "
        f"{_JUNCOES}WHERE c.responsavel = ? "
        "GROUP BY le.id, le.id_lote, l.tipo, l.nome, le.revisao, t.nome, fe.nome, le.situacao "
        f"HAVING le.situacao IN {SQL_ABERTAS} OR max(CASE WHEN c.concluido THEN 0 ELSE 1 END) = 1 "
        "ORDER BY sum(CASE WHEN c.concluido THEN 0 ELSE 1 END) = 0, folha_revisao",
        (ex.usuario,),
    )
    for p in passagens:
        converter(p, datas=("ultima_conclusao",))
    pendentes_abertas = [p for p in passagens if p["total"] > p["concluidas"]]
    return {
        "concluidas": concluidas,
        "desde": converter(total, datas=("desde",))["desde"],
        "pendentes": sum(p["total"] - p["concluidas"] for p in pendentes_abertas),
        "folhas_pendentes": len(pendentes_abertas),
        "passagens": passagens,
    }


def progresso(ex, id_lote_etapa: int) -> Optional[Dict]:
    """Minhas cargas concluídas / total numa passagem: o "35/93" da barra de status."""
    return ex.um(
        f"SELECT le.id AS id_lote_etapa, {rotulo()} AS folha_revisao, "
        "count(c.id) AS total, coalesce(sum(CASE WHEN c.concluido THEN 1 ELSE 0 END), 0) AS concluidas "
        "FROM lote_etapa le JOIN lote l ON l.id = le.id_lote "
        "LEFT JOIN carga_trabalho c ON c.id_lote_etapa = le.id AND c.responsavel = ? "
        "WHERE le.id = ? GROUP BY le.id, l.tipo, l.nome, le.revisao",
        (ex.usuario, id_lote_etapa),
    )


def _minha_para_mudar(ex, id_carga: int) -> Dict:
    linha = ex.um(
        "SELECT c.id, c.uuid, c.id_lote_etapa, c.concluido, c.concluido_em, c.responsavel, le.situacao "
        "FROM carga_trabalho c JOIN lote_etapa le ON le.id = c.id_lote_etapa WHERE c.id = ?",
        (id_carga,),
    )
    if not linha:
        raise ErroDados("carga não encontrada", 404)
    if linha["responsavel"] != ex.usuario:
        raise ErroDados("esta carga não está atribuída a você", 403)
    if linha["situacao"] not in ("pendente", "em_andamento"):
        raise ErroDados("a etapa desta folha já foi encerrada pelo supervisor")
    return converter(linha, datas=("concluido_em",), bools=("concluido",))


def concluir(ex, id_carga: int) -> Dict:
    """Conclui uma carga minha. Concluir de novo não faz nada. Se era a minha última pendente (em qualquer etapa
    aberta), a fila (B8) me passa a próxima folha no próprio workspace, na mesma transação: volta em `fila`."""
    from . import filas

    linha = _minha_para_mudar(ex, id_carga)
    fila = None
    if not linha["concluido"]:
        ex.atualizar("carga_trabalho", linha["uuid"], {"concluido": True, "concluido_em": ex.agora})
        fila = filas.puxar(ex, ex.usuario)
    return {"carga": uma(ex, id_carga), "progresso": progresso(ex, linha["id_lote_etapa"]), "fila": fila}


def desfazer(ex, id_carga: int) -> Dict:
    """Desfaz a conclusão de uma carga minha, até 24 horas depois de concluir. Não devolve a folha à fila (D-106)."""
    linha = _minha_para_mudar(ex, id_carga)
    if not linha["concluido"]:
        raise ErroDados("esta carga não está concluída")
    quando = linha["concluido_em"]
    if quando is None or (ex.agora - quando).total_seconds() >= JANELA_DESFAZER_HORAS * 3600:
        raise ErroDados(f"só dá para desfazer até {JANELA_DESFAZER_HORAS} horas depois de concluir")
    ex.atualizar("carga_trabalho", linha["uuid"], {"concluido": False, "concluido_em": None})
    return {"carga": uma(ex, id_carga), "progresso": progresso(ex, linha["id_lote_etapa"])}


def proxima(
    ex,
    referencia: Optional[int] = None,
    excluir: Optional[List[int]] = None,
    id_lote: Optional[int] = None,
) -> Optional[Dict]:
    """Minha próxima carga pendente, com a ordenação da B2: primeiro as da mesma passagem da
    referência (a carga atual ou, sem ela, a última que concluí), depois a menor distância entre centroides (em graus,
    como o ST_Distance em 4674), depois folha e id. Só passagens abertas; `excluir` deixa de fora as puladas (D-102);
    `id_lote` restringe a uma folha. Nenhuma pendente: None."""
    if referencia is not None:
        r = ex.um("SELECT id_lote_etapa, cx, cy FROM carga_trabalho WHERE id = ?", (referencia,))
    else:
        # Como o ORDER BY concluido_em DESC NULLS LAST do PostgreSQL: no SQLite o nulo já vem por último no DESC.
        r = ex.um(
            "SELECT id_lote_etapa, cx, cy FROM carga_trabalho WHERE responsavel = ? AND concluido "
            "ORDER BY concluido_em DESC LIMIT 1",
            (ex.usuario,),
        )
    fora = set(excluir or [])
    if referencia is not None:
        fora.add(referencia)
    sql = (
        f"SELECT {_CAMPOS}, c.cx, c.cy {_JUNCOES}WHERE c.responsavel = ? AND NOT c.concluido "
        f"AND le.situacao IN {SQL_ABERTAS}"
    )
    params: list = [ex.usuario]
    if id_lote is not None:
        sql += " AND le.id_lote = ?"
        params.append(id_lote)
    candidatas = [c for c in ex.todos(sql, tuple(params)) if c["id"] not in fora]
    if not candidatas:
        return None

    def chave(c):
        if r is None:
            mesma, dist = 0, None
        else:
            mesma = 0 if c["id_lote_etapa"] == r["id_lote_etapa"] else 1
            dist = None
            if None not in (c["cx"], c["cy"], r["cx"], r["cy"]):
                dist = math.hypot(c["cx"] - r["cx"], c["cy"] - r["cy"])
        return (mesma, dist is None, dist or 0.0, c["folha_revisao"] or "", c["id"])

    return _carga(min(candidatas, key=chave))


def execucao(ex, tz: dt.tzinfo, dias: int = 14) -> Dict:
    """Minhas conclusões por dia no fuso de quem olha (`core.dados.fuso`): as barras do Início e de Execução."""
    desde = (ex.agora - dt.timedelta(days=dias + 1)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    linhas = ex.todos(
        "SELECT concluido_em FROM carga_trabalho WHERE responsavel = ? AND concluido AND concluido_em > ?",
        (ex.usuario, desde),
    )
    por_dia: Dict[dt.date, int] = {}
    for r in linhas:
        dia = data(r["concluido_em"]).astimezone(tz).date()
        por_dia[dia] = por_dia.get(dia, 0) + 1
    return {"por_dia": [{"dia": d.isoformat(), "n": n} for d, n in sorted(por_dia.items())]}


# --- pular carga (B12, D-102) ---------------------------------------------------------------------------------------
# O pulo vive só na memória do plugin (`puladas`: id_lote_etapa -> [ids, na ordem em que foram pulados]), sem banco e
# sem outbox. Estas duas funções são a regra do `plugin._proxima`/`pular_carga` sobre o workspace, para o C3/C4.


def proxima_sem_puladas(
    ex, referencia: Optional[int], puladas: Dict[int, List[int]], passagem_atual=None, id_lote: Optional[int] = None
) -> Optional[Dict]:
    """Próxima deixando de fora as puladas. Se acabaram as não puladas da folha atual (`passagem_atual` =
    (id_lote_etapa, id_lote)), as puladas dela voltam à rotação antes de passar para outra folha."""
    le, lote = passagem_atual or (None, None)
    if id_lote is None and puladas.get(le):
        c = proxima(ex, referencia, [i for ids in puladas.values() for i in ids], lote)
        if c is not None:
            return c
        puladas.pop(le)
    return proxima(ex, referencia, [i for ids in puladas.values() for i in ids], id_lote)


def pular(ex, id_carga: int, puladas: Dict[int, List[int]]) -> Dict:
    """Deixa a carga para depois (volta no fim da folha) e devolve a próxima, com o progresso dela. Só carga
    pendente; a única pendente que tenho não pula. `puladas` é mudado no lugar."""
    carga = uma(ex, id_carga)
    if carga is None or carga["concluido"]:
        raise ErroDados("só dá para pular carga pendente")
    fila = puladas.setdefault(carga["id_lote_etapa"], [])
    if carga["id"] not in fila:
        fila.append(carga["id"])
    prox = proxima_sem_puladas(ex, carga["id"], puladas, (carga["id_lote_etapa"], carga["id_lote"]))
    if prox is None:
        fila.remove(carga["id"])
        raise ErroDados("esta é a única carga pendente que você tem: não há para onde pular")
    return {"carga": prox, "progresso": progresso(ex, prox["id_lote_etapa"]), "pulada": carga["id"]}
