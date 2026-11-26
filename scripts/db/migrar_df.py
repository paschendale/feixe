#!/usr/bin/env python3
"""Converte o sistema atual da GGC-DF (schema bc100ggcdf_apoio, no banco da GGC) para o mapcartacomp (banco da CCAR).

Uso:
    python3 scripts/db/migrar_df.py <conninfo_ggc> <conninfo_ccar> [--ensaio] [--relatorio arquivo.txt]

Lê o banco da GGC (só leitura) e escreve no da CCAR numa única transação, conectado como dono do mapcartacomp.
Com --ensaio tudo é desfeito no fim. Pode ser rodado de novo: os uuid são derivados das chaves de origem (uuid5) e
cada linha é inserida ou atualizada, nunca duplicada. Precisa de psycopg2 (o Python do QGIS já traz).

Mapeamento (decisões no build log do projeto):
- atividade -> as atividades do BC100 do pré-seed do catálogo (002_referencias.sql), pelo nome; fluxos
  "DF Hidrografia", "DF ADE" e "DF LML";
- folha_revisao "2534-3" -> lote 2534 do tema, passagem de etapa na revisão 3;
- "NNNN-E" e "NNNN-R" -> correção de inspeção; "FINAL" -> correção topológica; "INSUMO_NOME" e "CORTE_M_DAGUA" ->
  revisões pontuais que não contam revisão; estas três são repartidas pela folha onde está a maior parte da carga;
- CQ: uma atividade por tema + medida (o nome da medida é o do SGBC) e um plano retroativo por medida em cada
  passagem. Cada amostra de origem vira uma carga da atividade da sua medida, com uma amostra: a carga de hidrografia
  com três amostras (nome, omissão, comissão) vira três cargas na mesma célula. A medida vem da amostra, não da
  atividade da carga. Na ADE, omissão e acurácia temporal foram sorteadas na grade completa e comissão e consistência
  topológica nas células com ADE. A letra-código é a do tamanho de amostra tabelado mais próximo do n observado; LQA e
  Ac ficam abertos;
- ignorados (e listados no relatório): atividade nula, massa d'água (não executado), "NNNN-X", "SHOW",
  "u_3448274", CQ sem amostras e cargas com mais da metade da área fora da folha (exceto grupos de CQ inteiros fora
  da folha do rótulo, que são erro de digitação do rótulo e vão para a folha onde estão).
"""

from __future__ import annotations

import argparse
import collections
import datetime
import re
import sys
import uuid
from typing import Dict, List, Optional, Tuple

NAMESPACE = uuid.UUID("5b0f0d3e-6c1e-4f43-9a54-3c1b8f2f1d00")
UF = "DF"
PROJETO = "BC100"
FUSO = "America/Sao_Paulo"

TEMAS = {"hid": "Hidrografia", "ade": "Áreas densamente edificadas", "lml": "LML"}

# Medidas de qualidade (nome em mapcartctrl.t_qua_medidadequalidade) das atividades de CQ do DF.
NOME, OMISSAO, COMISSAO = "Nome Geográfico", "Omissão", "Comissão"
ACURACIA, TOPOLOGIA = "Acurácia Temporal", "Consistência Topológica"

# Atividades do DF: as do pré-seed do catálogo (002_referencias.sql, D-87), procuradas pelo nome; a conversão não as
# cria nem muda os padrões de geração delas. chave: (tema, fase, nome, medida de qualidade)
_HID = "BC100 - Hidrografia"
_ADE = "BC100 - Áreas densamente edificadas"
ATIVIDADES = {
    "hid_aq": ("hid", "aquisicao", f"Aquisição {_HID}", None),
    "hid_cq_nome": ("hid", "cq", f"CQ {_HID} - {NOME}", NOME),
    "hid_cq_omi": ("hid", "cq", f"CQ {_HID} - {OMISSAO}", OMISSAO),
    "hid_cq_com": ("hid", "cq", f"CQ {_HID} - {COMISSAO}", COMISSAO),
    "hid_ci": ("hid", "correcao_inspecao", f"Correção de inspeção {_HID}", None),
    "hid_ct": ("hid", "correcao_topologica", f"Correção topológica {_HID}", None),
    "hid_gcq": ("hid", "envio_gcq", f"Envio à GCQ {_HID}", None),
    "hid_ins": ("hid", "revisao", f"Revisão pontual {_HID} - nomes de insumo", None),
    "hid_cor": ("hid", "revisao", f"Revisão pontual {_HID} - corte de massa d'água", None),
    "ade_aq": ("ade", "aquisicao", f"Aquisição {_ADE}", None),
    "ade_cq_omi": ("ade", "cq", f"CQ {_ADE} - {OMISSAO}", OMISSAO),
    "ade_cq_acu": ("ade", "cq", f"CQ {_ADE} - {ACURACIA}", ACURACIA),
    "ade_cq_com": ("ade", "cq", f"CQ {_ADE} - {COMISSAO}", COMISSAO),
    "ade_cq_top": ("ade", "cq", f"CQ {_ADE} - {TOPOLOGIA}", TOPOLOGIA),
    "lml_aq": ("lml", "aquisicao", "Aquisição BC100 - LML", None),
}  # fmt: skip

