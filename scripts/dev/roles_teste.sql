-- Roles de teste do ambiente de dev: um grupo que recebe os GRANTs do Feixe, dois usuários membros dele e um usuário
-- de fora. Só para dev: em homologação e produção a DBA escolhe roles que já existem e nada é criado.
-- Idempotente. Os testes de banco (tests/db/test_grants.py) executam este arquivo dentro da própria transação.

DO $$
DECLARE
    r text;
BEGIN
    FOREACH r IN ARRAY ARRAY['feixe_teste_grupo', 'feixe_teste_df', 'feixe_teste_go', 'feixe_teste_fora']
    LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('CREATE ROLE %I NOLOGIN', r);
        END IF;
    END LOOP;
END
$$;

GRANT feixe_teste_grupo TO feixe_teste_df, feixe_teste_go;
