-- 004: cargas de trabalho e controle de qualidade: planos de amostragem, cargas, amostras e ocorrências de inspeção.
-- O plano vem antes da carga porque a carga de CQ aponta para o plano que a sorteou.
-- Compatível com PostgreSQL 9.6. Idempotente.
-- Tabelas sincronizadas: uuid gerado no plugin (nunca no banco), uf desnormalizada e (uf, atualizado_em) indexado.
-- O módulo de CQ ainda não foi desenhado: orientação, universo e nível ficam como texto aberto, sem lista fechada.
--
-- Atividade de CQ = tema + medida de qualidade. Cada atividade da etapa de CQ tem o seu plano (sorteio) na passagem, e
-- cada célula sorteada vira uma carga daquela atividade, avaliada uma vez (uma amostra). A mesma célula pode sair em
-- planos de atividades diferentes; na mesma atividade e passagem, não.

-- Plano de amostragem de uma atividade de CQ numa passagem.
CREATE TABLE IF NOT EXISTS mapcartacomp.cq_plano (
    id serial PRIMARY KEY,
    uuid uuid NOT NULL UNIQUE,
    id_lote_etapa integer NOT NULL REFERENCES mapcartacomp.lote_etapa (id) ON DELETE CASCADE,
    id_atividade integer NOT NULL REFERENCES mapcartacomp.atividade (id),
    uf char(2) NOT NULL CHECK (uf ~ '^[A-Z]{2}$'),
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
    fracao_critica numeric CHECK (fracao_critica > 0 AND fracao_critica < 100),
    resultado text NOT NULL DEFAULT 'pendente' CHECK (resultado IN ('pendente', 'aprovado', 'reprovado')),
    criado_em timestamptz NOT NULL DEFAULT now(),
    criado_por text NOT NULL DEFAULT current_user,
    atualizado_em timestamptz NOT NULL DEFAULT now(),
    atualizado_por text NOT NULL DEFAULT current_user,
    -- Alvo da FK composta da carga: a carga de CQ é da mesma passagem e atividade do plano que a sorteou.
    UNIQUE (id, id_lote_etapa, id_atividade)
);

COMMENT ON COLUMN mapcartacomp.cq_plano.orientacao IS 'Como a unidade de amostragem é definida (ex.: area). Aberto.';
COMMENT ON COLUMN mapcartacomp.cq_plano.universo IS
    'De onde as unidades foram sorteadas (ex.: todas as células do lote, só as que intersectam a camada alvo). Aberto.';

COMMENT ON COLUMN mapcartacomp.cq_plano.nivel_inspecao IS
    'Nível de inspeção do plano (ex.: II, III). Aberto. O nível III depois de aprovada no II é nova passagem (D-135).';
COMMENT ON COLUMN mapcartacomp.cq_plano.semente IS 'Semente do sorteio: com o mesmo universo, refaz a mesma amostra.';
COMMENT ON COLUMN mapcartacomp.cq_plano.fracao_critica IS
    'Fração crítica (em %) contra a qual se mostra o nível de conformidade deste plano (D-62): a da etapa '
    '(fluxo_etapa.fracao_critica) ou a do elemento (cq_elemento), gravada ao criar o plano, para não mudar quando a '
    'GGC trocar o padrão da etapa. Nula = sem velocímetro.';

-- Um plano por atividade em cada passagem (D-83): abrir a passagem gera os planos com o padrão da etapa (D-136) e
-- não pode gerar de novo. Nova passagem (revisão seguinte, nível III) tem os seus.
CREATE UNIQUE INDEX IF NOT EXISTS cq_plano_atividade_uq ON mapcartacomp.cq_plano (id_lote_etapa, id_atividade);
CREATE INDEX IF NOT EXISTS cq_plano_lote_etapa_idx ON mapcartacomp.cq_plano (id_lote_etapa);
CREATE INDEX IF NOT EXISTS cq_plano_atividade_idx ON mapcartacomp.cq_plano (id_atividade);
CREATE INDEX IF NOT EXISTS cq_plano_atualizado_em_idx ON mapcartacomp.cq_plano (uf, atualizado_em);

