"""Lotes (folhas e lotes livres): leituras e escritas das rotas. Recebe um `Executor` (ver o pacote)."""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional

from . import ErroDados, Executor, novo_uuid


def temas_com_lotes(ex: Executor, uf: Optional[str]) -> List[Dict]:
    """Temas que têm lote na UF (todas as UFs se nula), com quantos lotes, em ordem de nome."""
    sql = (
        "SELECT t.id, t.nome, count(*) AS lotes FROM mapcartacomp.tema t "
        "JOIN mapcartacomp.lote l ON l.id_tema = t.id"
        + (" WHERE l.uf = %s" if uf else "")
        + " GROUP BY t.id, t.nome ORDER BY t.nome"
    )
    return ex.todos(sql, (uf,) if uf else ())


# --- Criar e listar lotes (B3) ---------------------------------------------------------------------------------------

_ARTICULACAO = "mapcartctrl.v_articulacao_scn_100000"


def fluxos(ex: Executor, uf: str, cod_projeto: Optional[int] = None, id_tema: Optional[int] = None) -> List[Dict]:
    """Fluxos ativos da UF (com a primeira etapa, onde a folha nova começa)."""
    sql = (
        "SELECT f.id, f.nome, f.cod_projeto, p.nom_projeto AS projeto, f.id_tema, t.nome AS tema, "
        "(SELECT fe.nome FROM mapcartacomp.fluxo_etapa fe WHERE fe.id_fluxo = f.id ORDER BY fe.ordem LIMIT 1) "
        "AS primeira_etapa "
        "FROM mapcartacomp.fluxo f JOIN mapcartacomp.tema t ON t.id = f.id_tema "
        "JOIN mapcartctrl.t_projeto p ON p.cod_projeto = f.cod_projeto WHERE f.ativo AND f.uf = %s"
    )
    params: list = [uf]
    if cod_projeto is not None:
        sql += " AND f.cod_projeto = %s"
        params.append(cod_projeto)
    if id_tema is not None:
        sql += " AND f.id_tema = %s"
        params.append(id_tema)
    return ex.todos(sql + " ORDER BY p.nom_projeto, t.nome, f.nome", tuple(params))


def _fluxo_da_uf(ex: Executor, uf: str, id_fluxo: int, projetos: Optional[Iterable[int]] = None) -> Dict:
    fluxo = ex.um(
        "SELECT f.id, f.cod_projeto, f.id_tema, f.uf, f.ativo, t.nome AS tema, "
        "(SELECT fe.id FROM mapcartacomp.fluxo_etapa fe WHERE fe.id_fluxo = f.id ORDER BY fe.ordem LIMIT 1) "
        "AS primeira_etapa FROM mapcartacomp.fluxo f JOIN mapcartacomp.tema t ON t.id = f.id_tema WHERE f.id = %s",
        (id_fluxo,),
    )
    if not fluxo or fluxo["uf"] != uf or not fluxo["ativo"]:
        raise ErroDados("fluxo não encontrado entre os fluxos ativos da sua unidade", 404)
    if fluxo["primeira_etapa"] is None:
        raise ErroDados("o fluxo não tem etapas: configure o fluxo antes de criar folhas nele")
    if projetos is not None and fluxo["cod_projeto"] not in set(projetos):
        raise ErroDados("você não é supervisor no projeto deste fluxo (perfil S no SGBC)", 403)
    return fluxo


def _primeira_passagem(ex: Executor, id_lote: int, id_fluxo_etapa: int) -> None:
    ex.executar(
        "INSERT INTO mapcartacomp.lote_etapa (uuid, id_lote, id_fluxo_etapa) VALUES (%s, %s, %s)",
        (novo_uuid(), id_lote, id_fluxo_etapa),
    )


def criar_folhas(
    ex: Executor, uf: str, id_fluxo: int, ids_articulacao: List[int], projetos: Optional[Iterable[int]] = None
) -> Dict:
    """Cria um lote do tipo folha por folha 1:100.000, no projeto e tema do fluxo, já na primeira etapa (pendente).

    Folha que já tem lote no mesmo projeto e tema (D-46) não é criada de novo: volta em `existentes`.
    """
    fluxo = _fluxo_da_uf(ex, uf, id_fluxo, projetos)
    if not ids_articulacao:
        raise ErroDados("escolha pelo menos uma folha", 400)
    folhas = ex.todos(
        f"SELECT id_articulacao_scn AS id, cd_mi FROM {_ARTICULACAO} WHERE id_articulacao_scn = ANY(%s)",
        (list(ids_articulacao),),
    )
    faltam = set(ids_articulacao) - {f["id"] for f in folhas}
    if faltam:
        raise ErroDados(f"folha 1:100.000 não encontrada: {', '.join(map(str, sorted(faltam)))}", 404)
    ja = {
        r["id_articulacao_scn"]: r
        for r in ex.todos(
            "SELECT l.id, l.id_articulacao_scn, l.uf FROM mapcartacomp.lote l WHERE l.tipo = 'folha' "
            "AND l.cod_projeto = %s AND l.id_tema = %s AND l.id_articulacao_scn = ANY(%s)",
            (fluxo["cod_projeto"], fluxo["id_tema"], list(ids_articulacao)),
        )
    }
    criados, existentes = [], []
    for f in sorted(folhas, key=lambda x: x["cd_mi"]):
        if f["id"] in ja:
            existentes.append({"cd_mi": f["cd_mi"], "id_lote": ja[f["id"]]["id"], "uf": ja[f["id"]]["uf"]})
            continue
        id_lote = ex.um(
            "INSERT INTO mapcartacomp.lote (uuid, cod_projeto, id_tema, id_fluxo, uf, tipo, id_articulacao_scn, nome) "
            "VALUES (%s, %s, %s, %s, %s, 'folha', %s, %s) RETURNING id",
            (novo_uuid(), fluxo["cod_projeto"], fluxo["id_tema"], id_fluxo, uf, f["id"], f["cd_mi"]),
        )["id"]
        _primeira_passagem(ex, id_lote, fluxo["primeira_etapa"])
        criados.append({"cd_mi": f["cd_mi"], "id_lote": id_lote})
    return {"tema": fluxo["tema"], "criados": criados, "existentes": existentes}


