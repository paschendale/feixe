#!/usr/bin/env python3
"""Spike S-06: grade estatística do IBGE por fórmula (feixe/core/grade.py e mapcartacomp.f_grade_* em SQL).

Uso:
    python3 scripts/spikes/s06_grade.py <conninfo> --folhas 2534,2535 [--oficial schema.tabela:campo ...]

<conninfo> é um banco com mapcartctrl (articulação) e as migrações do Feixe. O SQL do Feixe roda numa transação
desfeita no fim (as funções são criadas nela), então serve também para um banco onde o mapcartacomp não está aplicado.

--oficial aponta tabelas com células do shapefile oficial da grade já carregadas (geoftp.ibge.gov.br, recortes para
fins estatísticos, grade estatística, censo 2022), em SIRGAS2000, com o geocódigo no campo indicado; ex.:
feixe_s06.br5km:nome_5km. Para cada uma, o geocódigo e os vértices calculados em Python e em SQL são comparados
com os oficiais.

Mede também, por folha 1:100.000: células com centroide na folha em 5 km, 2,5 km e 1 km (Python e SQL, que precisam
dar o mesmo conjunto), se alguma célula cai em duas folhas da lista, e o tempo de gerar e de gravar as cargas.
"""

from __future__ import annotations

import argparse
import glob
import math
import os
import sys
import time
import uuid

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, RAIZ)

import psycopg2  # noqa: E402
from feixe.core import grade  # noqa: E402

NIVEIS = (5000, 2500, 1000)


def _dist_m(a, b) -> float:
    """Distância aproximada em metros entre dois pontos (lon, lat) próximos."""
    lat = math.radians((a[1] + b[1]) / 2)
    return math.hypot((a[0] - b[0]) * 111320.0 * math.cos(lat), (a[1] - b[1]) * 110574.0)


def _aplicar_feixe(cur) -> None:
    cur.execute("SET LOCAL client_min_messages = warning")
    for caminho in sorted(glob.glob(os.path.join(RAIZ, "feixe", "db", "ccar", "[0-9][0-9][0-9]_*.sql"))):
        with open(caminho, encoding="utf-8") as f:
            cur.execute(f.read())


def comparar_oficial(cur, alvo: str) -> dict:
    tabela, campo = alvo.split(":")
    cur.execute(f"SELECT {campo}, ST_AsText(ST_GeometryN(geom, 1)) FROM {tabela}")  # noqa: S608 (argumento do spike)
    linhas = cur.fetchall()
    pior_py, errados_py = 0.0, 0
    for cod, texto in linhas:
        oficial = grade.de_wkt(texto)[0][0]
        nosso = grade.poligono(cod)
        pior_py = max(pior_py, max(_dist_m(a, b) for a, b in zip(nosso, oficial)))
        lon = sum(p[0] for p in oficial[:4]) / 4
        lat = sum(p[1] for p in oficial[:4]) / 4
        nivel = grade.ler_geocodigo(cod)[0]
        if grade.celula_do_ponto(nivel, lon, lat) != cod:
            errados_py += 1
    # SQL: as células oficiais são recalculadas em lote por f_grade_celulas sobre a extensão da amostra (como na
    # geração de cargas) e comparadas vértice a vértice, pelo geocódigo.
    nivel = grade.ler_geocodigo(linhas[0][0])[0]
    cur.execute(
        f"""
        WITH nossas AS (
            SELECT c.geocodigo, c.geom FROM mapcartacomp.f_grade_celulas(
                (SELECT ST_SetSRID(ST_Extent(geom), 4674) FROM {tabela}), %s) c
        ), par AS (
            SELECT o.{campo} AS cod, (d).path[2] AS v, (d).geom AS ponto, n.geom AS nossa
              FROM (SELECT {campo}, ST_DumpPoints(ST_GeometryN(geom, 1)) d FROM {tabela}) o
              LEFT JOIN nossas n ON n.geocodigo = o.{campo}
        )
        SELECT max(ST_Distance(p.ponto::geography,
                               ST_PointN(ST_ExteriorRing(ST_GeometryN(p.nossa, 1)), p.v)::geography)),
               count(DISTINCT p.cod) FILTER (WHERE p.nossa IS NULL)
          FROM par p
        """,  # noqa: S608
        (nivel,),
    )
    pior_sql, errados_sql = cur.fetchone()
    return {
        "tabela": tabela,
        "celulas": len(linhas),
        "py_pior_m": pior_py,
        "py_geocodigo_errado": errados_py,
        "sql_pior_m": pior_sql,
        "sql_geocodigo_errado": errados_sql,
    }


