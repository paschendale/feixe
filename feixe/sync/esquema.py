"""Esquema do workspace local: tabelas espelho, referências, controle e o mínimo do GeoPackage.

Espelho = subconjunto de `mapcartacomp` que a execução (operador e avaliador, D-111) precisa offline, com as mesmas
colunas de domínio da CCAR. Diferenças, todas de propósito:

- `fid` é a chave técnica (o GeoPackage exige INTEGER PRIMARY KEY nas tabelas de feições); a chave de verdade é o
  `uuid` (único), e o `id` serial da CCAR fica nulo numa linha criada offline até o primeiro push (C3);
- referências entre tabelas continuam pelo `id` da CCAR (`id_lote_etapa`, `id_carga_trabalho`...): o que a execução
  cria offline (fase D: ocorrências) só aponta para linhas que vieram da CCAR;
- colunas de controle: `versao_base` (o `atualizado_em` remoto visto no último pull, texto exato, para o C3 saber se a
  linha mudou no servidor desde então) e `sujo` (1 = tem alteração local ainda na outbox);
- geometria em blob do GeoPackage, com envelope (`xmin`..`ymax`) e centroide (`cx`, `cy`) em colunas;
- datas em texto ISO 8601 UTC, que ordena como texto: DATETIME com milissegundos (`2026-11-24T13:05:00.123Z`, como
  pede o GeoPackage), versões com microssegundos (ver `workspace.py`);
- sem rtree: os gatilhos do rtree chamam funções ST_* que o `sqlite3` do Python não tem (ver `workspace.py`).

Referências pequenas (tema, fase, atividade, etapa do fluxo) são só leitura e espelham a CCAR pela chave dela.
"""

from __future__ import annotations

import uuid
from typing import Dict, List, Optional, Tuple

from ..core.dados.local import SQL_ABERTAS, rotulo
from .geometria import SRID

# Versão do esquema do workspace. Subiu sem migração em MIGRACOES: o workspace é recriado (é cache), levando junto
# a outbox e o sync_log, que são o que não se pode perder. 2: `chave` e `acao` na outbox (C3). 3: o interruptor de
# escrita e os gatilhos que só deixam o plugin mudar as tabelas, e as views das camadas da execução (C4). 4: as colunas
# do CQ da fase D (D0, em 002/004 da CCAR): fração crítica do plano, passagem de CQ e carga avaliada da ocorrência. 5: o
# elemento de qualidade da atividade de CQ (o nome da medida no SGBC), que a ocorrência registrada offline grava (D3a).
# 6: as views das camadas do CQ no QGIS (amostras e ocorrências, D3c).
VERSAO = 6

_AUDITORIA = [
    ("criado_em", "DATETIME"),
    ("criado_por", "TEXT"),
    ("atualizado_em", "DATETIME"),
    ("atualizado_por", "TEXT"),
]
_CONTROLE = [("versao_base", "TEXT"), ("sujo", "BOOLEAN NOT NULL DEFAULT 0")]
_ENVELOPE = [(c, "DOUBLE") for c in ("xmin", "ymin", "xmax", "ymax", "cx", "cy")]


class Tabela:
    def __init__(
        self,
        nome: str,
        colunas: List[Tuple[str, str]],
        geom: Optional[str] = None,
        chave: str = "uuid",
        sincroniza: bool = True,
        descricao: str = "",
    ):
        self.nome = nome
        self.dominio = colunas  # colunas da CCAR, sem a geometria
        self.geom = geom  # tipo GeoPackage da coluna geom (MULTIPOLYGON, POINT) ou None
        self.chave = chave  # coluna (ou colunas, separadas por vírgula) pela qual o pull acha a linha
        self.sincroniza = sincroniza  # True = espelho com outbox; False = referência só leitura
        self.descricao = descricao

    @property
    def chaves(self) -> List[str]:
        return [c.strip() for c in self.chave.split(",")]

    def ddl(self) -> str:
        cols: List[str] = []
        if self.sincroniza:
            cols.append("fid INTEGER PRIMARY KEY AUTOINCREMENT")
        cols += [f"{c} {t}" for c, t in self.dominio]
        if self.geom:
            cols.append(f"geom {self.geom}")
            cols += [f"{c} {t}" for c, t in _ENVELOPE]
        if self.sincroniza:
            cols += [f"{c} {t}" for c, t in _CONTROLE]
        return f"CREATE TABLE {self.nome} (\n    " + ",\n    ".join(cols) + "\n)"


