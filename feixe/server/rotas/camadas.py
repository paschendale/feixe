"""B1/C4: montar o grupo de camadas do Feixe no QGIS."""

from __future__ import annotations

from ...core.dados import grupos
from ...core.dados.local import grupos as grupos_local
from ..api import SEM_CCAR, TODOS, ErroApi, sem_conexao

SUPERVISAO_SEM_CCAR = (
    "A supervisão precisa da conexão com a CCAR, que não está respondendo: o grupo Feixe veio só com a Execução. "
    "Carregue as camadas de novo quando a conexão voltar."
)


def montar(ctx) -> dict:
    """Usada pela rota e pela barra. As consultas (subgrupos por atividade em produção, D-102) rodam aqui; o QGIS só
    recebe o resultado. A execução vem do workspace (C4), online ou offline; a supervisão, da CCAR, e sem ela o grupo
    vem só com a Execução e um aviso (`avisos`)."""
    eu = ctx.eu()
    supervisor = "supervisor" in eu["papeis"]
    ws = ctx.ws()
    with ctx.leitura() as lx:
        execucao = grupos_local.execucao(lx)
    supervisao, responsaveis, avisos = None, [], []
    if supervisor:
        try:
            with ctx.tx() as ex:
                supervisao = grupos.supervisao(ex, eu.get("uf"))
                responsaveis = grupos.responsaveis(ex, eu.get("uf"))
        except ErroApi as e:
            if e.mensagem != SEM_CCAR:
                raise
            avisos.append(SUPERVISAO_SEM_CCAR)
        except Exception as e:  # noqa: BLE001 - a conexão caiu no meio: o mesmo caso, sem a CCAR
            if not sem_conexao(e):
                raise
            avisos.append(SUPERVISAO_SEM_CCAR)
    resultado = ctx.qgis("montar_camadas", eu, responsaveis, supervisao, execucao, ws.caminho)
    resultado = {**resultado, "avisos": avisos}
    ctx.publicar("qgis", {"acao": "camadas", **resultado})
    return resultado


def registrar(r, ctx) -> None:
    @r.rota("POST", "/api/camadas/montar", exige=TODOS)
    def _montar(req):
        return 200, montar(ctx)
