-- 006: regras no banco (PL/pgSQL compatível com PostgreSQL 9.6). Idempotente.
--
-- Derivações e validações (atividade da carga dentro da etapa, carga dentro da folha). Nenhuma regra muda a etapa de um lote: quem avança, pula,
-- volta ou repete etapas é o supervisor. Aqui se calcula o que decorre disso (status nacional, revisão, etapa atual) e
-- o que decorre das avaliações (carga de CQ concluída, resultado do plano), que só alimenta "prontas para avançar".

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
    FOREACH t IN ARRAY ARRAY['tema', 'atividade', 'fluxo', 'fluxo_etapa', 'fluxo_etapa_atividade', 'cq_elemento',
                             'usuario_feixe', 'calendario', 'lote', 'lote_etapa', 'lote_etapa_hist', 'carga_trabalho',
                             'cq_plano', 'cq_amostra', 'cq_inspecao']
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
-- O plano é de uma medida só (a da sua atividade): pendente enquanto houver amostra sem avaliação (ou sem Ac
-- definido); reprovado se os não conformes excedem Ac; aprovado caso contrário. Não muda etapa nenhuma.

CREATE OR REPLACE FUNCTION mapcartacomp.f_cq_plano_resultado(p_plano integer, p_ac integer) RETURNS text
LANGUAGE sql STABLE AS $$
    SELECT CASE
        WHEN count(*) = 0 OR count(*) FILTER (WHERE a.status IS NULL) > 0 OR p_ac IS NULL THEN 'pendente'
        WHEN count(*) FILTER (WHERE a.status = 0) > p_ac THEN 'reprovado'
        ELSE 'aprovado'
    END
    FROM mapcartacomp.cq_amostra a
    WHERE a.id_cq_plano = p_plano
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

-- Depois de mudar a amostra: a carga de CQ conclui quando a sua amostra tem status (e volta a pendente se a
-- avaliação for desfeita), e o plano é recalculado.

-- Roda com os direitos do dono do schema, para que a derivação não dependa dos privilégios de quem avaliou.
CREATE OR REPLACE FUNCTION mapcartacomp.f_amostra_derivar_um(p_carga integer, p_plano integer) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = mapcartacomp, public, pg_temp AS $$
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

-- Roda com os direitos do dono do schema, para que a derivação não dependa dos privilégios de quem mudou a etapa.
CREATE OR REPLACE FUNCTION mapcartacomp.f_lote_derivar(p_lote integer) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = mapcartacomp, public, pg_temp AS $$
DECLARE
    v_atual integer;
    v_situacao text;
    v_fase text;
    v_status_fase text;
    v_resultado text;
    v_status text;
    v_revisao integer;
BEGIN
    SELECT le.id, le.situacao, fe.fase, fa.status_nacional, le.resultado
      INTO v_atual, v_situacao, v_fase, v_status_fase, v_resultado
      FROM mapcartacomp.lote_etapa le
      JOIN mapcartacomp.fluxo_etapa fe ON fe.id = le.id_fluxo_etapa
      JOIN mapcartacomp.fase fa ON fa.codigo = fe.fase
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

-- Atividades da etapa ------------------------------------------------------------------------------------------------
-- A atividade ligada a uma etapa do fluxo tem a fase da etapa e o projeto e o tema do fluxo. Carga e plano de CQ de
-- uma passagem só podem ser de uma atividade da etapa dessa passagem.

CREATE OR REPLACE FUNCTION mapcartacomp.f_etapa_atividade_valida() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NOT EXISTS (SELECT 1
                     FROM mapcartacomp.fluxo_etapa fe
                     JOIN mapcartacomp.fluxo f ON f.id = fe.id_fluxo
                     JOIN mapcartacomp.atividade a ON a.id = NEW.id_atividade
                    WHERE fe.id = NEW.id_fluxo_etapa AND a.fase = fe.fase
                      AND a.cod_projeto = f.cod_projeto AND a.id_tema = f.id_tema) THEN
        RAISE EXCEPTION 'atividade % não serve à etapa %: fase, projeto ou tema diferente', NEW.id_atividade,
            NEW.id_fluxo_etapa USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END