# Fluxos: tema -> (nome, [(chave da etapa, fase, [atividades], nome, obrigatória, repetível, conta revisão)]).
# O CQ de LML nunca teve amostra no DF: a etapa fica sem atividade até a GGC escolher as medidas.
# Padrão dos planos na etapa de CQ do fluxo convertido (D-135): (nível de inspeção, LQA %, fração crítica %).
PADRAO_CQ_DF = ("II", 2.5, 2.5)

FLUXOS = {
    "hid": ("DF Hidrografia", [
        ("aq", "aquisicao", ["hid_aq"], "Aquisição e revisão", True, True, True),
        ("cq", "cq", ["hid_cq_nome", "hid_cq_omi", "hid_cq_com"], "Controle de qualidade", False, True, False),
        ("ci", "correcao_inspecao", ["hid_ci"], "Correção de inspeção", False, True, False),
        ("ct", "correcao_topologica", ["hid_ct"], "Correção topológica", True, True, False),
        ("gcq", "envio_gcq", ["hid_gcq"], "Envio à GCQ", True, True, False),
        ("ins", "revisao", ["hid_ins"], "Revisão pontual: nomes de insumo", False, True, False),
        ("cor", "revisao", ["hid_cor"], "Revisão pontual: corte de massa d'água", False, True, False),
    ]),
    "ade": ("DF ADE", [
        ("aq", "aquisicao", ["ade_aq"], "Aquisição e revisão", True, True, True),
        ("cq", "cq", ["ade_cq_omi", "ade_cq_acu", "ade_cq_com", "ade_cq_top"], "Controle de qualidade", False, True,
         False),
    ]),
    "lml": ("DF LML", [
        ("aq", "aquisicao", ["lml_aq"], "Aquisição e revisão", True, True, True),
        ("cq", "cq", [], "Controle de qualidade", False, True, False),
    ]),
}  # fmt: skip

# Elemento gravado no sistema atual -> medida de qualidade.
ELEMENTOS = {
    "Nome": NOME,
    "nome": NOME,
    "Omissão": OMISSAO,
    "Comissão": COMISSAO,
    "Omissão - ADE": OMISSAO,
    "Comissão - ADE": COMISSAO,
    "Acuracia Temporal - ADE": ACURACIA,
    "Consistência Topológica - ADE": TOPOLOGIA,
}
# Atividade de CQ de cada tema + medida.
ATIVIDADE_DA_MEDIDA = {(v[0], v[3]): k for k, v in ATIVIDADES.items() if v[1] == "cq"}
# Universo de sorteio de cada medida na ADE (oficina de 2026-09-29).
UNIVERSO_ADE = {
    OMISSAO: "todas as células da grade sobre a folha",
    ACURACIA: "todas as células da grade sobre a folha",
    COMISSAO: "células da grade que intersectam ADE",
    TOPOLOGIA: "células da grade que intersectam ADE",
}

# Tamanhos de amostra do quadro de amostragem simples (letra-código -> n).
TAMANHOS = [("A", 2), ("B", 3), ("C", 5), ("D", 8), ("E", 13), ("F", 20), ("G", 32), ("H", 50), ("J", 80),
            ("K", 125), ("L", 200), ("M", 315), ("N", 500), ("P", 800), ("Q", 1250), ("R", 2000)]  # fmt: skip

# Nível de inspeção conhecido de passagens de CQ específicas (rótulo de origem -> nível).
NIVEL_POR_ROTULO = {"2470-5": "II", "2570-5": "III"}

ROTULO_NUM = re.compile(r"^(\d{4})[-_](\d+)$")
ROTULO_SUFIXO = re.compile(r"^(\d{4})-([A-Z])$")


def letra_mais_proxima(n: int) -> Optional[str]:
    """Letra-código do tamanho tabelado mais próximo de n (empate: o maior, já que amostras foram apagadas)."""
    if not n:
        return None
    return min(TAMANHOS, key=lambda t: (abs(t[1] - n), -t[1]))[0]


def uid(*partes) -> str:
    return str(uuid.uuid5(NAMESPACE, "/".join(str(p) for p in partes)))


# --- extração (banco da GGC) ---------------------------------------------------------------------------------------

SQL_ARTICULACAO = """
CREATE TEMP TABLE feixe_art AS SELECT cd_mi::text AS cd_mi, geom FROM mapcartctrl.v_articulacao_scn_100000;
CREATE INDEX ON feixe_art USING gist (geom);
ANALYZE feixe_art;
"""