def _sync(nome, colunas, geom=None, descricao=""):
    base = [("id", "INTEGER UNIQUE"), ("uuid", "TEXT NOT NULL UNIQUE")]
    return Tabela(nome, base + colunas + _AUDITORIA, geom=geom, descricao=descricao)


# fmt: off
TABELAS: Dict[str, Tabela] = {
    t.nome: t
    for t in [
        # Referências (só leitura): o que minhas cargas, resumo, progresso e a fila juntam.
        Tabela(
            "tema",
            [("id", "INTEGER PRIMARY KEY"), ("nome", "TEXT NOT NULL"), ("ativo", "BOOLEAN"),
             ("atualizado_em", "DATETIME")],
            chave="id", sincroniza=False, descricao="Temas (referência da CCAR)",
        ),
        Tabela(
            "fase",
            [("codigo", "TEXT PRIMARY KEY"), ("nome", "TEXT NOT NULL"), ("ordem", "INTEGER"),
             ("status_nacional", "TEXT")],
            chave="codigo", sincroniza=False, descricao="Fases (referência da CCAR)",
        ),
        Tabela(
            "atividade",
            [("id", "INTEGER PRIMARY KEY"), ("cod_projeto", "INTEGER"), ("id_tema", "INTEGER"), ("fase", "TEXT"),
             ("nome", "TEXT NOT NULL"), ("geracao", "TEXT"), ("celula_largura", "DOUBLE"),
             ("celula_altura", "DOUBLE"), ("celula_unidade", "TEXT"), ("id_medidadequalidade", "INTEGER"),
             ("camada_alvo", "TEXT"), ("grade_nivel", "INTEGER"), ("ativo", "BOOLEAN"),
             ("atualizado_em", "DATETIME"), ("elemento", "TEXT")],
            chave="id", sincroniza=False, descricao="Atividades (referência da CCAR)",
        ),
        Tabela(
            "fluxo_etapa",
            [("id", "INTEGER PRIMARY KEY"), ("id_fluxo", "INTEGER"), ("ordem", "INTEGER"), ("fase", "TEXT"),
             ("nome", "TEXT NOT NULL"), ("obrigatoria", "BOOLEAN"), ("repetivel", "BOOLEAN"),
             ("conta_revisao", "BOOLEAN"), ("fracao_critica", "DOUBLE"), ("atualizado_em", "DATETIME")],
            chave="id", sincroniza=False, descricao="Etapas dos fluxos (referência da CCAR)",
        ),
        # Espelho sincronizado.
        _sync(
            "lote",
            [("cod_projeto", "INTEGER"), ("id_tema", "INTEGER"), ("id_fluxo", "INTEGER"), ("uf", "TEXT"),
             ("tipo", "TEXT"), ("id_articulacao_scn", "INTEGER"), ("nome", "TEXT"), ("revisao_atual", "INTEGER"),
             ("id_lote_etapa_atual", "INTEGER"), ("status_nacional", "TEXT")],
            geom="MULTIPOLYGON", descricao="Lotes (folhas e lotes livres)",
        ),
        _sync(
            "lote_etapa",
            [("id_lote", "INTEGER"), ("id_fluxo_etapa", "INTEGER"), ("uf", "TEXT"), ("instancia", "INTEGER"),
             ("revisao", "INTEGER"), ("situacao", "TEXT"), ("resultado", "TEXT"), ("expor_ocorrencias", "BOOLEAN"),
             ("iniciada_em", "DATETIME"), ("concluida_em", "DATETIME"), ("concluida_por", "TEXT")],
            descricao="Passagens dos lotes pelas etapas",
        ),
        _sync(
            "lote_etapa_hist",
            [("id_lote_etapa", "INTEGER"), ("uf", "TEXT"), ("acao", "TEXT"), ("em", "DATETIME"), ("por", "TEXT"),
             ("observacao", "TEXT")],
            descricao="Ações sobre as passagens feitas pela execução (iniciar ao puxar da fila)",
        ),
        _sync(
            "carga_trabalho",
            [("id_lote_etapa", "INTEGER"), ("id_atividade", "INTEGER"), ("id_cq_plano", "INTEGER"), ("uf", "TEXT"),
             ("responsavel", "TEXT"), ("geocodigo", "TEXT"), ("concluido", "BOOLEAN NOT NULL DEFAULT 0"),
             ("concluido_em", "DATETIME")],
            geom="MULTIPOLYGON", descricao="Cargas de trabalho",
        ),
        _sync(
            "fila_folha",
            [("id_lote_etapa", "INTEGER"), ("uf", "TEXT"), ("responsavel", "TEXT"), ("ordem", "INTEGER"),
             ("atribuida_em", "DATETIME"), ("atribuidas", "INTEGER")],
            descricao="Fila de lotes por pessoa",
        ),
        _sync(
            "cq_plano",
            [("id_lote_etapa", "INTEGER"), ("id_atividade", "INTEGER"), ("uf", "TEXT"), ("orientacao", "TEXT"),
             ("universo", "TEXT"), ("nivel_inspecao", "TEXT"), ("tamanho_lote_n", "INTEGER"),
             ("letra_codigo", "TEXT"), ("tamanho_amostra_n", "INTEGER"), ("lqa", "DOUBLE"),
             ("numero_aceitacao_ac", "INTEGER"), ("celula_largura", "DOUBLE"), ("celula_altura", "DOUBLE"),
             ("semente", "INTEGER"), ("resultado", "TEXT"), ("fracao_critica", "DOUBLE")],
            descricao="Planos de amostragem do CQ",
        ),
        _sync(
            "cq_amostra",
            [("id_cq_plano", "INTEGER"), ("id_carga_trabalho", "INTEGER"), ("uf", "TEXT"), ("status", "SMALLINT"),
             ("observacao", "TEXT"), ("avaliado_por", "TEXT"), ("avaliado_em", "DATETIME")],
            descricao="Amostras do CQ",
        ),
        _sync(
            "cq_inspecao",
            [("id_lote", "INTEGER"), ("id_carga_trabalho", "INTEGER"), ("uf", "TEXT"), ("elemento", "TEXT"),
             ("anotacao", "TEXT"), ("responsavel", "TEXT"), ("tratado", "BOOLEAN NOT NULL DEFAULT 0"),
             ("tratado_em", "DATETIME"), ("tratado_por", "TEXT"), ("ciente_em", "DATETIME"),
             ("ciente_por", "TEXT"), ("id_lote_etapa", "INTEGER"), ("id_carga_avaliada", "INTEGER")],
            geom="POINT", descricao="Ocorrências de inspeção",
        ),
    ]
}
# fmt: on

