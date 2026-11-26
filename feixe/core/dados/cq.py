"""Plano de amostragem do CQ (D2): universo, sorteio, cargas e amostras de uma atividade de CQ numa passagem.

Só por área (D-135): o universo de uma atividade de CQ numa passagem são as células da grade estatística no nível da
atividade (5 km por padrão, D-73 e D-74), com centroide no lote (a folha da articulação ou o polígono do lote livre),
menos as células já sorteadas para a mesma atividade em passagens anteriores do mesmo lote (a revisão seguinte e o
nível III inspecionam outras células). Letra-código, n e Ac vêm dos Quadros 5 e 6 (`core.cq.amostragem`); n >= N é a
inspeção de todas as células.

O sorteio é reprodutível: o universo é ordenado pelo geocódigo e `random.Random(semente).sample` escolhe as células; a
semente fica gravada no plano. Cada célula sorteada é uma carga da atividade de CQ (célula inteira, sem responsável)
com a sua amostra (D-83). Um plano por atividade em cada passagem.

Padrão dos parâmetros: nível de inspeção, LQA e fração crítica da etapa de CQ do fluxo (D-135); a fração crítica, sem
padrão na etapa, é a do elemento (`cq_elemento`). O supervisor pode sempre trocar: refazer o plano apaga as cargas e
amostras dele e sorteia de novo, com outra semente, enquanto nenhuma amostra foi avaliada e nenhuma carga foi
distribuída. Ao abrir a passagem de CQ, os planos com o padrão da etapa saem sozinhos (`gerar_padrao`, D-136).
"""

from __future__ import annotations

import random
from decimal import Decimal
from typing import Dict, List, Optional, Sequence, Tuple

from ..cq import amostragem as am
from . import ErroDados, Executor, novo_uuid

NIVEL_PADRAO = 5000  # CQ por área na grade de 5 km (D-73, D-74), quando a atividade não diz o nível
ABERTAS = ("pendente", "em_andamento")
# Gerações que se planejam por área. Inspeção por feição fica fora da v0 (D-135); manual e nenhuma não sorteiam.
FORA_DA_AREA = ("amostra_feicao", "manual", "nenhuma")
_MAX_SEMENTE = 2**31 - 1  # cabe num inteiro do JavaScript e no INTEGER do workspace sem surpresa


class Pedido:
    """Um plano a calcular: a passagem, a atividade de CQ e os parâmetros já normalizados."""

    __slots__ = ("le", "ativ", "nivel_grade", "nivel", "lqa", "fracao", "semente", "ident", "atividade", "elemento")

    def __init__(self, le, ativ, nivel_grade, nivel, lqa, fracao, semente, ident, atividade, elemento):
        self.le, self.ativ, self.nivel_grade = le, ativ, nivel_grade
        self.nivel, self.lqa, self.fracao, self.semente = nivel, lqa, fracao, semente
        self.ident, self.atividade, self.elemento = ident, atividade, elemento


# --- Peças puras -----------------------------------------------------------------------------------------------------


def nova_semente() -> int:
    return random.SystemRandom().randint(1, _MAX_SEMENTE)


def sortear(geocodigos: Sequence[str], n: int, semente: int) -> List[str]:
    """As `n` células sorteadas do universo, pela semente. O universo é ordenado antes, para que a mesma semente sobre o
    mesmo universo dê sempre o mesmo sorteio, qualquer que seja a ordem em que o banco devolveu as células. n >= N:
    todas."""
    universo = sorted(set(geocodigos))
    if n >= len(universo):
        return universo
    return sorted(random.Random(semente).sample(universo, n))


def calcular(N: int, nivel, lqa) -> am.Resultado:
    """`amostragem.calcular` com a recusa em português para o supervisor."""
    if N <= 0:
        raise ErroDados("não sobrou célula para sortear: todas já saíram em planos anteriores desta folha", 409)
    try:
        return am.calcular(N, nivel, lqa)
    except am.ErroAmostragem as e:
        raise ErroDados(str(e), 400) from None


def _fracao(valor) -> Optional[Decimal]:
    if valor is None or valor == "":
        return None
    try:
        f = Decimal(str(valor).replace(",", ".").replace("%", "").strip())
    except Exception:  # noqa: BLE001
        raise ErroDados("fração crítica inválida: informe um número, como 4 ou 2,5", 400) from None
    if not 0 < f < 100:
        raise ErroDados("a fração crítica fica entre 0 e 100%", 400)
    return f


def _num(v):
    return None if v is None else float(v)


