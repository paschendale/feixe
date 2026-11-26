"""CQ da execução sobre o workspace (D3a, D-111): o avaliador avalia as amostras e registra ocorrências; o APM autor
da carga apontada dá ciência. Online ou offline, como as cargas: linha e outbox juntas, e o push leva à CCAR.

Regras, as mesmas que o push confere de novo na CCAR (D-122):

- **Avaliar**: só a amostra de uma carga de CQ minha, com a passagem de CQ aberta. Status 1 (conforme) ou 0 (não
  conforme) e observação. Trocar o status ou a observação vale enquanto a passagem estiver aberta (a regra do banco:
  o gatilho `t10_avaliacao` aceita a troca e regrava `avaliado_em`); não há "desfazer" para pendente, porque a carga
  de CQ já está concluída e a troca de status cobre o engano. `avaliado_em` vai explícito (a hora real offline). Como
  o gatilho `t20_derivar`, a carga de CQ conclui quando a amostra tem avaliação, aqui mesmo no workspace (sem item na
  outbox: na CCAR quem conclui é o gatilho), para a tela mostrar na hora; a fila anda como no concluir, e a resposta
  já aponta a próxima amostra (D-136).
- **Ocorrência**: ponto em EPSG:4674 numa carga de CQ minha, com a passagem aberta; elemento = o da atividade da
  carga; `id_lote` e `id_lote_etapa` da carga; uuid do plugin. A carga avaliada (de quem errou) o banco deriva no
  INSERT (`t05_passagem`), porque o avaliador não tem as cargas dos outros no workspace. Editar (anotação, ponto) e
  apagar só a própria e com a passagem de CQ aberta.
- **Ciente**: só o autor da carga apontada (`id_carga_avaliada` é uma carga minha); grava `ciente_em`/`ciente_por` com
  a hora da ação. Dar ciência de novo não faz nada. Vale também com a passagem de CQ encerrada (é feedback).
- **Visibilidade** (D-66): vejo as ocorrências que registrei, as das minhas cargas de CQ, as que apontam uma carga
  minha e, só se tenho carga numa passagem aberta com `expor_ocorrencias`, as não tratadas da folha (lista de
  correção). Na correção de inspeção (D5), quem tem carga na passagem de correção aberta vê todas as da folha, de
  todas as revisões, tratadas ou não: ali não há revisão às cegas, é a varredura final (D-21). O pull já traz só isso
  (`sync.pull.escopos`); a consulta repete a regra.
- **Tratar** (D5): só quem tem carga na passagem de correção aberta da folha; marcar e desmarcar valem enquanto ela
  estiver aberta; `tratado_em`/`tratado_por` vão explícitos (a hora real offline). Como o gatilho `t20_correcao`, a
  carga da folha (`carga_da_folha`) conclui no workspace quando a última é tratada (sem item na outbox) e volta a
  pendente se alguma for desmarcada; a fila anda como no concluir, e a resposta aponta a próxima ocorrência.
"""

from __future__ import annotations

import datetime as dt
import math
import struct
from typing import Any, Dict, List, Optional

from .. import ErroDados
from . import ABERTAS, SQL_ABERTAS, carga_da_folha, converter, rotulo
from . import cargas as lc

STATUS = {1: "conforme", 0: "não conforme"}
_NADA = object()

_AMOSTRA = (
    "a.id, a.uuid, a.id_cq_plano, a.id_carga_trabalho, a.status, a.observacao, a.avaliado_em, a.avaliado_por, "
    f"c.id_lote_etapa, le.id_lote, {rotulo()} AS folha_revisao, t.nome AS tema, fe.nome AS etapa, "
    "at.nome AS atividade, at.elemento, c.geocodigo, c.concluido, le.situacao AS situacao_etapa, "
    "c.responsavel, c.xmin, c.ymin, c.xmax, c.ymax, "
    # Nomes sem colisão de maiúsculas: o sqlite3.Row acha coluna sem diferenciar N de n.
    "p.nivel_inspecao AS p_nivel, p.letra_codigo AS p_letra, p.tamanho_lote_n AS p_lote, "
    "p.tamanho_amostra_n AS p_amostra, p.numero_aceitacao_ac AS p_ac, p.lqa AS p_lqa, p.resultado AS p_resultado, "
    "(SELECT count(*) FROM cq_inspecao i WHERE i.id_carga_trabalho = c.id) AS ocorrencias "
    "FROM cq_amostra a JOIN carga_trabalho c ON c.id = a.id_carga_trabalho "
    "JOIN lote_etapa le ON le.id = c.id_lote_etapa JOIN lote l ON l.id = le.id_lote "
    "LEFT JOIN cq_plano p ON p.id = a.id_cq_plano "
    "LEFT JOIN tema t ON t.id = l.id_tema LEFT JOIN fluxo_etapa fe ON fe.id = le.id_fluxo_etapa "
    "LEFT JOIN atividade at ON at.id = c.id_atividade "
)


