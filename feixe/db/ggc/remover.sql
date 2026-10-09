-- GGC: remove o espelho do Feixe (rollback de 001 a 003, qualquer variante). Não toca em dado nenhum da CCAR nem
-- nas extensões postgres_fdw/dblink, que podem estar em uso por outros sistemas.
-- Compatível com PostgreSQL 9.6. Idempotente.

DROP SCHEMA IF EXISTS mapcartacomp CASCADE;
DROP SERVER IF EXISTS feixe_ccar CASCADE;
DROP SERVER IF EXISTS feixe_ccar_dblink CASCADE;