def _km(nivel_grade: int) -> str:
    return f"{nivel_grade // 1000} km" if nivel_grade % 1000 == 0 else f"{nivel_grade} m"


# --- Leituras --------------------------------------------------------------------------------------------------------


def _passagens(ex: Executor, ids: List[int], travar: bool = False) -> List[Dict]:
    return ex.todos(
        "SELECT le.id, le.id_lote, le.uf, le.situacao, l.tipo, mapcartacomp.f_rotulo(l.tipo, l.nome, le.revisao) "
        "AS folha_revisao, fe.nome AS etapa, fe.fase, fe.nivel_inspecao, fe.lqa, fe.fracao_critica "
        "FROM mapcartacomp.lote_etapa le JOIN mapcartacomp.lote l ON l.id = le.id_lote "
        "JOIN mapcartacomp.fluxo_etapa fe ON fe.id = le.id_fluxo_etapa WHERE le.id = ANY(%s) ORDER BY folha_revisao"
        + (" FOR UPDATE OF le" if travar else ""),
        (list(ids),),
    )


def _passagem(ex: Executor, uf: str, id_le: int, travar: bool = False) -> Dict:
    ps = _passagens(ex, [id_le], travar)
    if not ps or ps[0]["uf"] != uf:
        raise ErroDados("passagem não encontrada na sua unidade", 404)
    if ps[0]["fase"] != "cq":
        raise ErroDados(f"{ps[0]['folha_revisao']}, {ps[0]['etapa']}: plano de amostragem só em etapa de CQ", 400)
    return ps[0]


def _atividades(ex: Executor, ids_le: List[int]) -> List[Dict]:
    """Atividades de CQ ativas das etapas das passagens, com o nível da grade e a fração crítica do elemento."""
    return ex.todos(
        "SELECT le.id AS id_lote_etapa, a.id, a.nome, a.geracao, coalesce(a.grade_nivel, %s) AS grade_nivel, "
        "m.nome::text AS elemento, e.fracao_critica AS fracao_elemento "
        "FROM mapcartacomp.lote_etapa le "
        "JOIN mapcartacomp.fluxo_etapa_atividade x ON x.id_fluxo_etapa = le.id_fluxo_etapa "
        "JOIN mapcartacomp.atividade a ON a.id = x.id_atividade AND a.fase = 'cq' AND a.ativo "
        "LEFT JOIN mapcartacomp.cq_elemento e ON e.id_medidadequalidade = a.id_medidadequalidade "
        "LEFT JOIN mapcartctrl.t_qua_medidadequalidade m ON m.id = a.id_medidadequalidade "
        "WHERE le.id = ANY(%s) ORDER BY le.id, coalesce(e.ordem, 99), a.nome",
        (NIVEL_PADRAO, list(ids_le)),
    )


def _universos(ex: Executor, pares: List[Tuple[int, int, int]]) -> Dict[Tuple[int, int], Tuple[List[Dict], int]]:
    """Universo de cada (passagem, atividade, nível da grade): as células do nível com centroide no lote, sem as já
    sorteadas para a atividade em outras passagens do lote. A grade sai uma vez por (passagem, nível), na mesma conta
    das cargas de produção (`f_grade_celulas`, como em `cargas.preparar`). Volta {(passagem, atividade): (células
    ordenadas pelo geocódigo, quantas células do lote ficaram de fora por já terem saído antes)}."""
    if not pares:
        return {}
    grades = sorted({(le, nv) for le, _, nv in pares})
    celulas = ex.todos(
        "SELECT p.le, p.nivel, c.geocodigo, c.geom::text AS geom "
        "FROM unnest(%s::int[], %s::int[]) AS p(le, nivel) "
        "JOIN mapcartacomp.lote_etapa le ON le.id = p.le JOIN mapcartacomp.lote l ON l.id = le.id_lote "
        "LEFT JOIN mapcartctrl.t_articulacao_scn ar ON ar.id_articulacao_scn = l.id_articulacao_scn "
        "CROSS JOIN LATERAL mapcartacomp.f_grade_celulas(coalesce(l.geom, ST_Multi(ar.geom)), p.nivel) c",
        ([g[0] for g in grades], [g[1] for g in grades]),
    )
    por_grade: Dict[Tuple[int, int], List[Dict]] = {}
    for c in celulas:
        por_grade.setdefault((c["le"], c["nivel"]), []).append(c)
    anteriores = ex.todos(
        "SELECT DISTINCT p.le, p.ativ, c.geocodigo FROM unnest(%s::int[], %s::int[]) AS p(le, ativ) "
        "JOIN mapcartacomp.lote_etapa le ON le.id = p.le "
        "JOIN mapcartacomp.lote_etapa ant ON ant.id_lote = le.id_lote AND ant.id <> le.id "
        "JOIN mapcartacomp.cq_plano pl ON pl.id_lote_etapa = ant.id AND pl.id_atividade = p.ativ "
        "JOIN mapcartacomp.carga_trabalho c ON c.id_cq_plano = pl.id AND c.geocodigo IS NOT NULL",
        ([p[0] for p in pares], [p[1] for p in pares]),
    )
    fora: Dict[Tuple[int, int], set] = {}
    for r in anteriores:
        fora.setdefault((r["le"], r["ativ"]), set()).add(r["geocodigo"])
    saida = {}
    for le, ativ, nv in pares:
        tirar = fora.get((le, ativ), set())
        todas = por_grade.get((le, nv), [])
        ficam = sorted((c for c in todas if c["geocodigo"] not in tirar), key=lambda c: c["geocodigo"])
        saida[(le, ativ)] = (ficam, len(todas) - len(ficam))
    return saida


