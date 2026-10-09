-- 002: tabelas de referência do Feixe: tema, fase, atividade, fluxo, etapas do fluxo, usuários do Feixe e calendário.
-- Compatível com PostgreSQL 9.6. Idempotente.
-- Projeto, escala, usuário e articulação são lidos de mapcartctrl; aqui só há chaves estrangeiras para lá.

-- Tema da produção (hidrografia, ADE, LML...).
CREATE TABLE IF NOT EXISTS mapcartacomp.tema (
    id serial PRIMARY KEY,
    nome text NOT NULL UNIQUE,
    ativo boolean NOT NULL DEFAULT true,
    criado_em timestamptz NOT NULL DEFAULT now(),
    criado_por text NOT NULL DEFAULT current_user,
    atualizado_em timestamptz NOT NULL DEFAULT now(),
    atualizado_por text NOT NULL DEFAULT current_user
);

-- Fase (tipo) de uma atividade. Lista fixa, semeada abaixo; cada fase cai em exatamente um status nacional.
CREATE TABLE IF NOT EXISTS mapcartacomp.fase (
    codigo text PRIMARY KEY,
    nome text NOT NULL,
    ordem integer NOT NULL,
    status_nacional text NOT NULL CHECK (status_nacional IN ('EM_PRODUCAO', 'EM_CQ', 'ENTREGUE_GCQ'))
);

INSERT INTO mapcartacomp.fase (codigo, nome, ordem, status_nacional) VALUES
    ('aquisicao', 'Aquisição', 1, 'EM_PRODUCAO'),
    ('revisao', 'Revisão', 2, 'EM_PRODUCAO'),
    ('cq', 'Controle de qualidade', 3, 'EM_CQ'),
    ('correcao_inspecao', 'Correção de inspeção', 4, 'EM_PRODUCAO'),
    ('correcao_topologica', 'Correção topológica', 5, 'EM_PRODUCAO'),
    ('envio_gcq', 'Envio à GCQ', 6, 'ENTREGUE_GCQ'),
    ('outra', 'Outra produção', 7, 'EM_PRODUCAO')
ON CONFLICT (codigo) DO NOTHING;

-- Atividade = projeto + tema + fase, com os padrões de geração de cargas.
-- Os campos de geração e de CQ ficam abertos de propósito (sem lista fechada): o módulo de CQ ainda vai defini-los.
CREATE TABLE IF NOT EXISTS mapcartacomp.atividade (
    id serial PRIMARY KEY,
    cod_projeto integer NOT NULL REFERENCES mapcartctrl.t_projeto (cod_projeto),
    id_tema integer NOT NULL REFERENCES mapcartacomp.tema (id),
    fase text NOT NULL REFERENCES mapcartacomp.fase (codigo),
    nome text NOT NULL,
    geracao text,
    celula_largura numeric,
    celula_altura numeric,
    celula_unidade text,
    elementos_cq text[],
    camada_alvo text,
    ativo boolean NOT NULL DEFAULT true,
    criado_em timestamptz NOT NULL DEFAULT now(),
    criado_por text NOT NULL DEFAULT current_user,
    atualizado_em timestamptz NOT NULL DEFAULT now(),
    atualizado_por text NOT NULL DEFAULT current_user,
    UNIQUE (cod_projeto, nome)
);

COMMENT ON COLUMN mapcartacomp.atividade.geracao IS
    'Como as cargas são geradas. Valores previstos: grade, amostra_area, amostra_feicao, manual, nenhuma.';
COMMENT ON COLUMN mapcartacomp.atividade.celula_unidade IS 'Unidade de celula_largura/altura: grau, metro, cm_na_escala.';