SQL_CARGAS = f"""
WITH c AS (
    SELECT c.id_carga_trabalho, c.id_atividade, c.folha_revisao, c.responsavel,
           coalesce(c.concluido, false) AS concluido,
           c.concluido_em AT TIME ZONE '{FUSO}' AS concluido_em,
           coalesce(c.criada_em, c.concluido_em) AT TIME ZONE '{FUSO}' AS criada_em,
           ST_Multi(CASE WHEN ST_IsValid(c.geom) THEN c.geom
                         ELSE ST_CollectionExtract(ST_MakeValid(c.geom), 3) END) AS g,
           substring(c.folha_revisao FROM '^(\\d{{4}})[-_]') AS folha_rotulo
      FROM bc100ggcdf_apoio.carga_trabalho c
)
SELECT c.id_carga_trabalho, c.id_atividade, c.folha_revisao, c.responsavel, c.concluido, c.concluido_em, c.criada_em,
       encode(ST_AsEWKB(c.g), 'hex') AS geom, NOT ST_IsValid(c.g) OR ST_IsEmpty(c.g) AS geom_ruim,
       c.folha_rotulo,
       ST_Area(ST_Intersection(c.g, ar.geom)) / nullif(ST_Area(c.g), 0) AS frac_rotulo,
       m.cd_mi AS folha_maior, m.frac AS frac_maior
  FROM c
  LEFT JOIN feixe_art ar ON ar.cd_mi = c.folha_rotulo
  LEFT JOIN LATERAL (
        SELECT a.cd_mi, ST_Area(ST_Intersection(c.g, a.geom)) / nullif(ST_Area(c.g), 0) AS frac
          FROM feixe_art a WHERE a.geom && c.g ORDER BY 2 DESC NULLS LAST LIMIT 1) m ON true
"""

SQL_AMOSTRAS = f"""
SELECT id_cq_amostra, id_carga_trabalho, elemento, status, criado_em AT TIME ZONE '{FUSO}' AS criado_em
  FROM bc100ggcdf_apoio.cq_amostra
"""

SQL_INSPECOES = f"""
SELECT id_cq_inspecao, elemento, responsavel, anotacao, criado_em AT TIME ZONE '{FUSO}' AS criado_em,
       encode(ST_AsEWKB(geom), 'hex') AS geom
  FROM bc100ggcdf_apoio.cq_inspecao
"""


def _dicts(cur) -> List[dict]:
    nomes = [d[0] for d in cur.description]
    return [dict(zip(nomes, r)) for r in cur.fetchall()]


def extrair(ggc) -> dict:
    with ggc.cursor() as cur:
        cur.execute(SQL_ARTICULACAO)
        cur.execute(SQL_CARGAS)
        cargas = _dicts(cur)
        cur.execute(SQL_AMOSTRAS)
        amostras = _dicts(cur)
        cur.execute(SQL_INSPECOES)
        inspecoes = _dicts(cur)
        cur.execute("SELECT usuario, nullif(trim(equipe), '') AS equipe FROM bc100ggcdf_apoio.equipe")
        equipe = _dicts(cur)
        cur.execute("SELECT data, dia_util, descricao FROM bc100ggcdf_apoio.calendario")
        calendario = _dicts(cur)
    ggc.rollback()
    return {"cargas": cargas, "amostras": amostras, "inspecoes": inspecoes, "equipe": equipe, "calendario": calendario}


# --- classificação ---------------------------------------------------------------------------------------------------


class Relatorio:
    def __init__(self):
        self.ignoradas = collections.defaultdict(list)  # motivo -> [id de origem]
        self.amostras_ignoradas = collections.defaultdict(int)
        self.avisos: List[str] = []
        self.contagens: Dict[str, int] = collections.Counter()

    def ignorar(self, motivo: str, carga: dict):
        self.ignoradas[motivo].append(carga["id_carga_trabalho"])

    def texto(self) -> str:
        linhas = [f"Conversão bc100ggcdf_apoio -> mapcartacomp ({datetime.datetime.now():%Y-%m-%d %H:%M})", ""]
        for k in sorted(self.contagens):
            linhas.append(f"  {k}: {self.contagens[k]}")
        linhas += ["", "Cargas ignoradas:"]
        for motivo, ids in sorted(self.ignoradas.items(), key=lambda kv: -len(kv[1])):
            amostra = ", ".join(str(i) for i in sorted(ids)[:15]) + (" ..." if len(ids) > 15 else "")
            linhas.append(f"  {len(ids):6d}  {motivo}  [{amostra}]")
        linhas += ["", "Amostras ignoradas:"]
        for motivo, n in sorted(self.amostras_ignoradas.items()):
            linhas.append(f"  {n:6d}  {motivo}")
        linhas += ["", "Avisos:"] + [f"  - {a}" for a in self.avisos]
        return "\n".join(linhas) + "\n"


class Passagem:
    """Uma passagem de um lote por uma etapa (vira lote_etapa)."""

    def __init__(self, tema: str, folha: str, etapa: str, rotulo: str, revisao: Optional[int]):
        self.tema, self.folha, self.etapa, self.rotulo, self.revisao = tema, folha, etapa, rotulo, revisao
        self.cargas: List[dict] = []
        self.nivel: Optional[str] = None
        self.instancia = 0

    @property
    def chave(self):
        return (self.tema, self.folha, self.etapa, self.rotulo)

    @property
    def inicio(self):
        return min(c["criada_em"] for c in self.cargas)