def planos(ex: Executor, uf: str, id_le: int) -> Dict:
    """Os planos da passagem de CQ e as atividades da etapa ainda sem plano, com o padrão da etapa (a gaveta)."""
    p = _passagem(ex, uf, id_le)
    feitos = ex.todos(
        'SELECT p.id, p.id_atividade, a.nome AS atividade, m.nome::text AS elemento, p.tamanho_lote_n AS "N", '
        "p.nivel_inspecao AS nivel, p.letra_codigo AS letra, p.tamanho_amostra_n AS n, p.numero_aceitacao_ac AS ac, "
        "p.lqa::float8 AS lqa, p.fracao_critica::float8 AS fracao_critica, p.semente, p.universo, p.resultado, "
        "p.criado_em, count(c.id) AS amostras, count(am.id) FILTER (WHERE am.status IS NOT NULL) AS avaliadas, "
        "count(c.id) FILTER (WHERE c.responsavel IS NOT NULL) AS distribuidas, "
        "count(am.id) FILTER (WHERE am.status = 0) AS nao_conformes, "
        "count(c.id) FILTER (WHERE c.responsavel IS NULL AND am.status IS NULL) AS sem_avaliador "
        "FROM mapcartacomp.cq_plano p JOIN mapcartacomp.atividade a ON a.id = p.id_atividade "
        "LEFT JOIN mapcartctrl.t_qua_medidadequalidade m ON m.id = a.id_medidadequalidade "
        "LEFT JOIN mapcartacomp.cq_elemento e ON e.id_medidadequalidade = a.id_medidadequalidade "
        "LEFT JOIN mapcartacomp.carga_trabalho c ON c.id_cq_plano = p.id "
        "LEFT JOIN mapcartacomp.cq_amostra am ON am.id_carga_trabalho = c.id "
        "WHERE p.id_lote_etapa = %s GROUP BY p.id, a.nome, m.nome, e.ordem ORDER BY coalesce(e.ordem, 99), a.nome",
        (id_le,),
    )
    aberta = p["situacao"] in ABERTAS
    feitos = [resultado_plano(f) for f in feitos]
    for f in feitos:
        f["inspecao_completa"] = f["n"] is not None and f["N"] is not None and f["n"] >= f["N"]
        f["motivo_refazer"] = _motivo_refazer(f) if aberta else "a etapa já foi encerrada"
        f["pode_refazer"] = f["motivo_refazer"] is None
    com_plano = {f["id_atividade"] for f in feitos}
    sem_plano = [
        {"id_atividade": a["id"], "atividade": a["nome"], "elemento": a["elemento"], "geracao": a["geracao"],
         "fracao_critica": _num(p["fracao_critica"] if p["fracao_critica"] is not None else a["fracao_elemento"]),
         "por_feicao": a["geracao"] in FORA_DA_AREA}
        for a in _atividades(ex, [id_le]) if a["id"] not in com_plano
    ]  # fmt: skip
    return {
        "id_lote_etapa": p["id"], "folha_revisao": p["folha_revisao"], "etapa": p["etapa"],
        "situacao": p["situacao"], "tipo": p["tipo"],
        "padrao": {"nivel": p["nivel_inspecao"], "lqa": _num(p["lqa"]), "fracao_critica": _num(p["fracao_critica"])},
        "planos": feitos, "sem_plano": sem_plano, "resultado": {k: v for k, v in resumo_passagem(feitos).items()
                                                                if k != "planos"},
    }  # fmt: skip


