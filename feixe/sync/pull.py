"""Pull da CCAR para o workspace (C2, D-111): o escopo da pessoa, primeiro completo, depois só o que mudou.

Escopo (D-111). Referências pequenas, inteiras: `tema`, `fase`, `atividade` e as etapas (`fluxo_etapa`) dos fluxos da
UF. Da UF da pessoa: `lote` e `lote_etapa` (centenas). Da pessoa: os itens da `fila_folha` que ainda esperam
(`atribuida_em` nulo), as cargas dela e as cargas sem responsável das passagens que estão na fila dela (a fila anda no
workspace, `core/dados/local/filas.py`). CQ, coerente com a fase D (a amostra é da carga de CQ atribuída ao
avaliador): os planos e as amostras das cargas do escopo, e as ocorrências que a pessoa registrou ou que caem numa
carga de CQ do escopo. Ocorrências da folha para o APM autor dar ciência ficam para a D3, que desenha a visibilidade
(D-66: a revisão seguinte é às cegas, e o que vai para o workspace fica no disco). `lote_etapa_hist` não é puxada:
no workspace ela só guarda o que a execução grava para o push.

Como se acha o que mudou: comparação de versões, não marca d'água. Cada linha do espelho guarda em `versao_base` o
`atualizado_em` que veio do servidor. Um `atualizado_em > :ultimo_pull` não serviria sozinho: (1) o gatilho
`t00_atualizado` grava `now()`, que é a hora do início da transação, e uma transação que começou antes do pull e fez
commit depois dele grava uma hora que o próximo pull já deixou para trás; (2) linha que entra no escopo sem mudar
(carga sem responsável de uma folha que acabou de entrar na fila) não tem `atualizado_em` novo; (3) linha que sai do
escopo (carga reatribuída a outra pessoa) ou é apagada (cargas descartadas, passagem apagada) não aparece em consulta
nenhuma, porque o banco não tem tombstones. Então, num retrato só (REPEATABLE READ, `sincronizar`):

1. uma consulta só, de uma ida e volta, devolve por tabela a contagem e o md5 de `uuid|atualizado_em` de todo o
   escopo, em ordem de uuid; o workspace calcula o mesmo sobre `uuid|versao_base`. Igual: nada a fazer (é o caso de
   quase todo pull). Nas referências, o md5 é da linha inteira e é comparado com o do pull anterior (em `meta`);
2. diferente: vem a lista `uuid, atualizado_em` do escopo (uns 50 bytes por linha) e, dela, as linhas que faltam no
   workspace ou cuja versão não bate, com geometria (`ST_AsBinary`). Na primeira carga, ou quando falta mais da
   metade, vem o escopo inteiro de uma vez;
3. o que está no workspace e não está mais no escopo sai do workspace.

A hora do servidor (`statement_timestamp()` da primeira consulta do retrato) fica em `meta` como último pull de cada
tabela e como última sincronização; a estação não entra na conta. Nada disso depende de margem.

Linha com pendência na outbox (ou `sujo`): o pull não sobrescreve nem apaga, nem atualiza a `versao_base`. O C3
decide: o item da outbox leva a versão base de quando a pessoa mudou a linha, e o push compara essa versão com o
`atualizado_em` do servidor (diferente: a linha mudou lá desde a base, `conflito_vencido` ou `conflito_perdido`
pela hora; igual: `aplicado`). Avançar a `versao_base` de uma linha suja faria a próxima edição local parecer feita
sobre uma versão do servidor que a pessoa não viu. Essas linhas voltam na contagem como `adiadas` (vieram do servidor
e não foram gravadas) e `retidas` (saíram do escopo e ficaram); quando o push as limpa, o pull seguinte acerta.

SQL compatível com PostgreSQL 9.6. Parâmetros nomeados: `uf` e `usuario` (a conta do workspace, que é o
`current_user` da CCAR; `sincronizar` confere).
"""

from __future__ import annotations

import hashlib
import time
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from . import esquema
from .workspace import Workspace, _valores, iso_exato

S = "mapcartacomp"
LOTE_UUIDS = 2000  # uuids por consulta ao buscar as linhas que mudaram
FRACAO_COMPLETA = 0.5  # faltando mais que isto do escopo, vem o escopo inteiro numa consulta só


