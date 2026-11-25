"""Conflitos de sincronização para o supervisor (C5): o `sync_log` da CCAR em linguagem de gente.

O push (C3, D-120) grava em `sync_log.detalhe` os dois lados de cada envio: `local` (o que a pessoa fez, quem e a hora
da ação já corrigida pelo relógio da CCAR), `servidor` (o que estava na CCAR, quem gravou e quando), `descartado`, o
`motivo` da recusa, os itens `juntados` e, desde o C5, `ref` (a carga ou a folha como o workspace a conhecia). Aqui
isso vira uma lista da UF do supervisor, com a carga ou a folha resolvida pelo `uuid` na CCAR (ou pelo `ref`, se a
linha foi apagada depois), os valores lado a lado e uma frase: "Ana concluiu a carga às 09:12; Bruno tinha concluído
a carga às 10:05; ficou a conclusão de Bruno."

Nada aqui desfaz conflito: o supervisor decide e age pelas telas que já existem (nunca transição automática).

As partes puras (`frase`, `valores`, `acao_local`…) servem também à versão local, para quem executa
(`local/sync_log.py`), que fala na segunda pessoa e não mostra colegas. SQL compatível com PostgreSQL 9.6 (`jsonb`,
`->>`, `FILTER` e `count(*) OVER ()` existem desde 9.4).
"""

from __future__ import annotations

import datetime as dt
import json
from typing import Any, Dict, Iterable, List, Optional, Tuple

from . import Executor

S = "mapcartacomp"
CONFLITOS = ("conflito_vencido", "conflito_perdido")
NA_TELA = CONFLITOS + ("recusado",)
# Envio que chegou à CCAR bem depois da ação (offline, CCAR fora): a frase diz quando chegou.
ATRASO_ENVIO = dt.timedelta(minutes=5)
POR_PAGINA = 50
MAX_POR_PAGINA = 200

ROTULOS = {
    "concluido": "Situação",
    "concluido_em": "Concluída em",
    "responsavel": "Responsável",
    "atribuida_em": "Pega da fila em",
    "atribuidas": "Cargas pegas",
    "situacao": "Situação da etapa",
    "iniciada_em": "Etapa iniciada em",
    "acao": "Ação",
    "em": "Em",
    "por": "Por",
    "observacao": "Observação",
}
_ORDEM = list(ROTULOS)
_FORA = {"id", "uuid", "geom", "criado_em", "criado_por", "atualizado_em", "atualizado_por", "versao_base", "sujo"}
SITUACOES = {
    "pendente": "pendente",
    "em_andamento": "em andamento",
    "concluida": "concluída",
    "pulada": "pulada",
}
TABELAS = {"carga_trabalho": "carga", "fila_folha": "fila", "lote_etapa": "etapa", "lote_etapa_hist": "histórico"}


def resultados_de(texto: Optional[str]) -> List[str]:
    """`resultado` da query: lista separada por vírgula; `conflito_*` são os dois conflitos. Vazio: conflitos e
    recusas. Outro valor (inclusive `aplicado`): ValueError."""
    if not texto or not texto.strip():
        return list(NA_TELA)
    saida: List[str] = []
    for parte in texto.split(","):
        p = parte.strip()
        if not p:
            continue
        novos = list(CONFLITOS) if p in ("conflito_*", "conflito") else [p]
        for r in novos:
            if r not in NA_TELA:
                raise ValueError(f"resultado desconhecido: {p}")
            if r not in saida:
                saida.append(r)
    return saida or list(NA_TELA)


# --- partes puras: datas, valores, ações, frase -----------------------------------------------------------------------


def de_iso(v: Any) -> Optional[dt.datetime]:
    if v is None or isinstance(v, dt.datetime):
        return v
    try:
        d = dt.datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)


def _iso(d: Optional[dt.datetime]) -> Optional[str]:
    return d.astimezone(dt.timezone.utc).isoformat() if d is not None else None


def hora(d: Optional[dt.datetime], tz: dt.tzinfo, hoje: dt.date) -> str:
    """Hora no fuso de quem olha: "09:12" hoje, "17/11 às 09:12" em outro dia."""
    if d is None:
        return "?"
    x = d.astimezone(tz)
    return x.strftime("%H:%M") if x.date() == hoje else x.strftime("%d/%m às %H:%M")


def _as(d: Optional[dt.datetime], tz: dt.tzinfo, hoje: dt.date) -> str:
    """Hora da frase: "às 09:12" hoje, "em 17/11 às 09:12" em outro dia."""
    if d is None:
        return "em hora desconhecida"
    h = hora(d, tz, hoje)
    return f"em {h}" if "/" in h else f"às {h}"