def _amostra(linha: Optional[Dict]) -> Optional[Dict]:
    if linha is None:
        return None
    converter(linha, datas=("avaliado_em",), bools=("concluido",))
    linha["plano"] = {
        "id": linha["id_cq_plano"], "nivel": linha.pop("p_nivel"), "letra": linha.pop("p_letra"),
        "N": linha.pop("p_lote"), "n": linha.pop("p_amostra"), "ac": linha.pop("p_ac"), "lqa": linha.pop("p_lqa"),
        "resultado": linha.pop("p_resultado"),
    }  # fmt: skip
    linha["avaliada"] = linha["status"] is not None
    return linha


def amostras(ex, id_lote_etapa: Optional[int] = None, pendente: Optional[bool] = None) -> List[Dict]:
    """Minhas amostras (as das minhas cargas de CQ), com o plano, o elemento e a folha."""
    sql = f"SELECT {_AMOSTRA}WHERE c.responsavel = ?"
    params: list = [ex.usuario]
    if id_lote_etapa is not None:
        sql += " AND c.id_lote_etapa = ?"
        params.append(id_lote_etapa)
    if pendente is not None:
        sql += " AND a.status IS NULL" if pendente else " AND a.status IS NOT NULL"
    sql += " ORDER BY folha_revisao, a.status IS NOT NULL, at.elemento, c.geocodigo, c.id"
    return [_amostra(r) for r in ex.todos(sql, tuple(params))]


def amostra(ex, id_amostra: int) -> Optional[Dict]:
    return _amostra(ex.um(f"SELECT {_AMOSTRA}WHERE a.id = ?", (id_amostra,)))


def amostra_da_carga(ex, id_carga: int) -> Optional[Dict]:
    return _amostra(ex.um(f"SELECT {_AMOSTRA}WHERE c.id = ?", (id_carga,)))


def proxima(ex, referencia: Optional[int] = None) -> Optional[Dict]:
    """Próxima amostra: a próxima carga de CQ pendente minha, pela mesma ordem de `cargas.proxima` (mesma passagem
    primeiro, depois a mais perto). As cargas de produção pendentes ficam de fora. Nenhuma: None."""
    producao = [
        r["id"]
        for r in ex.todos(
            "SELECT id FROM carga_trabalho WHERE responsavel = ? AND NOT concluido AND id_cq_plano IS NULL",
            (ex.usuario,),
        )
    ]
    carga = lc.proxima(ex, referencia, producao)
    if carga is None:
        return None
    return {"carga": carga, "amostra": amostra_da_carga(ex, carga["id"])}


def _amostra_para_mudar(ex, id_amostra: int) -> Dict:
    linha = ex.um(
        "SELECT a.uuid, a.status, a.observacao, c.id AS id_carga, c.uuid AS uuid_carga, c.responsavel, c.concluido, "
        "c.id_lote_etapa, le.situacao FROM cq_amostra a JOIN carga_trabalho c ON c.id = a.id_carga_trabalho "
        "JOIN lote_etapa le ON le.id = c.id_lote_etapa WHERE a.id = ?",
        (id_amostra,),
    )
    if not linha:
        raise ErroDados("amostra não encontrada", 404)
    if linha["responsavel"] != ex.usuario:
        raise ErroDados("esta amostra não é de uma carga sua", 403)
    if linha["situacao"] not in ABERTAS:
        raise ErroDados("a etapa de CQ deste lote já foi encerrada pelo supervisor")
    return converter(linha, bools=("concluido",))


def _texto(v: Any) -> Optional[str]:
    if v is None:
        return None
    v = str(v).strip()
    return v or None