def _fila(alias: str = "f") -> str:
    return (
        f"SELECT {alias}.id_lote_etapa FROM {S}.fila_folha {alias} WHERE {alias}.uf = %(uf)s "
        f"AND {alias}.responsavel = %(usuario)s AND {alias}.atribuida_em IS NULL"
    )


def escopo_cargas_pessoa(alias: str) -> str:
    """Minhas cargas e as sem responsável das passagens na minha fila."""
    a = alias
    return (
        f"{a}.uf = %(uf)s AND ({a}.responsavel = %(usuario)s OR ({a}.responsavel IS NULL "
        f"AND {a}.id_lote_etapa IN ({_fila('f_' + a)})))"
    )


def escopo_cargas_uf(alias: str) -> str:
    """Toda a carga_trabalho da UF: só para medir (S-03), não é escopo de ninguém."""
    return f"{alias}.uf = %(uf)s"


def escopos(cargas: Callable[[str], str] = escopo_cargas_pessoa) -> Dict[str, str]:
    """WHERE de cada tabela do espelho, sobre o alias `t`."""
    return {
        "lote": "t.uf = %(uf)s",
        "lote_etapa": "t.uf = %(uf)s",
        "fila_folha": "t.uf = %(uf)s AND t.responsavel = %(usuario)s AND t.atribuida_em IS NULL",
        "carga_trabalho": cargas("t"),
        "cq_plano": f"t.uf = %(uf)s AND t.id IN (SELECT c.id_cq_plano FROM {S}.carga_trabalho c WHERE {cargas('c')})",
        "cq_amostra": (
            f"t.uf = %(uf)s AND t.id_carga_trabalho IN (SELECT c.id FROM {S}.carga_trabalho c WHERE {cargas('c')})"
        ),
        "cq_inspecao": (
            f"t.uf = %(uf)s AND (t.responsavel = %(usuario)s OR t.id_carga_trabalho IN (SELECT c.id FROM "
            f"{S}.carga_trabalho c WHERE c.id_cq_plano IS NOT NULL AND {cargas('c')}))"
        ),
    }


# Referências: WHERE sobre `t` e a ordem (a chave) para o md5 da linha inteira.
REFERENCIAS: Dict[str, Tuple[str, str]] = {
    "tema": ("true", "t.id"),
    "fase": ("true", "t.codigo"),
    "atividade": ("true", "t.id"),
    "fluxo_etapa": (
        f"t.id_fluxo IN (SELECT id FROM {S}.fluxo WHERE uf = %(uf)s) "
        f"OR t.id_fluxo IN (SELECT id_fluxo FROM {S}.lote WHERE uf = %(uf)s)",
        "t.id",
    ),
}

# Ordem de gravação: as referências primeiro, depois pais antes dos filhos (o SQLite não tem FK, é só por clareza).
ORDEM_ESPELHO = ["lote", "lote_etapa", "fila_folha", "cq_plano", "carga_trabalho", "cq_amostra", "cq_inspecao"]

_VERSAO_SQL = "to_char(t.atualizado_em AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"')"


def _colunas(tabela: str) -> str:
    t = esquema.TABELAS[tabela]
    cols = []
    for c, _ in t.dominio:
        cols.append("t.uuid::text AS uuid" if c == "uuid" else f"t.{c}")
    if t.geom:
        cols.append("ST_AsBinary(t.geom) AS geom")
    return ", ".join(cols)


def _resumo_remoto(rx, onde: Dict[str, str], params: Dict) -> Dict[str, Tuple[int, str]]:
    """Uma ida e volta: por tabela, (contagem, md5). Espelho: `uuid|atualizado_em` em ordem de uuid; referências: a
    linha inteira em ordem de chave."""
    partes = []
    for nome in ORDEM_ESPELHO:
        partes.append(
            f"(SELECT count(*) || ':' || coalesce(md5(string_agg(t.uuid::text || '|' || {_VERSAO_SQL}, ',' "
            f"ORDER BY t.uuid)), '') FROM {S}.{nome} t WHERE {onde[nome]}) AS {nome}"
        )
    for nome, (where, ordem) in REFERENCIAS.items():
        partes.append(
            f"(SELECT count(*) || ':' || coalesce(md5(string_agg(t::text, ',' ORDER BY {ordem})), '') "
            f"FROM {S}.{nome} t WHERE {where}) AS {nome}"
        )
    linha = rx.um("SELECT " + ", ".join(partes), params)
    saida = {}
    for nome, valor in linha.items():
        n, _, md5 = valor.partition(":")
        saida[nome] = (int(n), md5)
    return saida