# Índices do que a execução filtra e junta.
INDICES = [
    "CREATE INDEX carga_trabalho_responsavel_idx ON carga_trabalho (responsavel, concluido)",
    "CREATE INDEX carga_trabalho_lote_etapa_idx ON carga_trabalho (id_lote_etapa)",
    "CREATE INDEX lote_etapa_lote_idx ON lote_etapa (id_lote)",
    "CREATE INDEX fila_folha_responsavel_idx ON fila_folha (responsavel, atribuida_em, ordem)",
    "CREATE INDEX cq_amostra_carga_idx ON cq_amostra (id_carga_trabalho)",
    "CREATE INDEX cq_inspecao_lote_idx ON cq_inspecao (id_lote)",
]
# Fase D (esquema 4): idempotentes, porque a migração 3 -> 4 também os cria.
INDICES_CQ = [
    "CREATE INDEX IF NOT EXISTS cq_inspecao_carga_idx ON cq_inspecao (id_carga_trabalho)",
    "CREATE INDEX IF NOT EXISTS cq_inspecao_carga_avaliada_idx ON cq_inspecao (id_carga_avaliada)",
    "CREATE INDEX IF NOT EXISTS cq_inspecao_lote_etapa_idx ON cq_inspecao (id_lote_etapa)",
]

