"""A8: grade estatística em SQL, regra da carga na folha com geocódigo, catálogo de CQ e ciência de ocorrências.

Roda nos dois bancos (PostgreSQL 17 da CCAR e 9.6 da GGC), com as migrações aplicadas numa transação desfeita.
As células oficiais vêm do shapefile da Grade Estatística 2022 (as mesmas de tests/test_grade.py).
"""

from __future__ import annotations

import uuid

import pytest
from feixe.core import grade

from tests.db.migracoes import aplicar
from tests.test_grade import OFICIAIS

pytestmark = pytest.mark.db


def _um(cur, sql, params=()):
    cur.execute(sql, params)
    return cur.fetchone()[0]


@pytest.fixture
def cur(banco):
    aplicar(banco)
    with banco.cursor() as c:
        yield c


@pytest.mark.parametrize("cod", sorted(OFICIAIS))
def test_sql_igual_a_celula_oficial(cur, cod):
    cur.execute(
        "SELECT (d).path[3], ST_X((d).geom), ST_Y((d).geom) "
        "FROM (SELECT ST_DumpPoints(mapcartacomp.f_grade_celula(%s)) d) s ORDER BY 1",
        (cod,),
    )
    vertices = [(x, y) for _, x, y in cur.fetchall()]
    assert len(vertices) == 5
    for a, b in zip(vertices, OFICIAIS[cod]):
        assert abs(a[0] - b[0]) < 1e-7 and abs(a[1] - b[1]) < 1e-7  # ~1 cm
    lon = sum(p[0] for p in OFICIAIS[cod]) / 4
    lat = sum(p[1] for p in OFICIAIS[cod]) / 4
    nivel = grade.ler_geocodigo(cod)[0]
    cur.execute(
        "SELECT mapcartacomp.f_grade_geocodigo(%s, ST_X(p), ST_Y(p)) FROM "
        "(SELECT ST_Transform(ST_SetSRID(ST_MakePoint(%s, %s), 4674), mapcartacomp.f_grade_proj()) p) s",
        (nivel, lon, lat),
    )
    assert cur.fetchone()[0] == cod


def test_sql_ler_geocodigo(cur, psycopg2):
    cur.execute("SELECT * FROM mapcartacomp.f_grade_ler('2500ME51025N77625')")
    assert cur.fetchone() == (2500, 5102500, 7762500)
    cur.execute("SELECT * FROM mapcartacomp.f_grade_ler('100KME5000N7550')")
    assert cur.fetchone() == (100000, 5000000, 7550000)
    for ruim in ("4KME5724N9424", "5KME5726N9425", "lixo", "5000ME57250N94250"):
        cur.execute("SAVEPOINT s")
        with pytest.raises(psycopg2.errors.InvalidParameterValue):
            cur.execute("SELECT * FROM mapcartacomp.f_grade_ler(%s)", (ruim,))
        cur.execute("ROLLBACK TO SAVEPOINT s")


def _folha(cur, mi):
    cur.execute(
        "SELECT id_articulacao_scn, ST_AsText(geom) FROM mapcartctrl.v_articulacao_scn_100000 WHERE cd_mi = %s", (mi,)
    )
    return cur.fetchone()


def test_sql_e_python_dao_as_mesmas_celulas_e_nenhuma_em_duas_folhas(cur):
    """Folha 2534 e as vizinhas a leste, ao norte e a nordeste: mesmo conjunto em Python e SQL, nenhuma repetida."""
    vistas = {}
    for mi in ("2534", "2535", "2496", "2497"):
        id_folha, texto = _folha(cur, mi)
        for nivel in (5000, 2500):
            cur.execute(
                "SELECT c.geocodigo FROM mapcartctrl.t_articulacao_scn a, mapcartacomp.f_grade_celulas(a.geom, %s) c "
                "WHERE a.id_articulacao_scn = %s",
                (nivel, id_folha),
            )
            sql = [r[0] for r in cur.fetchall()]
            assert sql == list(grade.celulas_no_poligono(grade.de_wkt(texto), nivel))
            for c in sql:
                assert c not in vistas, f"{c} em {vistas.get(c)} e {mi}"
                vistas[c] = mi
    n_2534 = sum(1 for c, mi in vistas.items() if mi == "2534" and c.startswith("5KM"))
    assert 110 <= n_2534 <= 125