def _resumo_local(ex, tabela: str) -> Tuple[int, str, Dict[str, Optional[str]]]:
    versoes = {r["uuid"]: r["versao_base"] for r in ex.todos(f"SELECT uuid, versao_base FROM {tabela}")}
    if not versoes:
        return 0, "", versoes
    texto = ",".join(f"{u}|{versoes[u] or ''}" for u in sorted(versoes))
    return len(versoes), hashlib.md5(texto.encode("utf-8")).hexdigest(), versoes


def _pendentes(ex, tabela: str) -> set:
    """uuids da tabela com item na outbox ou marcados sujos: o pull não mexe neles."""
    r = {x["uuid"] for x in ex.todos("SELECT DISTINCT uuid FROM outbox WHERE tabela = ?", (tabela,))}
    r |= {x["uuid"] for x in ex.todos(f"SELECT uuid FROM {tabela} WHERE sujo = 1")}
    return r


def _buscar(rx, tabela: str, onde: str, params: Dict, uuids: Optional[List[str]] = None) -> List[Dict]:
    sql = f"SELECT {_colunas(tabela)} FROM {S}.{tabela} t WHERE {onde}"
    if uuids is None:
        return rx.todos(sql, params)
    linhas: List[Dict] = []
    for i in range(0, len(uuids), LOTE_UUIDS):
        p = dict(params, uuids=uuids[i : i + LOTE_UUIDS])
        linhas += rx.todos(sql + " AND t.uuid = ANY(%(uuids)s::uuid[])", p)
    return linhas


def _contagem() -> Dict[str, int]:
    return {"recebidas": 0, "inseridas": 0, "atualizadas": 0, "removidas": 0, "adiadas": 0, "retidas": 0}


