-- GGC 002 (variante dblink): mapcartacomp da CCAR como views somente leitura sobre dblink no banco da GGC.
-- Compatível com PostgreSQL 9.6. Idempotente. Requer 001_server_dblink.sql.
-- ARQUIVO GERADO por scripts/db/gerar_espelho.py a partir do catálogo da CCAR: não editar à mão.
--
-- Diferente da variante postgres_fdw, aqui os filtros não descem para a CCAR: cada consulta traz a tabela inteira
-- (o que a conta do mapeamento enxerga). Prefira postgres_fdw quando a DBA puder escolher.

CREATE SCHEMA IF NOT EXISTS mapcartacomp;

COMMENT ON SCHEMA mapcartacomp IS
    'Feixe: espelho somente leitura do mapcartacomp da CCAR (views sobre dblink). Não escrever aqui.';

DROP VIEW IF EXISTS mapcartacomp.vw_carga_trabalho, mapcartacomp.vw_cq_amostra, mapcartacomp.vw_cq_amostra_all,
    mapcartacomp.vw_cq_inspecao;

DROP VIEW IF EXISTS mapcartacomp.ctrl_lote;
DROP VIEW IF EXISTS mapcartacomp.ctrl_lote_etapa;
DROP VIEW IF EXISTS mapcartacomp.sync_log;
DROP VIEW IF EXISTS mapcartacomp.cq_inspecao;
DROP VIEW IF EXISTS mapcartacomp.cq_amostra;
DROP VIEW IF EXISTS mapcartacomp.cq_plano;
DROP VIEW IF EXISTS mapcartacomp.carga_trabalho;
DROP VIEW IF EXISTS mapcartacomp.lote_etapa_hist;
DROP VIEW IF EXISTS mapcartacomp.lote_etapa;
DROP VIEW IF EXISTS mapcartacomp.lote;
DROP VIEW IF EXISTS mapcartacomp.calendario;
DROP VIEW IF EXISTS mapcartacomp.usuario_feixe;
DROP VIEW IF EXISTS mapcartacomp.fluxo_etapa;
DROP VIEW IF EXISTS mapcartacomp.fluxo;
DROP VIEW IF EXISTS mapcartacomp.atividade;
DROP VIEW IF EXISTS mapcartacomp.fase;
DROP VIEW IF EXISTS mapcartacomp.tema;
DROP VIEW IF EXISTS mapcartacomp.schema_version;

CREATE VIEW mapcartacomp.schema_version AS
    SELECT * FROM dblink('feixe_ccar_dblink', 'SELECT versao, nome, aplicado_em, aplicado_por FROM mapcartacomp.schema_version')
        AS t (versao integer,
           nome text,
           aplicado_em timestamp with time zone,
           aplicado_por text);

CREATE VIEW mapcartacomp.tema AS
    SELECT * FROM dblink('feixe_ccar_dblink', 'SELECT id, nome, ativo, criado_em, criado_por, atualizado_em, atualizado_por FROM mapcartacomp.tema')
        AS t (id integer,
           nome text,
           ativo boolean,
           criado_em timestamp with time zone,
           criado_por text,
           atualizado_em timestamp with time zone,
           atualizado_por text);

CREATE VIEW mapcartacomp.fase AS
    SELECT * FROM dblink('feixe_ccar_dblink', 'SELECT codigo, nome, ordem, status_nacional FROM mapcartacomp.fase')
        AS t (codigo text,
           nome text,
           ordem integer,
           status_nacional text);

CREATE VIEW mapcartacomp.atividade AS
    SELECT * FROM dblink('feixe_ccar_dblink', 'SELECT id, cod_projeto, id_tema, fase, nome, geracao, celula_largura, celula_altura, celula_unidade, elementos_cq, camada_alvo, ativo, criado_em, criado_por, atualizado_em, atualizado_por FROM mapcartacomp.atividade')
        AS t (id integer,
           cod_projeto integer,
           id_tema integer,
           fase text,
           nome text,
           geracao text,
           celula_largura numeric,
           celula_altura numeric,
           celula_unidade text,
           elementos_cq text[],
           camada_alvo text,
           ativo boolean,
           criado_em timestamp with time zone,
           criado_por text,
           atualizado_em timestamp with time zone,
           atualizado_por text);

