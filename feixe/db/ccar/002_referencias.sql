-- 002: tabelas de referência do Feixe: tema, fase, catálogo de CQ, atividade, fluxo, etapas do fluxo e suas atividades,
-- usuários do Feixe e calendário.
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

-- Catálogo de CQ: os elementos de qualidade são os do SGBC (mapcartctrl.t_qua_medidadequalidade) e não são
-- replicados aqui. O Feixe guarda só o que acrescenta a eles: se o elemento é núcleo da GCQ e a fração crítica padrão.
CREATE TABLE IF NOT EXISTS mapcartacomp.cq_elemento (
    id_medidadequalidade integer PRIMARY KEY REFERENCES mapcartctrl.t_qua_medidadequalidade (id),
    nucleo boolean NOT NULL DEFAULT false,
    fracao_critica numeric NOT NULL DEFAULT 4 CHECK (fracao_critica > 0 AND fracao_critica < 100),
    ordem integer NOT NULL DEFAULT 0,
    ativo boolean NOT NULL DEFAULT true,
    criado_em timestamptz NOT NULL DEFAULT now(),
    criado_por text NOT NULL DEFAULT current_user,
    atualizado_em timestamptz NOT NULL DEFAULT now(),
    atualizado_por text NOT NULL DEFAULT current_user
);

COMMENT ON TABLE mapcartacomp.cq_elemento IS
    'Elementos de qualidade que o Feixe oferece no CQ. Nome e descrição vêm de mapcartctrl.t_qua_medidadequalidade.';
COMMENT ON COLUMN mapcartacomp.cq_elemento.nucleo IS 'Elemento núcleo da GCQ, presente no catálogo nacional.';
COMMENT ON COLUMN mapcartacomp.cq_elemento.fracao_critica IS
    'Fração crítica padrão da CCAR, em %. A etapa de CQ do fluxo pode adotar outra (fluxo_etapa.fracao_critica).';

-- Elementos núcleo da GCQ, com a fração crítica padrão de 4%. Procurados pelo nome no SGBC: a GCQ chama de
-- "correta classificação" e "inspeção topológica" o que no SGBC é "Correção da Classificação" e "Consistência
-- Topológica". Acurácia temporal fica fora: é atividade local do DF.
DO $$
DECLARE
    v_faltam text;
BEGIN
    INSERT INTO mapcartacomp.cq_elemento (id_medidadequalidade, nucleo, fracao_critica, ordem)
    SELECT m.id, true, 4, n.ordem
      FROM (VALUES ('Comissão', 1), ('Omissão', 2), ('Nome Geográfico', 3), ('Correção da Classificação', 4),
                   ('Consistência Topológica', 5)) n (nome, ordem)
      JOIN mapcartctrl.t_qua_medidadequalidade m ON m.nome = n.nome
    ON CONFLICT (id_medidadequalidade) DO NOTHING;

    SELECT string_agg(n.nome, ', ') INTO v_faltam
      FROM (VALUES ('Comissão'), ('Omissão'), ('Nome Geográfico'), ('Correção da Classificação'),
                   ('Consistência Topológica')) n (nome)
     WHERE NOT EXISTS (SELECT 1 FROM mapcartctrl.t_qua_medidadequalidade m WHERE m.nome = n.nome);
    IF v_faltam IS NOT NULL THEN
        RAISE EXCEPTION 'elementos núcleo da GCQ ausentes em mapcartctrl.t_qua_medidadequalidade: %', v_faltam;
    END IF;
END
$$;

-- Atividade = projeto + tema + fase, com os padrões de geração de cargas. Atividade de CQ é tema + medida de
-- qualidade: cada medida inspecionada tem a sua atividade (ex.: "CQ ADE - Omissão"), com plano e cargas próprios.
-- Os campos de geração ficam abertos de propósito (sem lista fechada): o módulo de CQ ainda vai defini-los.
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
    id_medidadequalidade integer REFERENCES mapcartacomp.cq_elemento (id_medidadequalidade),
    camada_alvo text,
    grade_nivel integer CHECK (grade_nivel IN (500000, 100000, 50000, 10000, 5000, 2500, 1000, 200)),
    ativo boolean NOT NULL DEFAULT true,
    criado_em timestamptz NOT NULL DEFAULT now(),
    criado_por text NOT NULL DEFAULT current_user,
    atualizado_em timestamptz NOT NULL DEFAULT now(),
    atualizado_por text NOT NULL DEFAULT current_user,
    UNIQUE (cod_projeto, nome),
    -- Toda atividade de CQ tem a sua medida; as outras fases não têm medida.
    CHECK ((fase = 'cq') = (id_medidadequalidade IS NOT NULL))
);