# Controle, fora do gpkg_contents (o QGIS não as lista como camadas).
CONTROLE = [
    "CREATE TABLE meta (chave TEXT PRIMARY KEY, valor TEXT)",
    # Uma linha por escrita local, na ordem: o push (C3) envia por `id` crescente e só apaga depois da confirmação.
    "CREATE TABLE outbox (\n"
    "    id INTEGER PRIMARY KEY AUTOINCREMENT,\n"
    "    tabela TEXT NOT NULL,\n"
    "    uuid TEXT NOT NULL,\n"
    "    operacao TEXT NOT NULL CHECK (operacao IN ('insert', 'update', 'delete')),\n"
    "    campos TEXT NOT NULL,\n"  # JSON: só os campos alterados (insert: a linha inteira)
    "    hora TEXT NOT NULL,\n"  # hora da ação, UTC: é ela que disputa com o atualizado_em do servidor
    "    versao_base TEXT,\n"  # atualizado_em remoto da linha quando foi alterada (nulo num insert)
    "    tentativas INTEGER NOT NULL DEFAULT 0,\n"
    "    erro TEXT,\n"
    "    chave TEXT,\n"  # uuid do item: vai no sync_log da CCAR, para o push repetido não aplicar duas vezes (C3)
    "    acao TEXT\n"  # uuid da transação local: os itens de uma ação (o puxar da fila) vão juntos (C3)
    ")",
    "CREATE INDEX outbox_linha_idx ON outbox (tabela, uuid)",
    # Mesmos campos que mapcartacomp.sync_log (005), com id local.
    "CREATE TABLE sync_log (\n"
    "    id INTEGER PRIMARY KEY AUTOINCREMENT,\n"
    "    usuario TEXT,\n"
    "    uf TEXT,\n"
    "    em TEXT NOT NULL,\n"
    "    tabela TEXT NOT NULL,\n"
    "    uuid TEXT,\n"
    "    operacao TEXT NOT NULL,\n"
    "    resultado TEXT NOT NULL,\n"
    "    detalhe TEXT\n"
    ")",
    "CREATE INDEX sync_log_em_idx ON sync_log (em)",
]


# --- só o plugin escreve (C4) ---------------------------------------------------------------------------------------
# O QGIS abre as tabelas do workspace pelo OGR, com outra conexão. Uma escrita que viesse por ali (tabela de atributos,
# calculadora de campos, outro programa) mudaria a linha sem item na outbox, e a mudança nunca chegaria à CCAR. As
# camadas do Feixe não deixam isso acontecer (`core/edicao.py`: a edição sai do buffer do QGIS e vai pelo
# `ExecutorLocal`), e estes gatilhos são a garantia no arquivo: toda escrita nas tabelas do espelho e nas referências
# é recusada, a menos que venha de uma transação do plugin. O interruptor é uma linha em `controle_escrita`: a
# `Workspace.transacao` liga logo depois do `BEGIN IMMEDIATE` e desliga antes do `COMMIT` (ou o `ROLLBACK` desfaz).
# Como o SQLite tem um escritor por vez e ninguém vê o que não foi confirmado, a escrita de outra conexão só acontece
# com o interruptor desligado. SQL puro: o gatilho roda também dentro do OGR, que não tem as funções do Python.

RECUSA_FORA_DO_PLUGIN = (
    "Feixe: o espaço de trabalho só muda pelas ações do Feixe (a mudança feita por fora não chegaria à CCAR). "
    "Para concluir uma carga, use a barra do Feixe ou a camada Minhas cargas."
)

# Idempotentes (IF NOT EXISTS), como as views abaixo: a migração 2 -> 3 pode rodar num arquivo que já tem parte disso.
INTERRUPTOR = [
    "CREATE TABLE IF NOT EXISTS controle_escrita (plugin INTEGER NOT NULL)",
    "INSERT INTO controle_escrita (plugin) SELECT 0 WHERE NOT EXISTS (SELECT 1 FROM controle_escrita)",
]


def gatilhos_guarda() -> List[str]:
    """Um gatilho por tabela e operação: fora de uma transação do plugin, a escrita é recusada (fail-closed: sem a
    linha do interruptor, também recusa)."""
    cmds = []
    for t in TABELAS:
        for op in ("INSERT", "UPDATE", "DELETE"):
            cmds.append(
                f"CREATE TRIGGER IF NOT EXISTS {t}_so_pelo_feixe_{op.lower()} BEFORE {op} ON {t} "
                "WHEN (SELECT plugin FROM controle_escrita) IS NOT 1 "
                f"BEGIN SELECT RAISE(ABORT, '{RECUSA_FORA_DO_PLUGIN}'); END"
            )
    return cmds


