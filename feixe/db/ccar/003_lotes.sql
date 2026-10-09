-- 003: lotes (folhas e lotes livres), passagens pelas etapas, histórico de ações do supervisor e cargas de trabalho.
-- Compatível com PostgreSQL 9.6. Idempotente.
-- Tabelas sincronizadas: uuid gerado no plugin (nunca no banco), uf desnormalizada e (uf, atualizado_em) indexado para o pull.

-- Lote: uma folha (tipo folha) ou um agrupamento ad hoc (tipo livre), por projeto + tema.
-- Revisões não são lotes novos: são passagens pelas etapas (lote_etapa).
CREATE TABLE IF NOT EXISTS mapcartacomp.lote (
    id serial PRIMARY KEY,
    uuid uuid NOT NULL UNIQUE,
    cod_projeto integer NOT NULL REFERENCES mapcartctrl.t_projeto (cod_projeto),
    id_tema integer NOT NULL REFERENCES mapcartacomp.tema (id),
    id_fluxo integer NOT NULL,
    uf char(2) NOT NULL CHECK (uf ~ '^[A-Z]{2}$'),
    tipo text NOT NULL CHECK (tipo IN ('folha', 'livre')),
    id_articulacao_scn integer REFERENCES mapcartctrl.t_articulacao_scn (id_articulacao_scn),
    nome text NOT NULL,
    geom geometry(MultiPolygon, 4674),
    revisao_atual integer NOT NULL DEFAULT 0,
    id_lote_etapa_atual integer,
    status_nacional text NOT NULL DEFAULT 'PLANEJADA'
        CHECK (status_nacional IN ('PLANEJADA', 'EM_PRODUCAO', 'EM_CQ', 'ENTREGUE_GCQ', 'CONCLUIDA', 'DEVOLVIDA')),
    criado_em timestamptz NOT NULL DEFAULT now(),
    criado_por text NOT NULL DEFAULT current_user,
    atualizado_em timestamptz NOT NULL DEFAULT now(),
    atualizado_por text NOT NULL DEFAULT current_user,
    CHECK ((tipo = 'folha') = (id_articulacao_scn IS NOT NULL)),
    FOREIGN KEY (id_fluxo, cod_projeto, id_tema) REFERENCES mapcartacomp.fluxo (id, cod_projeto, id_tema)
);

COMMENT ON COLUMN mapcartacomp.lote.revisao_atual IS 'Derivada: passagens por etapas com conta_revisao.';
COMMENT ON COLUMN mapcartacomp.lote.status_nacional IS 'Derivado da fase da etapa atual; é o que a CCAR consolida.';

-- Uma folha aparece uma vez por projeto + tema (a mesma folha passa por vários temas).
CREATE UNIQUE INDEX IF NOT EXISTS lote_folha_uk
    ON mapcartacomp.lote (cod_projeto, id_tema, id_articulacao_scn) WHERE tipo = 'folha';
CREATE UNIQUE INDEX IF NOT EXISTS lote_livre_uk
    ON mapcartacomp.lote (cod_projeto, id_tema, uf, nome) WHERE tipo = 'livre';
CREATE INDEX IF NOT EXISTS lote_geom_idx ON mapcartacomp.lote USING gist (geom);
CREATE INDEX IF NOT EXISTS lote_atualizado_em_idx ON mapcartacomp.lote (uf, atualizado_em);

-- Passagem de um lote por uma etapa do fluxo. A folha 2534 pode ter CQ instância 1 (reprovada), revisão, CQ instância 2.
CREATE TABLE IF NOT EXISTS mapcartacomp.lote_etapa (
    id serial PRIMARY KEY,
    uuid uuid NOT NULL UNIQUE,
    id_lote integer NOT NULL REFERENCES mapcartacomp.lote (id) ON DELETE CASCADE,
    id_fluxo_etapa integer NOT NULL REFERENCES mapcartacomp.fluxo_etapa (id),
    uf char(2) NOT NULL CHECK (uf ~ '^[A-Z]{2}$'),
    instancia integer NOT NULL DEFAULT 1 CHECK (instancia >= 1),
    revisao integer,
    situacao text NOT NULL DEFAULT 'pendente' CHECK (situacao IN ('pendente', 'em_andamento', 'concluida', 'pulada')),
    resultado text,
    iniciada_em timestamptz,
    concluida_em timestamptz,
    concluida_por text,
    criado_em timestamptz NOT NULL DEFAULT now(),
    criado_por text NOT NULL DEFAULT current_user,
    atualizado_em timestamptz NOT NULL DEFAULT now(),
    atualizado_por text NOT NULL DEFAULT current_user,
    UNIQUE (id_lote, id_fluxo_etapa, instancia)
);

