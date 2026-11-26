"""Push do workspace para a CCAR (C3, D-111 item 5, D-117): a outbox, em ordem, por `uuid`; a última escrita vence.

Um push é uma transação na CCAR e, depois do commit dela, uma transação no workspace. Nada do workspace fica travado
enquanto a rede trabalha: a pessoa continua concluindo cargas, e o que ela gravar durante o push fica para o próximo.

1. **Itens.** Lê a outbox em ordem. Cada item tem `chave` (uuid do item) e `acao` (uuid da transação local que o
   gravou). Os itens de uma ação vão juntos quando são o puxar da fila (`unidade`); os outros vão um a um.
2. **Relógio.** A hora da ação é do relógio da estação; o `atualizado_em` é do servidor. A primeira consulta do push
   lê `statement_timestamp()` entre duas leituras do relógio local; o desvio é o servidor menos o meio das duas
   (erro de meia ida e volta). Toda hora do item (a da ação e as datas que ele grava, como `concluido_em`) é
   corrigida por esse desvio e nunca passa da hora do servidor (ação no futuro não existe). O desvio fica em `meta`
   e vai no `sync_log`. Limite: o desvio é o de agora; se a pessoa acertou o relógio entre a ação offline e o push,
   a correção erra pela diferença.
3. **Idempotência.** Cada linha do `sync_log` da CCAR leva em `detalhe.itens` as chaves dos itens que ela registra, e
   é gravada na mesma transação da mudança. Antes de aplicar, o push procura as chaves no `sync_log` da CCAR: item já
   registrado (o push anterior fez commit e a resposta se perdeu) não é aplicado de novo; só se acerta o workspace com
   a linha atual do servidor. Sem DDL nova: o índice por `uuid` do `sync_log` já serve.
4. **Junção.** Atualizações seguidas da mesma linha, fora de unidade (concluir e depois desfazer), viram um envio só:
   os campos se somam na ordem, a hora é a da última ação e a versão base é a da primeira. O `sync_log` registra um
   envio com todas as chaves e, em `detalhe.juntados`, a hora e os campos de cada item. Itens não seguidos da mesma
   linha não se juntam (a ordem com as outras linhas importa para as regras), mas a versão que o push grava numa
   linha vale de base para o item seguinte dela, para um item não entrar em conflito com outro da mesma pessoa.
5. **Regras de novo no servidor** (D-111): carga que não existe mais, que não é mais da pessoa, concluir ou desfazer
   em etapa encerrada e desfazer depois de 24 h (pela hora corrigida da ação); o puxar da fila como unidade: o item da
   fila ainda existe, não foi entregue e é da pessoa, a etapa está aberta, a pessoa ainda tem o perfil no SGBC (a
   mesma `cargas.equipe` do `filas.puxar` da CCAR) e só passam as cargas ainda sem responsável; nenhuma passou,
   a unidade toda é recusada. Recusa: resultado `recusado` com o motivo, o workspace volta ao valor do servidor e
   a pessoa recebe um aviso. Linha que sumiu da CCAR (passagem apagada, carga descartada) também é recusa: sai do
   workspace. CQ (D3a): a amostra tem de ser de uma carga de CQ da pessoa, com a passagem aberta; a ocorrência nova,
   numa carga de CQ da pessoa com a passagem aberta; editar e apagar ocorrência, só a própria e com a passagem
   aberta; a ciência, só pelo autor da carga apontada (`id_carga_avaliada`), em qualquer situação da passagem.
6. **Última escrita vence** (D-111, D-117): versão base do item igual ao `atualizado_em` do servidor, `aplicado`.
   Diferente, a linha mudou lá desde o último pull: vence a mais nova entre a hora corrigida da ação e a hora da
   versão do servidor (`conflito_vencido`, aplica e o valor do servidor vai para o detalhe; `conflito_perdido`, o
   workspace fica com o do servidor e o valor local vai para o detalhe). A hora da versão do servidor é a hora da
   ação que a gravou quando ela veio de um push (o `sync_log` guarda versão e hora da ação), e o `atualizado_em`
   quando foi uma mudança direta: senão uma conclusão offline enviada tarde levaria a hora do envio e ganharia de uma
   ação mais nova. Exceção: a mesma carga concluída nas duas pontas não é disputa, fica a conclusão mais antiga
   (`aplicado`, com a nota no detalhe), que é quando o trabalho terminou de fato.
   Ciência que já estava na CCAR (dada noutra estação) fica como está (`aplicado` sem efeito).
7. **Falha de banco** que não é rede nem regra (gatilho que recusa, constraint): o item fica na outbox com
   `tentativas` e `erro`, registrado como `erro` nos dois `sync_log`; na quinta tentativa vira recusa. Falha de rede
   derruba o push inteiro: a transação da CCAR é desfeita e a outbox fica como estava.

Efeito do gatilho: avaliar a amostra conclui a carga de CQ na CCAR (`t20_derivar`), sem item na outbox. Depois dos
envios, as cargas das amostras enviadas são relidas e o workspace fica com elas, como com as linhas enviadas (recusa
inclusive: a conclusão local volta ao que está na CCAR).

Desempenho: uma transação na CCAR; as linhas do servidor, o `sync_log` das linhas e as etapas vêm em uma consulta
por tabela, com `FOR UPDATE`; cada envio é uma ida e volta (`SAVEPOINT` junto com o comando); o `sync_log` vai num
INSERT só no fim.

SQL compatível com PostgreSQL 9.6 (`INSERT ... AS`, `UPDATE ... AS`, `jsonb` e o operador `?` existem desde 9.5).
"""

from __future__ import annotations

import datetime as dt
import json
import time
from typing import Any, Callable, ContextManager, Dict, List, Optional, Tuple

from ..core.dados import cargas as dc
from ..core.dados import novo_uuid
from ..core.dados.local import cargas as lc
from ..core.dados.local import rotulo
from . import esquema
from .pull import _colunas
from .workspace import Workspace, _json_padrao, agora, de_iso, iso_exato

S = "mapcartacomp"
MAX_TENTATIVAS = 5
JANELA_DESFAZER = dt.timedelta(hours=lc.JANELA_DESFAZER_HORAS)
ABERTAS = ("pendente", "em_andamento")
AUDITORIA = ("criado_em", "criado_por", "atualizado_em", "atualizado_por")
DESVIO_AVISO = dt.timedelta(minutes=5)
RESULTADOS = ("aplicado", "conflito_vencido", "conflito_perdido", "recusado", "erro")