def avaliar(ex, id_amostra: int, status: int, observacao: Any = _NADA) -> Dict:
    """Avalia (ou troca a avaliação de) uma amostra minha. A carga de CQ conclui na hora, como pelo gatilho do banco;
    se era a minha última pendente, a fila anda (`fila`). Volta a amostra, a carga, o progresso e a próxima amostra."""
    from . import filas

    if status not in STATUS:
        raise ErroDados("status deve ser 1 (conforme) ou 0 (não conforme)", 400)
    linha = _amostra_para_mudar(ex, id_amostra)
    campos: Dict[str, Any] = {}
    if linha["status"] != status:
        campos.update(status=status, avaliado_em=ex.agora, avaliado_por=ex.usuario)
    if observacao is not _NADA and _texto(observacao) != linha["observacao"]:
        campos["observacao"] = _texto(observacao)
    if campos:
        ex.atualizar("cq_amostra", linha["uuid"], campos)
    fila = None
    if not linha["concluido"]:
        # O efeito do `t20_derivar` (e do `f_amostra_derivar_um`, que grava a hora da avaliação), sem outbox.
        ex.executar(
            "UPDATE carga_trabalho SET concluido = 1, concluido_em = ? WHERE uuid = ?",
            (ex.agora_iso, linha["uuid_carga"]),
        )
        fila = filas.puxar(ex, ex.usuario)
    return {
        "amostra": amostra(ex, id_amostra),
        "carga": lc.uma(ex, linha["id_carga"]),
        "progresso": lc.progresso(ex, linha["id_lote_etapa"]),
        "fila": fila,
        "proxima": proxima(ex, linha["id_carga"]),
    }


# --- ocorrências --------------------------------------------------------------------------------------------------


_N_VISIVEL = 5  # quantos `?` (a pessoa) a regra de visibilidade leva


def _visivel(i: str = "i") -> str:
    """A regra do D-66 (e a da correção de inspeção, D5) sobre o workspace, com um `?` (a pessoa) em cada uma das
    cinco partes."""
    return (
        f"({i}.responsavel = ? "
        f"OR {i}.id_carga_trabalho IN (SELECT id FROM carga_trabalho WHERE responsavel = ? "
        "AND id_cq_plano IS NOT NULL) "
        f"OR {i}.id_carga_avaliada IN (SELECT id FROM carga_trabalho WHERE responsavel = ?) "
        f"OR (NOT {i}.tratado AND {i}.id_lote IN (SELECT le2.id_lote FROM lote_etapa le2 WHERE le2.expor_ocorrencias "
        f"AND le2.situacao IN {SQL_ABERTAS} AND EXISTS (SELECT 1 FROM carga_trabalho c2 "
        "WHERE c2.id_lote_etapa = le2.id AND c2.responsavel = ?))) "
        f"OR {i}.id_lote IN ({_LOTES_EM_CORRECAO}))"
    )


# Lotes em que tenho carga numa passagem de correção de inspeção aberta (D5), com um `?` (a pessoa).
_LOTES_EM_CORRECAO = (
    "SELECT le3.id_lote FROM lote_etapa le3 JOIN fluxo_etapa fe3 ON fe3.id = le3.id_fluxo_etapa "
    f"WHERE fe3.fase = 'correcao_inspecao' AND le3.situacao IN {SQL_ABERTAS} AND EXISTS (SELECT 1 FROM carga_trabalho "
    "c3 WHERE c3.id_lote_etapa = le3.id AND c3.responsavel = ?)"
)


def em_correcao(ex) -> Dict[int, Dict]:
    """id_lote -> a passagem de correção de inspeção aberta em que tenho carga (id, rótulo, tema, etapa, situação)."""
    linhas = ex.todos(
        f"SELECT le.id_lote, le.id AS id_lote_etapa, {rotulo()} AS folha_revisao, t.nome AS tema, fe.nome AS etapa, "
        "le.situacao FROM lote_etapa le JOIN lote l ON l.id = le.id_lote "
        "JOIN fluxo_etapa fe ON fe.id = le.id_fluxo_etapa LEFT JOIN tema t ON t.id = l.id_tema "
        f"WHERE fe.fase = 'correcao_inspecao' AND le.situacao IN {SQL_ABERTAS} AND EXISTS (SELECT 1 FROM "
        "carga_trabalho c WHERE c.id_lote_etapa = le.id AND c.responsavel = ?) ORDER BY folha_revisao",
        (ex.usuario,),
    )
    return {r["id_lote"]: r for r in linhas}