def _motivo_refazer(f: Dict) -> Optional[str]:
    if f["avaliadas"]:
        return f"{f['avaliadas']} de {f['amostras']} amostras já foram avaliadas"
    if f["distribuidas"]:
        return f"as amostras já foram distribuídas ({f['distribuidas']} com avaliador)"
    return None


# --- Sorteio e gravação ----------------------------------------------------------------------------------------------


def _resolver(ped: Pedido, universo: List[Dict], fora: int, tipo: str) -> Dict:
    """Plano calculado e sorteado (sem gravar) de um pedido sobre o seu universo."""
    r = calcular(len(universo), ped.nivel, ped.lqa)
    escolhidas = set(sortear([c["geocodigo"] for c in universo], r.n, ped.semente))
    onde = "na folha" if tipo == "folha" else "no lote"
    texto = f"células de {_km(ped.nivel_grade)} da grade estatística com centroide {onde}"
    if fora:
        texto += f", menos {fora} já sorteadas em passagens anteriores"
    return {
        **ped.ident, "id_atividade": ped.ativ, "atividade": ped.atividade, "elemento": ped.elemento,
        "N": r.N, "nivel": r.nivel, "lqa": float(r.lqa), "letra": r.letra, "letra_ac": r.letra_ac,
        "n_quadro": r.n_quadro, "n": r.n, "ac": r.ac, "inspecao_completa": r.inspecao_completa,
        "fracao_critica": _num(ped.fracao), "semente": ped.semente, "grade_nivel": ped.nivel_grade,
        "universo": texto, "ja_sorteadas": fora, "geocodigos": sorted(escolhidas),
        "_celulas": [c for c in universo if c["geocodigo"] in escolhidas],
    }  # fmt: skip


def _gravar(ex: Executor, resolvidos: List[Dict]) -> None:
    """Grava planos, cargas e amostras de vários planos em três INSERTs (uuids do plugin)."""
    if not resolvidos:
        return
    for r in resolvidos:
        r["uuid"] = novo_uuid()
    ids = ex.todos(
        "INSERT INTO mapcartacomp.cq_plano (uuid, id_lote_etapa, id_atividade, orientacao, universo, nivel_inspecao, "
        "tamanho_lote_n, letra_codigo, tamanho_amostra_n, lqa, numero_aceitacao_ac, celula_largura, celula_altura, "
        "semente, fracao_critica) "
        "SELECT u, le, a, 'area', uni, nv, nn, lt, n, lqa, ac, cel, cel, s, fc FROM unnest(%s::uuid[], %s::int[], "
        "%s::int[], %s::text[], %s::text[], %s::int[], %s::text[], %s::int[], %s::numeric[], %s::int[], "
        "%s::numeric[], %s::bigint[], %s::numeric[]) AS t(u, le, a, uni, nv, nn, lt, n, lqa, ac, cel, s, fc) "
        "RETURNING id, uuid::text",
        (
            [r["uuid"] for r in resolvidos], [r["id_lote_etapa"] for r in resolvidos],
            [r["id_atividade"] for r in resolvidos], [r["universo"] for r in resolvidos],
            [r["nivel"] for r in resolvidos], [r["N"] for r in resolvidos], [r["letra"] for r in resolvidos],
            [r["n"] for r in resolvidos], [Decimal(str(r["lqa"])) for r in resolvidos],
            [r["ac"] for r in resolvidos], [r["grade_nivel"] for r in resolvidos],
            [r["semente"] for r in resolvidos],
            [None if r["fracao_critica"] is None else Decimal(str(r["fracao_critica"])) for r in resolvidos],
        ),
    )  # fmt: skip
    por_uuid = {x["uuid"]: x["id"] for x in ids}
    cu, cle, ca, cp, cg, cgeom = [], [], [], [], [], []
    for r in resolvidos:
        r["id"] = por_uuid[r["uuid"]]
        for c in r["_celulas"]:
            cu.append(novo_uuid())
            cle.append(r["id_lote_etapa"])
            ca.append(r["id_atividade"])
            cp.append(r["id"])
            cg.append(c["geocodigo"])
            cgeom.append(c["geom"])
    if not cu:
        return
    cargas = ex.todos(
        "INSERT INTO mapcartacomp.carga_trabalho (uuid, id_lote_etapa, id_atividade, id_cq_plano, geocodigo, geom) "
        "SELECT u, le, a, p, g, geom::geometry FROM unnest(%s::uuid[], %s::int[], %s::int[], %s::int[], %s::text[], "
        "%s::text[]) AS t(u, le, a, p, g, geom) RETURNING id, id_cq_plano",
        (cu, cle, ca, cp, cg, cgeom),
    )
    ex.executar(
        "INSERT INTO mapcartacomp.cq_amostra (uuid, id_cq_plano, id_carga_trabalho) "
        "SELECT u, p, c FROM unnest(%s::uuid[], %s::int[], %s::int[]) AS t(u, p, c)",
        ([novo_uuid() for _ in cargas], [c["id_cq_plano"] for c in cargas], [c["id"] for c in cargas]),
    )