$$;

DROP TRIGGER IF EXISTS t05_valida ON mapcartacomp.fluxo_etapa_atividade;
CREATE TRIGGER t05_valida BEFORE INSERT OR UPDATE ON mapcartacomp.fluxo_etapa_atividade
    FOR EACH ROW EXECUTE PROCEDURE mapcartacomp.f_etapa_atividade_valida();

CREATE OR REPLACE FUNCTION mapcartacomp.f_atividade_na_etapa() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NOT EXISTS (SELECT 1
                     FROM mapcartacomp.lote_etapa le
                     JOIN mapcartacomp.fluxo_etapa_atividade fa ON fa.id_fluxo_etapa = le.id_fluxo_etapa
                    WHERE le.id = NEW.id_lote_etapa AND fa.id_atividade = NEW.id_atividade) THEN
        RAISE EXCEPTION 'atividade % não é da etapa da passagem %', NEW.id_atividade, NEW.id_lote_etapa
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END
$$;

DO $$
DECLARE
    t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['carga_trabalho', 'cq_plano']
    LOOP
        EXECUTE format('DROP TRIGGER IF EXISTS t04_atividade ON mapcartacomp.%I', t);
        EXECUTE format('CREATE TRIGGER t04_atividade BEFORE INSERT OR UPDATE OF id_atividade, id_lote_etapa '
                       'ON mapcartacomp.%I FOR EACH ROW EXECUTE PROCEDURE mapcartacomp.f_atividade_na_etapa()', t);
    END LOOP;
END
$$;

-- Grade estatística do IBGE -----------------------------------------------------------------------------------------
-- Célula calculada por fórmula na projeção equivalente de Albers sobre SIRGAS2000, a mesma conta de
-- feixe/core/grade.py. A projeção vai como string proj4 para ST_Transform: não depende de SRID cadastrado em
-- spatial_ref_sys. As células se alinham a partir do canto inferior esquerdo da área de abrangência da grade
-- (E 2.800.000, N 7.350.000). Geocódigo: descritor do nível + E + N do canto inferior esquerdo; níveis em km dão as
-- coordenadas em km (5KME5725N9425), níveis em metros em hectômetros (200ME49836N78114, e o sub-nível
-- 2500ME51025N77625).

CREATE OR REPLACE FUNCTION mapcartacomp.f_grade_proj() RETURNS text
LANGUAGE sql IMMUTABLE AS $$
    SELECT '+proj=aea +lat_1=-2 +lat_2=-22 +lat_0=-12 +lon_0=-54 +x_0=5000000 +y_0=10000000 +ellps=GRS80 '
           '+units=m +no_defs'::text
$$;

-- Descritor do nível e o divisor das coordenadas no geocódigo; nulos se o nível não existe.
CREATE OR REPLACE FUNCTION mapcartacomp.f_grade_descritor(p_nivel integer, OUT descritor text, OUT divisor integer)
LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE WHEN p_nivel % 1000 = 0 THEN (p_nivel / 1000) || 'KM' ELSE p_nivel || 'M' END,
           CASE WHEN p_nivel % 1000 = 0 THEN 1000 ELSE 100 END
     WHERE p_nivel IN (500000, 100000, 50000, 10000, 5000, 2500, 1000, 200)
$$;

-- Geocódigo da célula do nível que contém o ponto (x, y), em metros na projeção da grade.
CREATE OR REPLACE FUNCTION mapcartacomp.f_grade_geocodigo(p_nivel integer, p_x double precision,
                                                          p_y double precision) RETURNS text
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE
    d record;
BEGIN
    SELECT * INTO d FROM mapcartacomp.f_grade_descritor(p_nivel);
    IF d.descritor IS NULL THEN
        RAISE EXCEPTION 'nível da grade estatística desconhecido: % m', p_nivel USING ERRCODE = 'invalid_parameter_value';
    END IF;
    RETURN d.descritor || 'E' || ((2800000 + floor((p_x - 2800000) / p_nivel)::bigint * p_nivel) / d.divisor)
                       || 'N' || ((7350000 + floor((p_y - 7350000) / p_nivel)::bigint * p_nivel) / d.divisor);