def _das(d: Optional[dt.datetime], tz: dt.tzinfo, hoje: dt.date) -> str:
    """Hora do que ficou: "das 09:12" hoje, "de 17/11 às 09:12" em outro dia."""
    if d is None:
        return "de hora desconhecida"
    h = hora(d, tz, hoje)
    return f"de {h}" if "/" in h else f"das {h}"


def texto_valor(campo: str, v: Any, tz: dt.tzinfo, nomes: Dict[str, str], desvio_s: float = 0.0) -> str:
    """Valor de um campo como se lê: concluída/pendente, data no fuso, nome da pessoa."""
    if v is None:
        return "ninguém" if campo == "responsavel" else "—"
    if campo == "concluido":
        return "concluída" if v else "pendente"
    if campo == "responsavel":
        return nomes.get(v, v)
    if campo == "situacao":
        return SITUACOES.get(v, str(v))
    if campo.endswith("_em") or campo == "em":
        d = de_iso(v)
        if d is None:
            return str(v)
        return (d + dt.timedelta(seconds=desvio_s)).astimezone(tz).strftime("%d/%m %H:%M")
    if isinstance(v, bool):
        return "sim" if v else "não"
    return str(v)


def valores(detalhe: Dict, tz: dt.tzinfo, nomes: Dict[str, str]) -> List[Dict]:
    """Os campos dos dois lados, lado a lado: o que a pessoa enviou e o que estava na CCAR. As datas do lado local
    vêm do relógio da estação e são corrigidas pelo desvio medido no push."""
    local = (detalhe.get("local") or {}).get("valores") or {}
    srv_d = detalhe.get("servidor")
    srv = (srv_d or {}).get("valores") or {}
    desvio = float(detalhe.get("desvio_s") or 0.0)
    campos = [c for c in dict.fromkeys(list(local) + list(srv)) if c not in _FORA]
    campos.sort(key=lambda c: _ORDEM.index(c) if c in _ORDEM else len(_ORDEM))
    saida = []
    for c in campos:
        lv = texto_valor(c, local.get(c), tz, nomes, desvio) if c in local else "—"
        sv = texto_valor(c, srv.get(c), tz, nomes) if srv_d is not None and c in srv else "—"
        saida.append({"campo": c, "rotulo": ROTULOS.get(c, c), "local": lv, "servidor": sv, "igual": lv == sv})
    return saida


def _acao_campos(tabela: str, operacao: str, campos: Dict) -> Tuple[str, str]:
    """(o que a pessoa fez, nome da ação) para um conjunto de campos enviados."""
    if tabela == "carga_trabalho":
        if "concluido" in campos:
            return ("concluiu a carga", "a conclusão") if campos["concluido"] else ("desfez a conclusão", "o desfazer")
        if "responsavel" in campos:
            return "pegou a carga pela fila", "a atribuição pela fila"
        return "alterou a carga", "a alteração"
    if tabela == "fila_folha":
        return "pegou a folha da fila", "a atribuição pela fila"
    if tabela == "lote_etapa":
        return "iniciou a etapa", "o início da etapa"
    if tabela == "lote_etapa_hist":
        return "registrou o início da etapa", "o registro no histórico"
    return f"alterou {tabela}", "a alteração"


def acao_local(tabela: str, operacao: str, detalhe: Dict) -> Tuple[str, str]:
    """O que a pessoa fez. Ações juntadas num envio (concluir e depois desfazer) aparecem em sequência."""
    juntados = detalhe.get("juntados") or []
    if len(juntados) > 1:
        verbos = []
        for j in juntados:
            v = _acao_campos(tabela, operacao, j.get("campos") or {})[0]
            if not verbos or verbos[-1] != v:
                verbos.append(v)
        nome = _acao_campos(tabela, operacao, (detalhe.get("local") or {}).get("valores") or {})[1]
        return " e depois ".join(verbos), nome
    return _acao_campos(tabela, operacao, (detalhe.get("local") or {}).get("valores") or {})


def acao_servidor(tabela: str, detalhe: Dict) -> Tuple[str, str]:
    """O que estava na CCAR, como particípio ("tinha concluído a carga"). Só se sabe dos campos que a pessoa enviou;
    mudança direta (supervisor, tabela online) sem conclusão vira "tinha alterado"."""
    srv = detalhe.get("servidor") or {}
    v = srv.get("valores") or {}
    origem_acao = srv.get("origem_em") == "acao"
    if tabela == "carga_trabalho" and "concluido" in v:
        if v["concluido"]:
            return "tinha concluído a carga", "a conclusão"
        if origem_acao:
            return "tinha desfeito a conclusão", "o desfazer"
        return "tinha alterado a carga", "a alteração"
    if tabela == "fila_folha":
        return "tinha mudado a fila", "a mudança na fila"
    if tabela == "lote_etapa":
        return "tinha mudado a etapa", "a mudança na etapa"
    return "tinha alterado a linha", "a alteração"


