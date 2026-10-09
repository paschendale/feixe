-- GGC 003: views de compatibilidade sobre o espelho (vale para as duas variantes, postgres_fdw e dblink).
-- Compatível com PostgreSQL 9.6. Idempotente. Requer 002.
--
-- Mesmas views da CCAR (vw_carga_trabalho, vw_cq_amostra, vw_cq_amostra_all, vw_cq_inspecao), mas filtradas pelo
-- usuário conectado no banco da GGC e somente leitura: quem quer editar usa o plugin, que escreve na CCAR.

CREATE OR REPLACE FUNCTION mapcartacomp.f_rotulo(p_tipo text, p_nome text, p_revisao integer) RETURNS text
LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE WHEN p_tipo = 'folha' THEN p_nome || '-' || coalesce(p_revisao, 0) ELSE p_nome END
$$;

CREATE OR REPLACE VIEW mapcartacomp.vw_carga_trabalho AS
SELECT c.id AS id_carga_trabalho,
       c.uuid,
       fe.id_atividade,
       at.nome AS atividade,
       fe.nome AS etapa,
       mapcartacomp.f_rotulo(l.tipo, l.nome, le.revisao) AS folha_revisao,
       c.criado_em AS criada_em,
       c.concluido,
       c.concluido_em,
       c.geom
  FROM mapcartacomp.carga_trabalho c
  JOIN mapcartacomp.lote_etapa le ON le.id = c.id_lote_etapa
  JOIN mapcartacomp.lote l ON l.id = le.id_lote
  JOIN mapcartacomp.fluxo_etapa fe ON fe.id = le.id_fluxo_etapa
  JOIN mapcartacomp.atividade at ON at.id = fe.id_atividade
 WHERE c.responsavel = current_user;

CREATE OR REPLACE VIEW mapcartacomp.vw_cq_amostra_all AS
SELECT a.id AS id_cq_amostra,
       a.uuid,
       c.id AS id_carga_trabalho,
       c.responsavel,
       c.geom,
       a.elemento,
       a.status,
       a.observacao,
       c.concluido,
       c.concluido_em,
       mapcartacomp.f_rotulo(l.tipo, l.nome, le.revisao) AS folha_revisao,
       le.id_lote,
       le.revisao,
       le.instancia
  FROM mapcartacomp.cq_amostra a
  JOIN mapcartacomp.carga_trabalho c ON c.id = a.id_carga_trabalho
  JOIN mapcartacomp.lote_etapa le ON le.id = c.id_lote_etapa
  JOIN mapcartacomp.lote l ON l.id = le.id_lote;

CREATE OR REPLACE VIEW mapcartacomp.vw_cq_amostra AS
SELECT id_cq_amostra, uuid, id_carga_trabalho, responsavel, geom, elemento, status, observacao, concluido,
       concluido_em, folha_revisao
  FROM (SELECT v.*, rank() OVER (PARTITION BY v.id_lote ORDER BY v.revisao DESC, v.instancia DESC) AS ordem
          FROM mapcartacomp.vw_cq_amostra_all v
         WHERE v.responsavel = current_user) s
 WHERE s.ordem = 1;

CREATE OR REPLACE VIEW mapcartacomp.vw_cq_inspecao AS
SELECT i.id AS id_cq_inspecao,
       i.uuid,
       i.id_lote,
       i.id_carga_trabalho,
       i.elemento,
       i.responsavel,
       i.anotacao,
       i.criado_em,
       i.tratado,
       i.geom
  FROM mapcartacomp.cq_inspecao i
 WHERE i.responsavel = current_user;