END
$$;

-- Nível e canto inferior esquerdo (metros) de um geocódigo; erro se o geocódigo não é de uma célula da grade.
CREATE OR REPLACE FUNCTION mapcartacomp.f_grade_ler(p_geocodigo text, OUT nivel integer, OUT x0 bigint, OUT y0 bigint)
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE
    m text[];
    d record;
BEGIN
    m := regexp_matches(coalesce(p_geocodigo, ''), '^([0-9]+)(KM|M)E([0-9]+)N([0-9]+)$');
    IF m IS NULL OR length(m[1]) > 6 THEN
        RAISE EXCEPTION 'geocódigo inválido: %', p_geocodigo USING ERRCODE = 'invalid_parameter_value';
    END IF;
    nivel := m[1]::integer * CASE WHEN m[2] = 'KM' THEN 1000 ELSE 1 END;
    SELECT * INTO d FROM mapcartacomp.f_grade_descritor(nivel);
    IF d.descritor IS DISTINCT FROM m[1] || m[2] THEN
        RAISE EXCEPTION 'geocódigo inválido: %', p_geocodigo USING ERRCODE = 'invalid_parameter_value';
    END IF;
    x0 := m[3]::bigint * d.divisor;
    y0 := m[4]::bigint * d.divisor;
    IF (x0 - 2800000) % nivel <> 0 OR (y0 - 7350000) % nivel <> 0 THEN
        RAISE EXCEPTION 'geocódigo inválido: % (canto fora da grade de % m)', p_geocodigo, nivel
            USING ERRCODE = 'invalid_parameter_value';
    END IF;
END
$$;

-- Ponto da projeção da grade levado para SIRGAS2000 (4674) pela fórmula inversa da projeção de Albers no elipsoide
-- (Snyder, Map Projections: a working manual, 1987), a mesma de feixe/core/grade.py. Usada no gatilho de cada carga:
-- com a projeção em string proj4, ST_Transform monta a transformação a cada chamada e custa de 5 a 12 ms no dev; esta
-- conta custa microssegundos e coincide com ST_Transform abaixo de 0,1 mm (tests/db/test_grade.py).
CREATE OR REPLACE FUNCTION mapcartacomp.f_grade_de_albers(p_x double precision, p_y double precision)
RETURNS geometry
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE
    a CONSTANT double precision := 6378137.0;
    e2 CONSTANT double precision := 2 / 298.257222101 - 1 / 298.257222101 ^ 2;
    e CONSTANT double precision := sqrt(e2);
    lon0 CONSTANT double precision := radians(-54.0);
    s0 CONSTANT double precision := sin(radians(-12.0));
    s1 CONSTANT double precision := sin(radians(-2.0));
    s2 CONSTANT double precision := sin(radians(-22.0));
    q0 double precision;
    q1 double precision;
    q2 double precision;
    m1 double precision;
    m2 double precision;
    n double precision;
    c double precision;
    rho0 double precision;
    rho double precision;
    theta double precision;
    q double precision;
    phi double precision;
    s double precision;
    um double precision;
    dphi double precision;
BEGIN
    q0 := (1 - e2) * (s0 / (1 - e2 * s0 * s0) - ln((1 - e * s0) / (1 + e * s0)) / (2 * e));
    q1 := (1 - e2) * (s1 / (1 - e2 * s1 * s1) - ln((1 - e * s1) / (1 + e * s1)) / (2 * e));
    q2 := (1 - e2) * (s2 / (1 - e2 * s2 * s2) - ln((1 - e * s2) / (1 + e * s2)) / (2 * e));
    m1 := cos(radians(-2.0)) / sqrt(1 - e2 * s1 * s1);
    m2 := cos(radians(-22.0)) / sqrt(1 - e2 * s2 * s2);
    n := (m1 * m1 - m2 * m2) / (q2 - q1);
    c := m1 * m1 + n * q1;
    rho0 := a * sqrt(c - n * q0) / n;
    -- n é negativo (paralelos padrão no hemisfério sul): os sinais de rho e de theta seguem o de n.
    rho := sign(n) * sqrt((p_x - 5000000) ^ 2 + (rho0 - (p_y - 10000000)) ^ 2);
    theta := atan2(sign(n) * (p_x - 5000000), sign(n) * (rho0 - (p_y - 10000000)));
    q := (c - (rho * n / a) ^ 2) / n;
    phi := asin(greatest(-1, least(1, q / 2)));
    FOR i IN 1..20 LOOP
        s := sin(phi);
        um := 1 - e2 * s * s;
        dphi := um * um / (2 * cos(phi)) * (q / (1 - e2) - s / um + ln((1 - e * s) / (1 + e * s)) / (2 * e));
        phi := phi + dphi;
        EXIT WHEN abs(dphi) < 1e-14;
    END LOOP;
    RETURN ST_SetSRID(ST_MakePoint(degrees(lon0 + theta / n), degrees(phi)), 4674);
