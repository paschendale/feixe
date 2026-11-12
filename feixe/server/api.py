"""Rotas da API JSON do plugin. Cada rota recebe (req) e devolve (status, objeto).

As rotas não importam o QGIS: tudo que precisa dele chega pelo `Contexto`, injetado pelo plugin.
Isso mantém o servidor testável fora do QGIS.
"""

from __future__ import annotations

import re
from contextlib import contextmanager
from typing import Any, Callable, ContextManager, Dict, Iterable, List, Optional, Tuple

from ..core import papeis
from ..core.dados import ErroDados, Executor


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


_FALTA = object()


def campo(req: Requisicao, nome: str, conv: Callable[[Any], Any] = None, padrao: Any = _FALTA) -> Any:
    """Campo do corpo JSON, convertido; ausente sem padrão ou inválido dá 400 com o nome do campo."""
    corpo = req.corpo if isinstance(req.corpo, dict) else {}
    if nome not in corpo or corpo[nome] is None:
        if padrao is _FALTA:
            raise ErroApi(400, f"campo obrigatório: {nome}")
        return padrao
    if conv is None:
        return corpo[nome]
    try:
        return conv(corpo[nome])
    except (TypeError, ValueError):
        raise ErroApi(400, f"campo inválido: {nome}") from None


def inteiro(valor: Any, nome: str = "id") -> int:
    try:
        return int(valor)
    except (TypeError, ValueError):
        raise ErroApi(400, f"{nome} inválido") from None


Rota = Tuple[str, "re.Pattern[str]", Callable[[Requisicao], Tuple[int, Any]]]


# Códigos do PostgreSQL que são recusa de regra, não falha: a mensagem do banco vai para o usuário.
_PG_RECUSA = {
    "P0001": 409,  # RAISE EXCEPTION das regras (006)
    "23505": 409,  # violação de unicidade
    "23503": 409,  # violação de chave estrangeira
    "23514": 422,  # violação de CHECK
    "42501": 403,  # sem GRANT
}


def _erro_pg(e: Exception) -> Optional[Tuple[int, str]]:
    codigo = getattr(e, "pgcode", None)
    if codigo not in _PG_RECUSA:
        return None
    diag = getattr(e, "diag", None)
    mensagem = getattr(diag, "message_primary", None) or str(e).strip().splitlines()[0]
    return _PG_RECUSA[codigo], mensagem


class Roteador:
    def __init__(self, papeis_atuais: Callable[[], Iterable[str]] = None):
        self._rotas: List[Rota] = []
        self._papeis_atuais = papeis_atuais

    def rota(self, metodo: str, padrao: str, exige: Optional[Iterable[str]] = None):
        """Decorador: @r.rota("GET", "/api/folhas/{id}/zoom"). `exige`: papéis aceitos (qualquer um deles)."""
        regex = re.compile("^" + re.sub(r"{(\w+)}", r"(?P<\1>[^/]+)", padrao) + "$")
        aceitos = tuple(exige or ())

        def registrar(fn):
            self._rotas.append((metodo.upper(), regex, self._guardar(fn, aceitos) if aceitos else fn))
            return fn

        return registrar

    def _guardar(self, fn, aceitos):
        """Autorização pelo papel do SGBC (D-57): o banco não barra, então quem barra é o plugin."""

        def guardada(req):
            atuais = set(self._papeis_atuais() if self._papeis_atuais else ())
            if not atuais.intersection(aceitos):
                nomes = " ou ".join(papeis.ROTULO.get(p, p).lower() for p in aceitos)
                raise ErroApi(403, f"esta ação é só para {nomes}")
            return fn(req)

        return guardada

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
            except ErroDados as e:
                return e.status, {"erro": e.mensagem}
            except Exception as e:  # noqa: BLE001
                recusa = _erro_pg(e)
                if recusa:
                    return recusa[0], {"erro": recusa[1]}
                return 500, {"erro": f"{e.__class__.__name__}: {e}"}
        if permitido:
            return 405, {"erro": "método não permitido"}
        return 404, {"erro": "rota não encontrada"}


class Contexto:
    """O que as rotas podem pedir ao plugin. Cada atributo é uma função injetada; `None` = indisponível.

    - `consultar(sql, params)`: leitura avulsa, conexão própria.
    - `transacao()`: gerenciador de contexto que entrega um `Executor` numa transação (commit ao sair, rollback em
      erro). É por ele que as funções de `core.dados` leem e escrevem.
    - `publicar(evento, dados)`: evento SSE para o front.
    - `qgis(nome, *args)`: ações que tocam o QGIS, já despachadas para a thread principal pelo plugin.
    """

    def __init__(
        self,
        status: Callable[[], Dict] = None,
        consultar: Callable[[str, Optional[tuple]], List[Dict]] = None,
        zoom_para: Callable[[float, float, float, float, int], None] = None,
        sincronizar: Callable[[], Dict] = None,
        transacao: Callable[[], ContextManager[Executor]] = None,
        publicar: Callable[[str, Dict], None] = None,
        qgis: Callable[..., Any] = None,
    ):
        self.status = status or (lambda: {"online": False})
        self.consultar = consultar
        self.zoom_para = zoom_para
        self.sincronizar = sincronizar
        self._transacao = transacao
        self.publicar = publicar or (lambda evento, dados: None)
        self._qgis = qgis
        self._eu: Optional[Dict] = None

    @contextmanager
    def tx(self):
        if self._transacao is None:
            raise ErroApi(503, "banco indisponível")
        with self._transacao() as ex:
            yield ex

    def qgis(self, nome: str, *args):
        if self._qgis is None:
            raise ErroApi(503, "QGIS indisponível")
        return self._qgis(nome, *args)

    def eu(self) -> Dict:
        """Identidade e papéis da conta conectada, guardados até `esquecer_eu` (troca de credencial)."""
        if self._eu is None:
            if self.consultar is None:
                raise ErroApi(503, "banco indisponível")
            self._eu = papeis.carregar(self.consultar)
        return self._eu

    def esquecer_eu(self) -> None:
        self._eu = None

    def papeis_atuais(self) -> List[str]:
        return list(self.eu().get("papeis") or [])


def criar_roteador(ctx: Contexto) -> Roteador:
    r = Roteador(papeis_atuais=ctx.papeis_atuais)

    @r.rota("GET", "/api/status")
    def _status(req):
        return 200, ctx.status()

    @r.rota("GET", "/api/eu")
    def _eu(req):
        # Quem está conectado e com que papel: só pelo SGBC (mapcartctrl) e por usuario_feixe, nunca por roles.
        return 200, ctx.eu()

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

    from . import rotas

    rotas.registrar(r, ctx)
    return r