def classificar(dados: dict, rel: Relatorio) -> Tuple[Dict[tuple, Passagem], Dict[int, List[dict]]]:
    amostras_por_carga: Dict[int, List[dict]] = collections.defaultdict(list)
    for a in dados["amostras"]:
        amostras_por_carga[a["id_carga_trabalho"]].append(a)

    # Grupos de CQ de hidrografia inteiramente fora da folha do rótulo: erro de digitação do rótulo.
    grupos = collections.defaultdict(list)
    for c in dados["cargas"]:
        if c["id_atividade"] == 2 and c["folha_revisao"]:
            grupos[c["folha_revisao"]].append(c)
    folha_corrigida = {}
    for rotulo, cs in grupos.items():
        fora = [c for c in cs if (c["frac_rotulo"] or 0) < 0.5]
        if len(fora) * 2 > len(cs):
            destino = collections.Counter(c["folha_maior"] for c in fora).most_common(1)[0][0]
            folha_corrigida[rotulo] = destino
            rel.avisos.append(f"CQ '{rotulo}' ({len(cs)} cargas) está na folha {destino}: convertido como dela")

    passagens: Dict[tuple, Passagem] = {}

    def por(c, tema, folha, etapa, rotulo, revisao):
        k = (tema, folha, etapa, rotulo)
        if k not in passagens:
            passagens[k] = Passagem(tema, folha, etapa, rotulo, revisao)
        passagens[k].cargas.append(c)

    for c in dados["cargas"]:
        a, fr = c["id_atividade"], c["folha_revisao"]
        m = ROTULO_NUM.match(fr or "")
        sufixo = ROTULO_SUFIXO.match(fr or "")
        if a is None:
            rel.ignorar("atividade nula", c)
        elif a in (5, 8):
            rel.ignorar("referência de massa d'água (não executado)", c)
        elif fr is None:
            rel.ignorar("sem folha_revisao", c)
        elif fr == "SHOW":
            rel.ignorar("demonstração (SHOW)", c)
        elif fr == "u_3448274":
            rel.ignorar("lote de teste (u_3448274)", c)
        elif sufixo and sufixo.group(2) == "X":
            rel.ignorar("revisão X (fora da conta)", c)
        elif c["geom_ruim"]:
            rel.ignorar("geometria inválida ou vazia mesmo depois de corrigida", c)
        elif fr in ("FINAL", "INSUMO_NOME", "CORTE_M_DAGUA") and a == 1:
            if (c["frac_maior"] or 0) < 0.5:
                rel.ignorar(f"{fr}: nenhuma folha tem metade da carga", c)
            else:
                etapa = {"FINAL": "ct", "INSUMO_NOME": "ins", "CORTE_M_DAGUA": "cor"}[fr]
                por(c, "hid", c["folha_maior"], etapa, fr, None)
        elif sufixo and sufixo.group(2) in ("E", "R") and a == 1:
            if (c["frac_rotulo"] or 0) < 0.5:
                rel.ignorar("correção de inspeção fora da folha do rótulo", c)
            else:
                por(c, "hid", sufixo.group(1), "ci", fr, None)
        elif m and a in (1, 2, 11, 12, 13, 14, 15, 21, 22):
            folha, revisao = m.group(1), int(m.group(2))
            if a == 2 and fr in folha_corrigida:
                folha = folha_corrigida[fr]
            elif (c["frac_rotulo"] or 0) < 0.5:
                rel.ignorar("mais da metade da área fora da folha do rótulo", c)
                continue
            if a == 1:
                por(c, "hid", folha, "aq", f"{folha}-{revisao}", revisao)
            elif a == 2:
                por(c, "hid", folha, "cq", fr, revisao)
            elif a == 11:
                por(c, "ade", folha, "aq", f"{folha}-{revisao}", revisao)
            elif a in (12, 13, 14, 15):
                if not amostras_por_carga.get(c["id_carga_trabalho"]):
                    rel.ignorar("CQ de ADE sem amostra (planejamento incompleto)", c)
                    continue
                por(c, "ade", folha, "cq", f"{folha}-{revisao}", revisao)
            elif a == 21:
                por(c, "lml", folha, "aq", f"{folha}-{revisao}", revisao)
            else:
                por(c, "lml", folha, "cq", f"{folha}-{revisao}", revisao)
        else:
            rel.ignorar(f"sem mapeamento (atividade {a}, rótulo {fr})", c)

    # Instâncias por lote e etapa, em ordem cronológica; revisão das etapas que não contam revisão = a revisão de
    # aquisição mais recente iniciada antes delas (ou a maior, se nenhuma).
    por_lote_etapa = collections.defaultdict(list)
    for p in passagens.values():
        por_lote_etapa[(p.tema, p.folha, p.etapa)].append(p)
    for lista in por_lote_etapa.values():
        lista.sort(key=lambda p: (p.inicio, p.rotulo))
        for i, p in enumerate(lista, start=1):
            p.instancia = i
    for p in passagens.values():
        if p.revisao is None:
            aqs = por_lote_etapa.get((p.tema, p.folha, "aq"), [])
            antes = [q.revisao for q in aqs if q.inicio <= p.inicio] or [q.revisao for q in aqs] or [0]
            p.revisao = max(antes)
        if p.etapa == "cq":
            p.nivel = "II" if p.tema == "ade" else NIVEL_POR_ROTULO.get(p.rotulo)
    return passagens, amostras_por_carga