END
$$;

-- Centro da célula, levado para SIRGAS2000 (4674). É o ponto que decide a folha da célula.
CREATE OR REPLACE FUNCTION mapcartacomp.f_grade_centroide(p_geocodigo text) RETURNS geometry
LANGUAGE sql IMMUTABLE AS $$
    SELECT mapcartacomp.f_grade_de_albers(c.x0 + c.nivel / 2.0, c.y0 + c.nivel / 2.0)
      FROM mapcartacomp.f_grade_ler(p_geocodigo) c
$$;

-- Célula como MultiPolygon em SIRGAS2000: os quatro cantos projetados de volta, como no shapefile oficial.
CREATE OR REPLACE FUNCTION mapcartacomp.f_grade_celula(p_geocodigo text) RETURNS geometry
LANGUAGE sql IMMUTABLE AS $$
    SELECT ST_Multi(ST_Transform(ST_MakeEnvelope(c.x0, c.y0, c.x0 + c.nivel, c.y0 + c.nivel),
                                 mapcartacomp.f_grade_proj(), 4674))
      FROM mapcartacomp.f_grade_ler(p_geocodigo) c
$$;

-- Células do nível com centroide dentro do polígono (4674). A célula fica inteira, sem corte na borda.
CREATE OR REPLACE FUNCTION mapcartacomp.f_grade_celulas(p_geom geometry, p_nivel integer)
RETURNS TABLE (geocodigo text, geom geometry)
LANGUAGE plpgsql STABLE AS $$
DECLARE
    v_ext geometry;
    v_i0 bigint;
    v_i1 bigint;
    v_j0 bigint;
    v_j1 bigint;
BEGIN
    IF (SELECT descritor FROM mapcartacomp.f_grade_descritor(p_nivel)) IS NULL THEN
        RAISE EXCEPTION 'nível da grade estatística desconhecido: % m', p_nivel USING ERRCODE = 'invalid_parameter_value';
    END IF;
    -- Arestas densificadas antes de projetar: um paralelo vira arco na projeção.
    v_ext := ST_Transform(ST_Segmentize(ST_SetSRID(p_geom, 4674), 0.01), mapcartacomp.f_grade_proj());
    v_i0 := floor((ST_XMin(v_ext) - 2800000) / p_nivel)::bigint - 1;
    v_i1 := floor((ST_XMax(v_ext) - 2800000) / p_nivel)::bigint + 1;
    v_j0 := floor((ST_YMin(v_ext) - 7350000) / p_nivel)::bigint - 1;
    v_j1 := floor((ST_YMax(v_ext) - 7350000) / p_nivel)::bigint + 1;
    -- Os centros e as células são projetados em lote (um ST_Transform por coleção): com a projeção em string proj4,
    -- cada chamada monta a transformação de novo, e uma chamada por célula custa milissegundos.
    RETURN QUERY
    WITH cand AS (
        SELECT row_number() OVER (ORDER BY j, i) AS k, 2800000 + i * p_nivel AS x0, 7350000 + j * p_nivel AS y0
          FROM generate_series(v_j0, v_j1) j, generate_series(v_i0, v_i1) i
    ), centros AS (
        SELECT (d).path[1] AS k, (d).geom AS centro
          FROM (SELECT ST_Dump(ST_Transform(ST_Collect(ST_MakePoint(x0 + p_nivel / 2.0, y0 + p_nivel / 2.0) ORDER BY k),
                                            mapcartacomp.f_grade_proj(), 4674)) AS d
                  FROM cand) s
    ), dentro AS (
        SELECT row_number() OVER (ORDER BY c.k) AS n, c.x0, c.y0
          FROM cand c JOIN centros t ON t.k = c.k
         WHERE ST_Intersects(p_geom, t.centro)
    ), celulas AS (
        SELECT (d).path[1] AS n, (d).geom AS celula
          FROM (SELECT ST_Dump(ST_Transform(ST_Collect(ST_MakeEnvelope(x0, y0, x0 + p_nivel, y0 + p_nivel) ORDER BY n),
                                            mapcartacomp.f_grade_proj(), 4674)) AS d
                  FROM dentro) s
    )
    SELECT mapcartacomp.f_grade_geocodigo(p_nivel, d.x0, d.y0), ST_Multi(c.celula)
      FROM dentro d JOIN celulas c ON c.n = d.n
     ORDER BY d.n;