# --- views das camadas da execução no QGIS (C4) ----------------------------------------------------------------------
# A camada Minhas cargas é a própria `carga_trabalho` (o OGR não grava em view do GeoPackage: o UPDATE pelo gatilho
# INSTEAD OF não conta linhas e ele dá a escrita por falha), filtrada pela pessoa e pelas passagens abertas; o que o
# formulário e a dica mostram da folha (rótulo, tema, etapa, atividade, progresso da pessoa) vem de uma view de
# atributos juntada pelo `id`. Minhas folhas é uma view com geometria, só leitura. A pessoa é a conta gravada em `meta`.
# Sem funções de janela (`count() OVER`, SQLite 3.25): o SQLite do QGIS no Windows não está garantido.

VW_CARGA_INFO = "vw_minhas_cargas_info"
VW_MINHAS_FOLHAS = "vw_minhas_folhas"
_EU = "(SELECT valor FROM meta WHERE chave = 'usuario')"

VIEWS = [
    f"CREATE VIEW IF NOT EXISTS {VW_CARGA_INFO} AS SELECT c.id AS id, le.id_lote AS id_lote, "
    f"{rotulo()} AS folha_revisao, "
    "t.nome AS tema, fe.nome AS etapa, a.nome AS atividade, le.situacao AS situacao_etapa, "
    "p.n AS minhas_na_folha, p.feitas AS minhas_concluidas_na_folha "
    "FROM carga_trabalho c JOIN lote_etapa le ON le.id = c.id_lote_etapa JOIN lote l ON l.id = le.id_lote "
    "LEFT JOIN tema t ON t.id = l.id_tema LEFT JOIN fluxo_etapa fe ON fe.id = le.id_fluxo_etapa "
    "LEFT JOIN atividade a ON a.id = c.id_atividade "
    "LEFT JOIN (SELECT id_lote_etapa, count(*) AS n, sum(CASE WHEN concluido THEN 1 ELSE 0 END) AS feitas "
    f"FROM carga_trabalho WHERE responsavel = {_EU} GROUP BY id_lote_etapa) p ON p.id_lote_etapa = c.id_lote_etapa "
    f"WHERE c.responsavel = {_EU}",
    f"CREATE VIEW IF NOT EXISTS {VW_MINHAS_FOLHAS} AS SELECT l.fid AS fid, l.id AS id_lote, "
    f"{rotulo()} AS folha_revisao, "
    "t.nome AS tema, fe.nome AS etapa, le.situacao AS situacao, l.geom AS geom "
    f"FROM lote l JOIN lote_etapa le ON le.id_lote = l.id AND le.situacao IN {SQL_ABERTAS} "
    "LEFT JOIN tema t ON t.id = l.id_tema LEFT JOIN fluxo_etapa fe ON fe.id = le.id_fluxo_etapa "
    "WHERE EXISTS (SELECT 1 FROM carga_trabalho c WHERE c.id_lote_etapa = le.id "
    f"AND c.responsavel = {_EU})",
]

# (nome, data_type do gpkg_contents, tipo da geometria ou None, descrição)
VIEWS_GPKG = [
    (VW_CARGA_INFO, "attributes", None, "Minhas cargas: lote, etapa, atividade e progresso (camada do Feixe)"),
    (VW_MINHAS_FOLHAS, "features", "MULTIPOLYGON", "Lotes em que tenho cargas abertas (camada do Feixe)"),
]

# --- views das camadas do CQ (D3c, esquema 6) -------------------------------------------------------------------------
# Como Minhas cargas: a camada Amostras é a própria `carga_trabalho` (as cargas de CQ da pessoa) e a de ocorrências a
# própria `cq_inspecao`; o que o formulário, a dica e o estilo mostram (status da amostra, plano, folha, quantas
# ocorrências, quem fez a carga apontada) vem destas views de atributos, juntadas com cache (pelo `id` da carga e pelo
# `uuid` da ocorrência, que a registrada offline já tem). Nomes de coluna que não existem na tabela da camada: a
# junção não repete campo. Progresso das amostras por passagem, como o "35/93" das cargas (uma amostra por carga).

VW_AMOSTRA_INFO = "vw_minhas_amostras_info"
VW_OCORRENCIA_INFO = "vw_ocorrencias_info"