# --- partes puras: relógio, junção, decisão ---------------------------------------------------------------------------


def estimar_desvio(t0: dt.datetime, servidor: dt.datetime, t1: dt.datetime) -> dt.timedelta:
    """Servidor menos estação: `t0` e `t1` são o relógio local antes e depois da consulta que leu `servidor`."""
    return servidor - (t0 + (t1 - t0) / 2)


def corrigir(hora: dt.datetime, desvio: dt.timedelta, teto: Optional[dt.datetime] = None) -> dt.datetime:
    """Hora da estação no relógio do servidor; nunca depois de `teto` (a hora do servidor no push)."""
    h = hora + desvio
    return min(h, teto) if teto is not None else h


def decidir(
    versao_base: Optional[str], versao_servidor: str, hora_acao: dt.datetime, hora_servidor: dt.datetime
) -> str:
    """aplicado | conflito_vencido | conflito_perdido. Empate fica com o servidor."""
    if versao_base == versao_servidor:
        return "aplicado"
    return "conflito_vencido" if hora_acao > hora_servidor else "conflito_perdido"


def _e_unidade(item: Dict) -> bool:
    """Itens que o `local.filas.puxar` grava numa ação: cargas passando de dono, início da passagem, histórico e o item
    da fila entregue."""
    t, op, campos = item["tabela"], item["operacao"], item["campos"]
    if t == "fila_folha":
        return op == "update" and "atribuida_em" in campos
    if t == "carga_trabalho":
        return op == "update" and set(campos) == {"responsavel"}
    if t == "lote_etapa":
        return op == "update" and "situacao" in campos
    return t == "lote_etapa_hist" and op == "insert"


def _grupo(item: Dict) -> Dict:
    return {
        "tabela": item["tabela"],
        "uuid": item["uuid"],
        "operacao": item["operacao"],
        "campos": dict(item["campos"]),
        "hora": item["hora"],
        "versao_base": item["versao_base"],
        "itens": [item],
        "juntados": None,
    }


def juntar(itens: List[Dict]) -> List[Tuple[str, Any]]:
    """Itens da outbox (em ordem) -> passos: ('envio', grupo) ou ('unidade', [grupos]). Uma ação com o item da fila
    entregue tem os itens do puxar como unidade (no fim da ação, na ordem); o resto da ação são envios. Envios
    seguidos de atualização da mesma linha se juntam."""
    acoes: List[List[Dict]] = []
    for it in itens:
        if acoes and it.get("acao") is not None and acoes[-1][0].get("acao") == it.get("acao"):
            acoes[-1].append(it)
        else:
            acoes.append([it])
    passos: List[Tuple[str, Any]] = []
    for acao in acoes:
        tem_unidade = any(i["tabela"] == "fila_folha" and _e_unidade(i) for i in acao)
        unidade = [i for i in acao if tem_unidade and _e_unidade(i)]
        for it in acao:
            if it in unidade:
                continue
            ant = passos[-1] if passos else None
            if (
                ant is not None
                and ant[0] == "envio"
                and it["operacao"] == "update"
                and ant[1]["operacao"] == "update"
                and (ant[1]["tabela"], ant[1]["uuid"]) == (it["tabela"], it["uuid"])
            ):
                g = ant[1]
                if g["juntados"] is None:
                    g["juntados"] = [_resumo_item(g["itens"][0])]
                g["juntados"].append(_resumo_item(it))
                g["campos"].update(it["campos"])
                g["hora"] = it["hora"]
                g["itens"].append(it)
            else:
                passos.append(("envio", _grupo(it)))
        if unidade:
            passos.append(("unidade", [_grupo(i) for i in unidade]))
    return passos


def _resumo_item(it: Dict) -> Dict:
    return {"chave": it.get("chave"), "hora": it["hora"], "campos": it["campos"]}


# --- valores ----------------------------------------------------------------------------------------------------------


def _tipos(tabela: str) -> Dict[str, str]:
    return dict(esquema.TABELAS[tabela].dominio)


def _para_pg(tabela: str, campos: Dict[str, Any], desvio: dt.timedelta, teto: dt.datetime) -> Dict[str, Any]:
    """Campos do JSON da outbox para o psycopg2: datas corrigidas pelo desvio, geometria em hex do WKB."""
    tipos = _tipos(tabela)
    saida = {}
    for c, v in campos.items():
        if c in AUDITORIA or c in ("id", "sujo", "versao_base"):
            continue
        tipo = tipos.get(c, "")
        if v is not None and tipo.startswith("DATETIME"):
            v = corrigir(de_iso(v), desvio, teto)
        saida[c] = v
    return saida


def _igual(a: Any, b: Any) -> bool:
    if isinstance(a, dt.datetime) and isinstance(b, dt.datetime):
        return a == b
    if isinstance(a, (bytes, memoryview)) or isinstance(b, (bytes, memoryview)):
        return False
    return a == b


def _json(v: Any) -> str:
    return json.dumps(v, default=_json_padrao, ensure_ascii=False)


def _sem_geom(linha: Optional[Dict], campos) -> Optional[Dict]:
    if linha is None:
        return None
    return {c: linha.get(c) for c in campos if c != "geom"}


# --- SQL --------------------------------------------------------------------------------------------------------------


def _set_sql(tabela: str, valores: Dict[str, Any]) -> Tuple[str, List[Any]]:
    partes, params = [], []
    for c, v in valores.items():
        if c == "geom":
            partes.append("geom = ST_GeomFromWKB(decode(%s, 'hex'), 4674)")
        else:
            partes.append(f"{c} = %s")
        params.append(v)
    return ", ".join(partes), params


def _returning(tabela: str) -> str:
    return _colunas(tabela)


def _buscar_linhas(rx, tabela: str, uuids: List[str]) -> Dict[str, Dict]:
    if not uuids:
        return {}
    linhas = rx.todos(
        f"SELECT {_colunas(tabela)} FROM {S}.{tabela} t WHERE t.uuid = ANY(%s::uuid[]) FOR UPDATE OF t", (uuids,)
    )
    return {r["uuid"]: r for r in linhas}


# --- referência legível (C5) ------------------------------------------------------------------------------------------