def frase(
    resultado: str,
    tabela: str,
    operacao: str,
    detalhe: Dict,
    em_log: Optional[dt.datetime],
    nomes: Dict[str, str],
    tz: dt.tzinfo,
    hoje: dt.date,
    usuario: str,
    responsavel_atual: Optional[str] = None,
    segunda_pessoa: bool = False,
) -> str:
    """O que aconteceu, numa frase. Supervisor: "Ana concluiu a carga às 09:12 (chegou à CCAR às 11:40); Bruno tinha
    concluído a carga às 10:05; ficou a conclusão de Bruno." Quem executa (`segunda_pessoa`): "Você concluiu…; na CCAR
    ela tinha mudado às 10:05; ficou o que estava na CCAR.", sem nomes de colegas."""
    local = detalhe.get("local") or {}
    srv = detalhe.get("servidor")
    quem = "Você" if segunda_pessoa else nomes.get(usuario, usuario)
    fez, nome_local = acao_local(tabela, operacao, detalhe)
    quando_local = de_iso(local.get("em"))
    partes = [f"{quem} {fez} {_as(quando_local, tz, hoje)}"]
    if em_log is not None and quando_local is not None and em_log - quando_local > ATRASO_ENVIO:
        partes[0] += f" (chegou à CCAR {_as(em_log, tz, hoje)})"
    tinha, nome_srv = acao_servidor(tabela, detalhe)
    quando_srv = de_iso((srv or {}).get("em"))
    por_srv = (srv or {}).get("por")
    if srv is not None and resultado in CONFLITOS:
        if segunda_pessoa:
            partes.append(f"na CCAR, a {TABELAS.get(tabela, 'linha')} tinha mudado {_as(quando_srv, tz, hoje)}")
        else:
            outro = nomes.get(por_srv, por_srv or "alguém")
            if por_srv == usuario:
                outro += ", em outro computador," if (srv or {}).get("origem_em") == "acao" else ", direto na CCAR,"
            partes.append(f"{outro} {tinha} {_as(quando_srv, tz, hoje)}")
    passou = tabela == "carga_trabalho" and responsavel_atual is not None and responsavel_atual != usuario
    if srv is not None and resultado == "recusado" and passou and not segunda_pessoa and por_srv != usuario:
        # Carga que passou para outra pessoa: a versão da CCAR é a reatribuição.
        quem_srv = nomes.get(por_srv, por_srv or "alguém")
        partes.append(f"{quem_srv} tinha reatribuído a carga {_as(quando_srv, tz, hoje)}")
    texto = "; ".join(partes)
    mesma = por_srv == usuario  # as duas estações da mesma pessoa: o que distingue os lados é a hora
    if resultado == "conflito_vencido":
        if segunda_pessoa:
            fim = "ficou o que você fez"
        else:
            de = "" if mesma else f" de {nomes.get(usuario, usuario)}"
            fim = f"ficou {nome_local}{de}, {_das(quando_local, tz, hoje)}"
    elif resultado == "conflito_perdido":
        if segunda_pessoa:
            fim = "ficou o que estava na CCAR"
        else:
            de = "" if mesma else f" de {nomes.get(por_srv, por_srv or 'quem gravou na CCAR')}"
            fim = f"ficou {nome_srv}{de}, {_das(quando_srv, tz, hoje)}"
    else:
        motivo = detalhe.get("motivo") or "regra da CCAR"
        if segunda_pessoa:
            fim = f"a CCAR recusou: {motivo}; voltou ao que está na CCAR"
        else:
            fim = f"a CCAR recusou e ficou o que estava lá. Motivo, como {quem.split()[0]} viu: “{motivo}”"
            if srv is None:
                fim = f"a CCAR recusou: a {TABELAS.get(tabela, 'linha')} não existe mais lá"
            elif passou:
                fim += f". A carga está com {nomes.get(responsavel_atual, responsavel_atual)}"
    return f"{texto}; {fim}."


def vencedor(resultado: str) -> str:
    """Qual lado ficou: `local` (o que a pessoa enviou) ou `servidor` (o que estava na CCAR)."""
    return "local" if resultado == "conflito_vencido" else "servidor"


# --- leitura na CCAR --------------------------------------------------------------------------------------------------


