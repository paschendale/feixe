"""As próprias recusas e conflitos perdidos de quem executa (C5), do `sync_log` do workspace: funciona offline.

O workspace é de uma conta só, então tudo aqui é da própria pessoa. A frase fala na segunda pessoa e não mostra
colegas: quem gravou o valor da CCAR fica de fora, e o responsável de outra pessoa vira "outra pessoa".
"""

from __future__ import annotations

import datetime as dt
import json
from typing import Dict, List

from .. import sync_log as sl
from . import rotulo

_REF_CARGA = (
    f"SELECT c.id, c.geocodigo, c.id_lote_etapa, le.id_lote, {rotulo()} AS folha, fe.nome AS etapa, "
    "at.nome AS atividade FROM carga_trabalho c LEFT JOIN lote_etapa le ON le.id = c.id_lote_etapa "
    "LEFT JOIN lote l ON l.id = le.id_lote LEFT JOIN fluxo_etapa fe ON fe.id = le.id_fluxo_etapa "
    "LEFT JOIN atividade at ON at.id = c.id_atividade WHERE c.uuid = ?"
)


def meus(ex, tz: dt.tzinfo, dias: int = 7, limite: int = 20) -> Dict:
    """Recusas e conflitos perdidos dos últimos `dias`, do mais recente ao mais antigo."""
    agora = dt.datetime.now(dt.timezone.utc)
    desde = (agora - dt.timedelta(days=dias)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    linhas = ex.todos(
        "SELECT id, em, tabela, uuid, operacao, resultado, detalhe FROM sync_log "
        "WHERE resultado IN ('conflito_perdido', 'recusado') AND em >= ? ORDER BY em DESC, id DESC",
        (desde,),
    )
    hoje = agora.astimezone(tz).date()
    itens: List[Dict] = []
    vistos = set()
    for r in linhas:
        d = json.loads(r["detalhe"]) if r["detalhe"] else {}
        if d.get("repetido"):  # resposta perdida de um push anterior: a linha original já está aqui
            continue
        chave = tuple(d.get("itens") or [r["id"]])
        if chave in vistos:
            continue
        vistos.add(chave)
        ref = dict(d.get("ref") or {})
        if not ref and r["tabela"] == "carga_trabalho" and r["uuid"]:
            ref = ex.um(_REF_CARGA, (r["uuid"],)) or {}
        nomes = {ex.usuario: "você"}
        for lado in ("local", "servidor"):
            outro = ((d.get(lado) or {}).get("valores") or {}).get("responsavel")
            if outro and outro != ex.usuario:
                nomes[outro] = "outra pessoa"
        em = sl.de_iso(r["em"])
        itens.append({
            "id": r["id"],
            "em": sl._iso(em),
            "resultado": r["resultado"],
            "tipo": sl.TABELAS.get(r["tabela"], r["tabela"]),
            "alvo": {k: ref.get(k) for k in ("id", "geocodigo", "id_lote", "id_lote_etapa", "folha", "etapa",
                                             "atividade")},  # fmt: skip
            "valores": sl.valores(d, tz, nomes),
            "motivo": d.get("motivo"),
            "frase": sl.frase(r["resultado"], r["tabela"], r["operacao"], d, em, nomes, tz, hoje, ex.usuario,
                              segunda_pessoa=True),  # fmt: skip
        })  # fmt: skip
        if len(itens) >= limite:
            break
    return {"itens": itens, "dias": dias}
