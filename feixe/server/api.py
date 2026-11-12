"""Rotas da API JSON do plugin. Cada rota recebe (req) e devolve (status, objeto).

As rotas não importam o QGIS: tudo que precisa dele chega pelo `Contexto`, injetado pelo plugin.
Isso mantém o servidor testável fora do QGIS.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..core import papeis


class ErroApi(Exception):
    def __init__(self, status: int, mensagem: str):
        super().__init__(mensagem)
        self.status = status
        self.mensagem = mensagem


class Requisicao:
    def __init__(self, metodo: str, caminho: str, query: Dict[str, str], corpo: Any, params: Dict[str, str]):
        self.metodo = metodo
        self.caminho = caminho
        self.query = query
        self.corpo = corpo
        self.params = params


Rota = Tuple[str, "re.Pattern[str]", Callable[[Requisicao], Tuple[int, Any]]]


class Roteador:
    def __init__(self):
        self._rotas: List[Rota] = []

    def rota(self, metodo: str, padrao: str):
        """Decorador: @r.rota("GET", "/api/folhas/{id}/zoom")."""
        regex = re.compile("^" + re.sub(r"{(\w+)}", r"(?P<\1>[^/]+)", padrao) + "$")

        def registrar(fn):
            self._rotas.append((metodo.upper(), regex, fn))
            return fn

        return registrar

    def despachar(self, metodo: str, caminho: str, query: Dict[str, str], corpo: Any) -> Tuple[int, Any]:
        permitido = False
        for m, regex, fn in self._rotas:
            casou = regex.match(caminho)
            if not casou:
                continue
            if m != metodo.upper():
                permitido = True
                continue
            try:
                return fn(Requisicao(metodo, caminho, query, corpo, casou.groupdict()))
            except ErroApi as e:
                return e.status, {"erro": e.mensagem}
            except Exception as e:  # noqa: BLE001
                return 500, {"erro": f"{e.__class__.__name__}: {e}"}
        if permitido:
            return 405, {"erro": "método não permitido"}
        return 404, {"erro": "rota não encontrada"}


class Contexto:
    """O que as rotas podem pedir ao plugin. Cada atributo é uma função injetada; `None` = indisponível."""

    def __init__(
        self,
        status: Callable[[], Dict] = None,
        consultar: Callable[[str, Optional[tuple]], List[Dict]] = None,
        zoom_para: Callable[[float, float, float, float, int], None] = None,
        sincronizar: Callable[[], Dict] = None,
    ):
        self.status = status or (lambda: {"online": False})
        self.consultar = consultar
        self.zoom_para = zoom_para
        self.sincronizar = sincronizar


def criar_roteador(ctx: Contexto) -> Roteador:
    r = Roteador()

    @r.rota("GET", "/api/status")
    def _status(req):
        return 200, ctx.status()

    @r.rota("GET", "/api/eu")
    def _eu(req):
        # Quem está conectado e com que papel: só pelo SGBC (mapcartctrl) e por usuario_feixe, nunca por roles.
        if ctx.consultar is None:
            raise ErroApi(503, "banco indisponível")
        return 200, papeis.carregar(ctx.consultar)

    @r.rota("GET", "/api/folhas")
    def _folhas(req):
        if ctx.consultar is None:
            raise ErroApi(503, "banco indisponível")
        limite = min(int(req.query.get("limite", "100")), 1000)
        filtro = req.query.get("q", "").strip()
        sql = (
            "SELECT id_articulacao_scn AS id, cd_mi, nm_carta, nm_nomenclatura_scn AS nomenclatura, "
            "ST_XMin(geom) AS xmin, ST_YMin(geom) AS ymin, ST_XMax(geom) AS xmax, ST_YMax(geom) AS ymax "
            "FROM mapcartctrl.v_articulacao_scn_100000 "
        )
        params: tuple = ()
        if filtro:
            sql += "WHERE cd_mi ILIKE %s OR nm_carta ILIKE %s OR nm_nomenclatura_scn ILIKE %s "
            params = (f"%{filtro}%", f"%{filtro}%", f"%{filtro}%")
        sql += "ORDER BY cd_mi LIMIT %s"
        return 200, {"itens": ctx.consultar(sql, params + (limite,))}

    @r.rota("POST", "/api/folhas/{id}/zoom")
    def _zoom(req):
        if ctx.consultar is None or ctx.zoom_para is None:
            raise ErroApi(503, "QGIS ou banco indisponível")
        linhas = ctx.consultar(
            "SELECT ST_XMin(geom) AS xmin, ST_YMin(geom) AS ymin, ST_XMax(geom) AS xmax, ST_YMax(geom) AS ymax "
            "FROM mapcartctrl.v_articulacao_scn_100000 WHERE id_articulacao_scn = %s",
            (int(req.params["id"]),),
        )
        if not linhas:
            raise ErroApi(404, "folha não encontrada")
        b = linhas[0]
        ctx.zoom_para(b["xmin"], b["ymin"], b["xmax"], b["ymax"], 4674)
        return 200, {"ok": True}

    @r.rota("POST", "/api/sincronizar")
    def _sync(req):
        if ctx.sincronizar is None:
            raise ErroApi(501, "sincronização ainda não implementada")
        return 200, ctx.sincronizar()

    return r