def criar_livre(
    ex: Executor, uf: str, id_fluxo: int, nome: str, wkt: str, projetos: Optional[Iterable[int]] = None
) -> Dict:
    """Lote livre: polígono ad hoc (bacia, município, área desenhada), em SIRGAS 2000 geográfico (4674)."""
    fluxo = _fluxo_da_uf(ex, uf, id_fluxo, projetos)
    nome = (nome or "").strip()
    if not nome:
        raise ErroDados("dê um nome ao lote", 400)
    geo = ex.um(
        "SELECT GeometryType(g) AS tipo, ST_IsValid(g) AS valida, ST_Area(g) > 0 AS area "
        "FROM (SELECT ST_GeomFromText(%s, 4674) AS g) x",
        (wkt,),
    )
    if geo["tipo"] not in ("POLYGON", "MULTIPOLYGON"):
        raise ErroDados("a geometria do lote precisa ser um polígono", 400)
    if not geo["valida"]:
        raise ErroDados("a geometria do lote é inválida (autointerseção?); corrija no QGIS e tente de novo", 400)
    if not geo["area"]:
        raise ErroDados("o polígono do lote não tem área", 400)
    if ex.um(
        "SELECT 1 FROM mapcartacomp.lote WHERE tipo = 'livre' AND cod_projeto = %s AND id_tema = %s AND uf = %s "
        "AND nome = %s",
        (fluxo["cod_projeto"], fluxo["id_tema"], uf, nome),
    ):
        raise ErroDados(f"já existe um lote chamado {nome} neste projeto e tema")
    id_lote = ex.um(
        "INSERT INTO mapcartacomp.lote (uuid, cod_projeto, id_tema, id_fluxo, uf, tipo, nome, geom) "
        "VALUES (%s, %s, %s, %s, %s, 'livre', %s, ST_Multi(ST_GeomFromText(%s, 4674))) RETURNING id",
        (novo_uuid(), fluxo["cod_projeto"], fluxo["id_tema"], id_fluxo, uf, nome, wkt),
    )["id"]
    _primeira_passagem(ex, id_lote, fluxo["primeira_etapa"])
    return {"tema": fluxo["tema"], "criados": [{"nome": nome, "id_lote": id_lote}], "existentes": []}


_CAMPOS_LOTE = (
    "c.id_lote AS id, c.tipo, c.nome, c.folha_revisao, c.cod_projeto, p.nom_projeto AS projeto, c.id_tema, c.tema, "
    "c.uf, c.status_nacional, c.etapa, c.fase, c.situacao, c.revisao_atual, c.cargas_total, c.cargas_concluidas, "
    "c.perc_concluidas, c.responsavel_principal, c.responsavel_nome, c.ultimo_cq_resultado, c.inicio, c.lead_time, "
    "(SELECT x.id_lote_etapa_atual FROM mapcartacomp.lote x WHERE x.id = c.id_lote) AS id_lote_etapa_atual, "
    "ST_XMin(c.geom) AS xmin, ST_YMin(c.geom) AS ymin, ST_XMax(c.geom) AS xmax, ST_YMax(c.geom) AS ymax"
)


def listar(ex: Executor, uf: Optional[str], id_tema: Optional[int] = None, status: Optional[str] = None) -> List[Dict]:
    sql = (
        f"SELECT {_CAMPOS_LOTE} FROM mapcartacomp.ctrl_lote c "
        "JOIN mapcartctrl.t_projeto p ON p.cod_projeto = c.cod_projeto WHERE true"
    )
    params: list = []
    for coluna, valor in (("c.uf", uf), ("c.id_tema", id_tema), ("c.status_nacional", status)):
        if valor is not None:
            sql += f" AND {coluna} = %s"
            params.append(valor)
    return ex.todos(sql + " ORDER BY c.tema, c.nome", tuple(params))


def um(ex: Executor, id_lote: int) -> Optional[Dict]:
    lote = ex.um(
        f"SELECT {_CAMPOS_LOTE} FROM mapcartacomp.ctrl_lote c "
        "JOIN mapcartctrl.t_projeto p ON p.cod_projeto = c.cod_projeto WHERE c.id_lote = %s",
        (id_lote,),
    )
    if lote:
        lote["passagens"] = ex.todos(
            "SELECT id_lote_etapa AS id, etapa, fase, ordem, instancia, revisao, situacao, resultado, iniciada_em, "
            "concluida_em, cargas_total, cargas_concluidas FROM mapcartacomp.ctrl_lote_etapa WHERE id_lote = %s "
            "ORDER BY coalesce(iniciada_em, concluida_em, 'infinity'::timestamptz), ordem, instancia",
            (id_lote,),
        )
    return lote


def folha_no_ponto(ex: Executor, x: float, y: float) -> Optional[Dict]:
    """Folha 1:100.000 que contém o ponto (SIRGAS 2000 geográfico): o clique no mapa do QGIS."""
    return ex.um(
        "SELECT id_articulacao_scn AS id, cd_mi, nm_carta, nm_nomenclatura_scn AS nomenclatura "
        f"FROM {_ARTICULACAO} WHERE ST_Intersects(geom, ST_SetSRID(ST_MakePoint(%s, %s), 4674)) LIMIT 1",
        (x, y),
    )