CREATE VIEW mapcartacomp.fluxo AS
    SELECT * FROM dblink('feixe_ccar_dblink', 'SELECT id, cod_projeto, id_tema, uf, nome, ativo, criado_em, criado_por, atualizado_em, atualizado_por FROM mapcartacomp.fluxo')
        AS t (id integer,
           cod_projeto integer,
           id_tema integer,
           uf character(2),
           nome text,
           ativo boolean,
           criado_em timestamp with time zone,
           criado_por text,
           atualizado_em timestamp with time zone,
           atualizado_por text);

CREATE VIEW mapcartacomp.fluxo_etapa AS
    SELECT * FROM dblink('feixe_ccar_dblink', 'SELECT id, id_fluxo, ordem, id_atividade, nome, obrigatoria, repetivel, conta_revisao, criado_em, criado_por, atualizado_em, atualizado_por FROM mapcartacomp.fluxo_etapa')
        AS t (id integer,
           id_fluxo integer,
           ordem integer,
           id_atividade integer,
           nome text,
           obrigatoria boolean,
           repetivel boolean,
           conta_revisao boolean,
           criado_em timestamp with time zone,
           criado_por text,
           atualizado_em timestamp with time zone,
           atualizado_por text);

CREATE VIEW mapcartacomp.usuario_feixe AS
    SELECT * FROM dblink('feixe_ccar_dblink', 'SELECT usuario, equipe, gerente, ativo, criado_em, criado_por, atualizado_em, atualizado_por FROM mapcartacomp.usuario_feixe')
        AS t (usuario text,
           equipe text,
           gerente boolean,
           ativo boolean,
           criado_em timestamp with time zone,
           criado_por text,
           atualizado_em timestamp with time zone,
           atualizado_por text);

CREATE VIEW mapcartacomp.calendario AS
    SELECT * FROM dblink('feixe_ccar_dblink', 'SELECT uf, data, dia_util, descricao, criado_em, criado_por, atualizado_em, atualizado_por FROM mapcartacomp.calendario')
        AS t (uf character(2),
           data date,
           dia_util boolean,
           descricao text,
           criado_em timestamp with time zone,
           criado_por text,
           atualizado_em timestamp with time zone,
           atualizado_por text);

CREATE VIEW mapcartacomp.lote AS
    SELECT * FROM dblink('feixe_ccar_dblink', 'SELECT id, uuid, cod_projeto, id_tema, id_fluxo, uf, tipo, id_articulacao_scn, nome, geom, revisao_atual, id_lote_etapa_atual, status_nacional, criado_em, criado_por, atualizado_em, atualizado_por FROM mapcartacomp.lote')
        AS t (id integer,
           uuid uuid,
           cod_projeto integer,
           id_tema integer,
           id_fluxo integer,
           uf character(2),
           tipo text,
           id_articulacao_scn integer,
           nome text,
           geom geometry(MultiPolygon,4674),
           revisao_atual integer,
           id_lote_etapa_atual integer,
           status_nacional text,
           criado_em timestamp with time zone,
           criado_por text,
           atualizado_em timestamp with time zone,
           atualizado_por text);

