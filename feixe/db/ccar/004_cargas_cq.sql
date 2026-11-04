-- 004: cargas de trabalho e controle de qualidade: planos de amostragem, cargas, amostras por elemento e ocorrências
-- de inspeção. O plano vem antes da carga porque a carga de CQ aponta para o plano que a sorteou.
-- Compatível com PostgreSQL 9.6. Idempotente.
-- Tabelas sincronizadas: uuid gerado no plugin (nunca no banco), uf desnormalizada e (uf, atualizado_em) indexado.
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

-- Carga de trabalho: unidade padronizada de trabalho dentro de uma passagem de etapa. Responsável nulo = disponível.
CREATE TABLE IF NOT EXISTS mapcartacomp.carga_trabalho (
    id serial PRIMARY KEY,
    uuid uuid NOT NULL UNIQUE,
    id_lote_etapa integer NOT NULL REFERENCES mapcartacomp.lote_etapa (id) ON DELETE CASCADE,
    id_cq_plano integer REFERENCES mapcartacomp.cq_plano (id) ON DELETE CASCADE,
    uf char(2) NOT NULL CHECK (uf ~ '^[A-Z]{2}$'),
    responsavel text,
    geom geometry(MultiPolygon, 4674) NOT NULL,
    geocodigo text CHECK (geocodigo ~ '^[0-9]+(KM|M)E[0-9]+N[0-9]+$'),
    concluido boolean NOT NULL DEFAULT false,
    concluido_em timestamptz,
    criado_em timestamptz NOT NULL DEFAULT now(),
    criado_por text NOT NULL DEFAULT current_user,
    atualizado_em timestamptz NOT NULL DEFAULT now(),
    atualizado_por text NOT NULL DEFAULT current_user
);

COMMENT ON COLUMN mapcartacomp.carga_trabalho.responsavel IS
    'mapcartctrl.t_usuario.nom_contausuario (igual a current_user). Nulo = disponível para atribuição.';
COMMENT ON COLUMN mapcartacomp.carga_trabalho.geocodigo IS
    'Geocódigo da célula da grade estatística do IBGE (ex.: 5KME5725N9425) quando a carga foi gerada pela grade. '
    'Nulo nas cargas legadas e nas de malha importada. Com geocódigo, a carga pertence à folha que contém o '
    'centroide da célula (006).';

CREATE INDEX IF NOT EXISTS carga_trabalho_lote_etapa_idx ON mapcartacomp.carga_trabalho (id_lote_etapa);
CREATE INDEX IF NOT EXISTS carga_trabalho_responsavel_idx ON mapcartacomp.carga_trabalho (responsavel);
CREATE INDEX IF NOT EXISTS carga_trabalho_geom_idx ON mapcartacomp.carga_trabalho USING gist (geom);
CREATE INDEX IF NOT EXISTS carga_trabalho_atualizado_em_idx ON mapcartacomp.carga_trabalho (uf, atualizado_em);
CREATE INDEX IF NOT EXISTS carga_trabalho_cq_plano_idx ON mapcartacomp.carga_trabalho (id_cq_plano);
CREATE INDEX IF NOT EXISTS carga_trabalho_geocodigo_idx ON mapcartacomp.carga_trabalho (geocodigo);


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

-- Ocorrência de inspeção: ponto registrado pelo avaliador. "tratado" é marcado na correção de inspeção; "ciente" é a
-- ciência do APM que errou.
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
    ciente_em timestamptz,
    ciente_por text,
    criado_em timestamptz NOT NULL DEFAULT now(),
    criado_por text NOT NULL DEFAULT current_user,
    atualizado_em timestamptz NOT NULL DEFAULT now(),
    atualizado_por text NOT NULL DEFAULT current_user,
    CHECK ((ciente_em IS NULL) = (ciente_por IS NULL))
);

COMMENT ON COLUMN mapcartacomp.cq_inspecao.ciente_em IS
    'Quando o APM autor da passagem avaliada deu ciência da ocorrência. Ciência não é correção: quem corrige é a '
    'correção de inspeção ou a revisão seguinte.';

CREATE INDEX IF NOT EXISTS cq_inspecao_lote_idx ON mapcartacomp.cq_inspecao (id_lote);
CREATE INDEX IF NOT EXISTS cq_inspecao_geom_idx ON mapcartacomp.cq_inspecao USING gist (geom);
CREATE INDEX IF NOT EXISTS cq_inspecao_atualizado_em_idx ON mapcartacomp.cq_inspecao (uf, atualizado_em);