_JUNCOES_REF = (
    "LEFT JOIN lote_etapa le ON le.id = x.id_lote_etapa LEFT JOIN lote l ON l.id = le.id_lote "
    "LEFT JOIN fluxo_etapa fe ON fe.id = le.id_fluxo_etapa "
)
_REF = {
    "carga_trabalho": (
        f"SELECT x.uuid, x.id, x.geocodigo, x.id_lote_etapa, le.id_lote, x.id_atividade, {rotulo()} AS folha, "
        f"fe.nome AS etapa, at.nome AS atividade FROM carga_trabalho x {_JUNCOES_REF}"
        "LEFT JOIN atividade at ON at.id = x.id_atividade"
    ),
    "fila_folha": f"SELECT x.uuid, x.id, x.id_lote_etapa, le.id_lote, {rotulo()} AS folha, fe.nome AS etapa "
    f"FROM fila_folha x {_JUNCOES_REF}",
    "lote_etapa_hist": f"SELECT x.uuid, x.id, x.id_lote_etapa, le.id_lote, {rotulo()} AS folha, fe.nome AS etapa "
    f"FROM lote_etapa_hist x {_JUNCOES_REF}",
    "lote_etapa": f"SELECT x.uuid, x.id, x.id AS id_lote_etapa, x.id_lote, {rotulo()} AS folha, fe.nome AS etapa "
    "FROM lote_etapa x LEFT JOIN lote_etapa le ON le.id = x.id LEFT JOIN lote l ON l.id = x.id_lote "
    "LEFT JOIN fluxo_etapa fe ON fe.id = x.id_fluxo_etapa",
    "cq_amostra": (
        f"SELECT x.uuid, x.id, x.id_carga_trabalho AS id_carga, c.geocodigo, c.id_lote_etapa, le.id_lote, "
        f"{rotulo()} AS folha, fe.nome AS etapa, at.nome AS atividade FROM cq_amostra x "
        "LEFT JOIN carga_trabalho c ON c.id = x.id_carga_trabalho LEFT JOIN lote_etapa le ON le.id = c.id_lote_etapa "
        "LEFT JOIN lote l ON l.id = le.id_lote LEFT JOIN fluxo_etapa fe ON fe.id = le.id_fluxo_etapa "
        "LEFT JOIN atividade at ON at.id = c.id_atividade"
    ),
    "cq_inspecao": f"SELECT x.uuid, x.id, x.id_lote_etapa, x.id_lote, {rotulo()} AS folha, fe.nome AS etapa, "
    "x.elemento FROM cq_inspecao x LEFT JOIN lote_etapa le ON le.id = x.id_lote_etapa "
    "LEFT JOIN lote l ON l.id = x.id_lote LEFT JOIN fluxo_etapa fe ON fe.id = le.id_fluxo_etapa",
}


def _referencias(ws: Workspace, por_tabela: Dict[str, List[str]]) -> Dict[Tuple[str, str], Dict]:
    """A carga ou a folha de cada linha enviada, como o workspace a conhece agora (folha-revisão, geocódigo, etapa,
    atividade e ids): vai no `detalhe.ref` do `sync_log`, para a tela de conflitos dizer de que carga se trata mesmo
    depois de a linha ser apagada na CCAR (C5)."""
    refs: Dict[Tuple[str, str], Dict] = {}
    with ws.leitura() as wx:
        for tabela, uuids in por_tabela.items():
            sql = _REF.get(tabela)
            if not sql or not uuids:
                continue
            marcas = ", ".join("?" * len(uuids))
            for r in wx.todos(f"{sql} WHERE x.uuid IN ({marcas})", tuple(uuids)):
                u = r.pop("uuid")
                refs[(tabela, u)] = {k: v for k, v in r.items() if v is not None}
    return refs


# --- push -------------------------------------------------------------------------------------------------------------