# --- carga (banco da CCAR) -------------------------------------------------------------------------------------------


def _executar_valores(cur, sql, linhas, template=None, page_size=500):
    from psycopg2.extras import execute_values

    if not linhas:
        return []
    return execute_values(cur, sql, linhas, template=template, page_size=page_size, fetch=True)


def _referencias(cur, rel) -> dict:
    cur.execute("SELECT cod_projeto FROM mapcartctrl.t_projeto WHERE nom_projeto = %s", (PROJETO,))
    projeto = cur.fetchone()[0]
    # Temas e atividades vêm do pré-seed do catálogo (002_referencias.sql): aqui só se procura pelo nome.
    temas = {}
    for k, nome in TEMAS.items():
        cur.execute("SELECT id FROM mapcartacomp.tema WHERE nome = %s", (nome,))
        linha = cur.fetchone()
        if linha is None:
            raise RuntimeError(f"tema {nome!r} ausente: aplique as migrações (pré-seed do 002) antes da conversão")
        temas[k] = linha[0]
    ativ = {}
    for k, (tema, fase, nome, _medida) in ATIVIDADES.items():
        cur.execute(
            "SELECT id, id_tema, fase FROM mapcartacomp.atividade WHERE cod_projeto = %s AND nome = %s",
            (projeto, nome),
        )
        linha = cur.fetchone()
        if linha is None or (linha[1], linha[2]) != (temas[tema], fase):
            raise RuntimeError(f"atividade {nome!r} ausente ou diferente no pré-seed do 002 (tema e fase)")
        ativ[k] = linha[0]
    fluxos, etapas, etapa_ativ = {}, {}, {}
    for tema, (nome, lista) in FLUXOS.items():
        cur.execute(
            "INSERT INTO mapcartacomp.fluxo (cod_projeto, id_tema, uf, nome) VALUES (%s, %s, %s, %s) "
            "ON CONFLICT (cod_projeto, id_tema, uf, nome) DO UPDATE SET ativo = true RETURNING id",
            (projeto, temas[tema], UF, nome),
        )
        fluxos[tema] = cur.fetchone()[0]
        for ordem, (chave, fase, atividades, nome_etapa, obrig, repet, conta) in enumerate(lista, start=1):
            # Padrão dos planos de CQ do DF (D-135): nível II, LQA 2,5% e fração crítica 2,5%.
            nivel, lqa, fracao = PADRAO_CQ_DF if fase == "cq" else (None, None, None)
            # A unicidade (fluxo, ordem) é adiável e não serve para ON CONFLICT: atualiza ou insere à mão.
            cur.execute(
                "UPDATE mapcartacomp.fluxo_etapa SET fase = %s, nome = %s, obrigatoria = %s, repetivel = %s, "
                "conta_revisao = %s, nivel_inspecao = %s, lqa = %s, fracao_critica = %s "
                "WHERE id_fluxo = %s AND ordem = %s RETURNING id",
                (fase, nome_etapa, obrig, repet, conta, nivel, lqa, fracao, fluxos[tema], ordem),
            )
            linha = cur.fetchone()
            if linha is None:
                cur.execute(
                    "INSERT INTO mapcartacomp.fluxo_etapa (id_fluxo, ordem, fase, nome, obrigatoria, repetivel, "
                    "conta_revisao, nivel_inspecao, lqa, fracao_critica) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
                    (fluxos[tema], ordem, fase, nome_etapa, obrig, repet, conta, nivel, lqa, fracao),
                )
                linha = cur.fetchone()
            etapas[(tema, chave)] = linha[0]
            ids = [ativ[a] for a in atividades]
            cur.execute(
                "DELETE FROM mapcartacomp.fluxo_etapa_atividade WHERE id_fluxo_etapa = %s AND id_atividade <> ALL(%s)",
                (linha[0], ids),
            )
            for i in ids:
                cur.execute(
                    "INSERT INTO mapcartacomp.fluxo_etapa_atividade (id_fluxo_etapa, id_atividade) VALUES (%s, %s) "
                    "ON CONFLICT DO NOTHING",
                    (linha[0], i),
                )
            if len(ids) == 1:
                etapa_ativ[(tema, chave)] = ids[0]
    cur.execute("SELECT cd_mi::text, id_articulacao_scn FROM mapcartctrl.v_articulacao_scn_100000")
    folhas = dict(cur.fetchall())
    return {
        "projeto": projeto,
        "temas": temas,
        "fluxos": fluxos,
        "etapas": etapas,
        "etapa_ativ": etapa_ativ,
        "ativ": ativ,
        "folhas": folhas,
    }


