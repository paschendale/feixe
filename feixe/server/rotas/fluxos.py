"""B6: fluxos da unidade e o andar da folha pelas etapas. Só o supervisor muda; o gerente vê os fluxos de todas."""

from __future__ import annotations

from ...core.dados import fluxos as df
from ..api import ErroApi, campo, inteiro
from .lotes import projetos_supervisor, uf_de

ACOES = ("iniciar", "concluir", "pular", "reabrir", "gcq")


def _etapas(req):
    etapas = campo(req, "etapas", padrao=None)
    if etapas is not None and not isinstance(etapas, list):
        raise ErroApi(400, "etapas deve ser uma lista")
    return etapas


def registrar(r, ctx) -> None:
    @r.rota("GET", "/api/fluxos/completos", exige=("supervisor", "gerente"))
    def _completos(req):
        # ?outras=1: de todas as unidades (para copiar); senão, só os da unidade de quem pede.
        uf = None if req.query.get("outras") else uf_de(ctx.eu(), True)
        with ctx.tx() as ex:
            return 200, {"itens": df.listar(ex, uf), "modelo": df.MODELO_CCAR}

    @r.rota("POST", "/api/fluxos", exige=("supervisor",))
    def _criar(req):
        eu = ctx.eu()
        uf = uf_de(eu)
        modo = campo(req, "modo", str, padrao="modelo")
        nome = campo(req, "nome", str)
        with ctx.tx() as ex:
            if modo == "copia":
                f = df.copiar(ex, uf, campo(req, "id_origem", int), nome)
            else:
                projeto, tema = campo(req, "cod_projeto", int), campo(req, "id_tema", int)
                if projeto not in projetos_supervisor(eu):
                    raise ErroApi(403, "você não é supervisor neste projeto (perfil S no SGBC)")
                if modo == "modelo":
                    f = df.do_modelo(ex, uf, projeto, tema, nome)
                elif modo == "novo":
                    f = df.criar(ex, uf, projeto, tema, nome, _etapas(req) or [])
                else:
                    raise ErroApi(400, "modo deve ser modelo, copia ou novo")
            if f["cod_projeto"] not in projetos_supervisor(eu):
                raise ErroApi(403, "você não é supervisor no projeto do fluxo copiado (perfil S no SGBC)")
        ctx.publicar("fluxo", {"id": f["id"]})
        return 200, f

    @r.rota("PUT", "/api/fluxos/{id}", exige=("supervisor",))
    def _alterar(req):
        with ctx.tx() as ex:
            f = df.alterar(
                ex, uf_de(ctx.eu()), inteiro(req.params["id"]), campo(req, "nome", str, padrao=None),
                campo(req, "ativo", bool, padrao=None), _etapas(req),
            )  # fmt: skip
        ctx.publicar("fluxo", {"id": f["id"]})
        return 200, f

    @r.rota("POST", "/api/lote_etapas/{id}/{acao}", exige=("supervisor",))
    def _acao(req):
        qual = req.params["acao"]
        if qual not in ACOES:
            raise ErroApi(404, "ação desconhecida")
        with ctx.tx() as ex:
            estado = df.acao(
                ex, uf_de(ctx.eu()), inteiro(req.params["id"]), qual, campo(req, "observacao", str, padrao=""),
                campo(req, "resultado", str, padrao=None),
            )  # fmt: skip
        ctx.publicar("lote", {"id": estado["id"], "acao": qual})
        return 200, estado

    @r.rota("POST", "/api/lotes/{id}/passagens", exige=("supervisor",))
    def _nova(req):
        with ctx.tx() as ex:
            estado = df.nova_passagem(
                ex, uf_de(ctx.eu()), inteiro(req.params["id"]), campo(req, "id_fluxo_etapa", int),
                campo(req, "observacao", str, padrao=""), campo(req, "expor_ocorrencias", bool, padrao=False),
            )  # fmt: skip
        ctx.publicar("lote", {"id": estado["id"], "acao": "passagem"})
        return 200, estado

    @r.rota("GET", "/api/lotes/{id}/historico", exige=("supervisor", "gerente"))
    def _historico(req):
        with ctx.tx() as ex:
            return 200, {"itens": df.historico(ex, inteiro(req.params["id"]))}

    @r.rota("GET", "/api/lotes/{id}/estado", exige=("supervisor", "gerente"))
    def _estado(req):
        with ctx.tx() as ex:
            return 200, df.estado(ex, inteiro(req.params["id"]))

    @r.rota("GET", "/api/prontas", exige=("supervisor",))
    def _prontas(req):
        with ctx.tx() as ex:
            return 200, {"itens": df.prontas(ex, uf_de(ctx.eu()))}