def contar_folhas(cur, folhas) -> list:
    saida = []
    vistos = {n: {} for n in NIVEIS}
    for mi in folhas:
        cur.execute(
            "SELECT id_articulacao_scn, ST_AsText(geom) FROM mapcartctrl.v_articulacao_scn_100000 WHERE cd_mi = %s",
            (mi,),
        )
        id_folha, texto = cur.fetchone()
        geom = grade.de_wkt(texto)
        linha = {"folha": mi}
        for nivel in NIVEIS:
            t = time.perf_counter()
            py = list(grade.celulas_no_poligono(geom, nivel))
            linha[f"py_{nivel}_s"] = time.perf_counter() - t
            t = time.perf_counter()
            cur.execute(
                "SELECT c.geocodigo FROM mapcartctrl.t_articulacao_scn a, "
                "mapcartacomp.f_grade_celulas(a.geom, %s) c WHERE a.id_articulacao_scn = %s",
                (nivel, id_folha),
            )
            sql = [r[0] for r in cur.fetchall()]
            linha[f"sql_{nivel}_s"] = time.perf_counter() - t
            linha[str(nivel)] = len(py)
            linha[f"igual_{nivel}"] = py == sql
            for cod in py:
                vistos[nivel].setdefault(cod, []).append(mi)
        saida.append(linha)
    duplicadas = {n: sum(1 for v in vistos[n].values() if len(v) > 1) for n in NIVEIS}
    return saida, duplicadas


