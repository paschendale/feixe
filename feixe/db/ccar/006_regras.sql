-- 006: regras no banco (PL/pgSQL compatível com PostgreSQL 9.6). Idempotente.
--
-- Só derivações: nenhuma regra muda a etapa de um lote. Quem avança, pula, volta ou repete etapas é o supervisor;
-- aqui se calculam o que decorre disso (status nacional, revisão, etapa atual) e o que decorre das avaliações
-- (carga de CQ concluída, resultado do plano), que só alimentam a lista "prontas para avançar".

-- atualizado_em/atualizado_por em todo UPDATE ------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION mapcartacomp.f_tocar_atualizado() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    NEW.atualizado_em := now();
    NEW.atualizado_por := current_user;
    RETURN NEW;
END
$$;

DO $$
DECLARE
    t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['tema', 'atividade', 'fluxo', 'fluxo_etapa', 'usuario_feixe', 'calendario', 'lote',
                             'lote_etapa', 'lote_etapa_hist', 'carga_trabalho', 'cq_plano', 'cq_amostra', 'cq_inspecao']
    LOOP
        EXECUTE format('DROP TRIGGER IF EXISTS t00_atualizado ON mapcartacomp.%I', t);
        EXECUTE format('CREATE TRIGGER t00_atualizado BEFORE UPDATE ON mapcartacomp.%I '
                       'FOR EACH ROW EXECUTE PROCEDURE mapcartacomp.f_tocar_atualizado()', t);
    END LOOP;
END
$$;

-- uf herdada do pai quando não informada ------------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION mapcartacomp.f_herdar_uf() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.uf IS NOT NULL THEN
        RETURN NEW;
    END IF;
    IF TG_TABLE_NAME = 'lote_etapa' THEN
        SELECT uf INTO NEW.uf FROM mapcartacomp.lote WHERE id = NEW.id_lote;
    ELSIF TG_TABLE_NAME IN ('carga_trabalho', 'cq_plano', 'lote_etapa_hist') THEN
        SELECT uf INTO NEW.uf FROM mapcartacomp.lote_etapa WHERE id = NEW.id_lote_etapa;
    ELSIF TG_TABLE_NAME = 'cq_amostra' THEN
        SELECT uf INTO NEW.uf FROM mapcartacomp.carga_trabalho WHERE id = NEW.id_carga_trabalho;
    ELSIF TG_TABLE_NAME = 'cq_inspecao' THEN
        SELECT uf INTO NEW.uf FROM mapcartacomp.lote WHERE id = NEW.id_lote;
    END IF;
    RETURN NEW;
END
$$;

DO $$
DECLARE
    t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['lote_etapa', 'lote_etapa_hist', 'carga_trabalho', 'cq_plano', 'cq_amostra', 'cq_inspecao']
    LOOP
        EXECUTE format('DROP TRIGGER IF EXISTS t01_uf ON mapcartacomp.%I', t);
        EXECUTE format('CREATE TRIGGER t01_uf BEFORE INSERT ON mapcartacomp.%I '
                       'FOR EACH ROW EXECUTE PROCEDURE mapcartacomp.f_herdar_uf()', t);
    END LOOP;
END
$$;

-- concluido_em da carga --------------------------------------------------------------------------------------------
-- Ao concluir: guarda a hora informada (conclusão feita offline e sincronizada depois) ou, se não veio, agora.
-- Ao desfazer: limpa. Num INSERT já concluído (migração, sincronização) mantém a hora que veio.

CREATE OR REPLACE FUNCTION mapcartacomp.f_carga_concluido_em() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NOT NEW.concluido THEN
        NEW.concluido_em := NULL;
    ELSIF TG_OP = 'INSERT' THEN
        NEW.concluido_em := coalesce(NEW.concluido_em, now());
    ELSIF NOT OLD.concluido THEN
        IF NEW.concluido_em IS NULL OR NEW.concluido_em IS NOT DISTINCT FROM OLD.concluido_em THEN
            NEW.concluido_em := now();
        END IF;
    END IF;
    RETURN NEW;
END
$$;

DROP TRIGGER IF EXISTS t10_concluido_em ON mapcartacomp.carga_trabalho;
CREATE TRIGGER t10_concluido_em BEFORE INSERT OR UPDATE ON mapcartacomp.carga_trabalho
    FOR EACH ROW EXECUTE PROCEDURE mapcartacomp.f_carga_concluido_em();

-- avaliado_em/avaliado_por da amostra ------------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION mapcartacomp.f_amostra_avaliacao() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    -- OLD só é lido em UPDATE: no 9.6, ler OLD num INSERT é erro.
    IF NEW.status IS NULL THEN
        NEW.avaliado_em := NULL;
        NEW.avaliado_por := NULL;
    ELSIF TG_OP = 'INSERT' THEN
        NEW.avaliado_em := coalesce(NEW.avaliado_em, now());
        NEW.avaliado_por := coalesce(NEW.avaliado_por, current_user);
    ELSIF OLD.status IS DISTINCT FROM NEW.status THEN
        IF NEW.avaliado_em IS NULL OR NEW.avaliado_em IS NOT DISTINCT FROM OLD.avaliado_em THEN
            NEW.avaliado_em := now();
        END IF;
        IF NEW.avaliado_por IS NULL OR NEW.avaliado_por IS NOT DISTINCT FROM OLD.avaliado_por THEN
            NEW.avaliado_por := current_user;
        END IF;
    END IF;
    RETURN NEW;
