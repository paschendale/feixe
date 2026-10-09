-- 005: registro da sincronização (push do workspace local para a CCAR). Última escrita vence; o lado perdedor fica aqui.
-- Compatível com PostgreSQL 9.6. Idempotente.

CREATE TABLE IF NOT EXISTS mapcartacomp.sync_log (
    id bigserial PRIMARY KEY,
    usuario text NOT NULL DEFAULT current_user,
    uf char(2) CHECK (uf ~ '^[A-Z]{2}$'),
    em timestamptz NOT NULL DEFAULT now(),
    tabela text NOT NULL,
    uuid uuid,
    operacao text NOT NULL,
    resultado text NOT NULL,
    detalhe jsonb
);

COMMENT ON COLUMN mapcartacomp.sync_log.resultado IS 'Valores previstos: aplicado, conflito_vencido, conflito_perdido, erro.';
COMMENT ON COLUMN mapcartacomp.sync_log.detalhe IS 'Valor descartado num conflito, ou o erro.';

CREATE INDEX IF NOT EXISTS sync_log_em_idx ON mapcartacomp.sync_log (uf, em);
CREATE INDEX IF NOT EXISTS sync_log_uuid_idx ON mapcartacomp.sync_log (uuid);
