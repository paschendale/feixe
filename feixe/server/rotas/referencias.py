"""B7: catálogo nacional. Todos os papéis leem; só o gerente (CCAR) cria e altera temas e atividades (D-87)."""

from __future__ import annotations

from ...core.dados import referencias as dr
from ..api import ErroApi, inteiro

TODOS = ("gerente", "supervisor", "avaliador", "apm", "consulta")
_ATIVIDADE = {
    "cod_projeto": int,
    "id_tema": int,
    "fase": str,
    "nome": str,
    "geracao": str,
    "grade_nivel": int,
    "id_medidadequalidade": int,
    "ativo": bool,
}


def _corpo(req, campos) -> dict:
    """Só os campos conhecidos que vieram, convertidos; nulo passa como nulo."""
    corpo = req.corpo if isinstance(req.corpo, dict) else {}
    saida = {}
    for nome, conv in campos.items():
        if nome in corpo:
            valor = corpo[nome]
            try:
                saida[nome] = None if valor is None else conv(valor)
            except (TypeError, ValueError):
                raise ErroApi(400, f"campo inválido: {nome}") from None
    return saida


def registrar(r, ctx) -> None:
    @r.rota("GET", "/api/catalogo", exige=TODOS)
    def _catalogo(req):
        # Tudo que as telas de catálogo e os formulários precisam, numa ida só.
        with ctx.tx() as ex:
            return 200, {
                "temas": dr.temas(ex),
                "atividades": dr.atividades(ex),
                "elementos_cq": dr.elementos_cq(ex),
                "fases": dr.fases(ex),
                "projetos": ex.todos(
                    "SELECT cod_projeto, nom_projeto AS nome FROM mapcartctrl.t_projeto ORDER BY nom_projeto"
                ),
                "geracoes": list(dr.GERACOES),
                "niveis_grade": list(dr.NIVEIS_GRADE),
            }

    @r.rota("GET", "/api/atividades", exige=TODOS)
    def _atividades(req):
        with ctx.tx() as ex:
            return 200, {"itens": dr.atividades(ex)}

    @r.rota("GET", "/api/temas", exige=TODOS)
    def _temas(req):
        with ctx.tx() as ex:
            return 200, {"itens": dr.temas(ex)}

    @r.rota("POST", "/api/atividades", exige=("gerente",))
    def _criar(req):
        with ctx.tx() as ex:
            a = dr.criar_atividade(ex, _corpo(req, _ATIVIDADE))
        ctx.publicar("atividade", {"id": a["id"]})
        return 200, a

    @r.rota("PATCH", "/api/atividades/{id}", exige=("gerente",))
    def _alterar(req):
        with ctx.tx() as ex:
            a = dr.alterar_atividade(ex, inteiro(req.params["id"]), _corpo(req, _ATIVIDADE))
        ctx.publicar("atividade", {"id": a["id"]})
        return 200, a

    @r.rota("POST", "/api/temas", exige=("gerente",))
    def _criar_tema(req):
        with ctx.tx() as ex:
            t = dr.criar_tema(ex, _corpo(req, {"nome": str}).get("nome"))
        ctx.publicar("atividade", {"tema": t["id"]})
        return 200, t

    @r.rota("PATCH", "/api/temas/{id}", exige=("gerente",))
    def _alterar_tema(req):
        c = _corpo(req, {"nome": str, "ativo": bool})
        with ctx.tx() as ex:
            t = dr.alterar_tema(ex, inteiro(req.params["id"]), c.get("nome"), c.get("ativo"))
        ctx.publicar("atividade", {"tema": t["id"]})
        return 200, t