_OCORRENCIA = (
    "i.id, i.uuid, i.id_lote, i.id_lote_etapa, i.id_carga_trabalho, i.id_carga_avaliada, i.elemento, i.anotacao, "
    "i.responsavel, i.tratado, i.tratado_em, i.tratado_por, i.ciente_em, i.ciente_por, i.criado_em, "
    "i.cx AS x, i.cy AS y, i.sujo, le.revisao, "
    f"(CASE WHEN le.id IS NULL THEN l.nome ELSE {rotulo()} END) AS folha_revisao, fe.nome AS etapa, "
    "le.situacao AS situacao_etapa, ca.responsavel AS autor, cq.responsavel AS responsavel_carga_cq "
    "FROM cq_inspecao i JOIN lote l ON l.id = i.id_lote "
    "LEFT JOIN lote_etapa le ON le.id = i.id_lote_etapa LEFT JOIN fluxo_etapa fe ON fe.id = le.id_fluxo_etapa "
    "LEFT JOIN carga_trabalho ca ON ca.id = i.id_carga_avaliada "
    "LEFT JOIN carga_trabalho cq ON cq.id = i.id_carga_trabalho "
)


def _ocorrencia(ex, linha: Optional[Dict], correcao: Optional[Dict[int, Dict]] = None) -> Optional[Dict]:
    if linha is None:
        return None
    if correcao is None:
        correcao = em_correcao(ex)
    converter(linha, datas=("tratado_em", "ciente_em", "criado_em"), bools=("tratado",))
    eu = ex.usuario
    minha = linha["responsavel"] == eu
    autor = linha.pop("autor") == eu
    carga_cq = linha.pop("responsavel_carga_cq") == eu
    linha["minha"] = minha
    linha["sou_autor"] = autor
    linha["enviada"] = linha["id"] is not None and not linha.pop("sujo")
    linha["pode_editar"] = minha and linha["situacao_etapa"] in ABERTAS
    linha["pode_ciente"] = autor and linha["ciente_em"] is None
    # Correção de inspeção (D5): estou com a folha na passagem de correção aberta, então marco e desmarco.
    linha["pode_tratar"] = linha["id_lote"] in correcao
    # Por que a pessoa vê a ocorrência: registrou (ou é da sua amostra), é da carga dela, ou é lista de correção.
    linha["motivo"] = "registrada" if minha or carga_cq else ("minha_carga" if autor else "correcao")
    return linha


def ocorrencias(ex, id_lote: Optional[int] = None, id_lote_etapa: Optional[int] = None) -> List[Dict]:
    """As ocorrências que eu posso ver (D-66), da folha (`id_lote`) ou da passagem de CQ (`id_lote_etapa`)."""
    sql = f"SELECT {_OCORRENCIA}WHERE {_visivel()}"
    params: list = [ex.usuario] * _N_VISIVEL
    if id_lote is not None:
        sql += " AND i.id_lote = ?"
        params.append(id_lote)
    if id_lote_etapa is not None:
        sql += " AND i.id_lote_etapa = ?"
        params.append(id_lote_etapa)
    sql += " ORDER BY folha_revisao, i.elemento, i.criado_em, i.fid"
    correcao = em_correcao(ex)
    return [_ocorrencia(ex, r, correcao) for r in ex.todos(sql, tuple(params))]


def ocorrencia(ex, uuid: str) -> Optional[Dict]:
    """Uma ocorrência visível, pelo uuid (a criada offline ainda não tem id da CCAR)."""
    return _ocorrencia(
        ex, ex.um(f"SELECT {_OCORRENCIA}WHERE i.uuid = ? AND {_visivel()}", (uuid, *([ex.usuario] * _N_VISIVEL)))
    )


def _ponto(x: Any, y: Any) -> bytes:
    """WKB de um ponto em EPSG:4674 (longitude, latitude). Sem o pacote `sync` (D-115): é só o formato."""
    try:
        x, y = float(x), float(y)
    except (TypeError, ValueError):
        raise ErroDados("ponto inválido: x e y são longitude e latitude em graus (SIRGAS 2000)", 400) from None
    if not (math.isfinite(x) and math.isfinite(y) and -180 <= x <= 180 and -90 <= y <= 90):
        raise ErroDados("ponto inválido: x e y são longitude e latitude em graus (SIRGAS 2000)", 400)
    return struct.pack("<BIdd", 1, 1, x, y)


