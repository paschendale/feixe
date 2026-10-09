-- 004: controle de qualidade: planos de amostragem, amostras por elemento e ocorrências de inspeção.
-- Compatível com PostgreSQL 9.6. Idempotente.
-- O módulo de CQ ainda não foi desenhado: orientação, universo, nível e elementos ficam como texto aberto, sem lista fechada.

-- Plano de amostragem. Uma passagem de etapa de CQ pode ter mais de um plano (ex.: elementos sorteados em universos
-- diferentes na mesma rodada).
CREATE TABLE IF NOT EXISTS mapcartacomp.cq_plano (
    id serial PRIMARY KEY,
    uuid uuid NOT NULL UNIQUE,
    id_lote_etapa integer NOT NULL REFERENCES mapcartacomp.lote_etapa (id) ON DELETE CASCADE,
    uf char(2) NOT NULL CHECK (uf ~ '^[A-Z]{2}$'),
    elementos text[] NOT NULL,
    orientacao text,
    universo text,
    nivel_inspecao text,
    tamanho_lote_n integer,
    letra_codigo text,
    tamanho_amostra_n integer,
    lqa numeric,
    numero_aceitacao_ac integer,
    celula_largura numeric,
    celula_altura numeric,
    semente bigint,
    resultado text NOT NULL DEFAULT 'pendente' CHECK (resultado IN ('pendente', 'aprovado', 'reprovado')),
    criado_em timestamptz NOT NULL DEFAULT now(),
    criado_por text NOT NULL DEFAULT current_user,
    atualizado_em timestamptz NOT NULL DEFAULT now(),
    atualizado_por text NOT NULL DEFAULT current_user
);

COMMENT ON COLUMN mapcartacomp.cq_plano.orientacao IS 'Como a unidade de amostragem é definida (ex.: area). Aberto.';
COMMENT ON COLUMN mapcartacomp.cq_plano.universo IS
    'De onde as unidades foram sorteadas (ex.: todas as células do lote, só as que intersectam a camada alvo). Aberto.';

CREATE INDEX IF NOT EXISTS cq_plano_lote_etapa_idx ON mapcartacomp.cq_plano (id_lote_etapa);
CREATE INDEX IF NOT EXISTS cq_plano_atualizado_em_idx ON mapcartacomp.cq_plano (uf, atualizado_em);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'mapcartacomp.carga_trabalho'::regclass AND conname = 'carga_trabalho_id_cq_plano_fkey'
    ) THEN
        ALTER TABLE mapcartacomp.carga_trabalho ADD CONSTRAINT carga_trabalho_id_cq_plano_fkey
            FOREIGN KEY (id_cq_plano) REFERENCES mapcartacomp.cq_plano (id) ON DELETE CASCADE;
    END IF;
END
$$;

CREATE INDEX IF NOT EXISTS carga_trabalho_cq_plano_idx ON mapcartacomp.carga_trabalho (id_cq_plano);

-- Amostra: avaliação de um elemento de qualidade numa carga de CQ. status nulo = pendente, 1 = conforme, 0 = não conforme.
CREATE TABLE IF NOT EXISTS mapcartacomp.cq_amostra (
    id serial PRIMARY KEY,
    uuid uuid NOT NULL UNIQUE,
    id_cq_plano integer NOT NULL REFERENCES mapcartacomp.cq_plano (id) ON DELETE CASCADE,
    id_carga_trabalho integer NOT NULL REFERENCES mapcartacomp.carga_trabalho (id) ON DELETE CASCADE,
    uf char(2) NOT NULL CHECK (uf ~ '^[A-Z]{2}$'),
    elemento text NOT NULL,
    status smallint CHECK (status IN (0, 1)),
    observacao text,
    avaliado_por text,
    avaliado_em timestamptz,
    criado_em timestamptz NOT NULL DEFAULT now(),
    criado_por text NOT NULL DEFAULT current_user,
    atualizado_em timestamptz NOT NULL DEFAULT now(),
    atualizado_por text NOT NULL DEFAULT current_user,
    UNIQUE (id_carga_trabalho, elemento)
);

CREATE INDEX IF NOT EXISTS cq_amostra_plano_idx ON mapcartacomp.cq_amostra (id_cq_plano);
CREATE INDEX IF NOT EXISTS cq_amostra_atualizado_em_idx ON mapcartacomp.cq_amostra (uf, atualizado_em);

-- Ocorrência de inspeção: ponto registrado pelo avaliador. "tratado" é marcado na correção de inspeção.
CREATE TABLE IF NOT EXISTS mapcartacomp.cq_inspecao (
    id serial PRIMARY KEY,
    uuid uuid NOT NULL UNIQUE,
    id_lote integer NOT NULL REFERENCES mapcartacomp.lote (id) ON DELETE CASCADE,
    id_carga_trabalho integer REFERENCES mapcartacomp.carga_trabalho (id) ON DELETE SET NULL,
    uf char(2) NOT NULL CHECK (uf ~ '^[A-Z]{2}$'),
    elemento text,
    geom geometry(Point, 4674) NOT NULL,
    anotacao text,
    responsavel text NOT NULL DEFAULT current_user,
    tratado boolean NOT NULL DEFAULT false,
    tratado_em timestamptz,
    tratado_por text,
    criado_em timestamptz NOT NULL DEFAULT now(),
    criado_por text NOT NULL DEFAULT current_user,
    atualizado_em timestamptz NOT NULL DEFAULT now(),
    atualizado_por text NOT NULL DEFAULT current_user
);

CREATE INDEX IF NOT EXISTS cq_inspecao_lote_idx ON mapcartacomp.cq_inspecao (id_lote);
CREATE INDEX IF NOT EXISTS cq_inspecao_geom_idx ON mapcartacomp.cq_inspecao USING gist (geom);
CREATE INDEX IF NOT EXISTS cq_inspecao_atualizado_em_idx ON mapcartacomp.cq_inspecao (uf, atualizado_em);
