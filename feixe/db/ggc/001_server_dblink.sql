-- GGC 001 (variante dblink): servidor remoto apontando para o banco da CCAR e mapeamento de usuário, para uso com
-- dblink('feixe_ccar_dblink', ...). Compatível com PostgreSQL 9.6. Idempotente. Aplicar com psql, passando:
--
--   psql "<conexão da GGC>" -v ON_ERROR_STOP=1 \
--        -v ccar_host=... -v ccar_porta=... -v ccar_banco=... -v conta=... -v senha=... \
--        -f feixe/db/ggc/001_server_dblink.sql
--
-- `conta` é a conta que a GGC já usa para falar com a CCAR (P-01); nenhuma role nova é criada. O espelho enxerga
-- o que essa conta enxerga na CCAR (RLS por UF): ela deve ser membro da role _atua da própria GGC.

CREATE EXTENSION IF NOT EXISTS dblink;

-- O 9.6 não tem CREATE SERVER/USER MAPPING IF NOT EXISTS, e variáveis do psql não entram em blocos DO: os valores
-- passam pela sessão (SET) e o bloco cria ou atualiza.
SET feixe.ccar_host = :'ccar_host';
SET feixe.ccar_porta = :'ccar_porta';
SET feixe.ccar_banco = :'ccar_banco';
SET feixe.conta = :'conta';
SET feixe.senha = :'senha';

DO $$
DECLARE
    h text := current_setting('feixe.ccar_host');
    p text := current_setting('feixe.ccar_porta');
    b text := current_setting('feixe.ccar_banco');
    c text := current_setting('feixe.conta');
    s text := current_setting('feixe.senha');
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_foreign_server WHERE srvname = 'feixe_ccar_dblink') THEN
        EXECUTE format('CREATE SERVER feixe_ccar_dblink FOREIGN DATA WRAPPER dblink_fdw '
                       'OPTIONS (host %L, port %L, dbname %L)', h, p, b);
    ELSE
        EXECUTE format('ALTER SERVER feixe_ccar_dblink OPTIONS (SET host %L, SET port %L, SET dbname %L)', h, p, b);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_user_mappings WHERE srvname = 'feixe_ccar_dblink' AND usename = 'public') THEN
        EXECUTE format('CREATE USER MAPPING FOR PUBLIC SERVER feixe_ccar_dblink OPTIONS (user %L, password %L)', c, s);
    ELSE
        EXECUTE format('ALTER USER MAPPING FOR PUBLIC SERVER feixe_ccar_dblink OPTIONS (SET user %L, SET password %L)', c, s);
    END IF;
END
$$;

RESET feixe.ccar_host;
RESET feixe.ccar_porta;
RESET feixe.ccar_banco;
RESET feixe.conta;
RESET feixe.senha;