class _Push:
    def __init__(self, ws: Workspace, rx, usuario: str, uf: str, desvio: dt.timedelta, servidor_agora: dt.datetime):
        self.ws = ws
        self.rx = rx
        self.usuario = usuario
        self.uf = uf
        self.desvio = desvio
        self.agora = servidor_agora
        self.servidor: Dict[str, Dict[str, Dict]] = {}  # tabela -> uuid -> linha atual (com o que o push gravou)
        self.logs: Dict[str, List[Dict]] = {}  # uuid -> linhas do sync_log da CCAR
        self.etapas: Dict[int, Dict] = {}  # id_lote_etapa -> situacao, cod_projeto, folha
        self.versoes: Dict[Tuple[str, str], str] = {}  # versão que este push gravou na linha
        self.log_ccar: List[Dict] = []  # envios, na ordem, para o sync_log da CCAR
        self.savepoint = False
        self.equipes: Dict[int, set] = {}
        self.refs: Dict[Tuple[str, str], Dict] = {}  # (tabela, uuid) -> carga/folha legível, do workspace
        self.cargas_cq: Dict[int, Dict] = {}  # id -> carga de CQ das amostras e ocorrências, e a carga avaliada
        self.derivadas: set = set()  # uuids das cargas de CQ que o gatilho da amostra pode ter mudado

    # --- leitura do servidor ---

    def carregar(self, itens: List[Dict]) -> None:
        por_tabela: Dict[str, List[str]] = {}
        for it in itens:
            por_tabela.setdefault(it["tabela"], [])
            if it["uuid"] not in por_tabela[it["tabela"]]:
                por_tabela[it["tabela"]].append(it["uuid"])
        for t, uuids in por_tabela.items():
            self.servidor[t] = _buscar_linhas(self.rx, t, uuids)
        self.refs = _referencias(self.ws, por_tabela)
        todos = sorted({it["uuid"] for it in itens})
        for r in self.rx.todos(
            f"SELECT s.uuid::text AS uuid, s.usuario, s.resultado, s.detalhe FROM {S}.sync_log s "
            "WHERE s.uuid = ANY(%s::uuid[]) AND s.detalhe ? 'itens' ORDER BY s.id",
            (todos,),
        ):
            d = r["detalhe"]
            if isinstance(d, str):
                d = json.loads(d)
            r["detalhe"] = d or {}
            self.logs.setdefault(r["uuid"], []).append(r)
        self._carregar_cq(itens)
        ids = set()
        for t in ("carga_trabalho", "fila_folha", "cq_inspecao"):
            ids |= {r["id_lote_etapa"] for r in self.servidor.get(t, {}).values() if r.get("id_lote_etapa")}
        ids |= {r["id"] for r in self.servidor.get("lote_etapa", {}).values()}
        ids |= {r["id_lote_etapa"] for r in self.cargas_cq.values() if r.get("id_lote_etapa")}
        if ids:
            for r in self.rx.todos(
                f"SELECT le.id, le.situacao, l.cod_projeto, {S}.f_rotulo(l.tipo, l.nome, le.revisao) AS folha "
                f"FROM {S}.lote_etapa le JOIN {S}.lote l ON l.id = le.id_lote WHERE le.id = ANY(%s)",
                (sorted(ids),),
            ):
                self.etapas[r["id"]] = r

    def _carregar_cq(self, itens: List[Dict]) -> None:
        """As cargas que as regras do CQ conferem, travadas: a da amostra, a de CQ da ocorrência (a do servidor ou, na
        ocorrência nova, a que veio no item) e a carga avaliada (o autor dá ciência)."""
        ids = set()
        for r in self.servidor.get("cq_amostra", {}).values():
            ids.add(r.get("id_carga_trabalho"))
        for r in self.servidor.get("cq_inspecao", {}).values():
            ids |= {r.get("id_carga_trabalho"), r.get("id_carga_avaliada")}
        for it in itens:
            if it["tabela"] == "cq_inspecao" and it["operacao"] == "insert":
                ids.add(it["campos"].get("id_carga_trabalho"))
        ids = sorted(i for i in ids if i is not None)
        if not ids:
            return
        for r in self.rx.todos(
            "SELECT t.id, t.uuid::text AS uuid, t.responsavel, t.id_lote_etapa, t.id_cq_plano "
            f"FROM {S}.carga_trabalho t WHERE t.id = ANY(%s) ORDER BY t.id FOR UPDATE OF t",
            (ids,),
        ):
            self.cargas_cq[r["id"]] = r

    def reler_derivadas(self) -> None:
        """Depois dos envios: as cargas de CQ das amostras enviadas como ficaram na CCAR (o gatilho as conclui)."""
        if not self.derivadas:
            return
        for r in self.rx.todos(
            f"SELECT {_colunas('carga_trabalho')} FROM {S}.carga_trabalho t WHERE t.uuid = ANY(%s::uuid[])",
            (sorted(self.derivadas),),
        ):
            self.servidor.setdefault("carga_trabalho", {})[r["uuid"]] = r

    def feitos(self) -> Dict[str, Tuple[str, str]]:
        """chave do item -> (resultado, uuid) já registrado na CCAR (menos erro, que não aplicou nada)."""
        r = {}
        for uuid, linhas in self.logs.items():
            for linha in linhas:
                if linha["resultado"] == "erro":
                    continue
                for ch in linha["detalhe"].get("itens") or []:
                    r[ch] = (linha["resultado"], uuid)
        return r

    def hora_servidor(self, tabela: str, uuid: str, linha: Dict) -> Tuple[dt.datetime, Optional[str], str]:
        """(hora, quem, origem) da versão atual da linha no servidor: a da ação que a gravou, se veio de um push."""
        versao = iso_exato(linha["atualizado_em"])
        for log in reversed(self.logs.get(uuid, [])):
            d = log["detalhe"]
            if log["resultado"] in ("aplicado", "conflito_vencido") and d.get("versao") == versao:
                em = (d.get("local") or {}).get("em")
                if em:
                    return de_iso(em), log["usuario"], "acao"
        return linha["atualizado_em"], linha.get("atualizado_por"), "atualizado_em"

    # --- escrita no servidor ---

    def _executar(self, sql: str, params) -> List[Dict]:
        prefixo = ("RELEASE SAVEPOINT feixe_push; " if self.savepoint else "") + "SAVEPOINT feixe_push; "
        self.savepoint = True
        return self.rx.todos(prefixo + sql, params)

    def _desfazer_savepoint(self) -> None:
        self.rx.executar("ROLLBACK TO SAVEPOINT feixe_push")

    def _abrir(self) -> None:
        """Savepoint para um passo que pode ter mais de um comando (unidade)."""
        self.rx.executar(("RELEASE SAVEPOINT feixe_push; " if self.savepoint else "") + "SAVEPOINT feixe_push")
        self.savepoint = True

    def atualizar(self, tabela: str, uuid: str, valores: Dict[str, Any], com_savepoint: bool = True) -> Dict:
        sets, params = _set_sql(tabela, valores)
        sql = f"UPDATE {S}.{tabela} AS t SET {sets} WHERE t.uuid = %s::uuid RETURNING {_returning(tabela)}"
        params.append(uuid)
        linhas = self._executar(sql, params) if com_savepoint else self.rx.todos(sql, params)
        nova = linhas[0]
        self.servidor.setdefault(tabela, {})[uuid] = nova
        self.versoes[(tabela, uuid)] = iso_exato(nova["atualizado_em"])
        return nova

    def inserir(self, tabela: str, uuid: str, valores: Dict[str, Any], com_savepoint: bool = True) -> Dict:
        valores = {**valores, "uuid": uuid}
        cols, marcas, params = [], [], []
        for c, v in valores.items():
            cols.append(c)
            marcas.append("ST_GeomFromWKB(decode(%s, 'hex'), 4674)" if c == "geom" else "%s")
            params.append(v)
        sql = (
            f"INSERT INTO {S}.{tabela} AS t ({', '.join(cols)}) VALUES ({', '.join(marcas)}) "
            f"RETURNING {_returning(tabela)}"
        )
        linhas = self._executar(sql, params) if com_savepoint else self.rx.todos(sql, params)
        nova = linhas[0]
        self.servidor.setdefault(tabela, {})[uuid] = nova
        self.versoes[(tabela, uuid)] = iso_exato(nova["atualizado_em"])
        return nova

    # --- registro ---

    def registrar(self, g: Dict, resultado: str, detalhe: Dict) -> None:
        """Resultado do envio; vai ao sync_log da CCAR no fim (`gravar_log`), na mesma transação."""
        g["resultado"] = resultado
        g["detalhe"] = detalhe
        self.log_ccar.append(g)

    def detalhe(self, g: Dict, hora: dt.datetime, antes: Optional[Dict], **extra) -> Dict:
        campos = list(g["campos"])
        d = {
            "itens": [i.get("chave") for i in g["itens"]],
            "acao": g["itens"][0].get("acao"),
            "hora_estacao": g["hora"],
            "desvio_s": round(self.desvio.total_seconds(), 3),
            "local": {"valores": _sem_geom(g["campos"], campos), "por": self.usuario, "em": iso_exato(hora)},
        }
        if antes is not None:
            em, por, origem = self.hora_servidor(g["tabela"], g["uuid"], antes)
            d["servidor"] = {
                "valores": _sem_geom(antes, campos),
                "por": por,
                "em": iso_exato(em),
                "origem_em": origem,
                "versao": iso_exato(antes["atualizado_em"]),
            }
        d["versao_base"] = g["versao_base"]
        ref = self.refs.get((g["tabela"], g["uuid"]))
        if ref:
            d["ref"] = ref
        if g["juntados"]:
            d["juntados"] = g["juntados"]
        d.update({k: v for k, v in extra.items() if v is not None})
        return d

    def depois(self, g: Dict) -> None:
        """Envio aplicado: a versão e o id que ficaram no servidor vão para o detalhe (é por eles que um push seguinte
        sabe a hora da ação que gravou a versão atual)."""
        nova = self.servidor.get(g["tabela"], {}).get(g["uuid"])
        if nova is not None and g.get("aplicou"):
            g["detalhe"]["versao"] = iso_exato(nova["atualizado_em"])
            g["detalhe"]["id"] = nova.get("id")

    # --- regras ---

    def _rotulo(self, tabela: str, linha: Optional[Dict], g: Dict) -> str:
        linha = linha or g.get("campos") or {}
        if tabela == "cq_amostra":
            carga = self.cargas_cq.get(linha.get("id_carga_trabalho")) or {}
            folha = (self.etapas.get(carga.get("id_lote_etapa")) or {}).get("folha")
            ident = carga.get("id") or linha.get("id_carga_trabalho")
            return f"Amostra da carga {ident} da {folha}" if folha else f"Amostra da carga {ident}"
        le = linha.get("id_lote_etapa")
        folha = (self.etapas.get(le) or {}).get("folha")
        if tabela == "cq_inspecao":
            return f"Ocorrência na {folha}" if folha else "Ocorrência"
        if tabela == "carga_trabalho":
            ident = (linha or {}).get("id")
            return f"Carga {ident} da {folha}" if folha else f"Carga {ident or g['uuid'][:8]}"
        if tabela == "fila_folha":
            return f"Folha {folha} da sua fila" if folha else "Folha da sua fila"
        return tabela

    def regras_carga(self, g: Dict, srv: Dict, valores: Dict, hora: dt.datetime) -> Optional[str]:
        if srv.get("responsavel") != self.usuario:
            return "esta carga não está mais atribuída a você"
        if "concluido" in valores and bool(valores["concluido"]) != bool(srv.get("concluido")):
            etapa = self.etapas.get(srv.get("id_lote_etapa")) or {}
            if etapa.get("situacao") not in ABERTAS:
                return "a etapa desta folha foi encerrada pelo supervisor"
            if not valores["concluido"]:
                quando = srv.get("concluido_em")
                if quando is None or hora - quando >= JANELA_DESFAZER:
                    return f"só dá para desfazer até {lc.JANELA_DESFAZER_HORAS} horas depois de concluir"
        return None

    def _aberta(self, id_lote_etapa: Optional[int]) -> bool:
        return (self.etapas.get(id_lote_etapa) or {}).get("situacao") in ABERTAS

    def regras_amostra(self, srv: Dict) -> Optional[str]:
        carga = self.cargas_cq.get(srv.get("id_carga_trabalho"))
        if carga is None:
            return "a carga desta amostra não existe mais na CCAR"
        if carga.get("responsavel") != self.usuario:
            return "esta amostra não é mais de uma carga sua"
        if not self._aberta(carga.get("id_lote_etapa")):
            return "a etapa de CQ desta folha foi encerrada pelo supervisor"
        return None

    def regras_ocorrencia_nova(self, valores: Dict) -> Optional[str]:
        if valores.get("responsavel") not in (None, self.usuario):
            return "a ocorrência é de outra pessoa"
        carga = self.cargas_cq.get(valores.get("id_carga_trabalho"))
        if carga is None or carga.get("id_cq_plano") is None:
            return "a carga de CQ desta ocorrência não existe mais na CCAR"
        if carga.get("responsavel") != self.usuario:
            return "a carga de CQ desta ocorrência não está mais atribuída a você"
        if not self._aberta(carga.get("id_lote_etapa")):
            return "a etapa de CQ desta folha foi encerrada pelo supervisor"
        return None

    def regras_ocorrencia(self, srv: Dict, campos) -> Optional[str]:
        campos = set(campos)
        if campos & {"ciente_em", "ciente_por"}:
            autor = (self.cargas_cq.get(srv.get("id_carga_avaliada")) or {}).get("responsavel")
            if autor != self.usuario:
                return "só quem fez a carga apontada pela ocorrência dá ciência"
        if campos - {"ciente_em", "ciente_por"}:
            if srv.get("responsavel") != self.usuario:
                return "esta ocorrência foi registrada por outra pessoa"
            if not self._aberta(srv.get("id_lote_etapa")):
                return "a etapa de CQ desta folha foi encerrada pelo supervisor"
        return None

    def perfil(self, cod_projeto: Optional[int]) -> bool:
        if cod_projeto is None:
            return False
        if cod_projeto not in self.equipes:
            self.equipes[cod_projeto] = {r["conta"] for r in dc.equipe(self.rx, self.uf, cod_projeto)}
        return self.usuario in self.equipes[cod_projeto]

    # --- passos ---

    def envio(self, g: Dict) -> None:
        t, u = g["tabela"], g["uuid"]
        hora = corrigir(de_iso(g["hora"]), self.desvio, self.agora)
        valores = _para_pg(t, g["campos"], self.desvio, self.agora)
        srv = self.servidor.get(t, {}).get(u)
        rot = self._rotulo(t, srv, g)
        if g["operacao"] == "delete":
            self.apagar(g, hora, srv, rot)
            return
        if g["operacao"] == "insert":
            if srv is not None:  # já existe (o mesmo uuid): nada a aplicar
                self.registrar(g, "aplicado", self.detalhe(g, hora, None, sem_efeito="a linha já estava na CCAR"))
                return
            motivo = self.regras_ocorrencia_nova(valores) if t == "cq_inspecao" else None
            if motivo:
                self.recusar(g, hora, None, motivo, rot)
                return
            self._tentar(g, hora, lambda: self.inserir(t, u, valores), rot)
            return
        if srv is None:
            self.recusar(g, hora, None, "a linha não existe mais na CCAR (foi apagada ou descartada)", rot)
            return
        motivo = None
        if t == "carga_trabalho":
            motivo = self.regras_carga(g, srv, valores, hora)
        elif t == "cq_amostra":
            carga = self.cargas_cq.get(srv.get("id_carga_trabalho"))
            if carga is not None:
                self.derivadas.add(carga["uuid"])
                g["carga_derivada"] = carga["uuid"]
            motivo = self.regras_amostra(srv)
        elif t == "cq_inspecao":
            motivo = self.regras_ocorrencia(srv, valores)
        if motivo:
            self.recusar(g, hora, srv, motivo, rot)
            return
        if t == "cq_inspecao" and set(valores) <= {"ciente_em", "ciente_por"} and srv.get("ciente_em") is not None:
            nota = "a ciência já estava registrada na CCAR: fica a que já estava"
            self.registrar(g, "aplicado", self.detalhe(g, hora, srv, sem_efeito=nota))
            return
        if t == "cq_inspecao" and set(valores) <= {"ciente_em", "ciente_por"}:
            # A ciência só toca os seus campos: não disputa a última escrita com a edição da anotação ou do ponto
            # pelo avaliador, que pode ter mudado a linha depois do último pull.
            self._tentar(g, hora, lambda: self.atualizar(t, u, valores), rot)
            return
        if all(_igual(v, srv.get(c)) for c, v in valores.items()):
            self.registrar(g, "aplicado", self.detalhe(g, hora, srv, sem_efeito="a CCAR já tinha estes valores"))
            return
        if t == "carga_trabalho" and self.conclusao_dupla(g, hora, srv, valores, rot):
            return
        base = self.versoes.get((t, u), g["versao_base"])
        em, _, _ = self.hora_servidor(t, u, srv)
        res = decidir(base, iso_exato(srv["atualizado_em"]), hora, em)
        if res == "conflito_perdido":
            self.registrar(g, res, self.detalhe(g, hora, srv, descartado="local"))
            g["aviso"] = f"{rot}: mudou na CCAR depois da sua alteração; ficou a versão da CCAR"
            return
        descartado = "servidor" if res == "conflito_vencido" else None
        self._tentar(g, hora, lambda: self.atualizar(t, u, valores), rot, res, srv, descartado)

    def apagar(self, g: Dict, hora: dt.datetime, srv: Optional[Dict], rot: str) -> None:
        """Exclusão (só de ocorrência própria, com a passagem de CQ aberta). Já não estava na CCAR: nada a fazer."""
        t, u = g["tabela"], g["uuid"]
        if srv is None:
            self.registrar(g, "aplicado", self.detalhe(g, hora, None, sem_efeito="a linha já não estava na CCAR"))
            return
        if t != "cq_inspecao":
            motivo = "o Feixe só apaga ocorrências"
        elif srv.get("responsavel") != self.usuario:
            motivo = "esta ocorrência foi registrada por outra pessoa"
        elif not self._aberta(srv.get("id_lote_etapa")):
            motivo = "a etapa de CQ desta folha foi encerrada pelo supervisor"
        else:
            motivo = None
        if motivo:
            self.recusar(g, hora, srv, motivo, rot)
            return
        self._tentar(g, hora, lambda: self.excluir(t, u), rot, "aplicado", srv)

    def excluir(self, tabela: str, uuid: str) -> None:
        self._executar(f"DELETE FROM {S}.{tabela} AS t WHERE t.uuid = %s::uuid RETURNING t.id", (uuid,))
        self.servidor.get(tabela, {}).pop(uuid, None)

    def conclusao_dupla(self, g: Dict, hora: dt.datetime, srv: Dict, valores: Dict, rot: str) -> bool:
        """A mesma carga concluída nas duas pontas (duas estações, ou a estação e a tabela de atributos online): não é
        disputa de última escrita, fica a conclusão mais antiga, que é quando o trabalho terminou de fato (é a que
        conta na produtividade). A local mais nova não muda nada; a local mais antiga corrige só a hora."""
        if set(valores) - {"concluido", "concluido_em"} or not valores.get("concluido") or not srv.get("concluido"):
            return False
        local, remota = valores.get("concluido_em"), srv.get("concluido_em")
        if local is None or remota is None:
            return False
        if local >= remota:
            nota = "a carga já estava concluída na CCAR, mais cedo: fica a conclusão mais antiga"
            self.registrar(g, "aplicado", self.detalhe(g, hora, srv, sem_efeito=nota))
            return True
        nota = "a carga já estava concluída na CCAR, mais tarde: fica a conclusão mais antiga, a desta estação"
        self._tentar(g, hora, lambda: self.atualizar(g["tabela"], g["uuid"], valores), rot, "aplicado", srv, nota=nota)
        return True

    def _tentar(self, g, hora, fazer, rot, resultado="aplicado", antes=None, descartado=None, nota=None) -> None:
        try:
            fazer()
        except Exception as e:  # noqa: BLE001 - só erro de banco que não é rede vira resultado
            if not _recusa_do_banco(e):
                raise
            self._desfazer_savepoint()
            self.falhou(g, hora, antes, _mensagem(e), rot)
            return
        g["aplicou"] = True
        self.registrar(g, resultado, self.detalhe(g, hora, antes, descartado=descartado, nota=nota))
        self.depois(g)

    def falhou(self, g: Dict, hora, antes, mensagem: str, rot: str) -> None:
        tentativas = max(int(i.get("tentativas") or 0) for i in g["itens"]) + 1
        if tentativas >= MAX_TENTATIVAS:
            self.recusar(g, hora, antes, f"a CCAR recusou {tentativas} vezes: {mensagem}", rot)
            return
        g["manter"] = True
        g["erro"] = mensagem
        self.registrar(g, "erro", self.detalhe(g, hora, antes, motivo=mensagem, tentativa=tentativas))

    def recusar(self, g: Dict, hora, antes, motivo: str, rot: str) -> None:
        self.registrar(g, "recusado", self.detalhe(g, hora, antes, motivo=motivo, descartado="local"))
        g["aviso"] = f"{rot}: {motivo}; voltou ao que está na CCAR"

    def unidade(self, grupos: List[Dict]) -> None:
        """Puxar da fila: confere a unidade e aplica as cargas que ainda estão sem responsável, a passagem iniciada
        (se ainda pendente), o histórico e o item da fila entregue, num savepoint só."""
        fila = next(g for g in grupos if g["tabela"] == "fila_folha")
        hora = corrigir(de_iso(fila["hora"]), self.desvio, self.agora)
        fsrv = self.servidor.get("fila_folha", {}).get(fila["uuid"])
        etapa = self.etapas.get((fsrv or {}).get("id_lote_etapa")) or {}
        rot = self._rotulo("fila_folha", fsrv, fila)
        motivo = None
        if fsrv is None:
            motivo = "a folha saiu da sua fila"
        elif fsrv.get("responsavel") != self.usuario:
            motivo = "a folha foi para a fila de outra pessoa"
        elif fsrv.get("atribuida_em") is not None:
            motivo = "a folha já tinha sido entregue pela fila"
        elif etapa.get("situacao") not in ABERTAS:
            motivo = "a etapa da folha foi encerrada pelo supervisor"
        elif not self.perfil(etapa.get("cod_projeto")):
            motivo = f"você não tem mais o perfil de execução no projeto (SGBC, lotação {self.uf})"
        cargas = [g for g in grupos if g["tabela"] == "carga_trabalho"]
        passam, minhas, outras = [], [], []
        if motivo is None:
            for g in cargas:
                c = self.servidor.get("carga_trabalho", {}).get(g["uuid"])
                if c is None or c.get("id_lote_etapa") != fsrv["id_lote_etapa"] or c.get("concluido"):
                    outras.append(g)
                elif c.get("responsavel") is None:
                    passam.append(g)
                elif c.get("responsavel") == self.usuario:
                    minhas.append(g)
                else:
                    outras.append(g)
            if not passam and not minhas:
                motivo = "outra pessoa já pegou as cargas desta folha"
        if motivo is not None:
            for g in grupos:
                self.recusar_sem_aviso(g, hora, motivo)
            fila["aviso"] = f"{rot}: {motivo}; as cargas dela voltaram ao que está na CCAR"
            return
        try:
            self._abrir()
            if passam:
                linhas = self.rx.todos(
                    f"UPDATE {S}.carga_trabalho AS t SET responsavel = %s WHERE t.uuid = ANY(%s::uuid[]) "
                    f"AND t.responsavel IS NULL RETURNING {_returning('carga_trabalho')}",
                    (self.usuario, [g["uuid"] for g in passam]),
                )
                for nova in linhas:
                    self.servidor["carga_trabalho"][nova["uuid"]] = nova
                    self.versoes[("carga_trabalho", nova["uuid"])] = iso_exato(nova["atualizado_em"])
            iniciar = [g for g in grupos if g["tabela"] == "lote_etapa"]
            hist = [g for g in grupos if g["tabela"] == "lote_etapa_hist"]
            le_srv = self.servidor.get("lote_etapa", {})
            iniciou = False
            for g in iniciar:
                srv = le_srv.get(g["uuid"])
                if srv is not None and srv.get("situacao") == "pendente":
                    self.atualizar("lote_etapa", g["uuid"], _para_pg("lote_etapa", g["campos"], self.desvio,
                                                                     self.agora), com_savepoint=False)  # fmt: skip
                    g["aplicou"] = iniciou = True
            if iniciou:
                for g in hist:
                    self.inserir("lote_etapa_hist", g["uuid"],
                                 _para_pg("lote_etapa_hist", g["campos"], self.desvio, self.agora),
                                 com_savepoint=False)  # fmt: skip
                    g["aplicou"] = True
            valores = _para_pg("fila_folha", fila["campos"], self.desvio, self.agora)
            valores["atribuidas"] = len(passam) + len(minhas)
            antes_fila = dict(fsrv)
            self.atualizar("fila_folha", fila["uuid"], valores, com_savepoint=False)
            fila["aplicou"] = True
        except Exception as e:  # noqa: BLE001
            if not _recusa_do_banco(e):
                raise
            self._desfazer_savepoint()
            for g in grupos:
                self.falhou(g, hora, None, _mensagem(e), rot)
            return
        for g in passam + minhas:
            g["aplicou"] = g in passam
            sem = None if g in passam else "a carga já era sua na CCAR"
            self.registrar(g, "aplicado", self.detalhe(g, hora, None, sem_efeito=sem))
            self.depois(g)
        for g in outras:
            self.recusar_sem_aviso(g, hora, "outra pessoa já pegou esta carga")
        for g in iniciar + hist:
            sem = None if g.get("aplicou") else "a etapa já estava em andamento na CCAR"
            self.registrar(g, "aplicado", self.detalhe(g, hora, None, sem_efeito=sem))
            self.depois(g)
        self.registrar(fila, "aplicado", self.detalhe(fila, hora, antes_fila))
        self.depois(fila)
        if outras:
            fila["aviso"] = (
                f"{rot}: {len(outras)} das cargas já estavam com outra pessoa; você ficou com "
                f"{len(passam) + len(minhas)}"
            )

    def recusar_sem_aviso(self, g: Dict, hora, motivo: str) -> None:
        antes = self.servidor.get(g["tabela"], {}).get(g["uuid"])
        self.registrar(g, "recusado", self.detalhe(g, hora, antes, motivo=motivo, descartado="local"))

    def gravar_log(self) -> None:
        if not self.log_ccar:
            return
        marcas = ", ".join(["(%s, %s, %s, %s::uuid, %s, %s, %s::jsonb)"] * len(self.log_ccar))
        params = [
            v
            for g in self.log_ccar
            for v in (self.usuario, self.uf, g["tabela"], g["uuid"], g["operacao"], g["resultado"], _json(g["detalhe"]))
        ]
        if self.savepoint:
            self.rx.executar("RELEASE SAVEPOINT feixe_push")
            self.savepoint = False
        self.rx.executar(
            f"INSERT INTO {S}.sync_log (usuario, uf, tabela, uuid, operacao, resultado, detalhe) VALUES {marcas}",
            params,
        )