-- Carga de trabalho: unidade padronizada de trabalho de uma atividade dentro de uma passagem de etapa, feita uma vez.
-- Responsável nulo = disponível.
CREATE TABLE IF NOT EXISTS mapcartacomp.carga_trabalho (
    id serial PRIMARY KEY,
    uuid uuid NOT NULL UNIQUE,
    id_lote_etapa integer NOT NULL REFERENCES mapcartacomp.lote_etapa (id) ON DELETE CASCADE,
    id_atividade integer NOT NULL REFERENCES mapcartacomp.atividade (id),
    id_cq_plano integer,
    uf char(2) NOT NULL CHECK (uf ~ '^[A-Z]{2}$'),
    responsavel text,
    geom geometry(MultiPolygon, 4674) NOT NULL,
    geocodigo text CHECK (geocodigo ~ '^[0-9]+(KM|M)E[0-9]+N[0-9]+$'),
    concluido boolean NOT NULL DEFAULT false,
    concluido_em timestamptz,
    criado_em timestamptz NOT NULL DEFAULT now(),
    criado_por text NOT NULL DEFAULT current_user,
    atualizado_em timestamptz NOT NULL DEFAULT now(),
    atualizado_por text NOT NULL DEFAULT current_user,
    FOREIGN KEY (id_cq_plano, id_lote_etapa, id_atividade)
        REFERENCES mapcartacomp.cq_plano (id, id_lote_etapa, id_atividade) ON DELETE CASCADE,
    -- Alvo da FK composta da amostra: a amostra é do plano da sua carga.
    UNIQUE (id, id_cq_plano)
);

COMMENT ON COLUMN mapcartacomp.carga_trabalho.id_atividade IS
    'Atividade da carga, uma das atividades da etapa da passagem (006). Na carga de CQ, a do plano que a sorteou.';
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
CREATE INDEX IF NOT EXISTS carga_trabalho_atividade_idx ON mapcartacomp.carga_trabalho (id_atividade);
-- A mesma célula da grade não vira duas cargas da mesma atividade na mesma passagem: carga se faz uma vez.
CREATE UNIQUE INDEX IF NOT EXISTS carga_trabalho_celula_unica_idx
    ON mapcartacomp.carga_trabalho (id_lote_etapa, id_atividade, geocodigo) WHERE geocodigo IS NOT NULL;