CREATE VIEW mapcartacomp.lote_etapa AS
    SELECT * FROM dblink('feixe_ccar_dblink', 'SELECT id, uuid, id_lote, id_fluxo_etapa, uf, instancia, revisao, situacao, resultado, iniciada_em, concluida_em, concluida_por, criado_em, criado_por, atualizado_em, atualizado_por FROM mapcartacomp.lote_etapa')
        AS t (id integer,
           uuid uuid,
           id_lote integer,
           id_fluxo_etapa integer,
           uf character(2),
           instancia integer,
           revisao integer,
           situacao text,
           resultado text,
           iniciada_em timestamp with time zone,
           concluida_em timestamp with time zone,
           concluida_por text,
           criado_em timestamp with time zone,
           criado_por text,
           atualizado_em timestamp with time zone,
           atualizado_por text);

CREATE VIEW mapcartacomp.lote_etapa_hist AS
    SELECT * FROM dblink('feixe_ccar_dblink', 'SELECT id, uuid, id_lote_etapa, uf, acao, em, por, observacao, criado_em, criado_por, atualizado_em, atualizado_por FROM mapcartacomp.lote_etapa_hist')
        AS t (id bigint,
           uuid uuid,
           id_lote_etapa integer,
           uf character(2),
           acao text,
           em timestamp with time zone,
           por text,
           observacao text,
           criado_em timestamp with time zone,
           criado_por text,
           atualizado_em timestamp with time zone,
           atualizado_por text);

CREATE VIEW mapcartacomp.carga_trabalho AS
    SELECT * FROM dblink('feixe_ccar_dblink', 'SELECT id, uuid, id_lote_etapa, id_cq_plano, uf, responsavel, geom, concluido, concluido_em, criado_em, criado_por, atualizado_em, atualizado_por FROM mapcartacomp.carga_trabalho')
        AS t (id integer,
           uuid uuid,
           id_lote_etapa integer,
           id_cq_plano integer,
           uf character(2),
           responsavel text,
           geom geometry(MultiPolygon,4674),
           concluido boolean,
           concluido_em timestamp with time zone,
           criado_em timestamp with time zone,
           criado_por text,
           atualizado_em timestamp with time zone,
           atualizado_por text);

CREATE VIEW mapcartacomp.cq_plano AS
    SELECT * FROM dblink('feixe_ccar_dblink', 'SELECT id, uuid, id_lote_etapa, uf, elementos, orientacao, universo, nivel_inspecao, tamanho_lote_n, letra_codigo, tamanho_amostra_n, lqa, numero_aceitacao_ac, celula_largura, celula_altura, semente, resultado, criado_em, criado_por, atualizado_em, atualizado_por FROM mapcartacomp.cq_plano')
        AS t (id integer,
           uuid uuid,
           id_lote_etapa integer,
           uf character(2),
           elementos text[],
           orientacao text,
           universo text,
           nivel_inspecao text,
           tamanho_lote_n integer,
           letra_codigo text,
           tamanho_amostra_n integer,
           lqa numeric,
           numero_aceitacao_ac integer,
           celula_largura numeric,
           celula_altura numeric,
           semente bigint,
           resultado text,
           criado_em timestamp with time zone,
           criado_por text,
           atualizado_em timestamp with time zone,
           atualizado_por text);

CREATE VIEW mapcartacomp.cq_amostra AS
    SELECT * FROM dblink('feixe_ccar_dblink', 'SELECT id, uuid, id_cq_plano, id_carga_trabalho, uf, elemento, status, observacao, avaliado_por, avaliado_em, criado_em, criado_por, atualizado_em, atualizado_por FROM mapcartacomp.cq_amostra')
        AS t (id integer,
           uuid uuid,
           id_cq_plano integer,
           id_carga_trabalho integer,
           uf character(2),
           elemento text,
           status smallint,
           observacao text,
           avaliado_por text,
           avaliado_em timestamp with time zone,
           criado_em timestamp with time zone,
           criado_por text,
           atualizado_em timestamp with time zone,
           atualizado_por text);