def _publico(r: Dict) -> Dict:
    return {k: v for k, v in r.items() if not k.startswith("_") and k != "uuid"}


def criar_plano(
    ex: Executor,
    uf: str,
    id_le: int,
    id_atividade: int,
    nivel,
    lqa,
    fracao_critica=None,
    previa: bool = False,
    refazer: bool = False,
    semente: Optional[int] = None,
) -> Dict:
    """Cria (ou refaz) o plano de uma atividade de CQ na passagem, com os parâmetros do supervisor. Na prévia, calcula e
    sorteia sem gravar; as mesmas recusas valem nos dois casos, para a tela saber antes de confirmar.

    Recusa: passagem que não é de CQ ou já encerrada, atividade fora da etapa ou por feição, plano já feito sem
    `refazer`, refazer depois de amostra avaliada ou carga distribuída, parâmetros fora dos quadros do manual e
    universo vazio. `fracao_critica` nula = a da etapa, ou a do elemento."""
    p = _passagem(ex, uf, id_le, travar=not previa)
    if p["situacao"] not in ABERTAS:
        raise ErroDados(f"{p['folha_revisao']}, {p['etapa']}: a etapa já foi encerrada; o plano fica como está")
    ativ = next((a for a in _atividades(ex, [id_le]) if a["id"] == id_atividade), None)
    if not ativ:
        raise ErroDados("atividade de CQ fora desta etapa (ou inativa no catálogo)", 400)
    if ativ["geracao"] in FORA_DA_AREA:
        raise ErroDados(
            f"{ativ['nome']}: só há plano por área nesta versão (inspeção por feição fica para depois)", 400
        )
    try:
        nivel_n, lqa_n = am.normalizar_nivel(nivel), am.normalizar_lqa(lqa)
    except am.ErroAmostragem as e:
        raise ErroDados(str(e), 400) from None
    fc = _fracao(fracao_critica)
    if fc is None:
        fc = p["fracao_critica"] if p["fracao_critica"] is not None else ativ["fracao_elemento"]
    existente = ex.um(
        "SELECT p.id, count(c.id) AS amostras, count(am.id) FILTER (WHERE am.status IS NOT NULL) AS avaliadas, "
        "count(c.id) FILTER (WHERE c.responsavel IS NOT NULL) AS distribuidas "
        "FROM mapcartacomp.cq_plano p LEFT JOIN mapcartacomp.carga_trabalho c ON c.id_cq_plano = p.id "
        "LEFT JOIN mapcartacomp.cq_amostra am ON am.id_carga_trabalho = c.id "
        "WHERE p.id_lote_etapa = %s AND p.id_atividade = %s GROUP BY p.id",
        (id_le, id_atividade),
    )
    if existente:
        if not refazer:
            raise ErroDados(f"{ativ['nome']} já tem plano nesta passagem: para trocar os parâmetros, refaça o plano")
        motivo = _motivo_refazer(existente)
        if motivo:
            raise ErroDados(f"{ativ['nome']}: o plano não pode mais ser refeito, porque {motivo}")
    ped = Pedido(
        id_le, id_atividade, ativ["grade_nivel"], nivel_n, lqa_n, fc, semente or nova_semente(),
        {"id_lote_etapa": p["id"], "folha_revisao": p["folha_revisao"], "etapa": p["etapa"]}, ativ["nome"],
        ativ["elemento"],
    )  # fmt: skip
    u = _universos(ex, [(id_le, id_atividade, ativ["grade_nivel"])])
    r = _resolver(ped, *u[(id_le, id_atividade)], p["tipo"])
    if previa:
        return {**_publico(r), "previa": True, "refeito": bool(existente)}
    if existente:
        ex.executar("DELETE FROM mapcartacomp.cq_plano WHERE id = %s", (existente["id"],))
    _gravar(ex, [r])
    return {**_publico(r), "previa": False, "refeito": bool(existente)}


