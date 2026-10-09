-- 007: views de compatibilidade (para quem continua operando direto no QGIS, como em bc100ggcdf_apoio) e views de
-- acompanhamento (ctrl_lote_etapa, ctrl_lote). Compatível com PostgreSQL 9.6. Idempotente.
--
-- As views vw_* são filtradas por current_user e editáveis por RULE. Inserir pela vw_cq_inspecao exige o uuid
-- preenchido pelo cliente (no QGIS, valor padrão do campo = uuid()), porque o banco nunca gera uuid.

-- Rótulo "2534-3" (folha 2534 na revisão 3); lote livre usa só o nome.
CREATE OR REPLACE FUNCTION mapcartacomp.f_rotulo(p_tipo text, p_nome text, p_revisao integer) RETURNS text
LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE WHEN p_tipo = 'folha' THEN p_nome || '-' || coalesce(p_revisao, 0) ELSE p_nome END
$$;

-- Cargas do usuário ------------------------------------------------------------------------------------------------

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

CREATE OR REPLACE RULE upd_vw_carga_trabalho AS ON UPDATE TO mapcartacomp.vw_carga_trabalho DO INSTEAD
    UPDATE mapcartacomp.carga_trabalho SET concluido = NEW.concluido WHERE id = OLD.id_carga_trabalho;

-- Amostras ----------------------------------------------------------------------------------------------------------

-- Todas as amostras, com a carga de CQ que as carrega (o responsável vem da carga).
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

CREATE OR REPLACE RULE upd_vw_cq_amostra_all AS ON UPDATE TO mapcartacomp.vw_cq_amostra_all DO INSTEAD
    UPDATE mapcartacomp.cq_amostra SET status = NEW.status, observacao = NEW.observacao WHERE id = OLD.id_cq_amostra;
CREATE OR REPLACE RULE del_vw_cq_amostra_all AS ON DELETE TO mapcartacomp.vw_cq_amostra_all DO INSTEAD
    DELETE FROM mapcartacomp.cq_amostra WHERE id = OLD.id_cq_amostra;

-- Amostras do usuário, só da passagem de CQ mais recente de cada lote (como a vw_cq_amostra do DF).
CREATE OR REPLACE VIEW mapcartacomp.vw_cq_amostra AS
SELECT id_cq_amostra, uuid, id_carga_trabalho, responsavel, geom, elemento, status, observacao, concluido,
       concluido_em, folha_revisao
  FROM (SELECT v.*, rank() OVER (PARTITION BY v.id_lote ORDER BY v.revisao DESC, v.instancia DESC) AS ordem
          FROM mapcartacomp.vw_cq_amostra_all v
         WHERE v.responsavel = current_user) s
 WHERE s.ordem = 1;

CREATE OR REPLACE RULE upd_vw_cq_amostra AS ON UPDATE TO mapcartacomp.vw_cq_amostra DO INSTEAD
    UPDATE mapcartacomp.cq_amostra SET status = NEW.status, observacao = NEW.observacao WHERE id = OLD.id_cq_amostra;

-- Ocorrências de inspeção do usuário ----------------------------------------------------------------------------------
-- Ao inserir sem lote/carga, usa a carga do usuário que contém o ponto (a mais recente).

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

CREATE OR REPLACE RULE ins_vw_cq_inspecao AS ON INSERT TO mapcartacomp.vw_cq_inspecao DO INSTEAD
    INSERT INTO mapcartacomp.cq_inspecao (uuid, id_lote, id_carga_trabalho, elemento, responsavel, anotacao, geom)
    SELECT NEW.uuid,
           coalesce(NEW.id_lote, x.id_lote),
           coalesce(NEW.id_carga_trabalho, x.id_carga),
           NEW.elemento,
           current_user,
           NEW.anotacao,
           NEW.geom
      FROM (SELECT NULL::integer AS z) um
      LEFT JOIN LATERAL (
            SELECT le.id_lote, c.id AS id_carga
              FROM mapcartacomp.carga_trabalho c
              JOIN mapcartacomp.lote_etapa le ON le.id = c.id_lote_etapa
             WHERE c.responsavel = current_user AND c.geom && NEW.geom AND ST_Intersects(c.geom, NEW.geom)
             ORDER BY c.criado_em DESC, c.id DESC
             LIMIT 1) x ON true
    RETURNING id, uuid, id_lote, id_carga_trabalho, elemento, responsavel, anotacao, criado_em, tratado, geom;