def _planos(p: Passagem, amostras_por_carga, rel: Relatorio) -> List[dict]:
    """Planos retroativos de uma passagem de CQ: um por medida, com os pares (carga de origem, amostra) dela.

    Carga sem amostra é ignorada (não há medida para dar a ela); amostra de elemento sem atividade também.
    """
    por_medida: Dict[str, list] = collections.defaultdict(list)
    for c in p.cargas:
        amostras = amostras_por_carga.get(c["id_carga_trabalho"], [])
        if not amostras:
            rel.ignorar("CQ sem amostra", c)
            continue
        medidas = [ELEMENTOS.get((a["elemento"] or "").strip()) for a in amostras]
        usadas = [(m, a) for m, a in zip(medidas, amostras) if (p.tema, m) in ATIVIDADE_DA_MEDIDA]
        if not usadas:
            rel.ignorar("CQ com elemento fora dos planos", c)  # as amostras contam como "da carga ignorada"
            continue
        rel.amostras_ignoradas["elemento sem atividade de CQ no tema"] += len(amostras) - len(usadas)
        for m, a in usadas:
            por_medida[m].append((c, a))
    planos = []
    for medida, itens in sorted(por_medida.items()):
        planos.append({
            "medida": medida,
            "atividade": ATIVIDADE_DA_MEDIDA[(p.tema, medida)],
            "universo": UNIVERSO_ADE.get(medida) if p.tema == "ade" else None,
            "itens": itens,
        })  # fmt: skip
    return planos


