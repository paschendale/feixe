"""Lotes (folhas e lotes livres): leituras e escritas das rotas. Recebe um `Executor` (ver o pacote)."""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional

from . import ErroDados, Executor, novo_uuid

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


def _primeira_passagem(ex: Executor, id_lote: int, id_fluxo_etapa: int) -> int:
    return ex.um(
        "INSERT INTO mapcartacomp.lote_etapa (uuid, id_lote, id_fluxo_etapa) VALUES (%s, %s, %s) RETURNING id",
        (novo_uuid(), id_lote, id_fluxo_etapa),
    )["id"]


def criar_folhas(
    ex: Executor, uf: str, id_fluxo: int, ids_articulacao: List[int], projetos: Optional[Iterable[int]] = None
) -> Dict:
    """Cria um lote do tipo folha por folha 1:100.000, no projeto e tema do fluxo, já na primeira etapa (pendente; as
    cargas vêm logo depois, em `cargas.preparar`).

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
        le = _primeira_passagem(ex, id_lote, fluxo["primeira_etapa"])
        criados.append({"cd_mi": f["cd_mi"], "id_lote": id_lote, "id_lote_etapa": le})
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
    le = _primeira_passagem(ex, id_lote, fluxo["primeira_etapa"])
    criado = {"nome": nome, "id_lote": id_lote, "id_lote_etapa": le}
    return {"tema": fluxo["tema"], "criados": [criado], "existentes": []}


def criar_livres(
    ex: Executor, uf: str, id_fluxo: int, itens: List[Dict], projetos: Optional[Iterable[int]] = None
) -> Dict:
    """Vários lotes livres de uma vez, um por polígono (D-154): as feições selecionadas no QGIS (ottobacias,
    municípios), cada uma com o seu nome. Cada um é conferido sozinho, num savepoint: nome vazio ou repetido na lista,
    geometria que não é polígono válido com área e nome que já existe no projeto e tema não impedem os outros.
    Volta `criados`, `existentes` (o nome já é de um lote; nada muda nele) e `erros` (nome e motivo)."""
    if not itens:
        raise ErroDados("nenhum polígono para criar", 400)
    fluxo = _fluxo_da_uf(ex, uf, id_fluxo, projetos)
    criados, existentes, erros, vistos = [], [], [], set()
    for i, item in enumerate(itens, 1):
        nome = (item.get("nome") or "").strip()
        if not nome:
            erros.append({"nome": f"polígono {i}", "erro": "sem nome"})
            continue
        if nome in vistos:
            erros.append({"nome": nome, "erro": "nome repetido nesta seleção"})
            continue
        vistos.add(nome)
        ja = ex.um(
            "SELECT id FROM mapcartacomp.lote WHERE tipo = 'livre' AND cod_projeto = %s AND id_tema = %s AND uf = %s "
            "AND nome = %s",
            (fluxo["cod_projeto"], fluxo["id_tema"], uf, nome),
        )
        if ja:
            existentes.append({"cd_mi": nome, "nome": nome, "id_lote": ja["id"], "uf": uf})
            continue
        ex.executar("SAVEPOINT livre")
        try:
            r = criar_livre(ex, uf, id_fluxo, nome, item.get("wkt") or "", projetos)
        except ErroDados as e:
            ex.executar("ROLLBACK TO SAVEPOINT livre")
            erros.append({"nome": nome, "erro": e.mensagem})
            continue
        except Exception as e:  # noqa: BLE001 - WKT ilegível etc.: o banco recusa e este fica de fora
            ex.executar("ROLLBACK TO SAVEPOINT livre")
            erros.append({"nome": nome, "erro": f"geometria ilegível ({str(e).splitlines()[0][:80]})"})
            continue
        ex.executar("RELEASE SAVEPOINT livre")
        criados += r["criados"]
    return {"tema": fluxo["tema"], "criados": criados, "existentes": existentes, "erros": erros}


def excluir(ex: Executor, uf: str, ids: List[int], previa: bool, projetos: Optional[Iterable[int]] = None) -> Dict:
    """Exclui folhas e lotes criados por engano (D-155): o lote, as passagens, as cargas, os planos de CQ, a fila e o
    histórico. Só sem trabalho feito: nenhuma carga concluída, nenhuma amostra avaliada e nenhuma ocorrência de
    inspeção; com trabalho, recusa com o motivo (o caminho é tirar cargas na gaveta). Cargas pendentes com alguém saem
    do workspace dessa pessoa no próximo pull. Na prévia, o que acontece com cada um; sem prévia, apaga os aceitos."""
    if not ids:
        raise ErroDados("escolha pelo menos uma folha", 400)
    linhas = ex.todos(
        "SELECT l.id AS id_lote, l.uf, l.cod_projeto, l.tipo, coalesce(c.folha_revisao, l.nome) AS folha_revisao, "
        "(SELECT count(*) FROM mapcartacomp.carga_trabalho x JOIN mapcartacomp.lote_etapa le "
        " ON le.id = x.id_lote_etapa WHERE le.id_lote = l.id) AS cargas, "
        "(SELECT count(*) FROM mapcartacomp.carga_trabalho x JOIN mapcartacomp.lote_etapa le "
        " ON le.id = x.id_lote_etapa WHERE le.id_lote = l.id AND x.concluido) AS concluidas, "
        "(SELECT count(DISTINCT x.responsavel) FROM mapcartacomp.carga_trabalho x JOIN mapcartacomp.lote_etapa le "
        " ON le.id = x.id_lote_etapa WHERE le.id_lote = l.id AND NOT x.concluido AND x.responsavel IS NOT NULL) "
        "AS com_alguem, "
        "(SELECT count(*) FROM mapcartacomp.cq_amostra a JOIN mapcartacomp.cq_plano p ON p.id = a.id_cq_plano "
        " JOIN mapcartacomp.lote_etapa le ON le.id = p.id_lote_etapa WHERE le.id_lote = l.id "
        " AND a.status IS NOT NULL) AS avaliadas, "
        "(SELECT count(*) FROM mapcartacomp.cq_inspecao i WHERE i.id_lote = l.id) AS ocorrencias "
        "FROM mapcartacomp.lote l LEFT JOIN mapcartacomp.ctrl_lote c ON c.id_lote = l.id "
        "WHERE l.id = ANY(%s) ORDER BY folha_revisao" + ("" if previa else " FOR UPDATE OF l"),
        (list(ids),),
    )
    permitidos = set(projetos) if projetos is not None else None
    itens = []
    for r in linhas:
        erro = None
        if r["uf"] != uf or (permitidos is not None and r["cod_projeto"] not in permitidos):
            erro = "lote de outra unidade ou projeto"
        elif r["concluidas"]:
            erro = f"já tem {r['concluidas']} cargas concluídas: tire na gaveta só as cargas que sobraram"
        elif r["avaliadas"]:
            erro = f"já tem {r['avaliadas']} amostras de CQ avaliadas"
        elif r["ocorrencias"]:
            erro = f"já tem {r['ocorrencias']} ocorrências de inspeção"
        itens.append({"id_lote": r["id_lote"], "folha_revisao": r["folha_revisao"], "tipo": r["tipo"],
                      "cargas": r["cargas"], "com_alguem": r["com_alguem"], "erro": erro})  # fmt: skip
    if previa:
        return {"itens": itens}
    apagar = [i["id_lote"] for i in itens if not i["erro"]]
    if apagar:
        # As passagens primeiro (levam cargas, planos, amostras, fila e histórico em cascata), com o lote ainda lá
        # para a derivação do status; depois o lote.
        ex.executar("DELETE FROM mapcartacomp.lote_etapa WHERE id_lote = ANY(%s)", (apagar,))
        ex.executar("DELETE FROM mapcartacomp.lote WHERE id = ANY(%s)", (apagar,))
    return {
        "excluidos": [{"id_lote": i["id_lote"], "folha_revisao": i["folha_revisao"]} for i in itens if not i["erro"]],
        "erros": [{"id_lote": i["id_lote"], "erro": i["erro"]} for i in itens if i["erro"]],
    }


# Etapa em que a folha está trabalhando (D-105): a aberta (pendente ou em andamento; no máximo uma), se houver; senão a
# atual do lote, que é a que dá o status nacional e fica na concluída até a seguinte começar. Sem isso, uma folha com a
# próxima etapa aberta e ainda não iniciada apareceria como "esperando" e gerar ou atribuir cargas iria para a etapa
# concluída. O status nacional continua o da view.
_CAMPOS_LOTE = (
    "c.id_lote AS id, c.tipo, c.nome, coalesce(ab.folha_revisao, c.folha_revisao) AS folha_revisao, c.cod_projeto, "
    "p.nom_projeto AS projeto, c.id_tema, c.tema, "
    "c.uf, c.status_nacional, coalesce(ab.etapa, c.etapa) AS etapa, coalesce(ab.fase, c.fase) AS fase, "
    "coalesce(ab.situacao, c.situacao) AS situacao, c.revisao_atual, "
    "CASE WHEN ab.id_lote_etapa IS NULL THEN c.cargas_total ELSE ab.cargas_total END AS cargas_total, "
    "CASE WHEN ab.id_lote_etapa IS NULL THEN c.cargas_concluidas ELSE ab.cargas_concluidas END AS cargas_concluidas, "
    "c.perc_concluidas, c.responsavel_principal, c.responsavel_nome, c.ultimo_cq_resultado, c.inicio, c.lead_time, "
    "coalesce(ab.id_lote_etapa, (SELECT x.id_lote_etapa_atual FROM mapcartacomp.lote x WHERE x.id = c.id_lote)) "
    "AS id_lote_etapa_atual, "
    "(SELECT x.id_fluxo FROM mapcartacomp.lote x WHERE x.id = c.id_lote) AS id_fluxo, "
    "ST_XMin(c.geom) AS xmin, ST_YMin(c.geom) AS ymin, ST_XMax(c.geom) AS xmax, ST_YMax(c.geom) AS ymax"
)

_ABERTA = (
    "LEFT JOIN LATERAL (SELECT e.id_lote_etapa, e.etapa, e.fase, e.situacao, e.cargas_total, e.cargas_concluidas, "
    "e.folha_revisao "
    "FROM mapcartacomp.ctrl_lote_etapa e WHERE e.id_lote = c.id_lote AND e.situacao IN ('pendente', 'em_andamento') "
    "LIMIT 1) ab ON true"
)


def listar(ex: Executor, uf: Optional[str], id_tema: Optional[int] = None, status: Optional[str] = None) -> List[Dict]:
    sql = (
        f"SELECT {_CAMPOS_LOTE} FROM mapcartacomp.ctrl_lote c {_ABERTA} "
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
        f"SELECT {_CAMPOS_LOTE} FROM mapcartacomp.ctrl_lote c {_ABERTA} "
        "JOIN mapcartctrl.t_projeto p ON p.cod_projeto = c.cod_projeto WHERE c.id_lote = %s",
        (id_lote,),
    )
    if lote:
        lote["passagens"] = ex.todos(
            "SELECT c.id_lote_etapa AS id, le.id_fluxo_etapa, c.etapa, c.fase, c.ordem, c.instancia, c.revisao, "
            "c.situacao, c.resultado, c.iniciada_em, c.concluida_em, c.cargas_total, c.cargas_concluidas, "
            "le.expor_ocorrencias FROM mapcartacomp.ctrl_lote_etapa c "
            "JOIN mapcartacomp.lote_etapa le ON le.id = c.id_lote_etapa WHERE c.id_lote = %s "
            "ORDER BY coalesce(c.iniciada_em, c.concluida_em, 'infinity'::timestamptz), c.id_lote_etapa",
            (id_lote,),
        )
        # Quem tem carga na etapa em que a folha está trabalhando, com o andamento de cada um (gaveta, D-103, D-105).
        lote["pessoas"] = ex.todos(
            "SELECT c.responsavel AS conta, coalesce(u.nom_usuario::text, c.responsavel) AS nome, count(*) AS total, "
            "count(*) FILTER (WHERE c.concluido) AS concluidas, max(c.concluido_em) AS ultima "
            "FROM mapcartacomp.carga_trabalho c "
            "LEFT JOIN mapcartctrl.t_usuario u ON u.nom_contausuario = c.responsavel WHERE c.id_lote_etapa = %s "
            "GROUP BY 1, 2 ORDER BY c.responsavel IS NULL, 2",
            (lote["id_lote_etapa_atual"],),
        )
        # Ocorrências da folha, de todas as revisões: o andamento da correção de inspeção na gaveta (D5).
        lote["ocorrencias"] = ex.um(
            "SELECT count(*) AS total, count(*) FILTER (WHERE tratado) AS tratadas FROM mapcartacomp.cq_inspecao "
            "WHERE id_lote = %s",
            (id_lote,),
        )
    return lote


def malha(ex: Executor) -> List[Dict]:
    """Todas as folhas 1:100.000 da articulação, com a geometria em WKT (SIRGAS 2000 geográfico): a malha que o QGIS
    mostra para escolher folhas no mapa. São retângulos (cerca de 3 mil no país), uma leitura só."""
    return ex.todos(
        "SELECT id_articulacao_scn AS id, cd_mi, nm_carta, nm_nomenclatura_scn AS nomenclatura, ST_AsText(geom) AS wkt "
        f"FROM {_ARTICULACAO} ORDER BY cd_mi"
    )


def folhas_no_feixe(ex: Executor, uf: str, id_fluxo: Optional[int] = None) -> Dict[int, str]:
    """Folhas da malha que já têm lote, para a malha mostrar o que já foi escolhido antes: {id_articulacao: rótulo}.

    Com fluxo, as do mesmo projeto e tema (são as que "Criar" recusaria, D-46), de qualquer unidade; de outra unidade
    o rótulo diz qual. Sem fluxo, as da unidade em qualquer tema, com os temas no rótulo."""
    if id_fluxo:
        linhas = ex.todos(
            "SELECT l.id_articulacao_scn AS id, l.uf FROM mapcartacomp.lote l JOIN mapcartacomp.fluxo f "
            "ON f.cod_projeto = l.cod_projeto AND f.id_tema = l.id_tema WHERE f.id = %s AND l.tipo = 'folha'",
            (id_fluxo,),
        )
        return {r["id"]: ("no Feixe" if r["uf"] == uf else f"no Feixe ({r['uf']})") for r in linhas}
    linhas = ex.todos(
        "SELECT l.id_articulacao_scn AS id, string_agg(DISTINCT t.nome, ', ' ORDER BY t.nome) AS temas "
        "FROM mapcartacomp.lote l JOIN mapcartacomp.tema t ON t.id = l.id_tema "
        "WHERE l.uf = %s AND l.tipo = 'folha' GROUP BY l.id_articulacao_scn",
        (uf,),
    )
    return {r["id"]: r["temas"] for r in linhas}


def buscar_folhas(ex: Executor, filtro: str, limite: int) -> List[Dict]:
    """Folhas 1:100.000 pelo MI, nome ou nomenclatura: MI exato primeiro, depois os que começam pelo texto (2534 antes
    de 1253 e 0253), depois o resto. Sem filtro, em ordem de MI."""
    sql = (
        "SELECT id_articulacao_scn AS id, cd_mi, nm_carta, nm_nomenclatura_scn AS nomenclatura, "
        "ST_XMin(geom) AS xmin, ST_YMin(geom) AS ymin, ST_XMax(geom) AS xmax, ST_YMax(geom) AS ymax "
        f"FROM {_ARTICULACAO} "
    )
    if not filtro:
        return ex.todos(sql + "ORDER BY cd_mi LIMIT %s", (limite,))
    sql += (
        "WHERE cd_mi ILIKE %s OR nm_carta ILIKE %s OR nm_nomenclatura_scn ILIKE %s "
        "ORDER BY cd_mi = %s DESC, cd_mi ILIKE %s DESC, nm_nomenclatura_scn ILIKE %s DESC, cd_mi LIMIT %s"
    )
    return ex.todos(sql, (f"%{filtro}%", f"%{filtro}%", f"%{filtro}%", filtro, f"{filtro}%", f"{filtro}%", limite))


def folha_no_ponto(ex: Executor, x: float, y: float) -> Optional[Dict]:
    """Folha 1:100.000 que contém o ponto (SIRGAS 2000 geográfico): o clique no mapa do QGIS."""
    return ex.um(
        "SELECT id_articulacao_scn AS id, cd_mi, nm_carta, nm_nomenclatura_scn AS nomenclatura "
        f"FROM {_ARTICULACAO} WHERE ST_Intersects(geom, ST_SetSRID(ST_MakePoint(%s, %s), 4674)) LIMIT 1",
        (x, y),
    )
