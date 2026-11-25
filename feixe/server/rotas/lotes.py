"""B3: folhas e lotes livres do supervisor, fluxos da UF e as ferramentas do QGIS para escolher folha e polígono."""

from __future__ import annotations

from typing import Dict, Optional

from ...core.dados import lotes as dl
from ..api import ErroApi, campo, inteiro

STATUS = ("PLANEJADA", "EM_PRODUCAO", "EM_CQ", "ENTREGUE_GCQ", "CONCLUIDA", "DEVOLVIDA")


def uf_de(eu: Dict, gerente_ve_tudo: bool = False) -> Optional[str]:
    """UF em que a pessoa trabalha. Gerente que não é supervisor vê todas (None)."""
    if gerente_ve_tudo and "gerente" in eu["papeis"] and "supervisor" not in eu["papeis"]:
        return None
    if not eu.get("uf"):
        raise ErroApi(403, "sua lotação no SGBC não é uma unidade (UF): peça o acerto à CCAR")
    return eu["uf"]


def projetos_supervisor(eu: Dict):
    return [p["cod_projeto"] for p in eu.get("perfis") or [] if p.get("papel") == "supervisor"]


def registrar(r, ctx) -> None:
    @r.rota("GET", "/api/lotes", exige=("supervisor", "gerente"))
    def _lista(req):
        status = req.query.get("status")
        if status and status not in STATUS:
            raise ErroApi(400, "status nacional desconhecido")
        tema = req.query.get("tema")
        with ctx.tx() as ex:
            itens = dl.listar(ex, uf_de(ctx.eu(), True), inteiro(tema, "tema") if tema else None, status)
        return 200, {"itens": itens}

    @r.rota("GET", "/api/lotes/{id}", exige=("supervisor", "gerente"))
    def _um(req):
        uf = uf_de(ctx.eu(), True)
        with ctx.tx() as ex:
            lote = dl.um(ex, inteiro(req.params["id"]))
        if not lote or (uf and lote["uf"] != uf):
            raise ErroApi(404, "lote não encontrado")
        return 200, lote

    @r.rota("POST", "/api/lotes/{id}/zoom", exige=("supervisor", "gerente"))
    def _zoom(req):
        uf = uf_de(ctx.eu(), True)
        with ctx.tx() as ex:
            lote = dl.um(ex, inteiro(req.params["id"]))
        if not lote or (uf and lote["uf"] != uf):
            raise ErroApi(404, "lote não encontrado")
        if ctx.zoom_para is None:
            raise ErroApi(503, "QGIS indisponível")
        ctx.zoom_para(lote["xmin"], lote["ymin"], lote["xmax"], lote["ymax"], 4674)
        return 200, {"ok": True}

    @r.rota("POST", "/api/lotes", exige=("supervisor",))
    def _criar(req):
        from .cargas import preparar

        eu = ctx.eu()
        uf, projetos = uf_de(eu), projetos_supervisor(eu)
        tipo = campo(req, "tipo", str)
        id_fluxo = campo(req, "id_fluxo", int)
        with ctx.tx() as ex:
            if tipo == "folha":
                folhas = campo(req, "folhas", lambda v: [int(x) for x in v])
                resultado = dl.criar_folhas(ex, uf, id_fluxo, folhas, projetos)
            elif tipo == "livre":
                resultado = dl.criar_livre(ex, uf, id_fluxo, campo(req, "nome", str), campo(req, "wkt", str), projetos)
            else:
                raise ErroApi(400, "tipo deve ser folha ou livre")
        if resultado["criados"]:
            ctx.publicar("lote", {"criados": [c["id_lote"] for c in resultado["criados"]]})
            resultado["preparo"] = preparar(ctx, uf, [c.get("id_lote_etapa") for c in resultado["criados"]])
        return 200, resultado

    @r.rota("GET", "/api/fluxos", exige=("supervisor", "gerente"))
    def _fluxos(req):
        projeto, tema = req.query.get("projeto"), req.query.get("tema")
        with ctx.tx() as ex:
            itens = dl.fluxos(
                ex,
                uf_de(ctx.eu()),
                inteiro(projeto, "projeto") if projeto else None,
                inteiro(tema, "tema") if tema else None,
            )
        return 200, {"itens": itens}

    @r.rota("GET", "/api/folhas", exige=("supervisor", "gerente"))
    def _folhas(req):
        # A busca de folhas da Nova folha, na articulação 1:100.000 do SGBC.
        limite = min(inteiro(req.query.get("limite", "100"), "limite"), 1000)
        with ctx.tx() as ex:
            return 200, {"itens": dl.buscar_folhas(ex, req.query.get("q", "").strip(), limite)}

    def _no_feixe(req):
        id_fluxo = campo(req, "id_fluxo", int, padrao=None)
        with ctx.tx() as ex:
            return dl.folhas_no_feixe(ex, uf_de(ctx.eu()), id_fluxo)

    @r.rota("POST", "/api/qgis/escolher_folhas", exige=("supervisor",))
    def _ferramenta(req):
        # Carrega no QGIS a malha de folhas 1:100.000 (já no Feixe, escolhidas, livres) e liga a ferramenta: clique
        # escolhe ou tira uma folha, Ctrl ou Shift e arrastar escolhe as de um retângulo. Cada mudança publica o
        # evento qgis {acao: "folhas", adicionar, tirar}; o painel guarda a lista e devolve por /folhas_escolhidas.
        escolhidas = campo(req, "escolhidas", lambda v: [int(x) for x in v], padrao=[])
        with ctx.tx() as ex:
            folhas = dl.malha(ex)
        ctx.qgis("ferramenta_folhas", folhas, _no_feixe(req), escolhidas)
        return 200, {"ok": True}

    @r.rota("POST", "/api/qgis/folhas_escolhidas", exige=("supervisor",))
    def _escolhidas(req):
        # A lista do painel mudou (ou o fluxo, que muda o que já está no Feixe): a malha no QGIS acompanha.
        escolhidas = campo(req, "escolhidas", lambda v: [int(x) for x in v], padrao=[])
        ctx.qgis("marcar_folhas", _no_feixe(req), escolhidas)
        return 200, {"ok": True}

    @r.rota("POST", "/api/qgis/folhas_fim", exige=("supervisor",))
    def _fim(req):
        ctx.qgis("fim_folhas")
        return 200, {"ok": True}

    @r.rota("POST", "/api/qgis/selecao", exige=("supervisor",))
    def _selecao(req):
        # Polígono das feições selecionadas na camada ativa do QGIS, unidas, em SIRGAS 2000 geográfico.
        return 200, ctx.qgis("selecao_wkt")