def carregar(ccar, dados: dict, passagens: Dict[tuple, Passagem], amostras_por_carga, rel: Relatorio) -> None:
    with ccar.cursor() as cur:
        cur.execute("SET LOCAL client_min_messages = warning")
        ref = _referencias(cur, rel)

        # Lotes (um por tema e folha).
        lotes = {}
        for tema, folha in sorted({(p.tema, p.folha) for p in passagens.values()}):
            if folha not in ref["folhas"]:
                rel.avisos.append(f"folha {folha} não está na articulação 1:100.000 da CCAR")
                continue
            cur.execute(
                "INSERT INTO mapcartacomp.lote (uuid, cod_projeto, id_tema, id_fluxo, uf, tipo, id_articulacao_scn, "
                "nome) VALUES (%s, %s, %s, %s, %s, 'folha', %s, %s) ON CONFLICT (uuid) DO UPDATE SET "
                "id_fluxo = EXCLUDED.id_fluxo RETURNING id",
                (
                    uid("lote", PROJETO, tema, folha),
                    ref["projeto"],
                    ref["temas"][tema],
                    ref["fluxos"][tema],
                    UF,
                    ref["folhas"][folha],
                    folha,
                ),  # fmt: skip
            )
            lotes[(tema, folha)] = cur.fetchone()[0]
        rel.contagens["lotes"] = len(lotes)

        cargas_linhas, amostras_linhas, hist = [], [], []
        convertidas = set()
        n_planos = 0
        for p in sorted(passagens.values(), key=lambda q: (q.tema, q.folha, q.inicio)):
            if (p.tema, p.folha) not in lotes:
                for c in p.cargas:
                    rel.ignorar("folha fora da articulação da CCAR", c)
                continue
            concl = [c for c in p.cargas if c["concluido"]]
            situacao = "concluida" if len(concl) == len(p.cargas) else "em_andamento"
            fim = max((c["concluido_em"] for c in concl if c["concluido_em"]), default=None)
            le_uuid = uid("lote_etapa", p.tema, p.folha, p.etapa, p.rotulo)
            cur.execute(
                "INSERT INTO mapcartacomp.lote_etapa (uuid, id_lote, id_fluxo_etapa, uf, instancia, revisao, "
                "situacao, iniciada_em, concluida_em) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (uuid) DO UPDATE SET instancia = EXCLUDED.instancia, revisao = EXCLUDED.revisao, "
                "situacao = EXCLUDED.situacao, iniciada_em = EXCLUDED.iniciada_em, "
                "concluida_em = EXCLUDED.concluida_em RETURNING id",
                (
                    le_uuid,
                    lotes[(p.tema, p.folha)],
                    ref["etapas"][(p.tema, p.etapa)],
                    UF,
                    p.instancia,
                    p.revisao,
                    situacao,
                    p.inicio,
                    fim if situacao == "concluida" else None,
                ),  # fmt: skip
            )
            id_le = cur.fetchone()[0]
            hist.append((uid("lote_etapa_hist", le_uuid), id_le, UF, "importar", p.inicio,
                         f"convertido de bc100ggcdf_apoio ({p.rotulo})"))  # fmt: skip

            if p.etapa != "cq":
                for c in p.cargas:
                    responsavel = None if c["responsavel"] in (None, "", "DISPONIVEL") else c["responsavel"]
                    cargas_linhas.append((uid("carga_trabalho", c["id_carga_trabalho"]), id_le,
                                          ref["etapa_ativ"][(p.tema, p.etapa)], None, UF, responsavel, c["geom"],
                                          c["concluido"], c["concluido_em"], c["criada_em"]))  # fmt: skip
                    convertidas.add(c["id_carga_trabalho"])
                continue
            for plano in _planos(p, amostras_por_carga, rel):
                n = len(plano["itens"])
                id_ativ = ref["ativ"][plano["atividade"]]
                cur.execute(
                    "INSERT INTO mapcartacomp.cq_plano (uuid, id_lote_etapa, id_atividade, uf, orientacao, universo, "
                    "nivel_inspecao, letra_codigo, tamanho_amostra_n, lqa) "
                    "VALUES (%s, %s, %s, %s, 'area', %s, %s, %s, %s, %s) ON CONFLICT (uuid) DO UPDATE SET "
                    "id_atividade = EXCLUDED.id_atividade, universo = EXCLUDED.universo, "
                    "nivel_inspecao = EXCLUDED.nivel_inspecao, letra_codigo = EXCLUDED.letra_codigo, "
                    "tamanho_amostra_n = EXCLUDED.tamanho_amostra_n, lqa = EXCLUDED.lqa RETURNING id",
                    (
                        uid("cq_plano", le_uuid, plano["medida"]),
                        id_le,
                        id_ativ,
                        UF,
                        plano["universo"],
                        p.nivel,
                        letra_mais_proxima(n),
                        n,
                        4.0 if p.tema == "hid" else None,
                    ),  # fmt: skip
                )
                id_plano = cur.fetchone()[0]
                n_planos += 1
                for c, a in plano["itens"]:
                    # Uma carga por amostra: concluída se a amostra foi avaliada, na hora de conclusão da carga de
                    # origem ou, sem ela, na da amostra.
                    avaliada = a["status"] is not None
                    concluido_em = (c["concluido_em"] if c["concluido"] else None) or a["criado_em"]
                    if avaliada and not c["concluido"]:
                        rel.contagens["cargas de CQ concluídas na conversão (amostra avaliada)"] += 1
                    responsavel = None if c["responsavel"] in (None, "", "DISPONIVEL") else c["responsavel"]
                    u_carga = uid("carga_trabalho", c["id_carga_trabalho"], plano["medida"])
                    cargas_linhas.append((u_carga, id_le, id_ativ, id_plano, UF, responsavel, c["geom"], avaliada,
                                          concluido_em if avaliada else None, c["criada_em"]))  # fmt: skip
                    amostras_linhas.append((uid("cq_amostra", a["id_cq_amostra"]), id_plano, u_carga, UF, a["status"],
                                            concluido_em if avaliada else None, responsavel if avaliada else None,
                                            a["criado_em"]))  # fmt: skip
                    convertidas.add(c["id_carga_trabalho"])
        rel.contagens["passagens de etapa"] = len(hist)
        rel.contagens["planos de CQ"] = n_planos

        _executar_valores(
            cur,
            "INSERT INTO mapcartacomp.lote_etapa_hist (uuid, id_lote_etapa, uf, acao, em, observacao) VALUES %s "
            "ON CONFLICT (uuid) DO UPDATE SET observacao = EXCLUDED.observacao RETURNING id",
            hist,
        )
        ids_carga = {}
        for u, i in _executar_valores(
            cur,
            "INSERT INTO mapcartacomp.carga_trabalho (uuid, id_lote_etapa, id_atividade, id_cq_plano, uf, responsavel, "
            "geom, concluido, concluido_em, criado_em) VALUES %s ON CONFLICT (uuid) DO UPDATE SET "
            "id_lote_etapa = EXCLUDED.id_lote_etapa, id_atividade = EXCLUDED.id_atividade, "
            "id_cq_plano = EXCLUDED.id_cq_plano, "
            "responsavel = EXCLUDED.responsavel, geom = EXCLUDED.geom, concluido = EXCLUDED.concluido, "
            "concluido_em = EXCLUDED.concluido_em RETURNING uuid::text, id",
            cargas_linhas,
            template="(%s, %s, %s, %s, %s, %s, %s::geometry, %s, %s, %s)",
        ):
            ids_carga[u] = i
        rel.contagens["cargas convertidas"] = len(convertidas)
        rel.contagens["cargas gravadas"] = len(ids_carga)

        _executar_valores(
            cur,
            "INSERT INTO mapcartacomp.cq_amostra (uuid, id_cq_plano, id_carga_trabalho, uf, status, "
            "avaliado_em, avaliado_por, criado_em) VALUES %s ON CONFLICT (uuid) DO UPDATE SET "
            "id_cq_plano = EXCLUDED.id_cq_plano, status = EXCLUDED.status, "
            "avaliado_em = EXCLUDED.avaliado_em, avaliado_por = EXCLUDED.avaliado_por RETURNING id",
            [(a[0], a[1], ids_carga[a[2]], *a[3:]) for a in amostras_linhas],
        )
        rel.contagens["amostras convertidas"] = len(amostras_linhas)
        ignoradas = {i for ids in rel.ignoradas.values() for i in ids}
        for a in dados["amostras"]:
            if a["id_carga_trabalho"] in ignoradas:
                rel.amostras_ignoradas["da carga ignorada"] += 1

        _inspecoes(cur, dados["inspecoes"], rel)
        _equipe_e_calendario(cur, dados, rel)