def puxar(
    ws: Workspace,
    rx,
    usuario: Optional[str] = None,
    onde: Optional[Dict[str, str]] = None,
    tabelas: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    """Traz o escopo da pessoa da CCAR (`rx`: executor psycopg2 numa transação, de preferência REPEATABLE READ READ
    ONLY, ver `sincronizar`) para o workspace. Volta as contagens por tabela, a hora do servidor e a duração.

    `usuario` muda a pessoa do escopo (padrão: a do workspace) e `onde` o escopo do espelho; os dois são para medir
    (S-03) e testar. `tabelas` limita o pull a algumas tabelas."""
    t0 = time.monotonic()
    params = {"uf": ws.uf, "usuario": usuario or ws.usuario}
    onde = onde or escopos()
    quais = set(tabelas) if tabelas is not None else set(ORDEM_ESPELHO) | set(REFERENCIAS)
    servidor = rx.um("SELECT statement_timestamp() AS agora")["agora"]
    remoto = _resumo_remoto(rx, onde, params)

    with ws.leitura() as lx:
        primeira = {n: lx.ultimo_pull(n) is None for n in quais}
        digest_ref = {n: lx.meta(f"resumo.{n}") for n in REFERENCIAS}
        local = {n: _resumo_local(lx, n) for n in ORDEM_ESPELHO if n in quais}

    contagens: Dict[str, Dict[str, int]] = {}
    recebido: Dict[str, Any] = {}  # tabela -> (linhas, uuids remotos ou None = referência inteira)

    for nome in REFERENCIAS:
        if nome not in quais:
            continue
        contagens[nome] = _contagem()
        if not primeira[nome] and digest_ref[nome] == remoto[nome][1]:
            continue
        where, ordem = REFERENCIAS[nome]
        cols = ", ".join(f"t.{c}" for c, _ in esquema.TABELAS[nome].dominio)
        recebido[nome] = rx.todos(f"SELECT {cols} FROM {S}.{nome} t WHERE {where} ORDER BY {ordem}", params)

    for nome in ORDEM_ESPELHO:
        if nome not in quais:
            continue
        contagens[nome] = _contagem()
        n_local, md5_local, versoes = local[nome]
        n_remoto, md5_remoto = remoto[nome]
        if not primeira[nome] and (n_local, md5_local) == (n_remoto, md5_remoto):
            continue
        if primeira[nome] or not versoes:
            linhas = _buscar(rx, nome, onde[nome], params)
            recebido[nome] = (linhas, {r["uuid"] for r in linhas})
            continue
        lista = rx.todos(
            f"SELECT t.uuid::text AS uuid, {_VERSAO_SQL} AS v FROM {S}.{nome} t WHERE {onde[nome]}", params
        )
        no_escopo = {r["uuid"] for r in lista}
        faltam = [r["uuid"] for r in lista if versoes.get(r["uuid"]) != r["v"]]
        if not faltam:
            linhas = []
        elif len(faltam) > FRACAO_COMPLETA * max(len(lista), 1):
            quero = set(faltam)
            linhas = [r for r in _buscar(rx, nome, onde[nome], params) if r["uuid"] in quero]
        else:
            linhas = _buscar(rx, nome, onde[nome], params, faltam)
        recebido[nome] = (linhas, no_escopo)

    t_rede = time.monotonic()
    with ws.transacao() as wx:
        for nome in REFERENCIAS:
            if nome in recebido:
                _gravar_referencia(wx, nome, recebido[nome], contagens[nome])
                wx.definir_meta(f"resumo.{nome}", remoto[nome][1])
            if nome in quais:
                wx.marcar_pull(nome, servidor)
        for nome in ORDEM_ESPELHO:
            if nome in recebido:
                linhas, no_escopo = recebido[nome]
                _gravar_espelho(wx, nome, linhas, no_escopo, contagens[nome])
            if nome in quais:
                wx.marcar_pull(nome, servidor)
        if tabelas is None:
            wx.definir_meta("ultima_sincronizacao", iso_exato(servidor))

    soma = _contagem()
    for c in contagens.values():
        for k in soma:
            soma[k] += c[k]
    return {
        "primeira": any(primeira.values()),
        "servidor_agora": iso_exato(servidor),
        "duracao_s": round(time.monotonic() - t0, 3),
        "duracao_ccar_s": round(t_rede - t0, 3),  # consultas e transferência
        "duracao_gravacao_s": round(time.monotonic() - t_rede, 3),  # escrita no workspace
        "tabelas": contagens,
        "recebidas": soma["recebidas"],
        "linhas": soma["inseridas"] + soma["atualizadas"] + soma["removidas"],
        "adiadas": soma["adiadas"],
        "retidas": soma["retidas"],
    }


def _gravar_espelho(wx, nome: str, linhas: List[Dict], no_escopo: set, cont: Dict[str, int]) -> None:
    pendentes = _pendentes(wx, nome)
    versoes = {r["uuid"]: r["versao_base"] for r in wx.todos(f"SELECT uuid, versao_base FROM {nome}")}
    cont["recebidas"] += len(linhas)
    for r in linhas:
        u = r["uuid"]
        if u in pendentes:
            cont["adiadas"] += 1
            continue
        if u in versoes and versoes[u] == iso_exato(r["atualizado_em"]):
            continue
        cont["inseridas" if wx.gravar_remoto(nome, r, nova=u not in versoes) == "insert" else "atualizadas"] += 1
    for u in versoes:
        if u in no_escopo:
            continue
        if u in pendentes:
            cont["retidas"] += 1
            continue
        wx.executar(f"DELETE FROM {nome} WHERE uuid = ?", (u,))
        cont["removidas"] += 1


def _gravar_referencia(wx, nome: str, linhas: List[Dict], cont: Dict[str, int]) -> None:
    t = esquema.TABELAS[nome]
    chave = t.chaves[0]
    cols = [c for c, _ in t.dominio]
    locais = {r[chave]: r for r in wx.todos(f"SELECT {', '.join(cols)} FROM {nome}")}
    cont["recebidas"] += len(linhas)
    vistos = set()
    for r in linhas:
        k = r[chave]
        vistos.add(k)
        atual = locais.get(k)
        if atual is not None and _valores(t, r) == {c: atual[c] for c in cols if c in r}:
            continue
        cont["inseridas" if wx.gravar_remoto(nome, r) == "insert" else "atualizadas"] += 1
    for k in locais:
        if k not in vistos:
            wx.executar(f"DELETE FROM {nome} WHERE {chave} = ?", (k,))
            cont["removidas"] += 1