VIEWS_CQ = [
    f"CREATE VIEW IF NOT EXISTS {VW_AMOSTRA_INFO} AS SELECT c.id AS id, a.id AS id_amostra, a.status AS status, "
    "a.observacao AS observacao, a.avaliado_em AS avaliado_em, coalesce(at.elemento, at.nome) AS elemento, "
    f"le.id_lote AS id_lote, {rotulo()} AS folha_revisao, t.nome AS tema, fe.nome AS etapa, "
    "le.situacao AS situacao_etapa, p.tamanho_amostra_n AS plano_n, p.numero_aceitacao_ac AS plano_ac, "
    "p.letra_codigo AS plano_letra, p.nivel_inspecao AS plano_nivel, p.lqa AS plano_lqa, "
    "(SELECT count(*) FROM cq_inspecao i WHERE i.id_carga_trabalho = c.id) AS ocorrencias, "
    "pr.n AS amostras_na_folha, pr.feitas AS avaliadas_na_folha "
    "FROM carga_trabalho c JOIN cq_amostra a ON a.id_carga_trabalho = c.id "
    "JOIN lote_etapa le ON le.id = c.id_lote_etapa JOIN lote l ON l.id = le.id_lote "
    "LEFT JOIN cq_plano p ON p.id = a.id_cq_plano LEFT JOIN tema t ON t.id = l.id_tema "
    "LEFT JOIN fluxo_etapa fe ON fe.id = le.id_fluxo_etapa LEFT JOIN atividade at ON at.id = c.id_atividade "
    "LEFT JOIN (SELECT c2.id_lote_etapa, count(*) AS n, sum(CASE WHEN a2.status IS NULL THEN 0 ELSE 1 END) AS feitas "
    "FROM carga_trabalho c2 JOIN cq_amostra a2 ON a2.id_carga_trabalho = c2.id "
    f"WHERE c2.responsavel = {_EU} GROUP BY c2.id_lote_etapa) pr ON pr.id_lote_etapa = c.id_lote_etapa "
    f"WHERE c.responsavel = {_EU}",
    f"CREATE VIEW IF NOT EXISTS {VW_OCORRENCIA_INFO} AS SELECT i.uuid AS uuid, "
    f"(CASE WHEN le.id IS NULL THEN l.nome ELSE {rotulo()} END) AS folha_revisao, t.nome AS tema, "
    "fe.nome AS etapa_cq, le.situacao AS situacao_cq, cq.geocodigo AS amostra_geocodigo, "
    "cq.id AS id_carga_amostra, ca.responsavel AS autor "
    "FROM cq_inspecao i JOIN lote l ON l.id = i.id_lote "
    "LEFT JOIN lote_etapa le ON le.id = i.id_lote_etapa LEFT JOIN tema t ON t.id = l.id_tema "
    "LEFT JOIN fluxo_etapa fe ON fe.id = le.id_fluxo_etapa "
    "LEFT JOIN carga_trabalho cq ON cq.id = i.id_carga_trabalho "
    "LEFT JOIN carga_trabalho ca ON ca.id = i.id_carga_avaliada",
]

VIEWS_GPKG_CQ = [
    (VW_AMOSTRA_INFO, "attributes", None, "Amostras de CQ: status, plano, lote e progresso (camada do Feixe)"),
    (VW_OCORRENCIA_INFO, "attributes", None, "Ocorrências: lote, amostra e autor da carga (camada do Feixe)"),
]


def registrar_views(conn, criado: str, views=None) -> None:
    """As views no `gpkg_contents` (e a de geometria no `gpkg_geometry_columns`), para o OGR abri-las como camadas.
    Sem `views`, todas (workspace novo)."""
    for nome, tipo, geom, descricao in VIEWS_GPKG + VIEWS_GPKG_CQ if views is None else views:
        if conn.execute("SELECT 1 FROM gpkg_contents WHERE table_name = ?", (nome,)).fetchone():
            continue
        conn.execute(
            "INSERT INTO gpkg_contents (table_name, data_type, identifier, description, last_change, srs_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (nome, tipo, nome, descricao, criado, SRID if geom else None),
        )
        if geom:
            conn.execute(
                "INSERT INTO gpkg_geometry_columns (table_name, column_name, geometry_type_name, srs_id, z, m) "
                "VALUES (?, 'geom', ?, ?, 0, 0)",
                (nome, geom, SRID),
            )