-- Amostra: a avaliação da carga de CQ na medida da sua atividade, uma por carga. status nulo = pendente,
-- 1 = conforme, 0 = não conforme.
CREATE TABLE IF NOT EXISTS mapcartacomp.cq_amostra (
    id serial PRIMARY KEY,
    uuid uuid NOT NULL UNIQUE,
    id_cq_plano integer NOT NULL REFERENCES mapcartacomp.cq_plano (id) ON DELETE CASCADE,
    id_carga_trabalho integer NOT NULL UNIQUE,
    uf char(2) NOT NULL CHECK (uf ~ '^[A-Z]{2}$'),
    status smallint CHECK (status IN (0, 1)),
    observacao text,
    avaliado_por text,
    avaliado_em timestamptz,
    criado_em timestamptz NOT NULL DEFAULT now(),
    criado_por text NOT NULL DEFAULT current_user,
    atualizado_em timestamptz NOT NULL DEFAULT now(),
    atualizado_por text NOT NULL DEFAULT current_user,
    FOREIGN KEY (id_carga_trabalho, id_cq_plano) REFERENCES mapcartacomp.carga_trabalho (id, id_cq_plano)
        ON DELETE CASCADE
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
    id_lote_etapa integer REFERENCES mapcartacomp.lote_etapa (id) ON DELETE SET NULL,
    id_carga_avaliada integer REFERENCES mapcartacomp.carga_trabalho (id) ON DELETE SET NULL,
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

COMMENT ON COLUMN mapcartacomp.cq_inspecao.id_carga_trabalho IS
    'Carga de CQ (a amostra) em que a ocorrência foi registrada, quando há. Opcional.';
COMMENT ON COLUMN mapcartacomp.cq_inspecao.id_lote_etapa IS
    'Passagem de CQ em que a ocorrência foi registrada. Nula no INSERT = a da carga de CQ (006). É por ela que a '
    'revisão seguinte fica às cegas (D-66): só vê as ocorrências se a sua passagem tem expor_ocorrencias.';
COMMENT ON COLUMN mapcartacomp.cq_inspecao.id_carga_avaliada IS
    'Carga de produção que a ocorrência aponta: a que contém o ponto na passagem que conta revisão avaliada por esta '
    'passagem de CQ (mesma revisão). O responsável dela é o APM autor, que dá ciência. Nula no INSERT = derivada '
    '(006), porque o avaliador pode registrar offline, sem as cargas dos outros no workspace.';
COMMENT ON COLUMN mapcartacomp.cq_inspecao.elemento IS
    'Elemento de qualidade da ocorrência (nome da medida no SGBC, como na atividade de CQ). Aberto.';
COMMENT ON COLUMN mapcartacomp.cq_inspecao.responsavel IS 'Quem registrou a ocorrência (o avaliador).';

CREATE INDEX IF NOT EXISTS cq_inspecao_lote_idx ON mapcartacomp.cq_inspecao (id_lote);
CREATE INDEX IF NOT EXISTS cq_inspecao_lote_etapa_idx ON mapcartacomp.cq_inspecao (id_lote_etapa);
CREATE INDEX IF NOT EXISTS cq_inspecao_carga_idx ON mapcartacomp.cq_inspecao (id_carga_trabalho);
CREATE INDEX IF NOT EXISTS cq_inspecao_carga_avaliada_idx ON mapcartacomp.cq_inspecao (id_carga_avaliada);
CREATE INDEX IF NOT EXISTS cq_inspecao_geom_idx ON mapcartacomp.cq_inspecao USING gist (geom);
CREATE INDEX IF NOT EXISTS cq_inspecao_atualizado_em_idx ON mapcartacomp.cq_inspecao (uf, atualizado_em);

-- Fila de folhas por pessoa (B8, D-65, D-106): o supervisor enfileira, para cada pessoa, folhas (passagens abertas com
-- cargas a atribuir) na ordem em que ela deve pegá-las. Quando a pessoa conclui a última carga pendente que tem numa
-- passagem, o plugin atribui a ela as cargas a atribuir do primeiro item da fila que ainda tem o que atribuir, na
-- mesma transação da conclusão, e marca o item como atribuído. Assim ninguém fica com várias folhas abertas e ninguém
-- fica parado. Não é sincronizada (só cargas, CQ e inspeções são): é planejamento do supervisor, online.
CREATE TABLE IF NOT EXISTS mapcartacomp.fila_folha (
    id serial PRIMARY KEY,
    uuid uuid NOT NULL UNIQUE,
    id_lote_etapa integer NOT NULL REFERENCES mapcartacomp.lote_etapa (id) ON DELETE CASCADE,
    uf char(2) NOT NULL CHECK (uf ~ '^[A-Z]{2}$'),
    responsavel text NOT NULL,
    ordem integer NOT NULL,
    atribuida_em timestamptz,
    atribuidas integer,
    criado_em timestamptz NOT NULL DEFAULT now(),
    criado_por text NOT NULL DEFAULT current_user,
    atualizado_em timestamptz NOT NULL DEFAULT now(),
    atualizado_por text NOT NULL DEFAULT current_user,
    CHECK ((atribuida_em IS NULL) = (atribuidas IS NULL))
);

COMMENT ON COLUMN mapcartacomp.fila_folha.ordem IS 'Posição na fila da pessoa (menor = próxima).';
COMMENT ON COLUMN mapcartacomp.fila_folha.atribuida_em IS
    'Quando a fila atribuiu as cargas da folha à pessoa; nulo = ainda na fila. Fica como registro.';

-- Uma folha espera na fila de uma pessoa só.
CREATE UNIQUE INDEX IF NOT EXISTS fila_folha_aguardando_uq ON mapcartacomp.fila_folha (id_lote_etapa)
    WHERE atribuida_em IS NULL;
CREATE INDEX IF NOT EXISTS fila_folha_responsavel_idx ON mapcartacomp.fila_folha (uf, responsavel, ordem)
    WHERE atribuida_em IS NULL;
