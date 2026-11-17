"""B1: montar o grupo de camadas do Feixe no QGIS."""

from __future__ import annotations

from ...core.dados import cargas, lotes

TODOS = ("gerente", "supervisor", "avaliador", "apm", "consulta")


def montar(ctx) -> dict:
    """Usada pela rota e pela barra. As consultas rodam aqui; o QGIS só recebe o resultado."""
    eu = ctx.eu()
    responsaveis = []
    with ctx.tx() as ex:
        temas = lotes.temas_com_lotes(ex, eu.get("uf"))
        if "supervisor" in eu["papeis"]:
            responsaveis = cargas.responsaveis_atuais(ex, eu.get("uf"))
    resultado = ctx.qgis("montar_camadas", eu, responsaveis, temas)
    ctx.publicar("qgis", {"acao": "camadas", **resultado})
    return resultado


def registrar(r, ctx) -> None:
    @r.rota("POST", "/api/camadas/montar", exige=TODOS)
    def _montar(req):
        return 200, montar(ctx)