END
$$;

DROP TRIGGER IF EXISTS t10_avaliacao ON mapcartacomp.cq_amostra;
CREATE TRIGGER t10_avaliacao BEFORE INSERT OR UPDATE ON mapcartacomp.cq_amostra
    FOR EACH ROW EXECUTE PROCEDURE mapcartacomp.f_amostra_avaliacao();

-- resultado do plano de CQ ----------------------------------------------------------------------------------------
-- pendente enquanto houver amostra sem avaliação (ou sem Ac definido); reprovado se em algum elemento os não
-- conformes excedem Ac; aprovado caso contrário. Não muda etapa nenhuma.

CREATE OR REPLACE FUNCTION mapcartacomp.f_cq_plano_resultado(p_plano integer, p_ac integer) RETURNS text
LANGUAGE sql STABLE AS $$
    SELECT CASE
        WHEN count(*) = 0 OR count(*) FILTER (WHERE status IS NULL) > 0 OR p_ac IS NULL THEN 'pendente'
        WHEN max(nc) > p_ac THEN 'reprovado'
        ELSE 'aprovado'
    END
    FROM (
        SELECT a.status, count(*) FILTER (WHERE a.status = 0) OVER (PARTITION BY a.elemento) AS nc
        FROM mapcartacomp.cq_amostra a
        WHERE a.id_cq_plano = p_plano
    ) s
$$;

CREATE OR REPLACE FUNCTION mapcartacomp.f_cq_plano_recalcular() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    NEW.resultado := mapcartacomp.f_cq_plano_resultado(NEW.id, NEW.numero_aceitacao_ac);
    RETURN NEW;
END
$$;

DROP TRIGGER IF EXISTS t10_resultado ON mapcartacomp.cq_plano;
CREATE TRIGGER t10_resultado BEFORE UPDATE ON mapcartacomp.cq_plano
    FOR EACH ROW EXECUTE PROCEDURE mapcartacomp.f_cq_plano_recalcular();

-- Depois de mudar amostras: a carga de CQ conclui quando todas as suas amostras têm status (e volta a pendente se
-- alguma avaliação for desfeita), e o plano é recalculado.

CREATE OR REPLACE FUNCTION mapcartacomp.f_amostra_derivar_um(p_carga integer, p_plano integer) RETURNS void
LANGUAGE plpgsql AS $$
BEGIN
    UPDATE mapcartacomp.carga_trabalho c
       SET concluido = d.todas
      FROM (SELECT count(*) > 0 AND bool_and(status IS NOT NULL) AS todas
              FROM mapcartacomp.cq_amostra WHERE id_carga_trabalho = p_carga) d
     WHERE c.id = p_carga AND c.concluido IS DISTINCT FROM d.todas;

    UPDATE mapcartacomp.cq_plano p
       SET resultado = mapcartacomp.f_cq_plano_resultado(p.id, p.numero_aceitacao_ac)
     WHERE p.id = p_plano
       AND p.resultado IS DISTINCT FROM mapcartacomp.f_cq_plano_resultado(p.id, p.numero_aceitacao_ac);
END
$$;

CREATE OR REPLACE FUNCTION mapcartacomp.f_amostra_derivar() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP IN ('UPDATE', 'DELETE') THEN
        PERFORM mapcartacomp.f_amostra_derivar_um(OLD.id_carga_trabalho, OLD.id_cq_plano);
    END IF;
    IF TG_OP IN ('INSERT', 'UPDATE') THEN
        PERFORM mapcartacomp.f_amostra_derivar_um(NEW.id_carga_trabalho, NEW.id_cq_plano);
    END IF;
    RETURN NULL;
END
$$;

DROP TRIGGER IF EXISTS t20_derivar ON mapcartacomp.cq_amostra;
CREATE TRIGGER t20_derivar AFTER INSERT OR UPDATE OF status, id_carga_trabalho, id_cq_plano OR DELETE
    ON mapcartacomp.cq_amostra FOR EACH ROW EXECUTE PROCEDURE mapcartacomp.f_amostra_derivar();

-- Revisão de uma passagem de etapa, quando não informada ------------------------------------------------------------
-- Passagem por etapa que conta revisão: 1 + passagens anteriores (não puladas) por etapas que contam revisão.
-- Demais etapas: a revisão corrente da folha.

CREATE OR REPLACE FUNCTION mapcartacomp.f_lote_etapa_revisao() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    v_conta boolean;
    v_anteriores integer;
