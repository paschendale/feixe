"""Esquema do workspace local: tabelas espelho, referências, controle e o mínimo do GeoPackage.

Espelho = subconjunto de `mapcartacomp` que a execução (APM e avaliador, D-111) precisa offline, com as mesmas colunas
de domínio da CCAR. Diferenças, todas de propósito:

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

from typing import Dict, List, Optional, Tuple

from .geometria import SRID

# Versão do esquema do workspace. Subiu sem migração em MIGRACOES: o workspace é recriado (é cache), levando junto
# a outbox e o sync_log, que são o que não se pode perder.
VERSAO = 1

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

    @property
    def colunas_dominio(self) -> List[str]:
        return [c for c, _ in self.dominio] + (["geom"] if self.geom else [])

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
             ("atualizado_em", "DATETIME")],
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
            descricao="Fila de folhas por pessoa",
        ),
        _sync(
            "cq_plano",
            [("id_lote_etapa", "INTEGER"), ("id_atividade", "INTEGER"), ("uf", "TEXT"), ("orientacao", "TEXT"),
             ("universo", "TEXT"), ("nivel_inspecao", "TEXT"), ("tamanho_lote_n", "INTEGER"),
             ("letra_codigo", "TEXT"), ("tamanho_amostra_n", "INTEGER"), ("lqa", "DOUBLE"),
             ("numero_aceitacao_ac", "INTEGER"), ("celula_largura", "DOUBLE"), ("celula_altura", "DOUBLE"),
             ("semente", "INTEGER"), ("resultado", "TEXT")],
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
             ("ciente_por", "TEXT")],
            geom="POINT", descricao="Ocorrências de inspeção",
        ),
    ]
}
# fmt: on

ESPELHO = [n for n, t in TABELAS.items() if t.sincroniza]

# Índices do que a execução filtra e junta.
INDICES = [
    "CREATE INDEX carga_trabalho_responsavel_idx ON carga_trabalho (responsavel, concluido)",
    "CREATE INDEX carga_trabalho_lote_etapa_idx ON carga_trabalho (id_lote_etapa)",
    "CREATE INDEX lote_etapa_lote_idx ON lote_etapa (id_lote)",
    "CREATE INDEX fila_folha_responsavel_idx ON fila_folha (responsavel, atribuida_em, ordem)",
    "CREATE INDEX cq_amostra_carga_idx ON cq_amostra (id_carga_trabalho)",
    "CREATE INDEX cq_inspecao_lote_idx ON cq_inspecao (id_lote)",
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
    "    erro TEXT\n"
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

# Migrações do esquema do workspace: versão de origem -> função(conexão) que leva à seguinte. Vazio na versão 1.
MIGRACOES: Dict[int, object] = {}


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
    cmds += INDICES + CONTROLE
    return cmds