CREATE OR REPLACE RULE upd_vw_cq_inspecao AS ON UPDATE TO mapcartacomp.vw_cq_inspecao DO INSTEAD
    UPDATE mapcartacomp.cq_inspecao
       SET elemento = NEW.elemento, anotacao = NEW.anotacao, tratado = NEW.tratado, geom = NEW.geom
     WHERE id = OLD.id_cq_inspecao;
CREATE OR REPLACE RULE del_vw_cq_inspecao AS ON DELETE TO mapcartacomp.vw_cq_inspecao DO INSTEAD
    DELETE FROM mapcartacomp.cq_inspecao WHERE id = OLD.id_cq_inspecao;

-- Acompanhamento por passagem de etapa ----------------------------------------------------------------------------
-- Uma linha por lote_etapa: cargas e conclusão, e para etapas de CQ o resultado e a contagem por elemento.

CREATE OR REPLACE VIEW mapcartacomp.ctrl_lote_etapa AS
WITH cargas AS (
    SELECT c.id_lote_etapa,
           count(*) AS cargas_total,
           count(*) FILTER (WHERE c.concluido) AS cargas_concluidas,
           min(c.concluido_em) AS primeira_conclusao,
           max(c.concluido_em) AS ultima_conclusao,
           mode() WITHIN GROUP (ORDER BY c.responsavel) AS responsavel_principal
      FROM mapcartacomp.carga_trabalho c
     GROUP BY c.id_lote_etapa
), por_elemento AS (
    SELECT p.id_lote_etapa,
           a.elemento,
           count(*) AS amostras,
           count(*) FILTER (WHERE a.status IS NULL) AS pendentes,
           count(*) FILTER (WHERE a.status = 1) AS conformes,
           count(*) FILTER (WHERE a.status = 0) AS nao_conformes
      FROM mapcartacomp.cq_amostra a
      JOIN mapcartacomp.cq_plano p ON p.id = a.id_cq_plano
     GROUP BY p.id_lote_etapa, a.elemento
), cq AS (
    SELECT e.id_lote_etapa,
           jsonb_object_agg(e.elemento, jsonb_build_object('amostras', e.amostras, 'pendentes', e.pendentes,
                            'conformes', e.conformes, 'nao_conformes', e.nao_conformes)) AS cq_por_elemento
      FROM por_elemento e
     GROUP BY e.id_lote_etapa
), planos AS (
    SELECT p.id_lote_etapa,
           count(*) AS cq_planos,
           CASE WHEN bool_or(p.resultado = 'reprovado') THEN 'reprovado'
                WHEN bool_or(p.resultado = 'pendente') THEN 'pendente'
                ELSE 'aprovado' END AS cq_resultado
      FROM mapcartacomp.cq_plano p
     GROUP BY p.id_lote_etapa
)
SELECT le.id AS id_lote_etapa,
       le.uuid,
       le.id_lote,
       le.uf,
       l.cod_projeto,
       l.id_tema,
       t.nome AS tema,
       l.tipo,
       l.nome AS lote,
       mapcartacomp.f_rotulo(l.tipo, l.nome, le.revisao) AS folha_revisao,
       fe.nome AS etapa,
       fe.ordem,
       at.fase,
       le.instancia,
       le.revisao,
       le.situacao,
       le.resultado,
       le.iniciada_em,
       le.concluida_em,
       coalesce(c.cargas_total, 0) AS cargas_total,
       coalesce(c.cargas_concluidas, 0) AS cargas_concluidas,
       round(100.0 * c.cargas_concluidas / nullif(c.cargas_total, 0), 2) AS perc_concluidas,
       c.primeira_conclusao,
       c.ultima_conclusao,
       c.responsavel_principal,
       pl.cq_planos,
       pl.cq_resultado,
       cq.cq_por_elemento
  FROM mapcartacomp.lote_etapa le
  JOIN mapcartacomp.lote l ON l.id = le.id_lote
  JOIN mapcartacomp.tema t ON t.id = l.id_tema
  JOIN mapcartacomp.fluxo_etapa fe ON fe.id = le.id_fluxo_etapa
  JOIN mapcartacomp.atividade at ON at.id = fe.id_atividade
  LEFT JOIN cargas c ON c.id_lote_etapa = le.id
  LEFT JOIN planos pl ON pl.id_lote_etapa = le.id
  LEFT JOIN cq ON cq.id_lote_etapa = le.id;