def _filtros(
    uf: str, resultados: Iterable[str], desde: dt.datetime, ate: dt.datetime, pessoa: Optional[str],
    folha: Optional[str],
) -> Tuple[str, list]:  # fmt: skip
    sql = (
        "s.uf = %s AND s.resultado = ANY(%s) AND s.em >= %s AND s.em < %s "
        "AND (%s::text IS NULL OR s.usuario = %s OR s.detalhe->'servidor'->>'por' = %s) "
        f"AND (%s::text IS NULL OR {S}.f_rotulo(l.tipo, l.nome, le.revisao) ILIKE %s "
        "OR s.detalhe->'ref'->>'folha' ILIKE %s OR coalesce(c.geocodigo, s.detalhe->'ref'->>'geocodigo') ILIKE %s)"
    )
    padrao = f"%{folha.strip()}%" if folha and folha.strip() else None
    return sql, [uf, list(resultados), desde, ate, pessoa, pessoa, pessoa, padrao, padrao, padrao, padrao]


_DE = (
    f"FROM {S}.sync_log s "
    f"LEFT JOIN {S}.carga_trabalho c ON s.tabela = 'carga_trabalho' AND c.uuid = s.uuid "
    f"LEFT JOIN {S}.fila_folha f ON s.tabela = 'fila_folha' AND f.uuid = s.uuid "
    f"LEFT JOIN {S}.lote_etapa_hist h ON s.tabela = 'lote_etapa_hist' AND h.uuid = s.uuid "
    f"LEFT JOIN {S}.lote_etapa le0 ON s.tabela = 'lote_etapa' AND le0.uuid = s.uuid "
    f"LEFT JOIN {S}.lote_etapa le ON le.id = coalesce(c.id_lote_etapa, f.id_lote_etapa, h.id_lote_etapa, le0.id, "
    "(s.detalhe->'ref'->>'id_lote_etapa')::int) "
    f"LEFT JOIN {S}.lote l ON l.id = le.id_lote "
    f"LEFT JOIN {S}.tema t ON t.id = l.id_tema "
    f"LEFT JOIN {S}.fluxo_etapa fe ON fe.id = le.id_fluxo_etapa "
    f"LEFT JOIN {S}.atividade a ON a.id = coalesce(c.id_atividade, (s.detalhe->'ref'->>'id_atividade')::int) "
)


def _nomes(ex: Executor, contas: Iterable[Optional[str]]) -> Dict[str, str]:
    lista = sorted({c for c in contas if c})
    if not lista:
        return {}
    return {
        r["conta"]: r["nome"]
        for r in ex.todos(
            "SELECT nom_contausuario AS conta, nom_usuario::text AS nome FROM mapcartctrl.t_usuario "
            "WHERE nom_contausuario = ANY(%s)",
            (lista,),
        )
        if r["nome"]
    }


def _detalhe(v: Any) -> Dict:
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except ValueError:
            v = None
    return v if isinstance(v, dict) else {}


def listar(
    ex: Executor,
    uf: str,
    resultados: Iterable[str] = NA_TELA,
    desde: Optional[dt.datetime] = None,
    ate: Optional[dt.datetime] = None,
    pessoa: Optional[str] = None,
    folha: Optional[str] = None,
    pagina: int = 1,
    por_pagina: int = POR_PAGINA,
    tz: dt.tzinfo = dt.timezone.utc,
) -> Dict:
    """Conflitos e recusas da UF, do mais recente ao mais antigo, paginados. `pessoa`: quem enviou ou quem tinha
    gravado o valor da CCAR. `folha`: texto na folha-revisão (ou no nome do lote livre) ou no geocódigo."""
    agora = dt.datetime.now(dt.timezone.utc)
    ate = ate or agora + dt.timedelta(minutes=1)
    desde = desde or agora - dt.timedelta(days=30)
    por_pagina = max(1, min(int(por_pagina), MAX_POR_PAGINA))
    pagina = max(1, int(pagina))
    filtro, params = _filtros(uf, resultados, desde, ate, pessoa, folha)
    linhas = ex.todos(
        "SELECT s.id, s.em, s.usuario, s.tabela, s.uuid::text AS uuid, s.operacao, s.resultado, s.detalhe, "
        "c.id AS id_carga, c.geocodigo, c.responsavel AS responsavel_atual, c.concluido AS concluido_atual, "
        f"le.id AS id_lote_etapa, le.id_lote, {S}.f_rotulo(l.tipo, l.nome, le.revisao) AS folha, "
        "t.nome AS tema, fe.nome AS etapa, a.nome AS atividade, "
        "(c.id IS NOT NULL OR f.id IS NOT NULL OR h.id IS NOT NULL OR le0.id IS NOT NULL) AS existe, "
        f"count(*) OVER () AS total {_DE}WHERE {filtro} ORDER BY s.em DESC, s.id DESC LIMIT %s OFFSET %s",
        tuple(params + [por_pagina, (pagina - 1) * por_pagina]),
    )
    total = int(linhas[0]["total"]) if linhas else 0
    for r in linhas:
        r["detalhe"] = _detalhe(r["detalhe"])
    contas: List[Optional[str]] = []
    for r in linhas:
        contas += [r["usuario"], r["responsavel_atual"], (r["detalhe"].get("servidor") or {}).get("por")]
        for lado in ("local", "servidor"):
            contas.append(((r["detalhe"].get(lado) or {}).get("valores") or {}).get("responsavel"))
    nomes = _nomes(ex, contas)
    hoje = agora.astimezone(tz).date()
    return {
        "itens": [_item(r, nomes, tz, hoje) for r in linhas],
        "total": total,
        "pagina": pagina,
        "por_pagina": por_pagina,
        "desde": _iso(desde),
        "ate": _iso(ate),
        "resultados": list(resultados),
    }