def registrar(ex, x: Any, y: Any, id_carga: int, anotacao: Any = None) -> Dict:
    """Ocorrência no ponto, numa carga de CQ minha com a passagem aberta. Volta a ocorrência e a amostra da carga
    (a tela sugere marcar não conforme; a decisão é do avaliador)."""
    geom = _ponto(x, y)
    carga = ex.um(
        "SELECT c.id, c.responsavel, c.id_cq_plano, c.id_lote_etapa, le.id_lote, le.situacao, at.elemento "
        "FROM carga_trabalho c JOIN lote_etapa le ON le.id = c.id_lote_etapa "
        "LEFT JOIN atividade at ON at.id = c.id_atividade WHERE c.id = ?",
        (id_carga,),
    )
    if not carga:
        raise ErroDados("carga não encontrada", 404)
    if carga["id_cq_plano"] is None:
        raise ErroDados("ocorrência só se registra numa carga de CQ (uma amostra)", 400)
    if carga["responsavel"] != ex.usuario:
        raise ErroDados("esta carga de CQ não está atribuída a você", 403)
    if carga["situacao"] not in ABERTAS:
        raise ErroDados("a etapa de CQ deste lote já foi encerrada pelo supervisor")
    uuid = ex.inserir(
        "cq_inspecao",
        {"id_lote": carga["id_lote"], "id_carga_trabalho": carga["id"], "id_lote_etapa": carga["id_lote_etapa"],
         "elemento": carga["elemento"], "geom": geom, "anotacao": _texto(anotacao), "responsavel": ex.usuario,
         "tratado": False},
    )  # fmt: skip
    return {"ocorrencia": ocorrencia(ex, uuid), "amostra": amostra_da_carga(ex, carga["id"])}


def _minha_para_mudar(ex, uuid: str) -> Dict:
    linha = ex.um(
        "SELECT i.uuid, i.id, i.responsavel, i.anotacao, i.elemento, i.id_carga_trabalho, le.situacao "
        "FROM cq_inspecao i LEFT JOIN lote_etapa le ON le.id = i.id_lote_etapa WHERE i.uuid = ?",
        (uuid,),
    )
    if not linha:
        raise ErroDados("ocorrência não encontrada", 404)
    if linha["responsavel"] != ex.usuario:
        raise ErroDados("esta ocorrência foi registrada por outra pessoa", 403)
    if linha["situacao"] not in ABERTAS:
        raise ErroDados("a etapa de CQ deste lote já foi encerrada: a ocorrência não muda mais")
    return linha


def editar(ex, uuid: str, anotacao: Any = _NADA, x: Any = None, y: Any = None) -> Dict:
    """Muda a anotação e/ou o ponto de uma ocorrência minha, com a passagem de CQ aberta. A carga avaliada de um
    ponto novo o banco deriva de novo no push."""
    linha = _minha_para_mudar(ex, uuid)
    campos: Dict[str, Any] = {}
    if anotacao is not _NADA and _texto(anotacao) != linha["anotacao"]:
        campos["anotacao"] = _texto(anotacao)
    if x is not None or y is not None:
        campos["geom"] = _ponto(x, y)
    if "geom" in campos:
        atual = ex.um("SELECT cx, cy FROM cq_inspecao WHERE uuid = ?", (uuid,))
        if atual and (atual["cx"], atual["cy"]) == (float(x), float(y)):
            campos.pop("geom")
    if campos:
        ex.atualizar("cq_inspecao", uuid, campos)
    return {"ocorrencia": ocorrencia(ex, uuid)}


def apagar(ex, uuid: str) -> Dict:
    """Apaga uma ocorrência minha, com a passagem de CQ aberta."""
    linha = _minha_para_mudar(ex, uuid)
    ex.apagar("cq_inspecao", uuid, {"anotacao": linha["anotacao"], "elemento": linha["elemento"]})
    return {"apagada": uuid, "id": linha["id"], "id_carga_trabalho": linha["id_carga_trabalho"]}


def ciente(ex, uuid: str) -> Dict:
    """Ciência do APM autor da carga apontada pela ocorrência (D-66). De novo, não faz nada."""
    linha = ex.um(
        "SELECT i.uuid, i.ciente_em, ca.responsavel AS autor FROM cq_inspecao i "
        "LEFT JOIN carga_trabalho ca ON ca.id = i.id_carga_avaliada WHERE i.uuid = ?",
        (uuid,),
    )
    if not linha:
        raise ErroDados("ocorrência não encontrada", 404)
    if linha["autor"] != ex.usuario:
        raise ErroDados("só quem fez a carga apontada pela ocorrência dá ciência", 403)
    if linha["ciente_em"] is None:
        ex.atualizar("cq_inspecao", uuid, {"ciente_em": ex.agora, "ciente_por": ex.usuario})
    return {"ocorrencia": ocorrencia(ex, uuid)}


