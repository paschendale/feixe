-- Roles e usuários de teste do ambiente de dev, reproduzindo o padrão das roles de grupo da CCAR
-- (role_<projeto><unidade>_atua / _sup). Só para dev: em homologação e produção as roles já existem e nada é criado.
-- Idempotente. Os testes de banco (tests/db/test_grants.py) executam este arquivo dentro da própria transação.

DO $$
DECLARE
    r text;
BEGIN
    FOREACH r IN ARRAY ARRAY['role_bc100ggcdf_atua', 'role_bc100ggcdf_sup', 'role_bc100ggcgo_atua', 'role_bc100ggcgo_sup']
    LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('CREATE ROLE %I NOLOGIN', r);
        END IF;
    END LOOP;
    -- Usuários de teste (sem senha: só usados com SET ROLE por um superusuário).
    FOREACH r IN ARRAY ARRAY['feixe_teste_apm_df', 'feixe_teste_apm2_df', 'feixe_teste_sup_df', 'feixe_teste_apm_go']
    LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('CREATE ROLE %I NOLOGIN', r);
        END IF;
    END LOOP;
END
$$;

GRANT role_bc100ggcdf_atua TO feixe_teste_apm_df, feixe_teste_apm2_df;
GRANT role_bc100ggcdf_sup TO feixe_teste_sup_df;
GRANT role_bc100ggcgo_atua TO feixe_teste_apm_go;
