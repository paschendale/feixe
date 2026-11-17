"""B1: montar o grupo de camadas do Feixe no QGIS."""

from __future__ import annotations

from typing import List, Optional

from ...core.dados import cargas, lotes
from ..api import ErroApi, campo

# Módulos de camadas, na ordem do grupo Feixe (a mesma de core.camadas.MODULOS, que importa o QGIS).
MODULOS = ("minhas", "equipe", "folhas")
TODOS = ("gerente", "supervisor", "avaliador", "apm", "consulta")


def montar(ctx, modulos: Optional[List[str]] = None) -> dict:
    """Usada pela rota e pela barra (todas, ou só os módulos pedidos). As consultas rodam aqui; o QGIS só recebe o
    resultado."""
    eu = ctx.eu()
    if modulos is not None:
        desconhecidos = set(modulos) - set(MODULOS)
        if desconhecidos or not modulos:
            raise ErroApi(400, f"módulos de camadas: {', '.join(MODULOS)}")
        if modulos == ["equipe"] and "supervisor" not in eu["papeis"]:
            raise ErroApi(403, "as cargas da equipe são só para supervisor")
    quer = set(modulos or MODULOS)
    responsaveis, temas = [], []
    with ctx.tx() as ex:
        if "folhas" in quer:
            temas = lotes.temas_com_lotes(ex, eu.get("uf"))
        if "equipe" in quer and "supervisor" in eu["papeis"]:
            responsaveis = cargas.responsaveis_atuais(ex, eu.get("uf"))
    resultado = ctx.qgis("montar_camadas", eu, responsaveis, temas, modulos)
    ctx.publicar("qgis", {"acao": "camadas", **resultado})
    return resultado


def registrar(r, ctx) -> None:
    @r.rota("POST", "/api/camadas/montar", exige=TODOS)
    def _montar(req):
        return 200, montar(ctx, campo(req, "modulos", list, padrao=None))