def gerar_padrao(ex: Executor, passagens: List[Dict]) -> Tuple[List[Dict], List[Dict]]:
    """Ao abrir passagens de CQ (D-136): um plano por atividade de CQ da etapa, com o padrão da etapa, e as cargas e
    amostras, sem decisão de ninguém. `passagens` são as linhas de `cargas.preparar` (id, folha_revisao, etapa), já
    filtradas (da UF, abertas, sem cargas). Etapa sem nível ou LQA padrão fica a iniciar, com o aviso do próximo passo
    (criar os planos na gaveta). Volta (geradas, avisos) no formato de `preparar`."""
    if not passagens:
        return [], []
    ps = {p["id"]: p for p in _passagens(ex, [p["id"] for p in passagens])}
    ativs: Dict[int, List[Dict]] = {}
    for a in _atividades(ex, list(ps)):
        ativs.setdefault(a["id_lote_etapa"], []).append(a)
    feitos = {
        (r["id_lote_etapa"], r["id_atividade"])
        for r in ex.todos(
            "SELECT id_lote_etapa, id_atividade FROM mapcartacomp.cq_plano WHERE id_lote_etapa = ANY(%s)", (list(ps),)
        )
    }
    avisos, pedidos = [], []
    for le, p in ps.items():
        ident = {"id_lote_etapa": le, "folha_revisao": p["folha_revisao"], "etapa": p["etapa"]}
        if p["nivel_inspecao"] is None or p["lqa"] is None:
            avisos.append({**ident, "aviso": "a etapa não tem nível de inspeção e LQA padrão: crie os planos de "
                                             "amostragem na gaveta da folha", "cq_sem_padrao": True})  # fmt: skip
            continue
        try:
            nivel, lqa = am.normalizar_nivel(p["nivel_inspecao"]), am.normalizar_lqa(p["lqa"])
        except am.ErroAmostragem as e:
            avisos.append({**ident, "aviso": f"padrão da etapa fora do manual ({e}): crie os planos na gaveta",
                           "cq_sem_padrao": True})  # fmt: skip
            continue
        por_area = [a for a in ativs.get(le, []) if a["geracao"] not in FORA_DA_AREA]
        if not por_area:
            avisos.append({**ident, "aviso": "a etapa de CQ não tem atividade com plano por área"})
            continue
        for a in por_area:
            if (le, a["id"]) in feitos:
                continue
            fc = p["fracao_critica"] if p["fracao_critica"] is not None else a["fracao_elemento"]
            pedidos.append(
                Pedido(le, a["id"], a["grade_nivel"], nivel, lqa, fc, nova_semente(), ident, a["nome"], a["elemento"])
            )
    u = _universos(ex, [(x.le, x.ativ, x.nivel_grade) for x in pedidos])
    resolvidos, por_le = [], {}
    for x in pedidos:
        try:
            r = _resolver(x, *u[(x.le, x.ativ)], ps[x.le]["tipo"])
        except ErroDados as e:
            avisos.append({**x.ident, "aviso": f"{x.elemento or x.atividade}: {e.mensagem}"})
            continue
        resolvidos.append(r)
        por_le.setdefault(x.le, []).append(r)
    _gravar(ex, resolvidos)
    geradas = []
    for le, rs in por_le.items():
        p = ps[le]
        geradas.append({
            "id_lote_etapa": le, "folha_revisao": p["folha_revisao"], "etapa": p["etapa"],
            "gravadas": sum(r["n"] for r in rs), "planos": len(rs),
        })  # fmt: skip
    return geradas, avisos


# --- Resultado (D4) ------------------------------------------------------------------------------------------------
# O resultado de cada plano é o do banco (`cq_plano.resultado`, derivado por `f_cq_plano_resultado`): pendente enquanto
# falta avaliar alguma amostra ou o plano não tem Ac (planos convertidos do DF), reprovado se os não conformes passam do
# Ac, aprovado senão. O da passagem de CQ: reprovado se algum plano reprovou; aprovado quando todos aprovaram e todas as
# amostras foram avaliadas; "sem_ac" quando tudo foi avaliado, nada reprovou e algum plano não tem Ac (o supervisor
# decide sem a régua). Nada disso muda a etapa: aprovar ou abrir nova revisão é decisão do supervisor
# (`fluxos.decidir_cq`). Nível de conformidade (D-62): percentual de não conformes sobre as avaliadas contra a fração
# crítica gravada no plano.

