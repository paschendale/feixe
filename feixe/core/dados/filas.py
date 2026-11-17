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
