-- 001: schema do Feixe e controle de versão das migrações.
-- Compatível com PostgreSQL 9.6. Idempotente: pode ser executado de novo sem efeito.
-- Em produção e homologação o schema é criado pela DBA da CCAR; o IF NOT EXISTS mantém o script aplicável nos dois casos.

CREATE SCHEMA IF NOT EXISTS mapcartacomp;

COMMENT ON SCHEMA mapcartacomp IS
    'Feixe: controle de cargas de trabalho da produção cartográfica (lotes, etapas, cargas, CQ). '
    'Usuários, projetos, escalas e articulação vêm de mapcartctrl e não são replicados aqui.';

CREATE TABLE IF NOT EXISTS mapcartacomp.schema_version (
    versao integer PRIMARY KEY,
    nome text NOT NULL,
    aplicado_em timestamptz NOT NULL DEFAULT now(),
    aplicado_por text NOT NULL DEFAULT current_user
);

COMMENT ON TABLE mapcartacomp.schema_version IS
    'Uma linha por migração aplicada (feixe/db/ccar/NNN_*.sql). O plugin compara max(versao) com a versão que espera.';