# Colunas que o esquema 4 acrescentou ao espelho do CQ (fase D).
_COLUNAS_V4 = {
    "cq_plano": [("fracao_critica", "DOUBLE")],
    "cq_inspecao": [("id_lote_etapa", "INTEGER"), ("id_carga_avaliada", "INTEGER")],
}


def _v5_para_v6(conn) -> None:
    """As views das camadas do CQ (D3c) num workspace que já existe: só views, nada a reler do pull."""
    for cmd in VIEWS_CQ:
        conn.execute(cmd)
    registrar_views(conn, conn.execute("SELECT strftime('%Y-%m-%dT%H:%M:%fZ', 'now')").fetchone()[0], VIEWS_GPKG_CQ)


def _v4_para_v5(conn) -> None:
    """O elemento de qualidade na referência `atividade` (D3a). O pull das referências compara o md5 com o do pull
    anterior: sem o md5 guardado, o próximo pull traz a tabela inteira de novo, já com o elemento."""
    existentes = {r[1] for r in conn.execute("PRAGMA table_info(atividade)")}
    if "elemento" not in existentes:
        conn.execute("ALTER TABLE atividade ADD COLUMN elemento TEXT")
    for cmd in INDICES_CQ:
        conn.execute(cmd)
    conn.execute("DELETE FROM meta WHERE chave = 'resumo.atividade'")


def _v3_para_v4(conn) -> None:
    """Colunas novas do CQ (fase D) num workspace que já existe. As linhas limpas dessas tabelas perdem a
    `versao_base`, para o próximo pull trazê-las de novo com as colunas novas preenchidas (sem isso, a versão bate e o
    pull não as relê); as que têm pendência ficam como estão, e o push e o pull seguinte as acertam."""
    for tabela, colunas in _COLUNAS_V4.items():
        existentes = {r[1] for r in conn.execute(f"PRAGMA table_info({tabela})")}
        for nome, tipo in colunas:
            if nome not in existentes:
                conn.execute(f"ALTER TABLE {tabela} ADD COLUMN {nome} {tipo}")
    for cmd in INDICES_CQ:
        conn.execute(cmd)
    # O UPDATE passa pelos gatilhos de guarda: liga o interruptor, como a transação do plugin.
    conn.execute("UPDATE controle_escrita SET plugin = 1")
    for tabela in _COLUNAS_V4:
        conn.execute(
            f"UPDATE {tabela} SET versao_base = NULL WHERE sujo = 0 "
            f"AND uuid NOT IN (SELECT uuid FROM outbox WHERE tabela = '{tabela}')"
        )
    conn.execute("UPDATE controle_escrita SET plugin = 0")


def _v2_para_v3(conn) -> None:
    """Interruptor de escrita, gatilhos de guarda e as views das camadas, num workspace que já existe."""
    for cmd in INTERRUPTOR + gatilhos_guarda() + VIEWS:
        conn.execute(cmd)
    registrar_views(conn, conn.execute("SELECT strftime('%Y-%m-%dT%H:%M:%fZ', 'now')").fetchone()[0], VIEWS_GPKG)


def _v1_para_v2(conn) -> None:
    """Outbox com `chave` (uuid do item, para a idempotência do push) e `acao` (a transação local que gravou o item).
    Itens que já estavam lá: chave nova, e a hora como ação (os itens de uma transação têm a mesma hora)."""
    conn.execute("ALTER TABLE outbox ADD COLUMN chave TEXT")
    conn.execute("ALTER TABLE outbox ADD COLUMN acao TEXT")
    for (id_item,) in conn.execute("SELECT id FROM outbox").fetchall():
        conn.execute("UPDATE outbox SET chave = ?, acao = hora WHERE id = ?", (str(uuid.uuid4()), id_item))


# Migrações do esquema do workspace: versão de origem -> função(conexão) que leva à seguinte.
MIGRACOES: Dict[int, object] = {1: _v1_para_v2, 2: _v2_para_v3, 3: _v3_para_v4, 4: _v4_para_v5, 5: _v5_para_v6}


# --- núcleo do GeoPackage 1.2 (requisitos 10 a 13 e 21 a 23) ----------------------------------------------------------