# --- leituras do painel (D3d) ---------------------------------------------------------------------------------------


def resumo(ex) -> List[Dict]:
    """Minhas amostras por passagem de CQ e atividade (elemento): as fichas e o andamento da Execução › CQ. `total` é o
    tamanho do plano (n, ou N na inspeção completa); `outras` = as do plano com outro avaliador (o workspace só tem as
    minhas). Abertas com pendentes primeiro, depois as abertas terminadas e, no fim, as encerradas."""
    linhas = ex.todos(
        f"SELECT c.id_lote_etapa, le.id_lote, {rotulo()} AS folha_revisao, t.nome AS tema, fe.nome AS etapa, "
        "le.situacao, c.id_atividade, at.nome AS atividade, at.elemento, p.id AS id_cq_plano, "
        "p.nivel_inspecao AS p_nivel, p.letra_codigo AS p_letra, p.tamanho_lote_n AS p_lote, "
        "p.tamanho_amostra_n AS p_amostra, p.numero_aceitacao_ac AS p_ac, p.lqa AS p_lqa, "
        "count(*) AS minhas, sum(CASE WHEN a.status IS NOT NULL THEN 1 ELSE 0 END) AS avaliadas, "
        "sum(CASE WHEN a.status = 0 THEN 1 ELSE 0 END) AS nao_conformes, max(a.avaliado_em) AS ultima "
        "FROM cq_amostra a JOIN carga_trabalho c ON c.id = a.id_carga_trabalho "
        "JOIN lote_etapa le ON le.id = c.id_lote_etapa JOIN lote l ON l.id = le.id_lote "
        "LEFT JOIN cq_plano p ON p.id = a.id_cq_plano LEFT JOIN tema t ON t.id = l.id_tema "
        "LEFT JOIN fluxo_etapa fe ON fe.id = le.id_fluxo_etapa LEFT JOIN atividade at ON at.id = c.id_atividade "
        "WHERE c.responsavel = ? GROUP BY c.id_lote_etapa, c.id_atividade, p.id",
        (ex.usuario,),
    )
    registradas = {
        (r["id_lote_etapa"], r["elemento"]): r["n"]
        for r in ex.todos(
            "SELECT id_lote_etapa, elemento, count(*) AS n FROM cq_inspecao WHERE responsavel = ? GROUP BY 1, 2",
            (ex.usuario,),
        )
    }
    saida = []
    for r in linhas:
        converter(r, datas=("ultima",))
        n, N = r.pop("p_amostra"), r.pop("p_lote")
        r["plano"] = {
            "id": r["id_cq_plano"], "nivel": r.pop("p_nivel"), "letra": r.pop("p_letra"), "N": N, "n": n,
            "ac": r.pop("p_ac"), "lqa": r.pop("p_lqa"),
        }  # fmt: skip
        total = min(n, N) if n is not None and N is not None else r["minhas"]
        r["total"] = max(total, r["minhas"])
        r["outras"] = r["total"] - r["minhas"]
        r["pendentes"] = r["minhas"] - r["avaliadas"]
        r["aberta"] = r["situacao"] in ABERTAS
        r["ocorrencias"] = registradas.get((r["id_lote_etapa"], r["elemento"]), 0)
        saida.append(r)
    saida.sort(
        key=lambda r: (not r["aberta"], r["aberta"] and r["pendentes"] == 0, r["folha_revisao"] or "",
                       r["elemento"] or r["atividade"] or "")
    )  # fmt: skip
    return saida


def para_ciencia(ex, dias: int = 30) -> Dict:
    """As ocorrências que apontam uma carga minha (D-66): as ainda sem ciência e as que já dei nos últimos `dias`,
    com o geocódigo da minha carga apontada. A lista de correção (revisão com `expor_ocorrencias`) não entra: ali não
    sou o autor, e o que vejo vem pela regra de visibilidade de sempre."""
    itens = [o for o in ocorrencias(ex) if o["sou_autor"] and not o["minha"]]
    ids = sorted({o["id_carga_avaliada"] for o in itens if o["id_carga_avaliada"] is not None})
    geo: Dict[int, Optional[str]] = {}
    if ids:
        marcas = ", ".join("?" * len(ids))
        geo = {
            r["id"]: r["geocodigo"]
            for r in ex.todos(f"SELECT id, geocodigo FROM carga_trabalho WHERE id IN ({marcas})", tuple(ids))
        }
    for o in itens:
        o["geocodigo_avaliada"] = geo.get(o["id_carga_avaliada"])
    limite = ex.agora - dt.timedelta(days=dias)
    pendentes = sorted((o for o in itens if o["ciente_em"] is None), key=lambda o: (o["folha_revisao"] or "",
                       o["criado_em"] or limite))  # fmt: skip
    cientes = sorted(
        (o for o in itens if o["ciente_em"] is not None and o["ciente_em"] >= limite),
        key=lambda o: o["ciente_em"],
        reverse=True,
    )
    return {"pendentes": pendentes, "cientes": cientes[:50], "dias": dias}