class Lote:
    """Folha 2534 num lote de teste com uma passagem de aquisição."""

    def __init__(self, cur, mi="2534"):
        self.cur = cur
        tema = _um(cur, "INSERT INTO mapcartacomp.tema (nome) VALUES ('teste_grade') RETURNING id")
        ativ = _um(
            cur,
            "INSERT INTO mapcartacomp.atividade (cod_projeto, id_tema, fase, nome, geracao, grade_nivel) "
            "VALUES (5, %s, 'aquisicao', 'teste grade', 'grade', 5000) RETURNING id",
            (tema,),
        )
        fluxo = _um(
            cur,
            "INSERT INTO mapcartacomp.fluxo (cod_projeto, id_tema, uf, nome) VALUES (5, %s, 'DF', 'f') RETURNING id",
            (tema,),
        )
        etapa = _um(
            cur,
            "INSERT INTO mapcartacomp.fluxo_etapa (id_fluxo, ordem, id_atividade, nome, fracao_critica) "
            "VALUES (%s, 1, %s, 'Aquisição', 2.5) RETURNING id",
            (fluxo, ativ),
        )
        self.id_folha, self.texto = _folha(cur, mi)
        self.lote = _um(
            cur,
            "INSERT INTO mapcartacomp.lote (uuid, cod_projeto, id_tema, id_fluxo, uf, tipo, id_articulacao_scn, nome) "
            "VALUES (%s, 5, %s, %s, 'DF', 'folha', %s, %s) RETURNING id",
            (str(uuid.uuid4()), tema, fluxo, self.id_folha, mi),
        )
        self.le = _um(
            cur,
            "INSERT INTO mapcartacomp.lote_etapa (uuid, id_lote, id_fluxo_etapa) VALUES (%s, %s, %s) RETURNING id",
            (str(uuid.uuid4()), self.lote, etapa),
        )

    def carga(self, geocodigo, geom_wkt=None):
        return _um(
            self.cur,
            "INSERT INTO mapcartacomp.carga_trabalho (uuid, id_lote_etapa, geocodigo, geom) "
            "VALUES (%s, %s, %s, coalesce(ST_GeomFromText(%s, 4674), mapcartacomp.f_grade_celula(%s))) RETURNING id",
            (str(uuid.uuid4()), self.le, geocodigo, geom_wkt, geocodigo),
        )

    def fracao(self, geocodigo):
        return _um(
            self.cur,
            "SELECT mapcartacomp.f_fracao_na_folha(mapcartacomp.f_grade_celula(%s), %s)",
            (geocodigo, self.id_folha),
        )


def test_regra_da_folha_com_e_sem_geocodigo(cur, psycopg2):
    # Folha 2496: a célula de canto 5KME5990N9195 tem o centroide dentro da folha e só 40,8% da área dentro.
    lote = Lote(cur, "2496")
    canto = "5KME5990N9195"
    assert 0.40 < lote.fracao(canto) < 0.41
    lon, lat = grade.centroide(canto)
    assert grade.contem(grade.de_wkt(lote.texto), lon, lat)
    lote.carga(canto)
    # Todas as células de 5 km da folha entram.
    for c in grade.celulas_no_poligono(grade.de_wkt(lote.texto), 5000):
        lote.carga(c)
    # Célula da folha vizinha a leste (2497), com centroide fora da 2496: recusada.
    _, texto_vizinha = _folha(cur, "2497")
    vizinha = next(iter(grade.celulas_no_poligono(grade.de_wkt(texto_vizinha), 5000)))
    cur.execute("SAVEPOINT s")
    with pytest.raises(psycopg2.errors.CheckViolation, match="centroide"):
        lote.carga(vizinha)
    cur.execute("ROLLBACK TO SAVEPOINT s")
    # Trocar o geocódigo de uma carga aceita para uma célula de fora também é recusado.
    aceita = lote.carga(canto)
    cur.execute("SAVEPOINT s")
    with pytest.raises(psycopg2.errors.CheckViolation):
        cur.execute("UPDATE mapcartacomp.carga_trabalho SET geocodigo = %s WHERE id = %s", (vizinha, aceita))
    cur.execute("ROLLBACK TO SAVEPOINT s")
    # A mesma célula de canto sem geocódigo (malha importada) cai na regra da metade da área: recusada.
    with pytest.raises(psycopg2.errors.CheckViolation, match="área"):
        lote.carga(None, grade.wkt(canto))


def test_geocodigo_mal_formado_e_recusado(cur, psycopg2):
    lote = Lote(cur)
    # O gatilho lê o geocódigo antes da restrição da coluna; qualquer das duas recusa.
    with pytest.raises((psycopg2.errors.CheckViolation, psycopg2.errors.InvalidParameterValue)):
        lote.carga("5km-5725-9425", grade.wkt("5KME5725N9425"))