def _item(r: Dict, nomes: Dict[str, str], tz: dt.tzinfo, hoje: dt.date) -> Dict:
    d = r["detalhe"]
    ref = d.get("ref") or {}
    local = d.get("local") or {}
    srv = d.get("servidor")
    pessoa = lambda c: {"conta": c, "nome": nomes.get(c, c)} if c else None  # noqa: E731
    quem = (r["usuario"], r["responsavel_atual"])
    return {
        "id": r["id"],
        "em": _iso(r["em"]),
        "resultado": r["resultado"],
        "tabela": r["tabela"],
        "tipo": TABELAS.get(r["tabela"], r["tabela"]),
        "operacao": r["operacao"],
        "uuid": r["uuid"],
        "enviado_por": pessoa(r["usuario"]),
        "alvo": {
            "existe": bool(r["existe"]),
            "id_carga": r["id_carga"] or (ref.get("id") if r["tabela"] == "carga_trabalho" else None),
            "geocodigo": r["geocodigo"] or ref.get("geocodigo"),
            "id_lote": r["id_lote"] or ref.get("id_lote"),
            "id_lote_etapa": r["id_lote_etapa"] or ref.get("id_lote_etapa"),
            "folha": r["folha"] or ref.get("folha"),
            "tema": r["tema"],
            "etapa": r["etapa"] or ref.get("etapa"),
            "atividade": r["atividade"] or ref.get("atividade"),
            "responsavel_atual": pessoa(r["responsavel_atual"]),
            "concluido_atual": r["concluido_atual"],
        },
        "local": {
            "por": pessoa(local.get("por") or r["usuario"]),
            "em": local.get("em"),
            "hora_estacao": d.get("hora_estacao"),
            "acao": acao_local(r["tabela"], r["operacao"], d)[0],
        },
        "servidor": None
        if srv is None
        else {
            "por": pessoa(srv.get("por")),
            "em": srv.get("em"),
            "origem_em": srv.get("origem_em"),
            "acao": acao_servidor(r["tabela"], d)[0],
        },
        "valores": valores(d, tz, nomes),
        "vencedor": vencedor(r["resultado"]),
        "descartado": d.get("descartado"),
        "motivo": d.get("motivo"),
        "juntados": len(d.get("juntados") or []),
        "desvio_s": d.get("desvio_s"),
        "frase": frase(r["resultado"], r["tabela"], r["operacao"], d, r["em"], nomes, tz, hoje, *quem),
    }


def contagem(ex: Executor, uf: str, dias: int = 7) -> Dict:
    """Conflitos e recusas da UF nos últimos `dias` (o contador do menu e do Início)."""
    desde = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=dias)
    r = (
        ex.um(
            f"SELECT count(*) FILTER (WHERE resultado IN ('conflito_vencido', 'conflito_perdido')) AS conflitos, "
            f"count(*) FILTER (WHERE resultado = 'recusado') AS recusas FROM {S}.sync_log "
            "WHERE uf = %s AND em >= %s AND resultado IN ('conflito_vencido', 'conflito_perdido', 'recusado')",
            (uf, desde),
        )
        or {}
    )
    conflitos, recusas = int(r.get("conflitos") or 0), int(r.get("recusas") or 0)
    return {"conflitos": conflitos, "recusas": recusas, "total": conflitos + recusas, "dias": dias,
            "desde": _iso(desde)}  # fmt: skip
