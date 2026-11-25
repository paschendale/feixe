"""C5: conflitos de sincronização. O supervisor lê o `sync_log` da CCAR da sua UF; quem executa, as próprias recusas
e conflitos perdidos, do workspace (offline também). Nada aqui desfaz um conflito: o supervisor age pelas telas de
sempre."""

from __future__ import annotations

import datetime as dt
from typing import Optional

from ...core.dados import sync_log as sl
from ...core.dados.local import sync_log as lsl
from ..api import ErroApi, fuso_de, inteiro
from .cargas import EXECUTORES
from .lotes import uf_de


def _dia(texto: Optional[str], tz: dt.tzinfo, nome: str) -> Optional[dt.datetime]:
    """'2026-11-24' no fuso de quem olha -> o começo desse dia."""
    if not texto:
        return None
    try:
        d = dt.date.fromisoformat(texto[:10])
    except ValueError:
        raise ErroApi(400, f"{nome} inválido: use AAAA-MM-DD") from None
    return dt.datetime(d.year, d.month, d.day, tzinfo=tz)


def filtros(req, tz: dt.tzinfo) -> dict:
    q = req.query
    try:
        resultados = sl.resultados_de(q.get("resultado"))
    except ValueError as e:
        raise ErroApi(400, f"{e}: use conflito_vencido, conflito_perdido, conflito_* ou recusado") from None
    desde = _dia(q.get("desde"), tz, "desde")
    ate = _dia(q.get("ate"), tz, "ate")
    if ate is not None:
        ate += dt.timedelta(days=1)  # até o fim do dia
    if desde and ate and desde >= ate:
        raise ErroApi(400, "o período começa depois de terminar")
    pagina = inteiro(q.get("pagina") or 1, "pagina")
    por_pagina = inteiro(q.get("por_pagina") or sl.POR_PAGINA, "por_pagina")
    if pagina < 1 or por_pagina < 1:
        raise ErroApi(400, "página inválida")
    return {
        "resultados": resultados,
        "desde": desde,
        "ate": ate,
        "pessoa": (q.get("pessoa") or "").strip() or None,
        "folha": (q.get("folha") or "").strip() or None,
        "pagina": pagina,
        "por_pagina": min(por_pagina, sl.MAX_POR_PAGINA),
    }


def registrar(r, ctx) -> None:
    @r.rota("GET", "/api/sync_log", exige=("supervisor",))
    def _lista(req):
        tz = fuso_de(req)
        f = filtros(req, tz)
        uf = uf_de(ctx.eu())
        with ctx.tx() as ex:
            return 200, sl.listar(ex, uf, tz=tz, **f)

    @r.rota("GET", "/api/sync_log/contagem", exige=("supervisor",))
    def _contagem(req):
        dias = inteiro(req.query.get("dias") or 7, "dias")
        if not 1 <= dias <= 90:
            raise ErroApi(400, "dias: de 1 a 90")
        uf = uf_de(ctx.eu())
        with ctx.tx() as ex:
            return 200, sl.contagem(ex, uf, dias)

    @r.rota("GET", "/api/sync_log/meus", exige=EXECUTORES)
    def _meus(req):
        tz = fuso_de(req)
        dias = inteiro(req.query.get("dias") or 7, "dias")
        if not 1 <= dias <= 90:
            raise ErroApi(400, "dias: de 1 a 90")
        if ctx.preparando():
            return 200, {"itens": [], "dias": dias, "preparando": True}
        with ctx.leitura() as ex:
            return 200, lsl.meus(ex, tz, dias)