_COLUNAS_RESULTADO = (
    "SELECT p.id, p.id_lote_etapa, le.uf, p.id_atividade, a.nome AS atividade, m.nome::text AS elemento, "
    "p.tamanho_amostra_n AS n, p.numero_aceitacao_ac AS ac, p.fracao_critica::float8 AS fracao_critica, p.resultado, "
    "count(c.id) AS amostras, count(am.id) FILTER (WHERE am.status IS NOT NULL) AS avaliadas, "
    "count(am.id) FILTER (WHERE am.status = 0) AS nao_conformes, "
    "count(c.id) FILTER (WHERE c.responsavel IS NULL AND am.status IS NULL) AS sem_avaliador, "
    "mapcartacomp.f_rotulo(l.tipo, l.nome, le.revisao) AS folha_revisao, fe.nome AS etapa, coalesce(e.ordem, 99) "
    "AS ordem FROM mapcartacomp.cq_plano p JOIN mapcartacomp.atividade a ON a.id = p.id_atividade "
    "JOIN mapcartacomp.lote_etapa le ON le.id = p.id_lote_etapa JOIN mapcartacomp.lote l ON l.id = le.id_lote "
    "JOIN mapcartacomp.fluxo_etapa fe ON fe.id = le.id_fluxo_etapa "
    "LEFT JOIN mapcartctrl.t_qua_medidadequalidade m ON m.id = a.id_medidadequalidade "
    "LEFT JOIN mapcartacomp.cq_elemento e ON e.id_medidadequalidade = a.id_medidadequalidade "
    "LEFT JOIN mapcartacomp.carga_trabalho c ON c.id_cq_plano = p.id "
    "LEFT JOIN mapcartacomp.cq_amostra am ON am.id_carga_trabalho = c.id "
)
_AGRUPAR_RESULTADO = (
    " GROUP BY p.id, le.id, l.id, fe.nome, a.nome, m.nome, e.ordem ORDER BY coalesce(e.ordem, 99), a.nome"
)


def _pc(x: float) -> str:
    """Percentual em português: 2.5 -> "2,5%", 10.0 -> "10%"."""
    return f"{x:.1f}".rstrip("0").rstrip(".").replace(".", ",") + "%"


def _nc(n: int) -> str:
    return f"{n} {'não conforme' if n == 1 else 'não conformes'}"


def resultado_plano(f: Dict) -> Dict:
    """Acrescenta ao plano (com elemento ou atividade, amostras, avaliadas, nao_conformes, ac, fracao_critica e
    resultado) a frase do resultado, o que falta avaliar e o nível de conformidade, para a tela e o histórico."""
    nome = f.get("elemento") or f["atividade"]
    nc, av, total, ac = f["nao_conformes"], f["avaliadas"], f["amostras"], f["ac"]
    faltam = total - av
    sem_ac = ac is None
    frase = f"{nome}: {_nc(nc)}, " + ("sem Ac no plano" if sem_ac else f"aceita até {ac}")
    if faltam:
        frase += f" ({av} de {total} avaliadas)"
    resumo = f"{nome} {nc} de {av}" + ("" if sem_ac else f" (aceita até {ac})")
    if faltam:
        resumo += f", faltam {faltam}"
    observado = round(100.0 * nc / av, 1) if av else None
    fc = f.get("fracao_critica")
    if observado is None:
        situacao, leitura = None, f"{nome}: nenhuma amostra avaliada ainda"
    elif fc is None:
        situacao = None
        leitura = f"{nome}: {_pc(observado)} de não conformes nas {av} avaliadas; o plano não tem fração crítica"
    else:
        situacao = "dentro" if observado <= fc else "acima"
        leitura = f"{nome}: {_pc(observado)} de não conformes nas {av} avaliadas, fração crítica {_pc(fc)}: " + (
            "dentro" if situacao == "dentro" else "acima da fração crítica"
        )
    return {
        **f, "faltam": faltam, "sem_ac": sem_ac, "excede": not sem_ac and nc > ac, "frase": frase, "resumo": resumo,
        "conformidade": {"observado": observado, "fracao_critica": fc, "situacao": situacao, "leitura": leitura},
    }  # fmt: skip


def resumo_passagem(planos_: List[Dict]) -> Dict:
    """Resultado da passagem de CQ a partir dos planos já com `resultado_plano`."""
    faltam = sum(p["faltam"] for p in planos_)
    if not planos_:
        resultado = "sem_planos"
    elif any(p["resultado"] == "reprovado" for p in planos_):
        resultado = "reprovado"
    elif faltam:
        resultado = "pendente"
    elif any(p["sem_ac"] for p in planos_):
        resultado = "sem_ac"
    else:
        resultado = "aprovado"
    return {
        "resultado": resultado,
        "amostras": sum(p["amostras"] for p in planos_),
        "avaliadas": sum(p["avaliadas"] for p in planos_),
        "faltam": faltam,
        "sem_avaliador": sum(p.get("sem_avaliador", 0) for p in planos_),
        "frase": "; ".join(p["frase"] for p in planos_),
        "resumo": "; ".join(p["resumo"] for p in planos_),
        "planos": planos_,
    }


