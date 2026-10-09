-- GGC 002 (variante postgres_fdw): mapcartacomp da CCAR como foreign tables somente leitura no banco da GGC.
-- Compatível com PostgreSQL 9.6. Idempotente: remove as foreign tables do espelho e as importa de novo, de modo que
-- reaplicar depois de uma migração na CCAR traz as colunas novas. Requer 001_server_fdw.sql.
--
-- Só as tabelas e as views de acompanhamento (ctrl_*). As views vw_* filtram por current_user e são recriadas
-- localmente em 003_views_compat.sql, para filtrar pelo usuário da GGC e não pela conta do mapeamento.

CREATE SCHEMA IF NOT EXISTS mapcartacomp;

COMMENT ON SCHEMA mapcartacomp IS
    'Feixe: espelho somente leitura do mapcartacomp da CCAR (foreign tables). Não escrever aqui.';

DROP VIEW IF EXISTS mapcartacomp.vw_carga_trabalho, mapcartacomp.vw_cq_amostra, mapcartacomp.vw_cq_amostra_all,
    mapcartacomp.vw_cq_inspecao;

DROP FOREIGN TABLE IF EXISTS
    mapcartacomp.schema_version, mapcartacomp.tema, mapcartacomp.fase, mapcartacomp.atividade, mapcartacomp.fluxo,
    mapcartacomp.fluxo_etapa, mapcartacomp.usuario_feixe, mapcartacomp.calendario, mapcartacomp.lote,
    mapcartacomp.lote_etapa, mapcartacomp.lote_etapa_hist, mapcartacomp.carga_trabalho, mapcartacomp.cq_plano,
    mapcartacomp.cq_amostra, mapcartacomp.cq_inspecao, mapcartacomp.sync_log, mapcartacomp.ctrl_lote_etapa,
    mapcartacomp.ctrl_lote;

IMPORT FOREIGN SCHEMA mapcartacomp LIMIT TO (
    schema_version, tema, fase, atividade, fluxo, fluxo_etapa, usuario_feixe, calendario, lote, lote_etapa,
    lote_etapa_hist, carga_trabalho, cq_plano, cq_amostra, cq_inspecao, sync_log, ctrl_lote_etapa, ctrl_lote
) FROM SERVER feixe_ccar INTO mapcartacomp;
