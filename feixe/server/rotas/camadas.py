"""B1: montar o grupo de camadas do Feixe no QGIS."""

from __future__ import annotations

from ...core.dados import grupos

TODOS = ("gerente", "supervisor", "avaliador", "apm", "consulta")


def montar(ctx) -> dict:
    """Usada pela rota e pela barra. As consultas (subgrupos por atividade em produção, D-102) rodam aqui; o QGIS só
    recebe o resultado."""
    eu = ctx.eu()
    supervisor = "supervisor" in eu["papeis"]
    with ctx.tx() as ex:
        execucao = grupos.execucao(ex)
        supervisao = grupos.supervisao(ex, eu.get("uf")) if supervisor else []
        responsaveis = grupos.responsaveis(ex, eu.get("uf")) if supervisor else []
    resultado = ctx.qgis("montar_camadas", eu, responsaveis, supervisao, execucao)
    ctx.publicar("qgis", {"acao": "camadas", **resultado})
    return resultado


def registrar(r, ctx) -> None:
    @r.rota("POST", "/api/camadas/montar", exige=TODOS)
    def _montar(req):
        return 200, montar(ctx)