def resultados(ex: Executor, ids_le: List[int]) -> Dict[int, Dict]:
    """Resultado de várias passagens de CQ numa consulta (Esperando você, decisão em lote): {passagem: resumo}.
    Passagem sem plano volta com resultado "sem_planos"."""
    if not ids_le:
        return {}
    por_le: Dict[int, List[Dict]] = {i: [] for i in ids_le}
    for r in ex.todos(_COLUNAS_RESULTADO + "WHERE p.id_lote_etapa = ANY(%s)" + _AGRUPAR_RESULTADO, (list(ids_le),)):
        por_le.setdefault(r["id_lote_etapa"], []).append(resultado_plano(_enxuto(r)))
    return {le: {"id_lote_etapa": le, **resumo_passagem(ps)} for le, ps in por_le.items()}


def _enxuto(r: Dict) -> Dict:
    return {k: v for k, v in r.items() if k not in ("uf", "ordem", "folha_revisao", "etapa")}


def plano(ex: Executor, uf: str, id_plano: int) -> Dict:
    """Um plano com o resultado (`GET /api/cq_planos/{id}`): n, avaliadas, não conformes, Ac, resultado, a frase e o
    nível de conformidade, mais a folha e a etapa."""
    r = ex.um(_COLUNAS_RESULTADO + "WHERE p.id = %s" + _AGRUPAR_RESULTADO, (id_plano,))
    if not r or r["uf"] != uf:
        raise ErroDados("plano de CQ não encontrado na sua unidade", 404)
    return {**resultado_plano(_enxuto(r)), "folha_revisao": r["folha_revisao"], "etapa": r["etapa"]}


# --- Ocorrências da folha (supervisão, D3a; base do D4 e do D5) ----------------------------------------------------


def ocorrencias_do_lote(ex: Executor, uf: str, id_lote: int) -> Dict:
    """Todas as ocorrências da folha, de todas as revisões, com a passagem de CQ em que foram registradas, quem
    registrou, a carga apontada e o autor dela, a ciência e o tratamento. Supervisão: lê a CCAR, sem a regra do D-66
    (quem planeja vê tudo)."""
    lote = ex.um(
        "SELECT l.id, l.uf, l.tipo, l.nome FROM mapcartacomp.lote l WHERE l.id = %s",
        (id_lote,),
    )
    if not lote or lote["uf"] != uf:
        raise ErroDados("folha não encontrada na sua unidade", 404)
    itens = ex.todos(
        "SELECT i.id, i.uuid::text AS uuid, i.id_lote_etapa, i.id_carga_trabalho, i.id_carga_avaliada, i.elemento, "
        "i.anotacao, i.responsavel, coalesce(ua.nom_usuario::text, i.responsavel) AS responsavel_nome, "
        "ca.responsavel AS autor, coalesce(ub.nom_usuario::text, ca.responsavel) AS autor_nome, "
        "i.ciente_em, i.ciente_por, i.tratado, i.tratado_em, i.tratado_por, i.criado_em, "
        "ST_X(i.geom) AS x, ST_Y(i.geom) AS y, le.revisao, le.instancia, le.situacao AS situacao_etapa, "
        "fe.nome AS etapa, mapcartacomp.f_rotulo(l.tipo, l.nome, le.revisao) AS folha_revisao "
        "FROM mapcartacomp.cq_inspecao i JOIN mapcartacomp.lote l ON l.id = i.id_lote "
        "LEFT JOIN mapcartacomp.lote_etapa le ON le.id = i.id_lote_etapa "
        "LEFT JOIN mapcartacomp.fluxo_etapa fe ON fe.id = le.id_fluxo_etapa "
        "LEFT JOIN mapcartacomp.carga_trabalho ca ON ca.id = i.id_carga_avaliada "
        "LEFT JOIN mapcartctrl.t_usuario ua ON ua.nom_contausuario = i.responsavel "
        "LEFT JOIN mapcartctrl.t_usuario ub ON ub.nom_contausuario = ca.responsavel "
        "WHERE i.id_lote = %s ORDER BY le.revisao NULLS FIRST, le.instancia, i.elemento, i.criado_em, i.id",
        (id_lote,),
    )
    return {
        "id_lote": lote["id"],
        "itens": itens,
        "total": len(itens),
        "pendentes": sum(1 for i in itens if not i["tratado"]),
        "sem_ciente": sum(1 for i in itens if i["ciente_em"] is None and i["autor"] is not None),
    }