BEGIN
    IF NEW.revisao IS NOT NULL THEN
        RETURN NEW;
    END IF;
    SELECT conta_revisao INTO v_conta FROM mapcartacomp.fluxo_etapa WHERE id = NEW.id_fluxo_etapa;
    SELECT count(*) INTO v_anteriores
      FROM mapcartacomp.lote_etapa le JOIN mapcartacomp.fluxo_etapa fe ON fe.id = le.id_fluxo_etapa
     WHERE le.id_lote = NEW.id_lote AND fe.conta_revisao AND le.situacao <> 'pulada';
    NEW.revisao := v_anteriores + CASE WHEN v_conta THEN 1 ELSE 0 END;
    RETURN NEW;
END
$$;

DROP TRIGGER IF EXISTS t10_revisao ON mapcartacomp.lote_etapa;
CREATE TRIGGER t10_revisao BEFORE INSERT ON mapcartacomp.lote_etapa
    FOR EACH ROW EXECUTE PROCEDURE mapcartacomp.f_lote_etapa_revisao();

-- Derivações do lote a partir das passagens de etapa ----------------------------------------------------------------
-- Etapa atual: a em andamento mais recente; sem nenhuma em andamento, a última concluída; sem nenhuma, a primeira
-- pendente. Status nacional: PLANEJADA se nada começou; senão o da fase da etapa atual, e no envio à GCQ o resultado
-- registrado pelo supervisor decide entre ENTREGUE_GCQ, CONCLUIDA (aprovada) e DEVOLVIDA (devolvida).
-- Revisão atual: a maior revisão entre as passagens não puladas.

CREATE OR REPLACE FUNCTION mapcartacomp.f_lote_derivar(p_lote integer) RETURNS void
LANGUAGE plpgsql AS $$
DECLARE
    v_atual integer;
    v_situacao text;
    v_fase text;
    v_status_fase text;
    v_resultado text;
    v_status text;
    v_revisao integer;
BEGIN
    SELECT le.id, le.situacao, fe_at.fase, fa.status_nacional, le.resultado
      INTO v_atual, v_situacao, v_fase, v_status_fase, v_resultado
      FROM mapcartacomp.lote_etapa le
      JOIN mapcartacomp.fluxo_etapa fe ON fe.id = le.id_fluxo_etapa
      JOIN mapcartacomp.atividade fe_at ON fe_at.id = fe.id_atividade
      JOIN mapcartacomp.fase fa ON fa.codigo = fe_at.fase
     WHERE le.id_lote = p_lote AND le.situacao <> 'pulada'
     ORDER BY CASE le.situacao WHEN 'em_andamento' THEN 0 WHEN 'concluida' THEN 1 ELSE 2 END,
              CASE WHEN le.situacao = 'pendente' THEN fe.ordem END,
              CASE WHEN le.situacao = 'pendente' THEN le.instancia END,
              CASE WHEN le.situacao = 'em_andamento' THEN le.iniciada_em ELSE le.concluida_em END DESC NULLS LAST,
              fe.ordem DESC, le.instancia DESC, le.id DESC
     LIMIT 1;

    IF v_atual IS NULL OR v_situacao = 'pendente' THEN
        v_status := 'PLANEJADA';
    ELSIF v_fase = 'envio_gcq' AND v_resultado = 'aprovada' THEN
        v_status := 'CONCLUIDA';
    ELSIF v_fase = 'envio_gcq' AND v_resultado = 'devolvida' THEN
        v_status := 'DEVOLVIDA';
    ELSE
        v_status := v_status_fase;
    END IF;

    SELECT coalesce(max(revisao), 0) INTO v_revisao
      FROM mapcartacomp.lote_etapa WHERE id_lote = p_lote AND situacao <> 'pulada' AND situacao <> 'pendente';

    UPDATE mapcartacomp.lote
       SET id_lote_etapa_atual = v_atual, status_nacional = v_status, revisao_atual = v_revisao
     WHERE id = p_lote
       AND (id_lote_etapa_atual IS DISTINCT FROM v_atual OR status_nacional IS DISTINCT FROM v_status
            OR revisao_atual IS DISTINCT FROM v_revisao);
END
$$;

CREATE OR REPLACE FUNCTION mapcartacomp.f_lote_etapa_derivar() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP IN ('UPDATE', 'DELETE') THEN
        PERFORM mapcartacomp.f_lote_derivar(OLD.id_lote);
    END IF;
    IF TG_OP = 'INSERT' THEN
        PERFORM mapcartacomp.f_lote_derivar(NEW.id_lote);
    ELSIF TG_OP = 'UPDATE' THEN
        IF NEW.id_lote IS DISTINCT FROM OLD.id_lote THEN
            PERFORM mapcartacomp.f_lote_derivar(NEW.id_lote);
        END IF;
    END IF;
    RETURN NULL;
END
$$;

DROP TRIGGER IF EXISTS t20_derivar ON mapcartacomp.lote_etapa;
CREATE TRIGGER t20_derivar AFTER INSERT OR UPDATE OR DELETE ON mapcartacomp.lote_etapa
    FOR EACH ROW EXECUTE PROCEDURE mapcartacomp.f_lote_etapa_derivar();