def test_carga_legada_sem_geocodigo_continua_na_regra_da_metade(cur, psycopg2):
    lote = Lote(cur)
    # Célula de 0,05° da 2534 (como as do DF): aceita; deslocada para ter 20% dentro: recusada.
    lote.carga(None, "MULTIPOLYGON(((-44.52 -20,-44.52 -19.95,-44.47 -19.95,-44.47 -20,-44.52 -20)))")
    with pytest.raises(psycopg2.errors.CheckViolation):
        lote.carga(None, "MULTIPOLYGON(((-44.54 -20,-44.54 -19.95,-44.49 -19.95,-44.49 -20,-44.54 -20)))")


def test_catalogo_de_cq(cur):
    cur.execute(
        "SELECT m.nome, e.nucleo, e.fracao_critica FROM mapcartacomp.cq_elemento e "
        "JOIN mapcartctrl.t_qua_medidadequalidade m ON m.id = e.id_medidadequalidade ORDER BY e.ordem"
    )
    assert cur.fetchall() == [
        ("Comissão", True, 4),
        ("Omissão", True, 4),
        ("Nome Geográfico", True, 4),
        ("Correção da Classificação", True, 4),
        ("Consistência Topológica", True, 4),
    ]
    cur.execute(
        "SELECT column_name, data_type, is_nullable FROM information_schema.columns "
        "WHERE table_schema = 'mapcartacomp' AND (table_name, column_name) IN "
        "(('fluxo_etapa', 'fracao_critica'), ('atividade', 'grade_nivel'), ('carga_trabalho', 'geocodigo'), "
        "('lote_etapa', 'expor_ocorrencias'), ('cq_inspecao', 'ciente_em'), "
        "('cq_inspecao', 'ciente_por')) ORDER BY 1"
    )
    assert cur.fetchall() == [
        ("ciente_em", "timestamp with time zone", "YES"),
        ("ciente_por", "text", "YES"),
        ("expor_ocorrencias", "boolean", "NO"),
        ("fracao_critica", "numeric", "YES"),
        ("geocodigo", "text", "YES"),
        ("grade_nivel", "integer", "YES"),
    ]


def test_nivel_da_grade_na_atividade(cur, psycopg2):
    tema = _um(cur, "INSERT INTO mapcartacomp.tema (nome) VALUES ('teste_nivel') RETURNING id")
    with pytest.raises(psycopg2.errors.CheckViolation):
        cur.execute(
            "INSERT INTO mapcartacomp.atividade (cod_projeto, id_tema, fase, nome, grade_nivel) "
            "VALUES (5, %s, 'cq', 'x', 4000)",
            (tema,),
        )


def test_ciencia_e_exposicao_de_ocorrencias(cur, psycopg2):
    lote = Lote(cur)
    assert _um(cur, "SELECT expor_ocorrencias FROM mapcartacomp.lote_etapa WHERE id = %s", (lote.le,)) is False
    oc = _um(
        cur,
        "INSERT INTO mapcartacomp.cq_inspecao (uuid, id_lote, elemento, geom) "
        "VALUES (%s, %s, 'Omissão', ST_SetSRID(ST_MakePoint(-44.3, -19.7), 4674)) RETURNING id",
        (str(uuid.uuid4()), lote.lote),
    )
    cur.execute(
        "UPDATE mapcartacomp.cq_inspecao SET ciente_em = now(), ciente_por = current_user WHERE id = %s "
        "RETURNING tratado",
        (oc,),
    )
    assert cur.fetchone()[0] is False  # ciência não é correção
    with pytest.raises(psycopg2.errors.CheckViolation):
        cur.execute("UPDATE mapcartacomp.cq_inspecao SET ciente_por = NULL WHERE id = %s", (oc,))


def test_formula_inversa_em_sql_igual_ao_st_transform(cur):
    """O gatilho usa a fórmula inversa em PL/pgSQL; ela tem que coincidir com o ST_Transform (e com o Python)."""
    cur.execute(
        "SELECT max(ST_Distance(f::geography, t::geography)), count(*) FROM ("
        "  SELECT mapcartacomp.f_grade_de_albers(x, y) f, "
        "         ST_Transform(ST_MakePoint(x, y), mapcartacomp.f_grade_proj(), 4674) t "
        "    FROM generate_series(2900000, 8100000, 400000) x, generate_series(7400000, 12100000, 400000) y) s"
    )
    pior, n = cur.fetchone()
    assert n > 150 and pior < 1e-4  # 0,1 mm
    cur.execute("SELECT ST_X(p), ST_Y(p) FROM (SELECT mapcartacomp.f_grade_de_albers(5727500, 9427500) p) s")
    lon, lat = cur.fetchone()
    assert (lon, lat) == pytest.approx(grade.de_albers(5727500, 9427500), abs=1e-11)
