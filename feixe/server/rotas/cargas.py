"""B2: minhas cargas. As funções de módulo servem às rotas e aos botões da barra do Feixe (mesmo caminho).

Execução (minhas cargas, resumo, próxima, concluir, desfazer, zoom): sobre o workspace local (C3, D-111), online ou
offline, com `core/dados/local`; cada escrita acorda a sincronização em segundo plano. Supervisão (preparar, descartar,
equipe): na CCAR, como antes. Concluir é da barra do Feixe (e da camada Minhas cargas), não do painel."""

from __future__ import annotations

import contextlib
from typing import Dict, List, Optional, Tuple

from ...core.dados import ErroDados
from ...core.dados import cargas as dc
from ...core.dados.local import cargas as lc
from ..api import ErroApi, campo, inteiro

# Quem pode ter carga atribuída. Consulta só olha.
EXECUTORES = ("apm", "avaliador", "supervisor")


def _no_qgis(ctx, nome: str, *args) -> None:
    """Ação no QGIS quando ele está lá (no painel de teste, sem QGIS, segue sem ela)."""
    with contextlib.suppress(ErroApi):
        ctx.qgis(nome, *args)


def _publicar(ctx, r: Dict) -> None:
    ctx.publicar("carga", {"id": r["carga"]["id"], "concluido": r["carga"]["concluido"], "progresso": r["progresso"]})
    if r.get("fila"):
        # A fila passou a próxima folha: o supervisor vê no painel (Filas, Folhas) e as camadas mudam de dono.
        ctx.publicar("fila", {"atribuida": r["fila"]})
        ctx.publicar("lote", {"fila": r["fila"]["id_lote"]})


def _mudou(ctx, r: Dict) -> Dict:
    """Depois de uma escrita da execução no workspace: o painel fica sabendo e as camadas do workspace (C4) mostram já;
    as da supervisão, na CCAR, esperam o push (`so_workspace`)."""
    _publicar(ctx, r)
    _no_qgis(ctx, "cargas_mudaram", r["progresso"], True)
    return r


def concluir(ctx, id_carga: int) -> Dict:
    ctx.exigir_pronto()
    with ctx.local() as ex:
        r = lc.concluir(ex, id_carga)
    return _mudou(ctx, r)


def desfazer(ctx, id_carga: int) -> Dict:
    ctx.exigir_pronto()
    with ctx.local() as ex:
        r = lc.desfazer(ex, id_carga)
    return _mudou(ctx, r)


def editar(ctx, mudancas: Dict[int, bool]) -> Dict:
    """A edição de `concluido` pela camada Minhas cargas (tabela de atributos, formulário), já tirada do buffer do QGIS
    (C4, `core/edicao.py`): cada carga vai pelo mesmo caminho da barra (`concluir` ou `desfazer`, com as regras do D-94
    e a fila), na sua transação, para a recusa de uma não impedir as outras. Quem chama recarrega as camadas: aqui não
    se toca no QGIS (a camada ainda está no meio do commit). Volta o que foi feito e as recusas, com o motivo."""
    ctx.exigir_pronto()
    feitas, recusadas, fila, progresso = [], [], None, None
    for id_carga, concluido in mudancas.items():
        folha = None
        try:
            with ctx.local() as ex:
                atual = lc.uma(ex, id_carga)
                if atual is None:
                    raise ErroDados("carga não encontrada", 404)
                folha = atual["folha_revisao"]
                if bool(atual["concluido"]) == bool(concluido):
                    continue
                r = lc.concluir(ex, id_carga) if concluido else lc.desfazer(ex, id_carga)
        except ErroDados as e:
            recusadas.append({"id": id_carga, "folha_revisao": folha, "motivo": e.mensagem})
            continue
        _publicar(ctx, r)
        feitas.append({"id": id_carga, "concluido": bool(concluido), "folha_revisao": folha})
        progresso = r["progresso"]
        fila = r.get("fila") or fila
    return {"feitas": feitas, "recusadas": recusadas, "progresso": progresso, "fila": fila}


def mensagens_edicao(r: Dict) -> Tuple[List[str], List[str]]:
    """O resultado de `editar` em textos para a barra de mensagens do QGIS: (feito, avisos de recusa)."""
    ok, avisos = [], []
    feitas = r.get("feitas") or []
    p = r.get("progresso")
    concluidas = [f for f in feitas if f["concluido"]]
    desfeitas = [f for f in feitas if not f["concluido"]]
    sufixo = f" · {p['folha_revisao']} · {p['concluidas']}/{p['total']}" if p else ""
    if len(feitas) == 1:
        ok.append(("Carga concluída" if concluidas else "Conclusão desfeita") + sufixo)
    elif feitas:
        partes = []
        if concluidas:
            partes.append(f"{len(concluidas)} cargas concluídas")
        if desfeitas:
            partes.append(f"{len(desfeitas)} conclusões desfeitas")
        ok.append(" e ".join(partes) + sufixo)
    f = r.get("fila")
    if f:
        ok.append(
            f"A próxima folha da sua fila é a {f['folha_revisao']} ({f['atribuidas']} cargas), já atribuída a você."
        )
    for x in r.get("recusadas") or []:
        folha = f" da {x['folha_revisao']}" if x.get("folha_revisao") else ""
        motivo = x["motivo"][:1].upper() + x["motivo"][1:]
        avisos.append(f"Carga {x['id']}{folha}: {motivo}. A mudança foi desfeita.")
    return ok, avisos