def _recusa_do_banco(e: BaseException) -> bool:
    """Erro do banco que não é de rede (gatilho que recusa, constraint, tipo): vira resultado do item."""
    try:
        import psycopg2
    except ImportError:  # pragma: no cover
        return False
    return isinstance(e, psycopg2.Error) and not isinstance(e, (psycopg2.OperationalError, psycopg2.InterfaceError))


def _mensagem(e: BaseException) -> str:
    diag = getattr(e, "diag", None)
    return getattr(diag, "message_primary", None) or str(e).strip().splitlines()[0]


# --- entrada ----------------------------------------------------------------------------------------------------------


def _preparar(ws: Workspace) -> List[Dict]:
    with ws.transacao() as wx:
        for r in wx.todos("SELECT id FROM outbox WHERE chave IS NULL"):
            wx.executar("UPDATE outbox SET chave = ? WHERE id = ?", (novo_uuid(), r["id"]))
        return wx.pendentes()


def enviar(ws: Workspace, remota: Callable[[], ContextManager[Any]], usuario: Optional[str] = None) -> Dict[str, Any]:
    """Envia a outbox do workspace. `remota()` abre uma transação na CCAR (commit ao sair); o workspace só é acertado
    depois do commit. Volta as contagens por resultado, os avisos para a pessoa, o desvio do relógio e a duração."""
    t_ini = time.monotonic()
    itens = _preparar(ws)
    contagem = dict.fromkeys(RESULTADOS, 0)
    saida: Dict[str, Any] = {"itens": len(itens), "enviados": 0, "repetidos": 0, "resultados": contagem,
                             "avisos": [], "desvio_s": None, "mudou": False}  # fmt: skip
    if not itens:
        saida["duracao_s"] = round(time.monotonic() - t_ini, 3)
        return saida
    usuario = usuario or ws.usuario
    with remota() as rx:
        t0 = agora()
        servidor_agora = rx.um("SELECT statement_timestamp() AS agora")["agora"]
        t1 = agora()
        desvio = estimar_desvio(t0, servidor_agora, t1)
        p = _Push(ws, rx, usuario, ws.uf, desvio, servidor_agora)
        p.carregar(itens)
        feitos = p.feitos()
        repetidos = [i for i in itens if i.get("chave") in feitos]
        passos = juntar([i for i in itens if i.get("chave") not in feitos])
        for tipo, conteudo in passos:
            if tipo == "envio":
                p.envio(conteudo)
            else:
                p.unidade(conteudo)
        p.reler_derivadas()
        p.gravar_log()
    grupos = [g for tipo, c in passos for g in ([c] if tipo == "envio" else c)]
    _finalizar(ws, p, grupos, repetidos, feitos)
    for g in grupos:
        contagem[g["resultado"]] += 1
        if g.get("aviso"):
            saida["avisos"].append(g["aviso"])
    saida["enviados"] = len(grupos)
    saida["repetidos"] = len(repetidos)
    saida["desvio_s"] = round(desvio.total_seconds(), 3)
    saida["mudou"] = bool(grupos or repetidos)
    if abs(desvio) > DESVIO_AVISO:
        minutos = round(abs(desvio.total_seconds()) / 60)
        lado = "atrasado" if desvio.total_seconds() > 0 else "adiantado"
        saida["avisos"].append(
            f"O relógio deste computador está {minutos} min {lado} em relação à CCAR. O Feixe corrige as horas ao "
            "enviar, mas acerte o relógio."
        )
    saida["duracao_s"] = round(time.monotonic() - t_ini, 3)
    return saida


