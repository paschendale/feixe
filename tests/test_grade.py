"""feixe.core.grade: células da grade estatística do IBGE por fórmula, conferidas contra o shapefile oficial."""

from __future__ import annotations

import math

import pytest
from feixe.core import grade

# Células do shapefile oficial da Grade Estatística 2022 (geoftp do IBGE, BR5KM_20251002 e BR1KM_20251002), em
# SIRGAS2000: geocódigo e os quatro cantos na ordem do arquivo.
OFICIAIS = {
    "5KME5645N9565": [(-47.899033631839636, -15.812169371531365), (-47.90006469418243, -15.767588575570054),
                      (-47.85279353485939, -15.766612618583576), (-47.851754487473904, -15.811193205120329)],
    "5KME5725N9425": [(-47.11000480037901, -17.044736610002783), (-47.111174644266974, -17.000091894706323),
                      (-47.06368490561076, -16.998988571482037), (-47.06250700371902, -17.043633029999512)],
    "1KME5647N9567": [(-47.880535676181445, -15.793947280462302), (-47.88074252745627, -15.785031138207781),
                      (-47.871287656831385, -15.784835930072012), (-47.87108048615485, -15.793752063949649)],
    "1KME5541N9703": [(-48.9062802091022, -14.600883086532939), (-48.90645161661158, -14.591975194438783),
                      (-48.897038641249715, -14.591812840522422), (-48.896866917116384, -14.600720726208133)],
}  # fmt: skip

# Folha 2534 (1:100.000) como na articulação: retângulo de meio grau.
FOLHA_2534 = [[[(-44.5, -20.0), (-44.5, -19.5), (-44.0, -19.5), (-44.0, -20.0), (-44.5, -20.0)]]]


def _dist_m(a, b):
    lat = math.radians(b[1])
    return math.hypot((a[0] - b[0]) * 111320 * math.cos(lat), (a[1] - b[1]) * 110574)


@pytest.mark.parametrize("cod", sorted(OFICIAIS))
def test_geometria_igual_a_oficial(cod):
    nosso = grade.poligono(cod)
    assert nosso[0] == nosso[-1] and len(nosso) == 5
    for a, b in zip(nosso, OFICIAIS[cod]):
        assert _dist_m(a, b) < 0.01  # 1 cm


@pytest.mark.parametrize("cod", sorted(OFICIAIS))
def test_geocodigo_do_ponto_igual_ao_oficial(cod):
    cantos = OFICIAIS[cod]
    lon = sum(p[0] for p in cantos) / 4
    lat = sum(p[1] for p in cantos) / 4
    nivel = grade.ler_geocodigo(cod)[0]
    assert grade.celula_do_ponto(nivel, lon, lat) == cod


def test_ida_e_volta_da_projecao():
    for lon, lat in [(-47.9, -15.8), (-73.9, 5.2), (-34.8, -33.7), (-54.0, -12.0)]:
        x, y = grade.para_albers(lon, lat)
        lon2, lat2 = grade.de_albers(x, y)
        assert abs(lon - lon2) < 1e-10 and abs(lat - lat2) < 1e-10
    # Origem da projeção: (-54, -12) cai no falso E/N.
    x, y = grade.para_albers(-54.0, -12.0)
    assert abs(x - 5000000) < 1e-6 and abs(y - 10000000) < 1e-6


@pytest.mark.parametrize(
    "cod,esperado",
    [
        ("1KME5100N7764", (1000, 5100000, 7764000)),  # exemplos das notas metodológicas
        ("200ME49836N78114", (200, 4983600, 7811400)),
        ("5KME5725N9425", (5000, 5725000, 9425000)),
        ("10KME5030N7590", (10000, 5030000, 7590000)),  # níveis em km sempre em km, também acima de 5 km
        ("500KME2800N9850", (500000, 2800000, 9850000)),
        ("2500ME51025N77625", (2500, 5102500, 7762500)),  # sub-nível do Feixe
    ],
)
def test_ler_e_escrever_geocodigo(cod, esperado):
    assert grade.ler_geocodigo(cod) == esperado
    assert grade.geocodigo(*esperado) == cod


@pytest.mark.parametrize(
    "cod",
    ["", "5KM", "5KME5725", "4KME5724N9424", "5000ME57250N94250", "5KME5726N9425", "2500ME51020N77625", "1kme1N1"],
)
def test_geocodigo_invalido(cod):
    with pytest.raises(grade.GeocodigoInvalido):
        grade.ler_geocodigo(cod)


def test_nivel_desconhecido():
    with pytest.raises(ValueError):
        grade.celula_do_ponto(4000, -47.9, -15.8)


def test_subnivel_de_2500_divide_a_celula_de_5km_em_quatro():
    _, x0, y0 = grade.ler_geocodigo("5KME5725N9425")
    filhas = {grade.geocodigo(2500, x0 + dx, y0 + dy) for dx in (0, 2500) for dy in (0, 2500)}
    assert filhas == {"2500ME57250N94250", "2500ME57275N94250", "2500ME57250N94275", "2500ME57275N94275"}
    for f in filhas:
        lon, lat = grade.centroide(f)
        assert grade.celula_do_ponto(5000, lon, lat) == "5KME5725N9425"


def test_celulas_da_folha_pelo_centroide():
    for nivel in (5000, 2500, 1000):
        cods = list(grade.celulas_no_poligono(FOLHA_2534, nivel))
        assert len(cods) == len(set(cods))
        for c in cods:
            lon, lat = grade.centroide(c)
            assert -44.5 <= lon <= -44.0 and -20.0 <= lat <= -19.5
        # A área da folha dividida pela área da célula, com folga para as células da borda.
        area_folha = 0.5 * 111320 * math.cos(math.radians(19.75)) * 0.5 * 110574
        assert abs(len(cods) - area_folha / nivel**2) < 4 * (2 * 55000 / nivel + 1)
    assert 110 <= len(list(grade.celulas_no_poligono(FOLHA_2534, 5000))) <= 125


def test_folhas_vizinhas_nao_dividem_celula():
    """Quatro folhas em bloco: toda célula de qualquer uma delas pertence a uma só."""
    folhas = []
    for dx in (0, 0.5):
        for dy in (0, 0.5):
            x, y = -44.5 + dx, -20.0 + dy
            folhas.append([[(x, y), (x, y + 0.5), (x + 0.5, y + 0.5), (x + 0.5, y), (x, y)]])
    for nivel in (5000, 2500):
        todas = [c for f in folhas for c in grade.celulas_no_poligono([f[0:1]], nivel)]
        assert len(todas) == len(set(todas))
        bloco = [[[(-44.5, -20.0), (-44.5, -19.0), (-43.5, -19.0), (-43.5, -20.0), (-44.5, -20.0)]]]
        assert set(todas) == set(grade.celulas_no_poligono(bloco, nivel))


def test_wkt():
    geom = grade.de_wkt("SRID=4674;MULTIPOLYGON(((0 0,0 1,1 1,1 0,0 0)),((2 2,2 3,3 3,2 2),(2.1 2.5,2.2 2.6,2.1 2.6)))")
    assert len(geom) == 2 and len(geom[1]) == 2
    assert grade.contem(geom, 0.5, 0.5) and not grade.contem(geom, 1.5, 1.5)
    assert grade.de_wkt("POLYGON((0 0,0 1,1 1,0 0))") == [[[(0, 0), (0, 1), (1, 1), (0, 0)]]]
    texto = grade.wkt("5KME5725N9425")
    assert grade.de_wkt(texto)[0][0] == grade.poligono("5KME5725N9425")