COMMENT ON COLUMN mapcartacomp.atividade.geracao IS
    'Como as cargas são geradas. Valores previstos: grade, amostra_area, amostra_feicao, manual, nenhuma.';
COMMENT ON COLUMN mapcartacomp.atividade.celula_unidade IS 'Unidade de celula_largura/altura: grau, metro, cm_na_escala.';
COMMENT ON COLUMN mapcartacomp.atividade.id_medidadequalidade IS
    'Medida de qualidade que a atividade de CQ inspeciona (cq_elemento, nome no SGBC). Obrigatória na fase cq.';
COMMENT ON COLUMN mapcartacomp.atividade.grade_nivel IS
    'Nível da grade estatística do IBGE (lado da célula em metros) em que as cargas da atividade são geradas: 5000, '
    '2500 (sub-nível do Feixe), 1000... Nulo = atividade que não usa a grade. Contas em mapcartacomp.f_grade_*.';

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

-- Etapa do fluxo. A fase decide o status nacional; as atividades da etapa ficam em fluxo_etapa_atividade (uma na
-- aquisição, uma por medida no CQ). O supervisor anda com a folha pelas etapas; nada avança sozinho.
CREATE TABLE IF NOT EXISTS mapcartacomp.fluxo_etapa (
    id serial PRIMARY KEY,
    id_fluxo integer NOT NULL REFERENCES mapcartacomp.fluxo (id) ON DELETE CASCADE,
    ordem integer NOT NULL,
    fase text NOT NULL REFERENCES mapcartacomp.fase (codigo),
    nome text NOT NULL,
    obrigatoria boolean NOT NULL DEFAULT true,
    repetivel boolean NOT NULL DEFAULT false,
    conta_revisao boolean NOT NULL DEFAULT false,
    fracao_critica numeric CHECK (fracao_critica > 0 AND fracao_critica < 100),
    criado_em timestamptz NOT NULL DEFAULT now(),
    criado_por text NOT NULL DEFAULT current_user,
    atualizado_em timestamptz NOT NULL DEFAULT now(),
    atualizado_por text NOT NULL DEFAULT current_user,
    -- Adiável para permitir reordenar etapas numa transação.
    UNIQUE (id_fluxo, ordem) DEFERRABLE INITIALLY IMMEDIATE
);

COMMENT ON COLUMN mapcartacomp.fluxo_etapa.conta_revisao IS
    'Cada passagem por esta etapa incrementa a revisão da folha (o "3" de "2534-3").';
COMMENT ON COLUMN mapcartacomp.fluxo_etapa.fracao_critica IS
    'Fração crítica (em %) que a GGC adota nesta etapa de CQ, contra a qual se mostra o nível de conformidade. '
    'Nula = a fração crítica padrão de cada elemento (cq_elemento).';

-- Atividades de cada etapa do fluxo, escolhidas pela GGC: na etapa de CQ, uma por medida inspecionada (o DF põe
-- acurácia temporal na ADE, outra GGC pode ficar só com as medidas núcleo). Cargas e planos da passagem só podem ser
-- de atividades da etapa, da mesma fase e do mesmo projeto e tema do fluxo (006).
CREATE TABLE IF NOT EXISTS mapcartacomp.fluxo_etapa_atividade (
    id_fluxo_etapa integer NOT NULL REFERENCES mapcartacomp.fluxo_etapa (id) ON DELETE CASCADE,
    id_atividade integer NOT NULL REFERENCES mapcartacomp.atividade (id),
    criado_em timestamptz NOT NULL DEFAULT now(),
    criado_por text NOT NULL DEFAULT current_user,
    atualizado_em timestamptz NOT NULL DEFAULT now(),
    atualizado_por text NOT NULL DEFAULT current_user,
    PRIMARY KEY (id_fluxo_etapa, id_atividade)
);

CREATE INDEX IF NOT EXISTS fluxo_etapa_atividade_atividade_idx ON mapcartacomp.fluxo_etapa_atividade (id_atividade);

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
CREATE INDEX IF NOT EXISTS fluxo_etapa_atividade_atualizado_em_idx ON mapcartacomp.fluxo_etapa_atividade (atualizado_em);
CREATE INDEX IF NOT EXISTS calendario_atualizado_em_idx ON mapcartacomp.calendario (uf, atualizado_em);
CREATE INDEX IF NOT EXISTS usuario_feixe_atualizado_em_idx ON mapcartacomp.usuario_feixe (atualizado_em);
CREATE INDEX IF NOT EXISTS cq_elemento_atualizado_em_idx ON mapcartacomp.cq_elemento (atualizado_em);