def gravar(cur, mi: str, nivel: int) -> dict:
    """Grava as cargas de uma folha num lote de teste (desfeito no fim) e mede o custo, com a regra da folha."""
    cur.execute("INSERT INTO mapcartacomp.tema (nome) VALUES ('s06') RETURNING id")
    tema = cur.fetchone()[0]
    cur.execute(
        "INSERT INTO mapcartacomp.atividade (cod_projeto, id_tema, fase, nome, geracao, grade_nivel) "
        "VALUES (5, %s, 'aquisicao', 's06', 'grade', %s) RETURNING id",
        (tema, nivel),
    )
    ativ = cur.fetchone()[0]
    cur.execute(
        "INSERT INTO mapcartacomp.fluxo (cod_projeto, id_tema, uf, nome) VALUES (5, %s, 'DF', 's06') RETURNING id",
        (tema,),
    )
    fluxo = cur.fetchone()[0]
    cur.execute(
        "INSERT INTO mapcartacomp.fluxo_etapa (id_fluxo, ordem, fase, nome) VALUES (%s, 1, 'aquisicao', 'a') "
        "RETURNING id",
        (fluxo,),
    )
    etapa = cur.fetchone()[0]
    cur.execute(
        "INSERT INTO mapcartacomp.fluxo_etapa_atividade (id_fluxo_etapa, id_atividade) VALUES (%s, %s)", (etapa, ativ)
    )
    cur.execute(
        "INSERT INTO mapcartacomp.lote (uuid, cod_projeto, id_tema, id_fluxo, uf, tipo, id_articulacao_scn, nome) "
        "SELECT %s, 5, %s, %s, 'DF', 'folha', id_articulacao_scn, cd_mi FROM mapcartctrl.v_articulacao_scn_100000 "
        "WHERE cd_mi = %s RETURNING id, (SELECT ST_AsText(geom) FROM mapcartctrl.v_articulacao_scn_100000 "
        "WHERE cd_mi = %s)",
        (str(uuid.uuid4()), tema, fluxo, mi, mi),
    )
    lote, texto = cur.fetchone()
    cur.execute(
        "INSERT INTO mapcartacomp.lote_etapa (uuid, id_lote, id_fluxo_etapa) VALUES (%s, %s, %s) RETURNING id",
        (str(uuid.uuid4()), lote, etapa),
    )
    le = cur.fetchone()[0]
    t = time.perf_counter()
    cods = list(grade.celulas_no_poligono(grade.de_wkt(texto), nivel))
    gerar = time.perf_counter() - t
    # Células geradas no servidor e gravadas com INSERT ... SELECT: mede o banco (gatilhos incluídos), sem a rede.
    cur.execute(
        "CREATE TEMP TABLE s06_celulas ON COMMIT DROP AS SELECT c.geocodigo, c.geom "
        "FROM mapcartctrl.v_articulacao_scn_100000 a, mapcartacomp.f_grade_celulas(a.geom, %s) c WHERE a.cd_mi = %s",
        (nivel, mi),
    )
    cur.execute("SELECT array_agg(geocodigo ORDER BY geocodigo) FROM s06_celulas")
    assert cur.fetchone()[0] == sorted(cods)
    t = time.perf_counter()
    cur.execute(
        "INSERT INTO mapcartacomp.carga_trabalho (uuid, id_lote_etapa, id_atividade, geom, geocodigo) "
        "SELECT md5(geocodigo || %s)::uuid, %s, %s, geom, geocodigo FROM s06_celulas",
        (str(uuid.uuid4()), le, ativ),
    )
    inserir = time.perf_counter() - t
    cur.execute("DROP TABLE s06_celulas")
    return {"folha": mi, "nivel": nivel, "cargas": len(cods), "gerar_s": gerar, "gravar_s": inserir}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("conninfo")
    p.add_argument("--folhas", required=True, help="MI das folhas 1:100.000, separados por vírgula")
    p.add_argument("--oficial", action="append", default=[], help="schema.tabela:campo com células oficiais")
    p.add_argument("--gravar", default="2534", help="folha onde medir a gravação das cargas")
    a = p.parse_args(argv)

    conn = psycopg2.connect(a.conninfo)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT version(), postgis_lib_version(), postgis_proj_version()")
            print("servidor:", *cur.fetchone())
            _aplicar_feixe(cur)
            for alvo in a.oficial:
                r = comparar_oficial(cur, alvo)
                print(
                    f"oficial {r['tabela']}: {r['celulas']} células; pior vértice Python {r['py_pior_m'] * 1000:.3f} mm"
                    f", SQL {r['sql_pior_m'] * 1000:.3f} mm; geocódigo errado Python {r['py_geocodigo_errado']}, "
                    f"SQL {r['sql_geocodigo_errado']}"
                )
            folhas = [f.strip() for f in a.folhas.split(",") if f.strip()]
            linhas, duplicadas = contar_folhas(cur, folhas)
            print("folha | 5 km | 2,5 km | 1 km | Python = SQL | tempo Python 5/2,5/1 km (ms) | tempo SQL (ms)")
            for li in linhas:
                print(
                    f"{li['folha']} | {li['5000']} | {li['2500']} | {li['1000']} | "
                    f"{all(li[f'igual_{n}'] for n in NIVEIS)} | "
                    + "/".join(f"{li[f'py_{n}_s'] * 1000:.0f}" for n in NIVEIS)
                    + " | "
                    + "/".join(f"{li[f'sql_{n}_s'] * 1000:.0f}" for n in NIVEIS)
                )
            for n in NIVEIS:
                valores = [li[str(n)] for li in linhas]
                print(
                    f"{n} m: mín {min(valores)}, máx {max(valores)}, média {sum(valores) / len(valores):.1f}, "
                    f"total {sum(valores)}, células em duas folhas {duplicadas[n]}"
                )
            for nivel in NIVEIS:
                cur.execute("SAVEPOINT g")
                r = gravar(cur, a.gravar, nivel)
                cur.execute("ROLLBACK TO SAVEPOINT g")
                print(
                    f"gravar folha {r['folha']} em {nivel} m: {r['cargas']} cargas; gerar {r['gerar_s'] * 1000:.0f} ms,"
                    f" gravar no servidor com a regra da folha {r['gravar_s'] * 1000:.0f} ms"
                )
    finally:
        conn.rollback()
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
