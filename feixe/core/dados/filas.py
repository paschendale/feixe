"""Fila de folhas por pessoa (B8, D-65, D-106). Recebe um `Executor` (ver o pacote).

O supervisor enfileira para cada pessoa folhas (passagens abertas com cargas) na ordem em que ela deve pegá-las. Quando
a pessoa conclui a última carga pendente que tem (em qualquer etapa aberta), `puxar` atribui a ela as cargas a
atribuir do primeiro item da fila que ainda tem o que atribuir, na mesma transação da conclusão. Só então: a fila
existe para ninguém ficar com várias folhas abertas (D-65), então quem ainda tem pendente não recebe outra.

Item sem nada a atribuir (outra pessoa já pegou as cargas, a etapa foi encerrada) é pulado e continua na fila, para o
supervisor ver e tirar. Desfazer a conclusão não desatribui.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from . import ErroDados, Executor, novo_uuid
from . import cargas as dc

_ABERTAS = "('pendente', 'em_andamento')"

# Itens ainda na fila, com o que cada folha tem a atribuir agora.
_ITENS = (
    "SELECT f.id, f.responsavel, coalesce(u.nom_usuario::text, f.responsavel) AS nome, f.ordem, f.id_lote_etapa, "
    "le.id_lote, mapcartacomp.f_rotulo(l.tipo, l.nome, le.revisao) AS folha_revisao, t.nome AS tema, "
    "fe.nome AS etapa, le.situacao, "
    "(SELECT count(*) FROM mapcartacomp.carga_trabalho c WHERE c.id_lote_etapa = f.id_lote_etapa) AS cargas, "
    "(SELECT count(*) FROM mapcartacomp.carga_trabalho c WHERE c.id_lote_etapa = f.id_lote_etapa "
    " AND c.responsavel IS NULL AND NOT c.concluido) AS a_atribuir "
    "FROM mapcartacomp.fila_folha f "
    "JOIN mapcartacomp.lote_etapa le ON le.id = f.id_lote_etapa "
    "JOIN mapcartacomp.lote l ON l.id = le.id_lote "
    "JOIN mapcartacomp.tema t ON t.id = l.id_tema "
    "JOIN mapcartacomp.fluxo_etapa fe ON fe.id = le.id_fluxo_etapa "
    "LEFT JOIN mapcartctrl.t_usuario u ON u.nom_contausuario = f.responsavel "
)


def listar(ex: Executor, uf: str) -> Dict:
    """Filas da UF (itens à espera, por pessoa e ordem) e o que a fila atribuiu nos últimos 7 dias."""
    itens = ex.todos(_ITENS + "WHERE f.uf = %s AND f.atribuida_em IS NULL ORDER BY nome, f.ordem", (uf,))
    recentes = ex.todos(
        "SELECT f.id, f.responsavel, coalesce(u.nom_usuario::text, f.responsavel) AS nome, f.atribuida_em, "
        "f.atribuidas, mapcartacomp.f_rotulo(l.tipo, l.nome, le.revisao) AS folha_revisao, le.id_lote "
        "FROM mapcartacomp.fila_folha f JOIN mapcartacomp.lote_etapa le ON le.id = f.id_lote_etapa "
        "JOIN mapcartacomp.lote l ON l.id = le.id_lote "
        "LEFT JOIN mapcartctrl.t_usuario u ON u.nom_contausuario = f.responsavel "
        "WHERE f.uf = %s AND f.atribuida_em > now() - interval '7 days' ORDER BY f.atribuida_em DESC LIMIT 50",
        (uf,),
    )
    return {"itens": itens, "recentes": recentes}


def adicionar(ex: Executor, uf: str, responsavel: str, id_lote_etapa: int) -> Dict:
    """Põe a folha (passagem aberta e com cargas, da UF) no fim da fila da pessoa. Se a pessoa está sem carga pendente,
    a fila anda na hora: volta em `atribuida` o que ela recebeu."""
    p = ex.um(
        "SELECT le.id, le.uf, le.situacao, l.cod_projeto, mapcartacomp.f_rotulo(l.tipo, l.nome, le.revisao) AS folha, "
        "(SELECT count(*) FROM mapcartacomp.carga_trabalho c WHERE c.id_lote_etapa = le.id) AS cargas "
        "FROM mapcartacomp.lote_etapa le JOIN mapcartacomp.lote l ON l.id = le.id_lote WHERE le.id = %s",
        (id_lote_etapa,),
    )
    if not p or p["uf"] != uf:
        raise ErroDados("folha não encontrada na sua unidade", 404)
    if p["situacao"] not in ("pendente", "em_andamento"):
        raise ErroDados(f"a etapa da {p['folha']} já foi encerrada: abra a próxima antes de pôr na fila")
    if not p["cargas"]:
        raise ErroDados(f"a {p['folha']} ainda não tem cargas: gere as cargas antes de pôr na fila")
    if responsavel not in {r["conta"] for r in dc.equipe(ex, uf, p["cod_projeto"])}:
        raise ErroDados(
            f"{responsavel} não pode receber cargas desta folha (conta ativa, lotação {uf} e perfil O, V ou S)"
        )
    ja = ex.um(
        "SELECT f.responsavel, coalesce(u.nom_usuario::text, f.responsavel) AS nome FROM mapcartacomp.fila_folha f "
        "LEFT JOIN mapcartctrl.t_usuario u ON u.nom_contausuario = f.responsavel "
        "WHERE f.id_lote_etapa = %s AND f.atribuida_em IS NULL",
        (id_lote_etapa,),
    )
    if ja:
        raise ErroDados(f"a {p['folha']} já está na fila de {ja['nome']}")
    ordem = ex.um(
        "SELECT coalesce(max(ordem), 0) + 1 AS o FROM mapcartacomp.fila_folha "
        "WHERE uf = %s AND responsavel = %s AND atribuida_em IS NULL",
        (uf, responsavel),
    )["o"]
    item = ex.um(
        "INSERT INTO mapcartacomp.fila_folha (uuid, id_lote_etapa, responsavel, ordem) VALUES (%s, %s, %s, %s) "
        "RETURNING id, ordem",
        (novo_uuid(), id_lote_etapa, responsavel, ordem),
    )
    # Quem está sem carga pendente não vai concluir nada para a fila andar: recebe já a primeira folha da fila.
    item["atribuida"] = puxar(ex, responsavel)
    return item


def reordenar(ex: Executor, uf: str, responsavel: str, ids: List[int]) -> None:
    """Nova ordem da fila da pessoa: `ids` são todos os itens à espera dela, na ordem nova."""
    atuais = {
        r["id"]
        for r in ex.todos(
            "SELECT id FROM mapcartacomp.fila_folha WHERE uf = %s AND responsavel = %s AND atribuida_em IS NULL "
            "FOR UPDATE",
            (uf, responsavel),
        )
    }
    if set(ids) != atuais or len(ids) != len(atuais):
        raise ErroDados("a fila mudou enquanto você reordenava: recarregue e tente de novo")
    ex.executar(
        "UPDATE mapcartacomp.fila_folha f SET ordem = t.o FROM unnest(%s::int[]) WITH ORDINALITY AS t(id, o) "
        "WHERE f.id = t.id AND f.ordem IS DISTINCT FROM t.o",
        (list(ids),),
    )


def remover(ex: Executor, uf: str, id_item: int) -> None:
    n = ex.executar(
        "DELETE FROM mapcartacomp.fila_folha WHERE id = %s AND uf = %s AND atribuida_em IS NULL", (id_item, uf)
    )
    if not n:
        raise ErroDados("item não está mais na fila", 404)


def puxar(ex: Executor, responsavel: str) -> Optional[Dict]:
    """Chamada depois que `responsavel` conclui uma carga: se não sobrou carga pendente dele em etapa aberta, atribui
    a ele as cargas a atribuir do primeiro item da fila com algo a atribuir. Devolve o que foi atribuído, ou None."""
    falta = ex.um(
        "SELECT count(*) AS n FROM mapcartacomp.carga_trabalho c "
        "JOIN mapcartacomp.lote_etapa le ON le.id = c.id_lote_etapa "
        f"WHERE c.responsavel = %s AND NOT c.concluido AND le.situacao IN {_ABERTAS}",
        (responsavel,),
    )["n"]
    if falta:
        return None
    fila = ex.todos(
        _ITENS + f"WHERE f.responsavel = %s AND f.atribuida_em IS NULL AND le.situacao IN {_ABERTAS} "
        "ORDER BY f.ordem FOR UPDATE OF f",
        (responsavel,),
    )
    for item in fila:
        if not item["a_atribuir"]:
            continue
        uf = ex.um("SELECT uf FROM mapcartacomp.fila_folha WHERE id = %s", (item["id"],))["uf"]
        try:
            r = dc.atribuir(ex, uf, responsavel, lote_etapas=[item["id_lote_etapa"]], so_disponiveis=True)
        except ErroDados:
            continue  # perdeu o perfil no SGBC: o item fica na fila para o supervisor ver
        if not r["atribuidas"]:
            continue
        ex.executar(
            "UPDATE mapcartacomp.fila_folha SET atribuida_em = now(), atribuidas = %s WHERE id = %s",
            (r["atribuidas"], item["id"]),
        )
        return {
            "id": item["id"],
            "id_lote": item["id_lote"],
            "id_lote_etapa": item["id_lote_etapa"],
            "folha_revisao": item["folha_revisao"],
            "tema": item["tema"],
            "atribuidas": r["atribuidas"],
        }
    return None


# --- Distribuir (D-109) ----------------------------------------------------------------------------------------------
# Uma folha por pessoa, sempre: quem está sem carga recebe a folha agora; quem já tem, recebe na fila. Distribuir é pôr
# cada folha na fila de alguém (`adicionar`), e a fila de quem está sem carga anda na hora.


def _perfil_da_fase(fase: Optional[str]) -> str:
    return "V" if fase == "cq" else "O"


def sugestao(ex: Executor, uf: str, id_lotes: List[int]) -> Dict:
    """Para cada folha, a passagem aberta com cargas a atribuir e a pessoa sugerida: entre as de perfil da fase no
    projeto (O na produção, V no CQ; sem ninguém com esse perfil, toda a equipe), quem tem menos nas mãos (sem carga
    primeiro, depois a fila mais curta), uma folha por pessoa neste lote antes de repetir alguém, e nunca quem já
    trabalhou numa passagem anterior da folha, se houver outra pessoa (a revisão é às cegas)."""
    folhas = ex.todos(
        "SELECT l.id AS id_lote, l.cod_projeto, le.id AS id_lote_etapa, "
        "mapcartacomp.f_rotulo(l.tipo, l.nome, le.revisao) AS folha_revisao, t.nome AS tema, fe.nome AS etapa, "
        "fe.fase, (SELECT count(*) FROM mapcartacomp.carga_trabalho c WHERE c.id_lote_etapa = le.id "
        " AND c.responsavel IS NULL AND NOT c.concluido) AS a_atribuir, "
        "(SELECT count(*) FROM mapcartacomp.carga_trabalho c WHERE c.id_lote_etapa = le.id) AS cargas, "
        "(SELECT f.responsavel FROM mapcartacomp.fila_folha f WHERE f.id_lote_etapa = le.id "
        " AND f.atribuida_em IS NULL) AS na_fila_de, "
        "(SELECT array_agg(DISTINCT c.responsavel) FROM mapcartacomp.carga_trabalho c "
        " JOIN mapcartacomp.lote_etapa x ON x.id = c.id_lote_etapa "
        " WHERE x.id_lote = l.id AND x.id <> le.id AND c.responsavel IS NOT NULL) AS anteriores, "
        "(SELECT array_agg(DISTINCT c.responsavel) FROM mapcartacomp.carga_trabalho c "
        " WHERE c.id_lote_etapa = le.id AND c.responsavel IS NOT NULL) AS com_cargas "
        "FROM mapcartacomp.lote l JOIN mapcartacomp.tema t ON t.id = l.id_tema "
        f"JOIN mapcartacomp.lote_etapa le ON le.id_lote = l.id AND le.situacao IN {_ABERTAS} "
        "JOIN mapcartacomp.fluxo_etapa fe ON fe.id = le.id_fluxo_etapa "
        "WHERE l.id = ANY(%s) AND l.uf = %s ORDER BY t.nome, folha_revisao",
        (list(id_lotes), uf),
    )
    filas = {
        r["responsavel"]: r["n"]
        for r in ex.todos(
            "SELECT responsavel, count(*) AS n FROM mapcartacomp.fila_folha WHERE uf = %s AND atribuida_em IS NULL "
            "GROUP BY responsavel",
            (uf,),
        )
    }
    pessoas: Dict[str, Dict] = {}
    equipes: Dict[int, List[Dict]] = {}
    for f in folhas:
        if f["cod_projeto"] not in equipes:
            equipes[f["cod_projeto"]] = dc.equipe(ex, uf, f["cod_projeto"])
            for p in equipes[f["cod_projeto"]]:
                pessoas.setdefault(p["conta"], {**p, "na_fila": filas.get(p["conta"], 0)})
    neste = dict.fromkeys(pessoas, 0)
    for f in folhas:
        f["anteriores"] = [c for c in (f["anteriores"] or []) if c]
        f["com_cargas"] = [c for c in (f["com_cargas"] or []) if c]
        f["sugerida"] = None
        if not f["a_atribuir"] or f["na_fila_de"]:
            f["sugerida"] = f["na_fila_de"]
            continue
        equipe = equipes[f["cod_projeto"]]
        perfil = _perfil_da_fase(f["fase"])
        pool = [p for p in equipe if f":{perfil}" in (p["perfis"] or "")] or equipe
        livres = [p for p in pool if p["conta"] not in f["anteriores"]] or pool
        if not livres:
            continue

        def peso(p):
            x = pessoas[p["conta"]]
            return (neste[p["conta"]] + (1 if x["pendentes"] else 0) + x["na_fila"], x["nome"] or "")

        escolhida = min(livres, key=peso)
        f["sugerida"] = escolhida["conta"]
        neste[escolhida["conta"]] += 1
    return {
        "folhas": folhas,
        "pessoas": sorted(
            (
                {
                    "conta": p["conta"],
                    "nome": p["nome"],
                    "perfis": p["perfis"],
                    "pendentes": p["pendentes"],
                    "na_fila": p["na_fila"],
                }
                for p in pessoas.values()
            ),
            key=lambda p: p["nome"] or "",
        ),  # fmt: skip
    }


def distribuir_uma(ex: Executor, uf: str, id_lote_etapa: int, responsavel: str) -> Dict:
    """Dá a folha a `responsavel`: entra no fim da fila dele (se estava na fila de outra pessoa, sai de lá) e, se ele
    está sem carga, a fila anda na hora. Volta `atribuida` (o que ele recebeu agora) ou nada (ficou na fila)."""
    ex.executar(
        "DELETE FROM mapcartacomp.fila_folha WHERE id_lote_etapa = %s AND uf = %s AND atribuida_em IS NULL "
        "AND responsavel <> %s",
        (id_lote_etapa, uf, responsavel),
    )
    ja = ex.um(
        "SELECT id, ordem FROM mapcartacomp.fila_folha WHERE id_lote_etapa = %s AND atribuida_em IS NULL",
        (id_lote_etapa,),
    )
    if ja:
        return {**ja, "atribuida": puxar(ex, responsavel)}
    return adicionar(ex, uf, responsavel, id_lote_etapa)
