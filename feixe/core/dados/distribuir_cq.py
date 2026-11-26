"""Distribuir as amostras de CQ por proporção entre avaliadores (D-147). Recebe um `Executor` (ver o pacote).

Na produção, a folha vai inteira para uma pessoa (D-109). No CQ, várias pessoas avaliam a mesma folha: o supervisor
escolhe os avaliadores e o peso de cada um, e o Feixe reparte as amostras de todas as folhas escolhidas juntas:

- por elemento (plano): cada avaliador recebe uma fatia de todos os elementos, na proporção do peso, com o
  arredondamento pelos maiores restos; o resultado do CQ não depende de quem pegou qual elemento;
- dentro do elemento, as amostras seguem a folha e o geocódigo (ordem da grade): cada um recebe blocos contínuos;
- sem fila: a amostra vai direto para a pessoa, e a etapa começa no primeiro distribuir;
- redistribuir é o mesmo gesto: só as amostras ainda não avaliadas mudam de mão, quem já tem as suas fica com elas até a
  cota nova, e as avaliadas ficam com quem avaliou (contam na cota dele);
- avaliadores: quem tem perfil V no projeto; sem ninguém com V, toda a equipe (como na sugestão de sempre);
- regra fixa: ninguém avalia folha que adquiriu (carga numa passagem de aquisição da folha, em qualquer revisão); fica
  fora só das amostras dessa folha;
- a equipe é lembrada: sem amostras distribuídas nas folhas escolhidas, o diálogo abre com a divisão da última passagem
  de CQ distribuída da mesma etapa do fluxo; sem nenhuma, o supervisor escolhe as pessoas.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from . import ErroDados, Executor
from . import cargas as dc

_ABERTAS = "('pendente', 'em_andamento')"


def maiores_restos(total: int, pesos: List[Tuple[str, float]]) -> Dict[str, int]:
    """Reparte `total` inteiros na proporção dos pesos: a parte inteira de cada um e o que sobra pelos maiores restos
    (empate: a ordem da lista). Pesos zerados ou negativos não recebem nada."""
    validos = [(c, float(p)) for c, p in pesos if p and float(p) > 0]
    soma = sum(p for _, p in validos)
    if total <= 0 or not validos:
        return {c: 0 for c, _ in pesos}
    exatos = [(c, total * p / soma) for c, p in validos]
    cota = {c: int(x) for c, x in exatos}
    sobra = total - sum(cota.values())
    ordem = sorted(range(len(exatos)), key=lambda i: (-(exatos[i][1] - int(exatos[i][1])), i))
    for i in ordem[:sobra]:
        cota[exatos[i][0]] += 1
    return {**{c: 0 for c, _ in pesos}, **cota}


def _passagens(ex: Executor, uf: str, id_lotes: List[int]) -> List[Dict]:
    return ex.todos(
        "SELECT l.id AS id_lote, l.tipo, l.cod_projeto, le.id AS id_lote_etapa, le.id_fluxo_etapa, "
        "mapcartacomp.f_rotulo(l.tipo, l.nome, le.revisao) AS folha_revisao, t.nome AS tema, fe.nome AS etapa "
        "FROM mapcartacomp.lote l JOIN mapcartacomp.tema t ON t.id = l.id_tema "
        f"JOIN mapcartacomp.lote_etapa le ON le.id_lote = l.id AND le.situacao IN {_ABERTAS} "
        "JOIN mapcartacomp.fluxo_etapa fe ON fe.id = le.id_fluxo_etapa AND fe.fase = 'cq' "
        "WHERE l.id = ANY(%s) AND l.uf = %s ORDER BY folha_revisao",
        (list(id_lotes), uf),
    )


def _amostras(ex: Executor, ids_le: List[int]) -> List[Dict]:
    return ex.todos(
        "SELECT c.id, c.id_lote_etapa, c.geocodigo, c.responsavel, c.concluido, p.id_atividade, "
        "coalesce(m.nome::text, a.nome) AS elemento, coalesce(e.ordem, 99) AS ordem_elemento, "
        "mapcartacomp.f_rotulo(l.tipo, l.nome, le.revisao) AS folha_revisao "
        "FROM mapcartacomp.carga_trabalho c JOIN mapcartacomp.cq_plano p ON p.id = c.id_cq_plano "
        "JOIN mapcartacomp.atividade a ON a.id = p.id_atividade "
        "LEFT JOIN mapcartacomp.cq_elemento e ON e.id_medidadequalidade = a.id_medidadequalidade "
        "LEFT JOIN mapcartctrl.t_qua_medidadequalidade m ON m.id = a.id_medidadequalidade "
        "JOIN mapcartacomp.lote_etapa le ON le.id = c.id_lote_etapa JOIN mapcartacomp.lote l ON l.id = le.id_lote "
        "WHERE c.id_lote_etapa = ANY(%s) ORDER BY ordem_elemento, elemento, folha_revisao, c.geocodigo, c.id",
        (list(ids_le),),
    )


def _executores(ex: Executor, id_lotes: List[int]) -> Dict[str, Dict[int, List[str]]]:
    """Quem adquiriu a folha (carga numa passagem de aquisição, em qualquer revisão): conta -> lote -> passagens.
    Revisão pontual e correções não contam (D-149): no DF, quem avalia costuma corrigir a folha depois."""
    por: Dict[str, Dict[int, List[str]]] = {}
    for r in ex.todos(
        "SELECT DISTINCT c.responsavel, le.id_lote, mapcartacomp.f_rotulo(l.tipo, l.nome, le.revisao) AS folha "
        "FROM mapcartacomp.carga_trabalho c JOIN mapcartacomp.lote_etapa le ON le.id = c.id_lote_etapa "
        "JOIN mapcartacomp.fluxo_etapa fe ON fe.id = le.id_fluxo_etapa AND fe.fase = 'aquisicao' "
        "JOIN mapcartacomp.lote l ON l.id = le.id_lote "
        "WHERE le.id_lote = ANY(%s) AND c.responsavel IS NOT NULL ORDER BY folha",
        (list(id_lotes),),
    ):
        por.setdefault(r["responsavel"], {}).setdefault(r["id_lote"], []).append(r["folha"])
    return por


def _ultima_equipe(ex: Executor, uf: str, etapas: List[int], fora: List[int]) -> Tuple[Dict[str, int], Optional[str]]:
    """A divisão da última passagem de CQ distribuída das mesmas etapas do fluxo (fora as escolhidas agora)."""
    ultima = ex.um(
        "SELECT le.id, mapcartacomp.f_rotulo(l.tipo, l.nome, le.revisao) AS folha_revisao "
        "FROM mapcartacomp.lote_etapa le JOIN mapcartacomp.lote l ON l.id = le.id_lote "
        "WHERE le.id_fluxo_etapa = ANY(%s) AND le.uf = %s AND NOT (le.id = ANY(%s)) AND le.iniciada_em IS NOT NULL "
        "AND EXISTS (SELECT 1 FROM mapcartacomp.carga_trabalho c WHERE c.id_lote_etapa = le.id "
        " AND c.responsavel IS NOT NULL) ORDER BY le.iniciada_em DESC, le.id DESC LIMIT 1",
        (list(etapas), uf, list(fora)),
    )
    if not ultima:
        return {}, None
    pesos = {
        r["responsavel"]: r["n"]
        for r in ex.todos(
            "SELECT responsavel, count(*) AS n FROM mapcartacomp.carga_trabalho WHERE id_lote_etapa = %s "
            "AND responsavel IS NOT NULL GROUP BY responsavel ORDER BY n DESC, responsavel",
            (ultima["id"],),
        )
    }
    return pesos, ultima["folha_revisao"]


def _contexto(ex: Executor, uf: str, id_lotes: List[int]) -> Dict:
    ps = _passagens(ex, uf, id_lotes)
    com_cq = {p["id_lote"] for p in ps}
    fora = [{"id_lote": i, "motivo": "o lote não está numa etapa de CQ aberta"} for i in id_lotes if i not in com_cq]
    amostras = _amostras(ex, [p["id_lote_etapa"] for p in ps]) if ps else []
    tem = {a["id_lote_etapa"] for a in amostras}
    for p in ps:
        if p["id_lote_etapa"] not in tem:
            fora.append({"id_lote": p["id_lote"], "folha_revisao": p["folha_revisao"],
                         "motivo": "sem amostras: os planos de CQ ainda não foram criados"})  # fmt: skip
    ps = [p for p in ps if p["id_lote_etapa"] in tem]
    executores = _executores(ex, [p["id_lote"] for p in ps]) if ps else {}
    projetos = sorted({p["cod_projeto"] for p in ps})
    equipes = {cp: dc.equipe(ex, uf, cp) for cp in projetos}
    pessoas: Dict[str, Dict] = {}
    for cp, eq in equipes.items():
        for p in eq:
            x = pessoas.setdefault(p["conta"], {"conta": p["conta"], "nome": p["nome"], "pendentes": p["pendentes"],
                                                "projetos": set(), "perfis": p["perfis"] or ""})  # fmt: skip
            x["projetos"].add(cp)
    # Sem ninguém com perfil de avaliador (V) no projeto (o DF de hoje avalia com perfil O), vale toda a equipe.
    tem_v = any(":V" in x["perfis"] for x in pessoas.values())
    # Quem executou uma folha só não avalia aquela folha (D-147): as amostras dela vão para os outros escolhidos.
    for x in pessoas.values():
        feitos = executores.get(x["conta"], {})
        x["bloqueadas"] = {p["id_lote_etapa"] for p in ps if p["id_lote"] in feitos}
        x["nao_avalia"] = [p["folha_revisao"] for p in ps if p["id_lote"] in feitos]
        x["executou"] = [f for lote in sorted(feitos) for f in feitos[lote]]
        if ps and len(x["bloqueadas"]) == len(ps):
            x["motivo"] = f"executou {', '.join(x['executou'])}: ninguém avalia o próprio trabalho"
        elif x["projetos"] != set(projetos):
            x["motivo"] = "sem perfil num dos projetos destes lotes"
        elif tem_v and ":V" not in x["perfis"]:
            x["motivo"] = "sem perfil de avaliador (V) no projeto"
        else:
            x["motivo"] = None
    # Quem já está com amostras e saiu da equipe (perdeu o perfil): aparece, para a redistribuição tirar dele.
    contas = {a["responsavel"] for a in amostras if a["responsavel"]} - set(pessoas)
    if contas:
        for r in ex.todos(
            "SELECT nom_contausuario AS conta, nom_usuario::text AS nome FROM mapcartctrl.t_usuario "
            "WHERE nom_contausuario = ANY(%s)",
            (list(contas),),
        ):
            pessoas[r["conta"]] = {"conta": r["conta"], "nome": r["nome"], "pendentes": 0, "projetos": set(),
                                   "perfis": "", "motivo": "não está mais na equipe do projeto",
                                   "bloqueadas": set(), "nao_avalia": [], "executou": []}  # fmt: skip
        for c in contas - set(pessoas):
            pessoas[c] = {"conta": c, "nome": c, "pendentes": 0, "projetos": set(), "perfis": "",
                          "motivo": "não está mais na equipe do projeto", "bloqueadas": set(), "nao_avalia": [],
                          "executou": []}  # fmt: skip
    return {"passagens": ps, "fora": fora, "amostras": amostras, "pessoas": pessoas, "sem_perfil_v": not tem_v}


def _elementos(amostras: List[Dict]) -> List[Dict]:
    els: Dict[int, Dict] = {}
    for a in amostras:
        e = els.setdefault(a["id_atividade"], {"id_atividade": a["id_atividade"], "elemento": a["elemento"],
                                               "amostras": 0, "avaliadas": 0})  # fmt: skip
        e["amostras"] += 1
        e["avaliadas"] += 1 if a["concluido"] else 0
    return list(els.values())


def sugestao(ex: Executor, uf: str, id_lotes: List[int]) -> Dict:
    """O que o diálogo precisa: as folhas (e as que ficam de fora, com o motivo), os elementos, os avaliadores aptos e
    os que não podem (com o motivo) e o peso inicial de cada um, com a origem: `atual` (a divisão que as folhas já
    têm), `ultima` (a última passagem de CQ distribuída da mesma etapa) ou `nenhuma` (ninguém marcado: o supervisor
    escolhe)."""
    ctx = _contexto(ex, uf, id_lotes)
    ps, amostras, pessoas = ctx["passagens"], ctx["amostras"], ctx["pessoas"]
    aptos = [c for c, p in pessoas.items() if not p["motivo"]]
    atual: Dict[str, int] = {}
    for a in amostras:
        if a["responsavel"]:
            atual[a["responsavel"]] = atual.get(a["responsavel"], 0) + 1
    origem, de = "nenhuma", None
    if atual:
        pesos, origem = atual, "atual"
    else:
        pesos, de = _ultima_equipe(ex, uf, sorted({p["id_fluxo_etapa"] for p in ps}), [p["id_lote_etapa"] for p in ps])
        pesos = {c: n for c, n in pesos.items() if c in aptos}
        if pesos:
            origem = "ultima"
        else:
            pesos, de = {}, None  # sem equipe a lembrar: o supervisor escolhe as pessoas
    # Os pesos vão em amostras (a unidade que o diálogo mostra ao lado da %): a proporção sobre o total.
    total = len(amostras)
    em_amostras = maiores_restos(total, list(pesos.items())) if origem != "atual" else pesos
    folhas = []
    for p in ps:
        da = [a for a in amostras if a["id_lote_etapa"] == p["id_lote_etapa"]]
        folhas.append({
            "id_lote": p["id_lote"], "id_lote_etapa": p["id_lote_etapa"], "folha_revisao": p["folha_revisao"],
            "tipo": p["tipo"],
            "tema": p["tema"], "etapa": p["etapa"], "amostras": len(da),
            "avaliadas": sum(1 for a in da if a["concluido"]),
            "sem_avaliador": sum(1 for a in da if not a["responsavel"] and not a["concluido"]),
        })  # fmt: skip
    return {
        "folhas": folhas,
        "fora": ctx["fora"],
        "elementos": _elementos(amostras),
        "total": total,
        "origem": origem,
        "origem_folha": de,
        "sem_perfil_v": ctx["sem_perfil_v"],
        "pessoas": sorted(
            (
                {
                    "conta": p["conta"],
                    "nome": p["nome"],
                    "pendentes": p["pendentes"],
                    "motivo": p["motivo"],
                    "com": atual.get(p["conta"], 0),
                    "nao_avalia": p["nao_avalia"],
                    "peso": em_amostras.get(p["conta"], 0),
                }  # fmt: skip
                for p in pessoas.values()
            ),
            key=lambda p: (p["motivo"] is not None, p["nome"] or ""),
        ),
    }


def repartir(
    amostras: List[Dict], pesos: List[Tuple[str, float]], bloqueadas: Optional[Dict[str, set]] = None
) -> Dict[int, Optional[str]]:
    """O novo responsável de cada amostra não avaliada (id da carga -> conta), elemento a elemento.

    Por elemento: a cota de cada um sobre o total do elemento (menos as avaliadas por quem ficou fora da divisão),
    pelos maiores restos; as avaliadas contam na cota de quem avaliou; as pendentes completam o que falta a cada um,
    primeiro mantendo as que a pessoa já tem, depois em blocos contínuos na ordem da folha e da grade.

    `bloqueadas` (conta -> passagens): a pessoa não recebe amostras dessas passagens (executou a folha). Quem tem
    bloqueio escolhe primeiro, entre as que pode; o que ninguém da cota pôde pegar vai para quem pode e tem mais cota
    sobrando; amostra que nenhum escolhido pode avaliar fica sem avaliador (None)."""
    bloqueadas = bloqueadas or {}
    contas = [c for c, p in pesos if p and float(p) > 0]

    def pode(c, a):
        return a["id_lote_etapa"] not in bloqueadas.get(c, ())

    novo: Dict[int, Optional[str]] = {}
    por_elem: Dict[int, List[Dict]] = {}
    for a in amostras:
        por_elem.setdefault(a["id_atividade"], []).append(a)
    # Os com bloqueio primeiro (escolhem entre as que podem), mantendo a ordem dos pesos entre iguais.
    ordem = sorted(contas, key=lambda c: (-len(bloqueadas.get(c, ())), contas.index(c)))
    for itens in por_elem.values():
        feitas = [a for a in itens if a["concluido"]]
        pend = [a for a in itens if not a["concluido"]]
        if not pend:
            continue
        fixas = {c: sum(1 for a in feitas if a["responsavel"] == c) for c in contas}
        fora = sum(1 for a in feitas if a["responsavel"] not in fixas)
        alvo = maiores_restos(len(itens) - fora, pesos)
        falta = [(c, max(0, alvo.get(c, 0) - fixas[c])) for c in contas]
        if sum(n for _, n in falta) != len(pend):
            # Alguém já avaliou além da cota nova: as pendentes se repartem na proporção do que falta a cada um.
            base = falta if any(n for _, n in falta) else [(c, p) for c, p in pesos if c in fixas]
            cota = maiores_restos(len(pend), base)
        else:
            cota = dict(falta)
        livres = []
        for a in pend:
            c = a["responsavel"]
            if c in cota and cota[c] > 0 and pode(c, a):
                novo[a["id"]] = c
                cota[c] -= 1
            else:
                livres.append(a)
        for c in ordem:
            if not livres or cota.get(c, 0) <= 0:
                continue
            resto = []
            for a in livres:
                if cota[c] > 0 and pode(c, a):
                    novo[a["id"]] = c
                    cota[c] -= 1
                else:
                    resto.append(a)
            livres = resto
        for a in livres:
            aptos = [c for c in contas if pode(c, a)]
            if not aptos:
                novo[a["id"]] = None
                continue
            c = max(aptos, key=lambda x: (cota.get(x, 0), -contas.index(x)))
            novo[a["id"]] = c
            cota[c] = cota.get(c, 0) - 1
    return novo


def distribuir(ex: Executor, uf: str, id_lotes: List[int], pesos: Dict[str, float], previa: bool) -> Dict:
    """Reparte as amostras das folhas escolhidas na proporção de `pesos` (conta -> peso relativo; o diálogo manda em
    amostras). Na prévia, só o que aconteceria. Devolve, por pessoa, o total, as avaliadas, as que recebe e as que
    perde, e por elemento; `movidas` conta as amostras que mudam de mão."""
    ctx = _contexto(ex, uf, id_lotes)
    amostras, pessoas = ctx["amostras"], ctx["pessoas"]
    if not amostras:
        raise ErroDados("nenhum destes lotes tem amostras de CQ a distribuir", 400)
    lista = [(c, float(p)) for c, p in pesos.items() if p is not None and float(p) > 0]
    if not lista:
        raise ErroDados("escolha ao menos um avaliador com peso maior que zero", 400)
    for c, _ in lista:
        p = pessoas.get(c)
        if p is None:
            raise ErroDados(f"{c} não está na equipe do projeto destes lotes", 400)
        if p["motivo"]:
            raise ErroDados(f"{p['nome'] or c} não pode avaliar estes lotes: {p['motivo']}", 400)
    lista.sort(key=lambda x: (pessoas[x[0]]["nome"] or "", x[0]))
    novo = repartir(amostras, lista, {c: pessoas[c]["bloqueadas"] for c, _ in lista})
    mudam = {a["id"]: novo[a["id"]] for a in amostras if a["id"] in novo and novo[a["id"]] != a["responsavel"]}
    resumo: Dict[str, Dict] = {}

    def de(c):
        return resumo.setdefault(c, {"conta": c, "nome": pessoas.get(c, {}).get("nome") or c, "total": 0,
                                     "avaliadas": 0, "recebe": 0, "perde": 0, "por_elemento": {}})  # fmt: skip

    for a in amostras:
        final = a["responsavel"] if a["concluido"] else novo.get(a["id"], a["responsavel"])
        if final:
            r = de(final)
            r["total"] += 1
            r["avaliadas"] += 1 if a["concluido"] else 0
            r["por_elemento"][a["id_atividade"]] = r["por_elemento"].get(a["id_atividade"], 0) + 1
        if a["id"] in mudam:
            if mudam[a["id"]]:
                de(mudam[a["id"]])["recebe"] += 1
            if a["responsavel"]:
                de(a["responsavel"])["perde"] += 1
    if not previa and mudam:
        por_conta: Dict[str, List[int]] = {}
        for i, c in mudam.items():
            por_conta.setdefault(c, []).append(i)
        for c, ids in por_conta.items():
            dc.atribuir(ex, uf, c, ids=ids)  # c None: fica sem avaliador (nenhum escolhido pode avaliar a folha)
        # A fila é da produção (uma folha por pessoa): amostras não esperam em fila.
        ex.executar(
            "DELETE FROM mapcartacomp.fila_folha WHERE id_lote_etapa = ANY(%s) AND atribuida_em IS NULL",
            ([p["id_lote_etapa"] for p in ctx["passagens"]],),
        )
    # Amostras que nenhum dos escolhidos pode avaliar (todos executaram a folha): ficam sem avaliador, com o aviso.
    sem: Dict[str, int] = {}
    for a in amostras:
        if not a["concluido"] and a["id"] in novo and novo[a["id"]] is None:
            sem[a["folha_revisao"]] = sem.get(a["folha_revisao"], 0) + 1
    return {
        "previa": previa,
        "movidas": len(mudam),
        "sem_avaliador": [{"folha_revisao": f, "amostras": n} for f, n in sorted(sem.items())],
        "excluidos": [
            {"conta": c, "nome": pessoas[c]["nome"], "folhas": pessoas[c]["nao_avalia"]}
            for c, _ in lista
            if pessoas[c]["nao_avalia"]
        ],
        "folhas": [p["folha_revisao"] for p in ctx["passagens"]],
        "ids_lote": [p["id_lote"] for p in ctx["passagens"]],
        "elementos": _elementos(amostras),
        "pessoas": sorted(resumo.values(), key=lambda r: (r["nome"] or "", r["conta"])),
    }