def proxima_amostra(ex, id_lote: Optional[int] = None, referencia: Optional[int] = None) -> Optional[Dict]:
    """A próxima amostra pendente minha, só entre as cargas de CQ (nesta folha, se `id_lote`): o "Continuar no QGIS"
    da Execução › CQ. Nenhuma: None."""
    producao = [
        r["id"]
        for r in ex.todos(
            "SELECT id FROM carga_trabalho WHERE responsavel = ? AND NOT concluido AND id_cq_plano IS NULL",
            (ex.usuario,),
        )
    ]
    carga = lc.proxima(ex, referencia, producao, id_lote)
    if carga is None:
        return None
    return {"carga": carga, "amostra": amostra_da_carga(ex, carga["id"])}


def ciente_da_folha(ex, id_lote: int) -> Dict:
    """Ciente em todas desta folha: dá ciência, numa transação, de todas as ocorrências da folha que apontam carga
    minha e ainda não têm ciência. Volta quantas."""
    feitas = [o["uuid"] for o in ocorrencias(ex, id_lote) if o["pode_ciente"]]
    for u in feitas:
        ciente(ex, u)
    return {"cientes": len(feitas), "uuids": feitas}


# --- correção de inspeção (D5) ----------------------------------------------------------------------------------------


def progresso_correcao(ex, id_lote: int) -> Optional[Dict]:
    """Ocorrências tratadas / todas da folha na minha passagem de correção aberta: o "12/40 tratadas" da barra de
    status. Fora da correção: None."""
    p = em_correcao(ex).get(id_lote)
    if p is None:
        return None
    n = ex.um(
        "SELECT count(*) AS total, coalesce(sum(CASE WHEN tratado THEN 1 ELSE 0 END), 0) AS tratadas "
        "FROM cq_inspecao WHERE id_lote = ?",
        (id_lote,),
    )
    return {**p, "total": int(n["total"]), "tratadas": int(n["tratadas"]), "pendentes": int(n["total"] - n["tratadas"])}


def _derivar_folha(ex, id_lote: int) -> bool:
    """O efeito do `t20_correcao` no workspace, sem outbox: a carga da folha (minha, na passagem de correção aberta)
    conclui quando todas as ocorrências da folha estão tratadas e volta a pendente quando alguma é desmarcada. Volta
    True se alguma carga minha acabou de concluir (a fila pode andar)."""
    todas = not ex.um("SELECT count(*) AS n FROM cq_inspecao WHERE id_lote = ? AND NOT tratado", (id_lote,))["n"]
    cargas = ex.todos(
        "SELECT c.uuid, c.concluido FROM carga_trabalho c JOIN lote_etapa le ON le.id = c.id_lote_etapa "
        f"WHERE le.id_lote = ? AND le.situacao IN {SQL_ABERTAS} AND c.responsavel = ? AND {carga_da_folha()}",
        (id_lote, ex.usuario),
    )
    mudar = [c["uuid"] for c in cargas if bool(c["concluido"]) != todas]
    for u in mudar:
        ex.executar(
            "UPDATE carga_trabalho SET concluido = ?, concluido_em = ? WHERE uuid = ?",
            (1 if todas else 0, ex.agora_iso if todas else None, u),
        )
    return todas and bool(mudar)