END
$$;

-- Carga de lote-folha precisa pertencer à folha ------------------------------------------------------------------
-- Recusa INSERT ou UPDATE (da geometria, do geocódigo ou da passagem de etapa) de carga que não pertence à folha:
-- - carga gerada pela grade estatística (com geocódigo): o centroide da célula tem que estar na folha. A célula fica
--   inteira e pode passar da borda (D-73);
-- - carga sem geocódigo (legada ou malha importada): menos da metade da área dentro da folha é recusada (D-51). Pega o
--   erro de lançar cargas no rótulo da folha errada; células que vazam um pouco continuam aceitas.
-- Lotes livres não são verificados. Custo medido no 9.6 do dev, sem geocódigo: cerca de 60 µs por carga.

CREATE OR REPLACE FUNCTION mapcartacomp.f_fracao_na_folha(p_geom geometry, p_folha integer) RETURNS double precision
LANGUAGE sql STABLE AS $$
    SELECT ST_Area(ST_Intersection(CASE WHEN ST_IsValid(p_geom) THEN p_geom ELSE ST_MakeValid(p_geom) END, a.geom))
           / nullif(ST_Area(p_geom), 0)
      FROM mapcartctrl.t_articulacao_scn a
     WHERE a.id_articulacao_scn = p_folha
$$;

CREATE OR REPLACE FUNCTION mapcartacomp.f_carga_na_folha() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    v_folha integer;
    v_nome text;
    v_fracao double precision;
BEGIN
    SELECT l.id_articulacao_scn, l.nome INTO v_folha, v_nome
      FROM mapcartacomp.lote_etapa le JOIN mapcartacomp.lote l ON l.id = le.id_lote
     WHERE le.id = NEW.id_lote_etapa AND l.tipo = 'folha';
    IF v_folha IS NULL THEN
        RETURN NEW;
    END IF;
    IF NEW.geocodigo IS NOT NULL THEN
        IF NOT EXISTS (SELECT 1 FROM mapcartctrl.t_articulacao_scn a
                        WHERE a.id_articulacao_scn = v_folha
                          AND ST_Intersects(a.geom, mapcartacomp.f_grade_centroide(NEW.geocodigo))) THEN
            RAISE EXCEPTION 'carga fora da folha %: o centroide da célula % não está nela', v_nome, NEW.geocodigo
                USING ERRCODE = 'check_violation';
        END IF;
        RETURN NEW;
    END IF;
    v_fracao := mapcartacomp.f_fracao_na_folha(NEW.geom, v_folha);
    IF v_fracao < 0.5 THEN
        RAISE EXCEPTION 'carga fora da folha %: só % %% da área está dentro dela', v_nome, round((100 * v_fracao)::numeric, 1)
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END
$$;

DROP TRIGGER IF EXISTS t05_na_folha ON mapcartacomp.carga_trabalho;
CREATE TRIGGER t05_na_folha BEFORE INSERT OR UPDATE OF geom, geocodigo, id_lote_etapa ON mapcartacomp.carga_trabalho
    FOR EACH ROW EXECUTE PROCEDURE mapcartacomp.f_carga_na_folha();
