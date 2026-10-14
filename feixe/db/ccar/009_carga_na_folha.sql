-- 009: carga de lote do tipo folha tem que estar, na maior parte, dentro da folha. Compatível com PostgreSQL 9.6 e
-- PostGIS 2.4. Idempotente.
--
-- Recusa INSERT ou UPDATE (da geometria ou da passagem de etapa) de carga cujo lote é uma folha quando menos da
-- metade da área da carga cai dentro da folha. Pega o erro de lançar cargas no rótulo da folha errada; células de
-- grade que vazam um pouco da folha continuam aceitas. Lotes livres não são verificados. Custo medido no 9.6 do dev:
-- cerca de 60 µs por carga.

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
    v_fracao := mapcartacomp.f_fracao_na_folha(NEW.geom, v_folha);
    IF v_fracao < 0.5 THEN
        RAISE EXCEPTION 'carga fora da folha %: só % %% da área está dentro dela', v_nome, round((100 * v_fracao)::numeric, 1)
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END
$$;

DROP TRIGGER IF EXISTS t05_na_folha ON mapcartacomp.carga_trabalho;
CREATE TRIGGER t05_na_folha BEFORE INSERT OR UPDATE OF geom, id_lote_etapa ON mapcartacomp.carga_trabalho
    FOR EACH ROW EXECUTE PROCEDURE mapcartacomp.f_carga_na_folha();