def tratar(ex, uuid: str, tratado: bool = True) -> Dict:
    """Marca (ou desmarca) a ocorrência como tratada na correção de inspeção. Só quem está com a folha na passagem de
    correção aberta; marcar de novo não faz nada. Volta a ocorrência, o andamento da folha, a fila (se a carga da folha
    concluiu e a fila me passou outra) e a próxima ocorrência por tratar."""
    from . import filas

    linha = ex.um("SELECT uuid, id_lote, tratado FROM cq_inspecao WHERE uuid = ?", (uuid,))
    if not linha:
        raise ErroDados("ocorrência não encontrada", 404)
    if linha["id_lote"] not in em_correcao(ex):
        raise ErroDados("só quem está com o lote na correção de inspeção aberta marca a ocorrência como tratada", 403)
    if bool(linha["tratado"]) != bool(tratado):
        campos = (
            {"tratado": True, "tratado_em": ex.agora, "tratado_por": ex.usuario}
            if tratado
            else {"tratado": False, "tratado_em": None, "tratado_por": None}
        )
        ex.atualizar("cq_inspecao", uuid, campos)
    fila = filas.puxar(ex, ex.usuario) if _derivar_folha(ex, linha["id_lote"]) else None
    return {
        "ocorrencia": ocorrencia(ex, uuid),
        "progresso": progresso_correcao(ex, linha["id_lote"]),
        "fila": fila,
        "proxima": proxima_ocorrencia(ex, uuid),
    }


def proxima_ocorrencia(ex, referencia: Optional[str] = None, id_lote: Optional[int] = None) -> Optional[Dict]:
    """A próxima ocorrência por tratar das minhas folhas na correção: primeiro a da mesma folha da referência (o
    uuid da atual), a mais perto dela; depois as outras folhas, por folha, revisão e elemento. Só das folhas na minha
    passagem de correção aberta (`id_lote`: só nesta). Nenhuma: None."""
    lotes = em_correcao(ex)
    if id_lote is not None:
        lotes = {k: v for k, v in lotes.items() if k == id_lote}
    if not lotes:
        return None
    marcas = ", ".join("?" * len(lotes))
    ref = ex.um("SELECT id_lote, cx, cy FROM cq_inspecao WHERE uuid = ?", (referencia,)) if referencia else None
    candidatas = [
        r
        for r in ex.todos(
            f"SELECT i.uuid, i.id_lote, i.cx, i.cy, le.revisao, i.elemento, i.criado_em FROM cq_inspecao i "
            f"LEFT JOIN lote_etapa le ON le.id = i.id_lote_etapa WHERE NOT i.tratado AND i.id_lote IN ({marcas})",
            tuple(lotes),
        )
        if r["uuid"] != referencia
    ]
    if not candidatas:
        return None

    def chave(r):
        mesma = 0 if ref is not None and r["id_lote"] == ref["id_lote"] else 1
        dist = 0.0
        if ref is not None and mesma == 0 and None not in (r["cx"], r["cy"], ref["cx"], ref["cy"]):
            dist = math.hypot(r["cx"] - ref["cx"], r["cy"] - ref["cy"])
        return (mesma, dist, lotes[r["id_lote"]]["folha_revisao"] or "", r["revisao"] or 0, r["elemento"] or "",
                r["criado_em"] or "", r["uuid"])  # fmt: skip

    escolhida = min(candidatas, key=chave)
    return ocorrencia(ex, escolhida["uuid"])


def correcao(ex) -> List[Dict]:
    """Execução › Correção: as minhas folhas na correção de inspeção aberta, cada uma com as ocorrências da folha (de
    todas as revisões), quantas foram tratadas e, em `so_folha`, se a minha parte é só a varredura (a carga da folha)
    ou se há também cargas pela grade a concluir (`cargas_pendentes`)."""
    lotes = em_correcao(ex)
    if not lotes:
        return []
    todas = ocorrencias(ex)
    saida = []
    for id_lote, p in lotes.items():
        itens = sorted(
            (o for o in todas if o["id_lote"] == id_lote),
            key=lambda o: (o["tratado"], o["revisao"] or 0, o["elemento"] or "", o["criado_em"] or ex.agora),
        )
        c = ex.um(
            "SELECT count(*) AS n, coalesce(sum(CASE WHEN " + carga_da_folha() + " THEN 1 ELSE 0 END), 0) AS folha, "
            f"coalesce(sum(CASE WHEN NOT c.concluido AND NOT {carga_da_folha()} THEN 1 ELSE 0 END), 0) AS pendentes "
            "FROM carga_trabalho c WHERE c.id_lote_etapa = ? AND c.responsavel = ?",
            (p["id_lote_etapa"], ex.usuario),
        )
        tratadas = sum(1 for o in itens if o["tratado"])
        saida.append(
            {**p, "total": len(itens), "tratadas": tratadas, "pendentes": len(itens) - tratadas,
             "so_folha": int(c["n"]) == int(c["folha"]), "cargas_pendentes": int(c["pendentes"]), "ocorrencias": itens}
        )  # fmt: skip
    return saida