WKT_4674 = (
    'GEOGCS["SIRGAS 2000",DATUM["Sistema_de_Referencia_Geocentrico_para_las_AmericaS_2000",'
    'SPHEROID["GRS 1980",6378137,298.257222101,AUTHORITY["EPSG","7019"]],TOWGS84[0,0,0,0,0,0,0],'
    'AUTHORITY["EPSG","6674"]],PRIMEM["Greenwich",0,AUTHORITY["EPSG","8901"]],'
    'UNIT["degree",0.0174532925199433,AUTHORITY["EPSG","9122"]],AUTHORITY["EPSG","4674"]]'
)
WKT_4326 = (
    'GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563,AUTHORITY["EPSG","7030"]],'
    'AUTHORITY["EPSG","6326"]],PRIMEM["Greenwich",0,AUTHORITY["EPSG","8901"]],'
    'UNIT["degree",0.0174532925199433,AUTHORITY["EPSG","9122"]],AUTHORITY["EPSG","4326"]]'
)

GPKG_ID_APLICACAO = 0x47504B47  # "GPKG"
GPKG_VERSAO = 10200  # 1.2.0

GPKG_NUCLEO = [
    "CREATE TABLE gpkg_spatial_ref_sys (\n"
    "    srs_name TEXT NOT NULL,\n"
    "    srs_id INTEGER NOT NULL PRIMARY KEY,\n"
    "    organization TEXT NOT NULL,\n"
    "    organization_coordsys_id INTEGER NOT NULL,\n"
    "    definition TEXT NOT NULL,\n"
    "    description TEXT\n"
    ")",
    "CREATE TABLE gpkg_contents (\n"
    "    table_name TEXT NOT NULL PRIMARY KEY,\n"
    "    data_type TEXT NOT NULL,\n"
    "    identifier TEXT UNIQUE,\n"
    "    description TEXT DEFAULT '',\n"
    "    last_change DATETIME NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),\n"
    "    min_x DOUBLE,\n"
    "    min_y DOUBLE,\n"
    "    max_x DOUBLE,\n"
    "    max_y DOUBLE,\n"
    "    srs_id INTEGER,\n"
    "    CONSTRAINT fk_gc_r_srs_id FOREIGN KEY (srs_id) REFERENCES gpkg_spatial_ref_sys(srs_id)\n"
    ")",
    "CREATE TABLE gpkg_geometry_columns (\n"
    "    table_name TEXT NOT NULL,\n"
    "    column_name TEXT NOT NULL,\n"
    "    geometry_type_name TEXT NOT NULL,\n"
    "    srs_id INTEGER NOT NULL,\n"
    "    z TINYINT NOT NULL,\n"
    "    m TINYINT NOT NULL,\n"
    "    CONSTRAINT pk_geom_cols PRIMARY KEY (table_name, column_name),\n"
    "    CONSTRAINT uk_gc_table_name UNIQUE (table_name),\n"
    "    CONSTRAINT fk_gc_tn FOREIGN KEY (table_name) REFERENCES gpkg_contents(table_name),\n"
    "    CONSTRAINT fk_gc_srs FOREIGN KEY (srs_id) REFERENCES gpkg_spatial_ref_sys (srs_id)\n"
    ")",
]

GPKG_SRS = [
    ("Undefined cartesian SRS", -1, "NONE", -1, "undefined", "undefined cartesian coordinate reference system"),
    ("Undefined geographic SRS", 0, "NONE", 0, "undefined", "undefined geographic coordinate reference system"),
    ("WGS 84 geodetic", 4326, "EPSG", 4326, WKT_4326, "longitude/latitude coordinates in decimal degrees on WGS 84"),
    ("SIRGAS 2000", SRID, "EPSG", SRID, WKT_4674, "SIRGAS 2000 geográfico, o das tabelas da CCAR"),
]


def ddl_completo() -> List[str]:
    """Todos os comandos para criar um workspace vazio (núcleo do GeoPackage, espelho, controle)."""
    cmds = list(GPKG_NUCLEO)
    cmds += [t.ddl() for t in TABELAS.values()]
    cmds += INDICES + INDICES_CQ + CONTROLE + INTERRUPTOR + gatilhos_guarda() + VIEWS + VIEWS_CQ
    return cmds