def _finalizar(ws: Workspace, p: _Push, grupos: List[Dict], repetidos: List[Dict], feitos: Dict) -> None:
    """Depois do commit na CCAR: tira da outbox o que terminou, registra no sync_log local e deixa cada linha tocada
    com a versão do servidor, a menos que ela tenha ganhado item novo na outbox durante o push."""
    linhas: Dict[Tuple[str, str], bool] = {}  # (tabela, uuid) -> algum envio aplicou
    with ws.transacao() as wx:
        for it in repetidos:
            resultado, _ = feitos[it["chave"]]
            wx.executar("DELETE FROM outbox WHERE id = ?", (it["id"],))
            nota = "já estava registrado na CCAR (a resposta de um push anterior se perdeu)"
            detalhe = {"itens": [it["chave"]], "repetido": True, "nota": nota}
            wx.registrar_log(it["tabela"], it["uuid"], it["operacao"], resultado, detalhe)
            chave = (it["tabela"], it["uuid"])
            linhas[chave] = linhas.get(chave, False) or resultado in ("aplicado", "conflito_vencido")
        for g in grupos:
            ids = [i["id"] for i in g["itens"]]
            marcas = ", ".join("?" * len(ids))
            if g.get("manter"):
                wx.executar(
                    f"UPDATE outbox SET tentativas = tentativas + 1, erro = ? WHERE id IN ({marcas})",
                    (g["erro"], *ids),
                )
                wx.registrar_log(g["tabela"], g["uuid"], g["operacao"], "erro", g["detalhe"])
                linhas.setdefault((g["tabela"], g["uuid"]), False)
                continue
            wx.executar(f"DELETE FROM outbox WHERE id IN ({marcas})", tuple(ids))
            wx.registrar_log(g["tabela"], g["uuid"], g["operacao"], g["resultado"], g["detalhe"])
            chave = (g["tabela"], g["uuid"])
            linhas[chave] = linhas.get(chave, False) or bool(g.get("aplicou"))
            if g.get("carga_derivada"):
                # A carga de CQ que o gatilho da amostra concluiu (ou não, na recusa): fica como está na CCAR.
                linhas.setdefault(("carga_trabalho", g["carga_derivada"]), False)
        for (tabela, uuid), aplicou in linhas.items():
            srv = p.servidor.get(tabela, {}).get(uuid)
            resta = wx.todos("SELECT id FROM outbox WHERE tabela = ? AND uuid = ?", (tabela, uuid))
            if not resta:
                if srv is not None:
                    wx.gravar_remoto(tabela, srv)
                else:
                    wx.executar(f"DELETE FROM {tabela} WHERE uuid = ?", (uuid,))
                continue
            if srv is None:
                continue
            versao = iso_exato(srv["atualizado_em"])
            if srv.get("id") is not None:
                wx.executar(f"UPDATE {tabela} SET id = ? WHERE uuid = ? AND id IS NULL", (srv["id"], uuid))
            if aplicou:
                # O que a pessoa gravou durante o push partiu da versão anterior, que era a nossa: passa a partir
                # da que o push gravou, para não entrar em conflito consigo mesmo.
                wx.executar(f"UPDATE {tabela} SET versao_base = ? WHERE uuid = ?", (versao, uuid))
                wx.executar(
                    f"UPDATE outbox SET versao_base = ? WHERE id IN ({', '.join('?' * len(resta))})",
                    (versao, *[r["id"] for r in resta]),
                )
        if p.desvio is not None:
            wx.definir_meta("relogio.desvio_s", str(round(p.desvio.total_seconds(), 3)))