def _inspecoes(cur, inspecoes, rel):
    """Liga cada ocorrência à carga convertida que contém o ponto (de preferência do mesmo responsável)."""
    n = 0
    for i in inspecoes:
        if i["geom"] is None:
            rel.avisos.append(f"ocorrência {i['id_cq_inspecao']} sem geometria: ignorada")
            continue
        cur.execute(
            "SELECT c.id, le.id_lote FROM mapcartacomp.carga_trabalho c "
            "JOIN mapcartacomp.lote_etapa le ON le.id = c.id_lote_etapa "
            "WHERE c.uf = %s AND c.geom && %s::geometry AND ST_Intersects(c.geom, %s::geometry) "
            "ORDER BY (c.responsavel = %s) DESC NULLS LAST, (c.id_cq_plano IS NOT NULL) DESC, c.criado_em DESC "
            "LIMIT 1",
            (UF, i["geom"], i["geom"], i["responsavel"]),
        )
        achou = cur.fetchone()
        if achou is None:
            rel.avisos.append(f"ocorrência {i['id_cq_inspecao']} fora de qualquer carga convertida: ignorada")
            continue
        elemento = ELEMENTOS.get((i["elemento"] or "").strip())
        cur.execute(
            "INSERT INTO mapcartacomp.cq_inspecao (uuid, id_lote, id_carga_trabalho, uf, elemento, geom, anotacao, "
            "responsavel, criado_em) VALUES (%s, %s, %s, %s, %s, %s::geometry, %s, %s, coalesce(%s, now())) "
            "ON CONFLICT (uuid) DO UPDATE SET id_lote = EXCLUDED.id_lote, "
            "id_carga_trabalho = EXCLUDED.id_carga_trabalho, elemento = EXCLUDED.elemento, "
            "anotacao = EXCLUDED.anotacao",
            (
                uid("cq_inspecao", i["id_cq_inspecao"]),
                achou[1],
                achou[0],
                UF,
                elemento,
                i["geom"],
                i["anotacao"],
                i["responsavel"] or "desconhecido",
                i["criado_em"],
            ),  # fmt: skip
        )
        n += 1
    rel.contagens["ocorrências convertidas"] = n


def _equipe_e_calendario(cur, dados, rel):
    n = 0
    for e in dados["equipe"]:
        if e["usuario"] == "DISPONIVEL":  # usuário fictício do sistema atual; disponível agora é responsável nulo
            continue
        cur.execute("SELECT 1 FROM mapcartctrl.t_usuario WHERE nom_contausuario = %s", (e["usuario"],))
        if cur.fetchone() is None:
            rel.avisos.append(f"usuário de equipe {e['usuario']} não existe em mapcartctrl.t_usuario da CCAR")
            continue
        equipe = e["equipe"]
        if equipe and equipe.lower().startswith("estagi"):
            equipe = "Estagiários"
        cur.execute(
            "INSERT INTO mapcartacomp.usuario_feixe (usuario, equipe) VALUES (%s, %s) "
            "ON CONFLICT (usuario) DO UPDATE SET equipe = EXCLUDED.equipe",
            (e["usuario"], equipe),
        )
        n += 1
    rel.contagens["usuários do Feixe"] = n
    _executar_valores(
        cur,
        "INSERT INTO mapcartacomp.calendario (uf, data, dia_util, descricao) VALUES %s ON CONFLICT (uf, data) "
        "DO UPDATE SET dia_util = EXCLUDED.dia_util, descricao = EXCLUDED.descricao RETURNING data",
        [(UF, d["data"], d["dia_util"], d["descricao"]) for d in dados["calendario"]],
    )
    rel.contagens["dias de calendário"] = len(dados["calendario"])


def converter(ggc, ccar) -> Relatorio:
    """Faz a conversão na transação aberta de `ccar`, sem confirmar. Quem chama decide entre commit e rollback."""
    rel = Relatorio()
    dados = extrair(ggc)
    rel.contagens["cargas na origem"] = len(dados["cargas"])
    rel.contagens["amostras na origem"] = len(dados["amostras"])
    rel.contagens["ocorrências na origem"] = len(dados["inspecoes"])
    passagens, amostras_por_carga = classificar(dados, rel)
    carregar(ccar, dados, passagens, amostras_por_carga, rel)
    rel.contagens["cargas ignoradas"] = sum(len(v) for v in rel.ignoradas.values())
    return rel


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("ggc", help="conexão com o banco da GGC-DF (lê bc100ggcdf_apoio)")
    p.add_argument("ccar", help="conexão com o banco da CCAR (escreve em mapcartacomp, como dono do schema)")
    p.add_argument("--ensaio", action="store_true", help="converte e desfaz tudo no fim")
    p.add_argument("--relatorio", help="arquivo onde gravar o relatório (além de imprimir)")
    a = p.parse_args(argv)
    import psycopg2

    ggc, ccar = psycopg2.connect(a.ggc), psycopg2.connect(a.ccar)
    try:
        rel = converter(ggc, ccar)
        if a.ensaio:
            ccar.rollback()
        else:
            ccar.commit()
    finally:
        ggc.close()
        ccar.close()
    texto = rel.texto() + ("\n(ensaio: nada foi gravado)\n" if a.ensaio else "")
    sys.stdout.write(texto)
    if a.relatorio:
        with open(a.relatorio, "w", encoding="utf-8") as f:
            f.write(texto)
    return 0


if __name__ == "__main__":
    sys.exit(main())
