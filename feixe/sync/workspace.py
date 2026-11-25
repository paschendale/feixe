"""Workspace local da execução (C1, D-111): um GeoPackage por ambiente e usuário, com espelho, outbox e sync_log.

Onde: `~/.feixe/<ambiente>/<usuario>/workspace.gpkg` (a raiz muda nos testes). Abrir confere a tabela `meta`: um
workspace de outro ambiente ou de outro usuário é recusado (`WorkspaceRecusado`), nunca reaproveitado. Versão de
esquema mais nova que a do plugin também é recusada; mais velha migra (`esquema.MIGRACOES`) ou, sem migração, o
workspace é recriado, porque é cache: a outbox e o sync_log vão junto para o arquivo novo e o resto volta no próximo
pull. Mudança de UF (lotação) recria do mesmo jeito.

Escrita: toda escrita local muda a linha e grava o item da outbox na mesma transação SQLite (`ExecutorLocal.atualizar`
e `inserir`). O pull (C2) grava pelo `gravar_remoto`, que não passa pela outbox. Só o plugin escreve: a transação liga
o interruptor (`controle_escrita`) que os gatilhos de guarda consultam, e a escrita de qualquer outra conexão (o OGR
do QGIS, outro programa) nas tabelas do espelho é recusada no próprio arquivo (C4, ver `esquema.py`).

Concorrência. O arquivo é aberto ao mesmo tempo pelas threads do servidor HTTP (o painel), pela thread da
sincronização (C2/C3) e pelo QGIS, que lê (e, no C4, edita) as camadas pelo OGR, com outra conexão e outra cópia do
SQLite. Por isso:

- WAL (`journal_mode=WAL`, gravado no arquivo): leitores não bloqueiam o escritor nem o contrário, e o OGR entende.
  WAL exige disco local (a pasta do usuário é; pasta de rede não serviria);
- `busy_timeout` de 10 s: quando outro processo (o OGR) está escrevendo, a transação espera em vez de falhar na hora;
- uma trava (`threading.RLock`) por arquivo, compartilhada por todos os `Workspace` do processo que abrem o mesmo
  caminho, e uma conexão por `Workspace`: dentro do plugin as transações ficam em fila, uma de cada vez, o que tira o
  `database is locked` entre as nossas threads e deixa o SQLite cuidar só do OGR. As operações são de milissegundos;
- escrita com `BEGIN IMMEDIATE`: a trava de escrita do arquivo é pedida no início, e não no primeiro UPDATE de uma
  transação que já leu (onde o SQLite devolveria erro sem esperar);
- `synchronous=FULL`: a outbox é o que não pode se perder numa queda de energia.

SQLite: nada de `ON CONFLICT ... DO UPDATE` (UPSERT, SQLite 3.24) nem `FILTER` em agregados (3.30): o QGIS-LTR 3.22
do Mac traz o SQLite 3.35.2, mas a versão do Python do QGIS no Windows não está garantida. `gravar_remoto` faz UPDATE
e, se não achou a linha, INSERT, dentro da mesma transação.

Funções ST_*: o workspace não tem rtree (os gatilhos dele chamam ST_IsEmpty, ST_MinX... que só existem dentro do
OGR). Se o QGIS um dia criar o índice no arquivo, os gatilhos passariam a falhar nas nossas escritas; para isso não
quebrar nada, a conexão registra essas funções em Python, lendo o envelope do blob.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import json
import os
import re
import sqlite3
import threading
from decimal import Decimal
from typing import Any, Dict, Iterator, List, Optional

from ..core.dados import Executor, novo_uuid
from . import esquema, geometria

TIMEOUT_OCUPADO = 10.0  # segundos esperando outro processo (o OGR) soltar a escrita


class WorkspaceRecusado(Exception):
    """O arquivo existe mas não serve para este ambiente, usuário ou versão do plugin."""


# --- datas ----------------------------------------------------------------------------------------------------------
# Tudo em UTC e texto ISO 8601 com Z, num formato só por coluna, para comparar e ordenar como texto (min, max, >).
# Colunas DATETIME do GeoPackage: milissegundos (`2026-11-24T13:05:00.123Z`, o formato da especificação; com mais
# casas o OGR avisa "Non-conformant content"). Versões (`versao_base`, último pull, hora da outbox): microssegundos,
# para guardar o `atualizado_em` do servidor exatamente como ele é e o C3 comparar por igualdade.

UTC = dt.timezone.utc


def agora() -> dt.datetime:
    return dt.datetime.now(UTC)


def _utc(v: Any) -> dt.datetime:
    if isinstance(v, str):
        v = de_iso(v)
    if v.tzinfo is None:
        v = v.replace(tzinfo=UTC)
    return v.astimezone(UTC)


def iso(v: Any) -> Optional[str]:
    """Data para coluna DATETIME do GeoPackage (milissegundos)."""
    if v is None:
        return None
    v = _utc(v)
    return v.strftime("%Y-%m-%dT%H:%M:%S.") + f"{v.microsecond // 1000:03d}Z"


def iso_exato(v: Any) -> Optional[str]:
    """Data para versão e hora de sincronização (microssegundos, a precisão do timestamptz)."""
    if v is None:
        return None
    return _utc(v).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def de_iso(s: Optional[str]) -> Optional[dt.datetime]:
    """Texto ISO (com Z, com fuso ou sem) para datetime com fuso; sem fuso = UTC."""
    if s is None:
        return None
    t = s.strip().replace("Z", "+00:00").replace(" ", "T", 1)
    # O fromisoformat do Python 3.9 só aceita 3 ou 6 casas nos segundos e fuso com dois pontos.
    m = re.match(r"^(.*?T\d\d:\d\d:\d\d)(\.\d+)?([+-]\d\d(?::?\d\d)?)?$", t)
    if m:
        base, frac, fuso = m.groups()
        frac = (frac or ".0")[1:].ljust(6, "0")[:6]
        if fuso and ":" not in fuso:
            fuso = fuso[:3] + ":" + (fuso[3:] or "00")
        t = f"{base}.{frac}{fuso or ''}"
    d = dt.datetime.fromisoformat(t)
    return d if d.tzinfo else d.replace(tzinfo=UTC)


def _json_padrao(v):
    if isinstance(v, dt.datetime):
        return iso(v)
    if isinstance(v, (dt.date, Decimal)):
        return str(v)
    if isinstance(v, (bytes, bytearray, memoryview)):
        return bytes(v).hex()
    return str(v)


def _para_sqlite(v: Any, tipo: str) -> Any:
    if v is None:
        return None
    if tipo.startswith("DATETIME"):
        return iso(v)
    if tipo.startswith("BOOLEAN"):
        return 1 if v else 0
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (dt.datetime, dt.date)):
        return v.isoformat()
    if not isinstance(v, (int, float, str, bytes)):
        return str(v)  # uuid.UUID e afins
    return v


# --- caminho e travas -----------------------------------------------------------------------------------------------


def raiz_padrao() -> str:
    return os.path.join(os.path.expanduser("~"), ".feixe")


def _pasta_segura(nome: str) -> str:
    limpo = re.sub(r"[^A-Za-z0-9_.-]", "_", nome or "").strip(".")
    if not limpo:
        raise WorkspaceRecusado("nome vazio para a pasta do workspace")
    return limpo


def caminho(ambiente: str, usuario: str, raiz: Optional[str] = None) -> str:
    return os.path.join(raiz or raiz_padrao(), _pasta_segura(ambiente), _pasta_segura(usuario), "workspace.gpkg")


def uf_gravada(path: str) -> Optional[str]:
    """A UF gravada num workspace que já existe (None se não existe ou não é workspace), sem abrir para escrita: é
    como o plugin abre o workspace sem ir ao banco (offline, a lotação no SGBC não está ao alcance)."""
    if not os.path.isfile(path):
        return None
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=TIMEOUT_OCUPADO)
        try:
            r = conn.execute("SELECT valor FROM meta WHERE chave = 'uf'").fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return None
    return r[0] if r else None


_travas: Dict[str, threading.RLock] = {}
_travas_trava = threading.Lock()


def _trava_de(path: str) -> threading.RLock:
    chave = os.path.normcase(os.path.realpath(path))
    with _travas_trava:
        return _travas.setdefault(chave, threading.RLock())


# --- funções ST_* para os gatilhos de um rtree criado por outro programa --------------------------------------------


def _registrar_st(conn: sqlite3.Connection) -> None:
    def env(i):
        def f(blob):
            e = geometria.envelope_do_blob(blob)
            return None if e is None else e[i]

        return f

    conn.create_function("ST_IsEmpty", 1, lambda b: 1 if geometria.envelope_do_blob(b) is None else 0)
    for i, nome in enumerate(("ST_MinX", "ST_MaxX", "ST_MinY", "ST_MaxY")):
        conn.create_function(nome, 1, env(i))


def _conectar(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=TIMEOUT_OCUPADO, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(f"PRAGMA busy_timeout={int(TIMEOUT_OCUPADO * 1000)}")
    conn.execute("PRAGMA synchronous=FULL")
    _registrar_st(conn)
    return conn


# --- executor -------------------------------------------------------------------------------------------------------


class ExecutorLocal(Executor):
    """Executor sobre o workspace, dentro de uma transação aberta. Parâmetros com `?` (SQLite).

    Além de `todos`/`um`/`executar`, sabe quem é o usuário (`usuario`, o `current_user` da CCAR), a UF e a hora da
    ação (`agora`, uma só por transação: todos os itens da outbox de uma ação têm a mesma hora). `acao` identifica a
    transação nos itens da outbox: o push (C3) trata os itens de uma ação juntos (o puxar da fila é uma unidade)."""

    def __init__(self, conn: sqlite3.Connection, usuario: str, uf: str, hora: Optional[dt.datetime] = None):
        self.conn = conn
        self.usuario = usuario
        self.uf = uf
        self.agora = hora or agora()
        self.acao = novo_uuid()

    @property
    def agora_iso(self) -> str:
        """Hora da ação como vai nas colunas DATETIME."""
        return iso(self.agora)

    def todos(self, sql, params=None):
        cur = self.conn.execute(sql, tuple(params or ()))
        if cur.description is None:
            return []
        return [dict(r) for r in cur.fetchall()]

    def executar(self, sql, params=None):
        return self.conn.execute(sql, tuple(params or ())).rowcount

    # --- escrita local (com outbox) ---

    def atualizar(self, tabela: str, uuid: str, campos: Dict[str, Any]) -> None:
        """Muda campos de domínio de uma linha do espelho e grava o item da outbox, na mesma transação."""
        t = _espelho(tabela)
        tipos = dict(t.dominio)
        desconhecidos = set(campos) - set(tipos)
        if desconhecidos:
            raise ValueError(f"{tabela}: campos fora do espelho: {sorted(desconhecidos)}")
        linha = self.um(f"SELECT versao_base FROM {tabela} WHERE uuid = ?", (uuid,))
        if linha is None:
            raise LookupError(f"{tabela} {uuid} não está no workspace")
        vals = {c: _para_sqlite(v, tipos[c]) for c, v in campos.items()}
        vals.update(atualizado_em=self.agora_iso, atualizado_por=self.usuario, sujo=1)
        sets = ", ".join(f"{c} = ?" for c in vals)
        self.executar(f"UPDATE {tabela} SET {sets} WHERE uuid = ?", (*vals.values(), uuid))
        self._outbox(tabela, uuid, "update", campos, linha["versao_base"])

    def inserir(self, tabela: str, linha: Dict[str, Any]) -> str:
        """Linha nova criada no plugin (sem `id` da CCAR até o push). Volta o uuid. `geom` vem em WKB."""
        t = _espelho(tabela)
        linha = dict(linha)
        linha.setdefault("uuid", novo_uuid())
        linha.setdefault("uf", self.uf)
        for c in ("criado_em", "atualizado_em"):
            linha.setdefault(c, self.agora)
        for c in ("criado_por", "atualizado_por"):
            linha.setdefault(c, self.usuario)
        linha.pop("id", None)
        vals = _valores(t, linha)
        vals.update(sujo=1, versao_base=None)
        self.executar(
            f"INSERT INTO {tabela} ({', '.join(vals)}) VALUES ({', '.join('?' * len(vals))})", tuple(vals.values())
        )
        self._outbox(tabela, linha["uuid"], "insert", linha, None)
        return linha["uuid"]

    def _outbox(self, tabela, uuid, operacao, campos, versao_base) -> None:
        self.executar(
            "INSERT INTO outbox (tabela, uuid, operacao, campos, hora, versao_base, chave, acao) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (tabela, uuid, operacao, json.dumps(campos, default=_json_padrao, ensure_ascii=False),
             iso_exato(self.agora), versao_base, novo_uuid(), self.acao),
        )  # fmt: skip

    # --- escrita vinda da CCAR (pull, C2), sem outbox ---

    def gravar_remoto(self, tabela: str, linha: Dict[str, Any], nova: bool = False) -> str:
        """Grava a linha como veio da CCAR: UPDATE pela chave e, se não havia, INSERT. Nas tabelas do espelho a linha
        fica limpa (`sujo` = 0) e `versao_base` = o `atualizado_em` remoto. `geom` vem em WKB (`ST_AsBinary`).
        Não olha se a linha local tem alteração pendente: quem decide isso é o pull/push (C2/C3). Volta 'update' ou
        'insert'. `nova`: quem chama já sabe que a linha não está no workspace (vai direto ao INSERT)."""
        t = esquema.TABELAS[tabela]
        vals = _valores(t, linha)
        if t.sincroniza:
            vals["versao_base"] = iso_exato(linha.get("atualizado_em"))
            vals["sujo"] = 0
        chaves = t.chaves
        faltam = [c for c in chaves if vals.get(c) is None]
        if faltam:
            raise ValueError(f"{tabela}: linha sem a chave {faltam}")
        sets = [c for c in vals if c not in chaves]
        onde = " AND ".join(f"{c} = ?" for c in chaves)
        n = 0
        if sets and not nova:
            n = self.executar(
                f"UPDATE {tabela} SET {', '.join(f'{c} = ?' for c in sets)} WHERE {onde}",
                (*(vals[c] for c in sets), *(vals[c] for c in chaves)),
            )
        if n:
            return "update"
        achou = (
            not sets
            and not nova
            and self.um(f"SELECT 1 AS x FROM {tabela} WHERE {onde}", tuple(vals[c] for c in chaves))
        )
        if achou:
            return "update"
        self.executar(
            f"INSERT INTO {tabela} ({', '.join(vals)}) VALUES ({', '.join('?' * len(vals))})", tuple(vals.values())
        )
        return "insert"

    # --- meta, outbox e sync_log, para o C2/C3 ---

    def meta(self, chave: str) -> Optional[str]:
        r = self.um("SELECT valor FROM meta WHERE chave = ?", (chave,))
        return r["valor"] if r else None

    def definir_meta(self, chave: str, valor: Optional[str]) -> None:
        if not self.executar("UPDATE meta SET valor = ? WHERE chave = ?", (valor, chave)):
            self.executar("INSERT INTO meta (chave, valor) VALUES (?, ?)", (chave, valor))

    def ultimo_pull(self, tabela: str) -> Optional[str]:
        return self.meta(f"ultimo_pull.{tabela}")

    def marcar_pull(self, tabela: str, quando: Any) -> None:
        self.definir_meta(f"ultimo_pull.{tabela}", iso_exato(quando))

    def pendentes(self, limite: Optional[int] = None) -> List[Dict]:
        """Itens da outbox na ordem em que foram gravados, com `campos` já como dicionário."""
        sql = "SELECT * FROM outbox ORDER BY id"
        itens = self.todos(sql + (" LIMIT ?" if limite else ""), (limite,) if limite else ())
        for i in itens:
            i["campos"] = json.loads(i["campos"])
        return itens

    def registrar_log(
        self, tabela: str, uuid: Optional[str], operacao: str, resultado: str, detalhe: Any = None
    ) -> None:
        self.executar(
            "INSERT INTO sync_log (usuario, uf, em, tabela, uuid, operacao, resultado, detalhe) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (self.usuario, self.uf, iso_exato(agora()), tabela, uuid, operacao, resultado,
             None if detalhe is None else json.dumps(detalhe, default=_json_padrao, ensure_ascii=False)),
        )  # fmt: skip


def _espelho(tabela: str) -> esquema.Tabela:
    t = esquema.TABELAS.get(tabela)
    if t is None or not t.sincroniza:
        raise ValueError(f"{tabela} não é tabela do espelho")
    return t


def _valores(t: esquema.Tabela, linha: Dict[str, Any]) -> Dict[str, Any]:
    vals = {c: _para_sqlite(linha[c], tipo) for c, tipo in t.dominio if c in linha}
    if t.geom and "geom" in linha:
        g = geometria.de_wkb(bytes(linha["geom"]) if linha["geom"] is not None else None)
        for c in ("xmin", "ymin", "xmax", "ymax", "cx", "cy"):
            vals[c] = getattr(g, c) if g else None
        vals["geom"] = g.blob if g else None
    return vals


# --- workspace ------------------------------------------------------------------------------------------------------


class Workspace:
    """Um workspace aberto. Use `Workspace.abrir(...)`, depois `transacao()` para escrever e `leitura()` para ler."""

    def __init__(self, path: str, ambiente: str, usuario: str, uf: str):
        self.caminho = path
        self.ambiente = ambiente
        self.usuario = usuario
        self.uf = uf
        self._trava = _trava_de(path)
        self._conn: Optional[sqlite3.Connection] = None
        self._ex: Optional[ExecutorLocal] = None  # transação aberta (para aninhar na mesma thread)

    @classmethod
    def abrir(
        cls, ambiente: str, usuario: str, uf: str, raiz: Optional[str] = None, path: Optional[str] = None
    ) -> Workspace:
        path = path or caminho(ambiente, usuario, raiz)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        ws = cls(path, ambiente, usuario, uf)
        with ws._trava:
            ws._preparar()
        return ws

    def fechar(self) -> None:
        with self._trava:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.fechar()

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = _conectar(self.caminho)
        return self._conn

    # --- transações ---

    @contextlib.contextmanager
    def transacao(self, hora: Optional[dt.datetime] = None) -> Iterator[ExecutorLocal]:
        """Transação de escrita (`BEGIN IMMEDIATE`). Aninhada na mesma thread, reaproveita a de fora (não abra uma
        escrita dentro de `leitura()`: ela seguiria adiada e poderia falhar sem esperar se o OGR estiver escrevendo)."""
        with self._trava:
            if self._ex is not None:
                yield self._ex
                return
            conn = self.conn
            conn.execute("BEGIN IMMEDIATE")
            # Interruptor dos gatilhos de guarda (esquema, C4): ligado só dentro desta transação; o ROLLBACK desfaz.
            conn.execute("UPDATE controle_escrita SET plugin = 1")
            self._ex = ExecutorLocal(conn, self.usuario, self.uf, hora)
            try:
                yield self._ex
                conn.execute("UPDATE controle_escrita SET plugin = 0")
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            finally:
                self._ex = None

    @contextlib.contextmanager
    def leitura(self) -> Iterator[ExecutorLocal]:
        """Leitura num retrato só (`BEGIN` adiado): o OGR e a sincronização podem escrever enquanto isso."""
        with self._trava:
            if self._ex is not None:
                yield self._ex
                return
            conn = self.conn
            conn.execute("BEGIN")
            self._ex = ExecutorLocal(conn, self.usuario, self.uf)
            try:
                yield self._ex
            finally:
                self._ex = None
                conn.execute("COMMIT")

    # --- criação, conferência e recriação ---

    def _preparar(self) -> None:
        conn = self.conn
        tem_meta = conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'meta'").fetchone()
        if not tem_meta:
            if conn.execute("SELECT count(*) FROM sqlite_master").fetchone()[0]:
                raise WorkspaceRecusado(f"{self.caminho} existe e não é um workspace do Feixe")
            self._criar(conn)
            return
        meta = {r["chave"]: r["valor"] for r in conn.execute("SELECT chave, valor FROM meta")}
        if meta.get("ambiente") != self.ambiente:
            raise WorkspaceRecusado(
                f"este workspace é do ambiente {meta.get('ambiente')!r}, não de {self.ambiente!r}: o Feixe não mistura "
                "dados de ambientes (D-41)"
            )
        if meta.get("usuario") != self.usuario:
            raise WorkspaceRecusado(
                f"este workspace é do usuário {meta.get('usuario')!r}, não de {self.usuario!r}: cada conta tem o seu"
            )
        versao = int(meta.get("versao_esquema") or 0)
        if versao > esquema.VERSAO:
            raise WorkspaceRecusado(
                f"este workspace foi gravado por um Feixe mais novo (esquema {versao}, este entende até "
                f"{esquema.VERSAO}): atualize o plugin"
            )
        while versao < esquema.VERSAO and versao in esquema.MIGRACOES:
            conn.execute("BEGIN IMMEDIATE")
            try:
                esquema.MIGRACOES[versao](conn)
                versao += 1
                conn.execute("UPDATE meta SET valor = ? WHERE chave = 'versao_esquema'", (str(versao),))
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
        if versao < esquema.VERSAO or meta.get("uf") != self.uf:
            self._recriar()

    def _criar(self, conn: sqlite3.Connection) -> None:
        conn.execute(f"PRAGMA application_id={esquema.GPKG_ID_APLICACAO}")
        conn.execute(f"PRAGMA user_version={esquema.GPKG_VERSAO}")
        conn.execute("BEGIN IMMEDIATE")
        try:
            for cmd in esquema.ddl_completo():
                conn.execute(cmd)
            conn.executemany(
                "INSERT INTO gpkg_spatial_ref_sys (srs_name, srs_id, organization, organization_coordsys_id, "
                "definition, description) VALUES (?, ?, ?, ?, ?, ?)",
                esquema.GPKG_SRS,
            )
            criado = iso(agora())
            for t in esquema.TABELAS.values():
                conn.execute(
                    "INSERT INTO gpkg_contents (table_name, data_type, identifier, description, last_change, srs_id) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (t.nome, "features" if t.geom else "attributes", t.nome, t.descricao, criado,
                     geometria.SRID if t.geom else None),
                )  # fmt: skip
                if t.geom:
                    conn.execute(
                        "INSERT INTO gpkg_geometry_columns (table_name, column_name, geometry_type_name, srs_id, z, m) "
                        "VALUES (?, 'geom', ?, ?, 0, 0)",
                        (t.nome, t.geom, geometria.SRID),
                    )
            esquema.registrar_views(conn, criado)
            conn.executemany(
                "INSERT INTO meta (chave, valor) VALUES (?, ?)",
                [("ambiente", self.ambiente), ("usuario", self.usuario), ("uf", self.uf),
                 ("versao_esquema", str(esquema.VERSAO)), ("criado_em", criado)],
            )  # fmt: skip
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        # Em WAL o cabeçalho novo (application_id "GPKG") fica no -wal até um checkpoint, e o OGR lê o cabeçalho direto
        # do arquivo principal: sem isto, ele avisa "bad application_id" enquanto a conexão estiver aberta.
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    def _recriar(self) -> None:
        """Esquema velho sem migração ou UF trocada: arquivo novo, levando a outbox e o sync_log. O antigo fica em
        `workspace.gpkg.anterior` até a próxima recriação."""
        conn = self.conn
        guardar = {}
        for tabela in ("outbox", "sync_log"):
            cols_novas = _colunas_ddl(tabela)
            cols = [r[1] for r in conn.execute(f"PRAGMA table_info({tabela})") if r[1] in cols_novas and r[1] != "id"]
            guardar[tabela] = (cols, conn.execute(f"SELECT {', '.join(cols)} FROM {tabela} ORDER BY id").fetchall())
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        self.fechar()
        anterior = self.caminho + ".anterior"
        for sufixo in ("", "-wal", "-shm"):
            with contextlib.suppress(FileNotFoundError):
                os.remove(anterior + sufixo)
        os.replace(self.caminho, anterior)
        for sufixo in ("-wal", "-shm"):
            with contextlib.suppress(FileNotFoundError):
                os.remove(self.caminho + sufixo)
        conn = self.conn
        self._criar(conn)
        conn.execute("BEGIN IMMEDIATE")
        for tabela, (cols, linhas) in guardar.items():
            if cols and linhas:
                conn.executemany(
                    f"INSERT INTO {tabela} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                    [tuple(r) for r in linhas],
                )
        conn.execute("COMMIT")


def _colunas_ddl(tabela: str) -> List[str]:
    ddl = next(c for c in esquema.CONTROLE if c.startswith(f"CREATE TABLE {tabela} "))
    return re.findall(r"^\s+(\w+) ", ddl, flags=re.M)