def uma(ctx, id_carga: int) -> Optional[Dict]:
    """A carga, do workspace (para o pular da barra)."""
    ctx.exigir_pronto()
    with ctx.leitura() as ex:
        return lc.uma(ex, id_carga)


def focar(ctx, id_carga: int) -> Dict:
    ctx.exigir_pronto()
    with ctx.leitura() as ex:
        carga = lc.uma(ex, id_carga)
        if not carga:
            raise ErroApi(404, "carga não encontrada")
        progresso = lc.progresso(ex, carga["id_lote_etapa"])
    carga.pop("responsavel", None)
    ctx.qgis("focar_carga", carga, progresso)
    return {"carga": carga, "progresso": progresso}


def proxima(ctx, referencia: Optional[int] = None, excluir=None, id_lote: Optional[int] = None) -> Dict:
    """Próxima carga pendente; no QGIS, vira a carga atual. Sem pendentes: carga nula."""
    ctx.exigir_pronto()
    with ctx.leitura() as ex:
        carga = lc.proxima(ex, referencia, excluir, id_lote)
        progresso = lc.progresso(ex, carga["id_lote_etapa"]) if carga else None
    if carga:
        _no_qgis(ctx, "focar_carga", carga, progresso)
    return {"carga": carga, "progresso": progresso}


def preparar(ctx, uf: str, ids_lote_etapa) -> Dict:
    """Depois de abrir passagens (folha nova, próxima etapa): gera as cargas pela grade e inicia as etapas sem
    atividade, numa transação à parte, para a folha aberta não depender disso (D-109). Uma falha volta em `erro`."""
    ids = [i for i in ids_lote_etapa if i]
    if not ids:
        return {"geradas": [], "iniciadas": [], "avisos": []}
    try:
        with ctx.tx() as ex:
            r = dc.preparar(ex, uf, ids)
    except ErroDados as e:
        return {"geradas": [], "iniciadas": [], "avisos": [], "erro": e.mensagem}
    if r["geradas"]:
        ctx.publicar("carga", {"geradas": [g["id_lote_etapa"] for g in r["geradas"]]})
        _no_qgis(ctx, "cargas_geradas")
    if r["geradas"] or r["iniciadas"]:
        ctx.publicar("lote", {"preparadas": ids})
    return r


def registrar(r, ctx) -> None:
    @r.rota("POST", "/api/lotes/preparar", exige=("supervisor",))
    def _preparar(req):
        # Para a folha que ficou sem cargas (a geração falhou, ou a etapa ganhou atividade depois de aberta).
        from .lotes import uf_de

        return 200, preparar(ctx, uf_de(ctx.eu()), campo(req, "lote_etapas", lambda v: [int(x) for x in v]))

    @r.rota("GET", "/api/equipe", exige=("supervisor",))
    def _equipe(req):
        from .lotes import uf_de

        projeto = req.query.get("projeto")
        with ctx.tx() as ex:
            return 200, {"itens": dc.equipe(ex, uf_de(ctx.eu()), inteiro(projeto, "projeto") if projeto else None)}

    @r.rota("POST", "/api/cargas/descartar", exige=("supervisor",))
    def _descartar(req):
        from .lotes import uf_de

        with ctx.tx() as ex:
            res = dc.descartar(ex, uf_de(ctx.eu()), campo(req, "ids", lambda v: [int(x) for x in v]))
        if res["tiradas"]:
            ctx.publicar("carga", {"descartadas": res["tiradas"]})
            ctx.publicar("lote", {"descartadas": res["lote_etapas"]})
            _no_qgis(ctx, "cargas_geradas")
        return 200, res

    @r.rota("POST", "/api/qgis/selecao_cargas", exige=("supervisor",))
    def _selecao(req):
        # Cargas selecionadas no QGIS (em qualquer camada do grupo Feixe que tenha as cargas).
        return 200, ctx.qgis("selecao_cargas")

    @r.rota("GET", "/api/cargas", exige=EXECUTORES)
    def _lista(req):
        le = req.query.get("lote_etapa")
        situacao = req.query.get("situacao")
        concluido = {"pendente": False, "concluida": True}.get(situacao or "")
        if situacao and concluido is None:
            raise ErroApi(400, "situacao deve ser pendente ou concluida")
        id_le = inteiro(le, "lote_etapa") if le else None
        if ctx.preparando():
            return 200, {"itens": [], "preparando": True}
        with ctx.leitura() as ex:
            return 200, {"itens": lc.minhas(ex, id_le, concluido)}

    @r.rota("GET", "/api/cargas/resumo", exige=EXECUTORES)
    def _resumo(req):
        if ctx.preparando():
            vazio = {"concluidas": 0, "desde": None, "pendentes": 0, "folhas_pendentes": 0, "passagens": []}
            return 200, {**vazio, "preparando": True}
        with ctx.leitura() as ex:
            return 200, lc.resumo(ex)

    @r.rota("POST", "/api/cargas/proxima", exige=EXECUTORES)
    def _proxima(req):
        return 200, proxima(
            ctx, campo(req, "referencia", int, padrao=None), id_lote=campo(req, "id_lote", int, padrao=None)
        )

    @r.rota("POST", "/api/cargas/{id}/desfazer", exige=EXECUTORES)
    def _desfazer(req):
        return 200, desfazer(ctx, inteiro(req.params["id"]))

    @r.rota("POST", "/api/cargas/{id}/zoom", exige=EXECUTORES)
    def _zoom(req):
        return 200, focar(ctx, inteiro(req.params["id"]))