COMMENT ON COLUMN mapcartacomp.lote_etapa.revisao IS 'Revisão da folha nesta passagem. Nula no INSERT = derivada pelas regras (006).';
COMMENT ON COLUMN mapcartacomp.lote_etapa.resultado IS
    'Desfecho registrado pelo supervisor quando a etapa tem um (ex.: envio à GCQ: aprovada ou devolvida).';

CREATE INDEX IF NOT EXISTS lote_etapa_lote_idx ON mapcartacomp.lote_etapa (id_lote);
CREATE INDEX IF NOT EXISTS lote_etapa_atualizado_em_idx ON mapcartacomp.lote_etapa (uf, atualizado_em);

-- FK circular: etapa atual do lote (derivada). Criada depois de lote_etapa existir.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'mapcartacomp.lote'::regclass AND conname = 'lote_id_lote_etapa_atual_fkey'
    ) THEN
        ALTER TABLE mapcartacomp.lote ADD CONSTRAINT lote_id_lote_etapa_atual_fkey
            FOREIGN KEY (id_lote_etapa_atual) REFERENCES mapcartacomp.lote_etapa (id) ON DELETE SET NULL;
    END IF;
END
$$;

-- Ações do supervisor sobre as etapas (iniciar, concluir, pular, voltar, reabrir...), com quem e quando.
CREATE TABLE IF NOT EXISTS mapcartacomp.lote_etapa_hist (
    id bigserial PRIMARY KEY,
    uuid uuid NOT NULL UNIQUE,
    id_lote_etapa integer NOT NULL REFERENCES mapcartacomp.lote_etapa (id) ON DELETE CASCADE,
    uf char(2) NOT NULL CHECK (uf ~ '^[A-Z]{2}$'),
    acao text NOT NULL,
    em timestamptz NOT NULL DEFAULT now(),
    por text NOT NULL DEFAULT current_user,
    observacao text,
    criado_em timestamptz NOT NULL DEFAULT now(),
    criado_por text NOT NULL DEFAULT current_user,
    atualizado_em timestamptz NOT NULL DEFAULT now(),
    atualizado_por text NOT NULL DEFAULT current_user
);

COMMENT ON COLUMN mapcartacomp.lote_etapa_hist.acao IS
    'Valores previstos: iniciar, concluir, pular, voltar, reabrir, repetir, gcq_aprovada, gcq_devolvida.';

CREATE INDEX IF NOT EXISTS lote_etapa_hist_etapa_idx ON mapcartacomp.lote_etapa_hist (id_lote_etapa);
CREATE INDEX IF NOT EXISTS lote_etapa_hist_atualizado_em_idx ON mapcartacomp.lote_etapa_hist (uf, atualizado_em);

-- Carga de trabalho: unidade padronizada de trabalho dentro de uma passagem de etapa. Responsável nulo = disponível.
CREATE TABLE IF NOT EXISTS mapcartacomp.carga_trabalho (
    id serial PRIMARY KEY,
    uuid uuid NOT NULL UNIQUE,
    id_lote_etapa integer NOT NULL REFERENCES mapcartacomp.lote_etapa (id) ON DELETE CASCADE,
    id_cq_plano integer,
    uf char(2) NOT NULL CHECK (uf ~ '^[A-Z]{2}$'),
    responsavel text,
    geom geometry(MultiPolygon, 4674) NOT NULL,
    concluido boolean NOT NULL DEFAULT false,
    concluido_em timestamptz,
    criado_em timestamptz NOT NULL DEFAULT now(),
    criado_por text NOT NULL DEFAULT current_user,
    atualizado_em timestamptz NOT NULL DEFAULT now(),
    atualizado_por text NOT NULL DEFAULT current_user
);

COMMENT ON COLUMN mapcartacomp.carga_trabalho.responsavel IS
    'mapcartctrl.t_usuario.nom_contausuario (igual a current_user). Nulo = disponível para atribuição.';

CREATE INDEX IF NOT EXISTS carga_trabalho_lote_etapa_idx ON mapcartacomp.carga_trabalho (id_lote_etapa);
CREATE INDEX IF NOT EXISTS carga_trabalho_responsavel_idx ON mapcartacomp.carga_trabalho (responsavel);
CREATE INDEX IF NOT EXISTS carga_trabalho_geom_idx ON mapcartacomp.carga_trabalho USING gist (geom);
CREATE INDEX IF NOT EXISTS carga_trabalho_atualizado_em_idx ON mapcartacomp.carga_trabalho (uf, atualizado_em);