CREATE VIEW mapcartacomp.cq_inspecao AS
    SELECT * FROM dblink('feixe_ccar_dblink', 'SELECT id, uuid, id_lote, id_carga_trabalho, uf, elemento, geom, anotacao, responsavel, tratado, tratado_em, tratado_por, criado_em, criado_por, atualizado_em, atualizado_por FROM mapcartacomp.cq_inspecao')
        AS t (id integer,
           uuid uuid,
           id_lote integer,
           id_carga_trabalho integer,
           uf character(2),
           elemento text,
           geom geometry(Point,4674),
           anotacao text,
           responsavel text,
           tratado boolean,
           tratado_em timestamp with time zone,
           tratado_por text,
           criado_em timestamp with time zone,
           criado_por text,
           atualizado_em timestamp with time zone,
           atualizado_por text);

CREATE VIEW mapcartacomp.sync_log AS
    SELECT * FROM dblink('feixe_ccar_dblink', 'SELECT id, usuario, uf, em, tabela, uuid, operacao, resultado, detalhe FROM mapcartacomp.sync_log')
        AS t (id bigint,
           usuario text,
           uf character(2),
           em timestamp with time zone,
           tabela text,
           uuid uuid,
           operacao text,
           resultado text,
           detalhe jsonb);

CREATE VIEW mapcartacomp.ctrl_lote_etapa AS
    SELECT * FROM dblink('feixe_ccar_dblink', 'SELECT id_lote_etapa, uuid, id_lote, uf, cod_projeto, id_tema, tema, tipo, lote, folha_revisao, etapa, ordem, fase, instancia, revisao, situacao, resultado, iniciada_em, concluida_em, cargas_total, cargas_concluidas, perc_concluidas, primeira_conclusao, ultima_conclusao, responsavel_principal, cq_planos, cq_resultado, cq_por_elemento FROM mapcartacomp.ctrl_lote_etapa')
        AS t (id_lote_etapa integer,
           uuid uuid,
           id_lote integer,
           uf character(2),
           cod_projeto integer,
           id_tema integer,
           tema text,
           tipo text,
           lote text,
           folha_revisao text,
           etapa text,
           ordem integer,
           fase text,
           instancia integer,
           revisao integer,
           situacao text,
           resultado text,
           iniciada_em timestamp with time zone,
           concluida_em timestamp with time zone,
           cargas_total bigint,
           cargas_concluidas bigint,
           perc_concluidas numeric,
           primeira_conclusao timestamp with time zone,
           ultima_conclusao timestamp with time zone,
           responsavel_principal text,
           cq_planos bigint,
           cq_resultado text,
           cq_por_elemento jsonb);

CREATE VIEW mapcartacomp.ctrl_lote AS
    SELECT * FROM dblink('feixe_ccar_dblink', 'SELECT id_lote, uuid, uf, cod_projeto, id_tema, tema, tipo, nome, id_articulacao_scn, folha_revisao, revisao_atual, status_nacional, etapa, fase, situacao, cargas_total, cargas_concluidas, perc_concluidas, responsavel_principal, ultimo_cq_folha_revisao, ultimo_cq_resultado, ultimo_cq_por_elemento, ocorrencias, ocorrencias_tratadas, inicio, fim, lead_time, geom FROM mapcartacomp.ctrl_lote')
        AS t (id_lote integer,
           uuid uuid,
           uf character(2),
           cod_projeto integer,
           id_tema integer,
           tema text,
           tipo text,
           nome text,
           id_articulacao_scn integer,
           folha_revisao text,
           revisao_atual integer,
           status_nacional text,
           etapa text,
           fase text,
           situacao text,
           cargas_total bigint,
           cargas_concluidas bigint,
           perc_concluidas numeric,
           responsavel_principal text,
           ultimo_cq_folha_revisao text,
           ultimo_cq_resultado text,
           ultimo_cq_por_elemento jsonb,
           ocorrencias bigint,
           ocorrencias_tratadas bigint,
           inicio timestamp with time zone,
           fim timestamp with time zone,
           lead_time interval,
           geom geometry(MultiPolygon,4674));