-- Fluxo da GGC: sequência de etapas por projeto + tema + UF.
CREATE TABLE IF NOT EXISTS mapcartacomp.fluxo (
    id serial PRIMARY KEY,
    cod_projeto integer NOT NULL REFERENCES mapcartctrl.t_projeto (cod_projeto),
    id_tema integer NOT NULL REFERENCES mapcartacomp.tema (id),
    uf char(2) NOT NULL CHECK (uf ~ '^[A-Z]{2}$'),
    nome text NOT NULL,
    ativo boolean NOT NULL DEFAULT true,
    criado_em timestamptz NOT NULL DEFAULT now(),
    criado_por text NOT NULL DEFAULT current_user,
    atualizado_em timestamptz NOT NULL DEFAULT now(),
    atualizado_por text NOT NULL DEFAULT current_user,
    UNIQUE (cod_projeto, id_tema, uf, nome),
    -- Alvo da FK composta de lote: garante que o lote usa um fluxo do mesmo projeto e tema.
    UNIQUE (id, cod_projeto, id_tema)
);

-- Etapa do fluxo, ligada a uma atividade. O supervisor anda com a folha pelas etapas; nada avança sozinho.
CREATE TABLE IF NOT EXISTS mapcartacomp.fluxo_etapa (
    id serial PRIMARY KEY,
    id_fluxo integer NOT NULL REFERENCES mapcartacomp.fluxo (id) ON DELETE CASCADE,
    ordem integer NOT NULL,
    id_atividade integer NOT NULL REFERENCES mapcartacomp.atividade (id),
    nome text NOT NULL,
    obrigatoria boolean NOT NULL DEFAULT true,
    repetivel boolean NOT NULL DEFAULT false,
    conta_revisao boolean NOT NULL DEFAULT false,
    criado_em timestamptz NOT NULL DEFAULT now(),
    criado_por text NOT NULL DEFAULT current_user,
    atualizado_em timestamptz NOT NULL DEFAULT now(),
    atualizado_por text NOT NULL DEFAULT current_user,
    -- Adiável para permitir reordenar etapas numa transação.
    UNIQUE (id_fluxo, ordem) DEFERRABLE INITIALLY IMMEDIATE
);

COMMENT ON COLUMN mapcartacomp.fluxo_etapa.conta_revisao IS
    'Cada passagem por esta etapa incrementa a revisão da folha (o "3" de "2534-3").';

-- O que o Feixe guarda sobre o usuário e não existe em mapcartctrl: equipe (subgrupo na GGC) e o papel gerente.
CREATE TABLE IF NOT EXISTS mapcartacomp.usuario_feixe (
    usuario text PRIMARY KEY REFERENCES mapcartctrl.t_usuario (nom_contausuario),
    equipe text,
    gerente boolean NOT NULL DEFAULT false,
    ativo boolean NOT NULL DEFAULT true,
    criado_em timestamptz NOT NULL DEFAULT now(),
    criado_por text NOT NULL DEFAULT current_user,
    atualizado_em timestamptz NOT NULL DEFAULT now(),
    atualizado_por text NOT NULL DEFAULT current_user
);

-- Dias que não contam para a produtividade, por UF.
CREATE TABLE IF NOT EXISTS mapcartacomp.calendario (
    uf char(2) NOT NULL CHECK (uf ~ '^[A-Z]{2}$'),
    data date NOT NULL,
    dia_util boolean NOT NULL DEFAULT true,
    descricao text,
    criado_em timestamptz NOT NULL DEFAULT now(),
    criado_por text NOT NULL DEFAULT current_user,
    atualizado_em timestamptz NOT NULL DEFAULT now(),
    atualizado_por text NOT NULL DEFAULT current_user,
    PRIMARY KEY (uf, data)
);

CREATE INDEX IF NOT EXISTS atividade_atualizado_em_idx ON mapcartacomp.atividade (atualizado_em);
CREATE INDEX IF NOT EXISTS fluxo_atualizado_em_idx ON mapcartacomp.fluxo (uf, atualizado_em);
CREATE INDEX IF NOT EXISTS fluxo_etapa_atualizado_em_idx ON mapcartacomp.fluxo_etapa (atualizado_em);
CREATE INDEX IF NOT EXISTS calendario_atualizado_em_idx ON mapcartacomp.calendario (uf, atualizado_em);
CREATE INDEX IF NOT EXISTS usuario_feixe_atualizado_em_idx ON mapcartacomp.usuario_feixe (atualizado_em);