-- Acompanhamento por lote (substitui ctrl_folha_revisao) --------------------------------------------------------------
-- Uma linha por lote: etapa atual e seu andamento, status nacional, último CQ, ocorrências e lead time.

CREATE OR REPLACE VIEW mapcartacomp.ctrl_lote AS
WITH ultimo_cq AS (
    SELECT DISTINCT ON (e.id_lote) e.id_lote, e.folha_revisao, e.cq_resultado, e.cq_por_elemento
      FROM mapcartacomp.ctrl_lote_etapa e
     WHERE e.cq_planos > 0
     ORDER BY e.id_lote, e.revisao DESC, e.instancia DESC, e.id_lote_etapa DESC
), ocorrencias AS (
    SELECT i.id_lote,
           count(*) AS ocorrencias,
           count(*) FILTER (WHERE i.tratado) AS ocorrencias_tratadas
      FROM mapcartacomp.cq_inspecao i
     GROUP BY i.id_lote
), tempos AS (
    SELECT le.id_lote,
           least(min(le.iniciada_em), min(c.primeira_conclusao)) AS inicio,
           greatest(max(le.concluida_em), max(c.ultima_conclusao)) AS ultimo_movimento
      FROM mapcartacomp.lote_etapa le
      LEFT JOIN mapcartacomp.ctrl_lote_etapa c ON c.id_lote_etapa = le.id
     GROUP BY le.id_lote
)
SELECT l.id AS id_lote,
       l.uuid,
       l.uf,
       l.cod_projeto,
       l.id_tema,
       t.nome AS tema,
       l.tipo,
       l.nome,
       l.id_articulacao_scn,
       mapcartacomp.f_rotulo(l.tipo, l.nome, l.revisao_atual) AS folha_revisao,
       l.revisao_atual,
       l.status_nacional,
       a.etapa,
       a.fase,
       a.situacao,
       a.cargas_total,
       a.cargas_concluidas,
       a.perc_concluidas,
       a.responsavel_principal,
       u.folha_revisao AS ultimo_cq_folha_revisao,
       u.cq_resultado AS ultimo_cq_resultado,
       u.cq_por_elemento AS ultimo_cq_por_elemento,
       coalesce(o.ocorrencias, 0) AS ocorrencias,
       coalesce(o.ocorrencias_tratadas, 0) AS ocorrencias_tratadas,
       tp.inicio,
       CASE WHEN l.status_nacional = 'CONCLUIDA' THEN tp.ultimo_movimento END AS fim,
       (CASE WHEN l.status_nacional = 'CONCLUIDA' THEN tp.ultimo_movimento ELSE now() END) - tp.inicio AS lead_time,
       coalesce(l.geom, ST_Multi(art.geom)::geometry(MultiPolygon, 4674)) AS geom
  FROM mapcartacomp.lote l
  JOIN mapcartacomp.tema t ON t.id = l.id_tema
  LEFT JOIN mapcartacomp.ctrl_lote_etapa a ON a.id_lote_etapa = l.id_lote_etapa_atual
  LEFT JOIN ultimo_cq u ON u.id_lote = l.id
  LEFT JOIN ocorrencias o ON o.id_lote = l.id
  LEFT JOIN tempos tp ON tp.id_lote = l.id
  LEFT JOIN mapcartctrl.t_articulacao_scn art ON art.id_articulacao_scn = l.id_articulacao_scn;
