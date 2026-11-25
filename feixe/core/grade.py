"""Grade estatística do IBGE calculada por fórmula: célula, geocódigo e células com centroide dentro de um polígono.

A grade é definida na projeção equivalente de Albers sobre SIRGAS2000 (meridiano central -54°, latitude de origem
-12°, paralelos padrão -2° e -22°, falso E 5.000.000 m e falso N 10.000.000 m, elipsoide GRS80). Cada célula é um
quadrado nessa projeção, alinhado a múltiplos do lado a partir do canto inferior esquerdo da área de abrangência
(E 2.800.000, N 7.350.000; esse canto é múltiplo de 50 km, então até 50 km é o mesmo que alinhar na origem). A
geometria em SIRGAS2000 geográfico (EPSG:4674) é o quadrilátero dos quatro cantos projetados de volta, como no
shapefile oficial.

Geocódigo oficial (notas metodológicas da Grade Estatística 2022): descritor do nível + "E" + "N" do canto inferior
esquerdo. Níveis em quilômetros dão as coordenadas em km (`5KME5725N9425`, `10KME5030N7590`); níveis em metros dão
as coordenadas em hectômetros (`200ME49836N78114`). O sub-nível de 2,5 km, que o IBGE não publica, segue a regra dos
níveis em metros: `2500ME51025N77625` (canto em 5.102.500, 7.762.500).

Puro Python (sem QGIS) para ser testável e usado tanto pelo plugin quanto por scripts. A mesma conta existe em SQL
(`mapcartacomp.f_grade_*`, em feixe/db/ccar/006_regras.sql), com `ST_Transform` e a mesma projeção em string proj4.
"""

from __future__ import annotations

import math
import re
from typing import Iterator, List, Sequence, Tuple

# Níveis publicados pelo IBGE e o sub-nível de 2,5 km do Feixe, em metros.
NIVEIS = (500000, 100000, 50000, 10000, 5000, 2500, 1000, 200)

Ponto = Tuple[float, float]
Anel = Sequence[Ponto]
Poligono = Sequence[Anel]  # anel externo seguido dos buracos
MultiPoligono = Sequence[Poligono]

# Elipsoide GRS80 e parâmetros da projeção.
_A = 6378137.0
_F = 1 / 298.257222101
_E2 = 2 * _F - _F * _F
_E = math.sqrt(_E2)
_LON0 = math.radians(-54.0)
_LAT0 = math.radians(-12.0)
_LAT1 = math.radians(-2.0)
_LAT2 = math.radians(-22.0)
_X0 = 5000000.0
_Y0 = 10000000.0
# Canto inferior esquerdo da área de abrangência da grade: a partir dele as células se alinham em todos os níveis.
ORIGEM_E = 2800000
ORIGEM_N = 7350000


def _q(phi: float) -> float:
    s = math.sin(phi)
    return (1 - _E2) * (s / (1 - _E2 * s * s) - (1 / (2 * _E)) * math.log((1 - _E * s) / (1 + _E * s)))


def _m(phi: float) -> float:
    s = math.sin(phi)
    return math.cos(phi) / math.sqrt(1 - _E2 * s * s)


_M1, _M2 = _m(_LAT1), _m(_LAT2)
_Q0, _Q1, _Q2 = _q(_LAT0), _q(_LAT1), _q(_LAT2)
_N = (_M1 * _M1 - _M2 * _M2) / (_Q2 - _Q1)
_C = _M1 * _M1 + _N * _Q1
_RHO0 = _A * math.sqrt(_C - _N * _Q0) / _N
_SINAL = 1.0 if _N > 0 else -1.0


class GeocodigoInvalido(ValueError):
    pass


def para_albers(lon: float, lat: float) -> Ponto:
    """(lon, lat) em graus SIRGAS2000 -> (E, N) em metros na projeção da grade."""
    rho = _A * math.sqrt(_C - _N * _q(math.radians(lat))) / _N
    theta = _N * (math.radians(lon) - _LON0)
    return _X0 + rho * math.sin(theta), _Y0 + _RHO0 - rho * math.cos(theta)


def de_albers(x: float, y: float) -> Ponto:
    """(E, N) em metros na projeção da grade -> (lon, lat) em graus SIRGAS2000."""
    dx, dy = x - _X0, _RHO0 - (y - _Y0)
    rho = _SINAL * math.hypot(dx, dy)
    theta = math.atan2(_SINAL * dx, _SINAL * dy)
    q = (_C - (rho * _N / _A) ** 2) / _N
    phi = math.asin(max(-1.0, min(1.0, q / 2)))
    for _ in range(20):
        s = math.sin(phi)
        um = 1 - _E2 * s * s
        dphi = (um * um / (2 * math.cos(phi))) * (
            q / (1 - _E2) - s / um + (1 / (2 * _E)) * math.log((1 - _E * s) / (1 + _E * s))
        )
        phi += dphi
        if abs(dphi) < 1e-14:
            break
    return math.degrees(_LON0 + theta / _N), math.degrees(phi)


def _descritor(nivel: int) -> Tuple[str, int]:
    """Descritor do nível e o divisor das coordenadas no geocódigo."""
    if nivel not in NIVEIS:
        raise ValueError(
            f"nível da grade estatística desconhecido: {nivel} m (use um de {', '.join(map(str, NIVEIS))})"
        )
    if nivel % 1000 == 0:
        return f"{nivel // 1000}KM", 1000
    return f"{nivel}M", 100


def geocodigo(nivel: int, x0: float, y0: float) -> str:
    """Geocódigo da célula do nível cujo canto inferior esquerdo é (x0, y0), em metros na projeção da grade."""
    desc, div = _descritor(nivel)
    return f"{desc}E{int(round(x0)) // div}N{int(round(y0)) // div}"


_RE_GEOCODIGO = re.compile(r"^(\d+)(KM|M)E(\d+)N(\d+)$")


def ler_geocodigo(cod: str) -> Tuple[int, int, int]:
    """'5KME5725N9425' -> (5000, 5725000, 9425000): nível e canto inferior esquerdo em metros."""
    casou = _RE_GEOCODIGO.match(cod or "")
    if not casou:
        raise GeocodigoInvalido(f"geocódigo inválido: {cod!r}")
    valor, unidade, e, n = casou.groups()
    nivel = int(valor) * (1000 if unidade == "KM" else 1)
    try:
        desc, div = _descritor(nivel)
    except ValueError as erro:
        raise GeocodigoInvalido(str(erro)) from erro
    if desc != valor + unidade:
        raise GeocodigoInvalido(f"geocódigo inválido: {cod!r} (o nível se escreve {desc})")
    x0, y0 = int(e) * div, int(n) * div
    if (x0 - ORIGEM_E) % nivel or (y0 - ORIGEM_N) % nivel:
        raise GeocodigoInvalido(f"geocódigo inválido: {cod!r} (canto fora da grade de {nivel} m)")
    return nivel, x0, y0


def celula_do_ponto(nivel: int, lon: float, lat: float) -> str:
    """Geocódigo da célula do nível que contém o ponto."""
    _descritor(nivel)
    x, y = para_albers(lon, lat)
    return geocodigo(nivel, _alinhar(x, ORIGEM_E, nivel), _alinhar(y, ORIGEM_N, nivel))


def _alinhar(v: float, origem: int, nivel: int) -> int:
    return origem + math.floor((v - origem) / nivel) * nivel


def centroide(cod: str) -> Ponto:
    """Centro da célula (na projeção da grade) levado para (lon, lat). É o ponto que decide a folha da célula."""
    nivel, x0, y0 = ler_geocodigo(cod)
    return de_albers(x0 + nivel / 2, y0 + nivel / 2)


def poligono(cod: str) -> List[Ponto]:
    """Anel fechado da célula em (lon, lat): cantos inferior esquerdo, superior esquerdo, superior direito, inferior
    direito e o primeiro de novo (mesma ordem do shapefile oficial)."""
    nivel, x0, y0 = ler_geocodigo(cod)
    cantos = [(x0, y0), (x0, y0 + nivel), (x0 + nivel, y0 + nivel), (x0 + nivel, y0)]
    anel = [de_albers(x, y) for x, y in cantos]
    return anel + [anel[0]]


def wkt(cod: str) -> str:
    """Célula como MULTIPOLYGON em WKT (SIRGAS2000), no formato de carga_trabalho.geom."""
    return "MULTIPOLYGON(((" + ",".join(f"{lon!r} {lat!r}" for lon, lat in poligono(cod)) + ")))"


# Ponto em polígono ---------------------------------------------------------------------------------------------------
# Regra par-ímpar com intervalos semiabertos: um ponto exatamente sobre a divisa entre duas folhas vizinhas cai em uma
# só delas, então nenhuma célula aparece em duas folhas.


def _no_anel(lon: float, lat: float, anel: Anel) -> bool:
    dentro = False
    n = len(anel)
    j = n - 1
    for i in range(n):
        xi, yi = anel[i]
        xj, yj = anel[j]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            dentro = not dentro
        j = i
    return dentro


def contem(geom: MultiPoligono, lon: float, lat: float) -> bool:
    """O ponto está dentro de algum polígono (anel externo menos os buracos)?"""
    for pol in geom:
        if pol and _no_anel(lon, lat, pol[0]) and not any(_no_anel(lon, lat, buraco) for buraco in pol[1:]):
            return True
    return False


def _extensao_albers(geom: MultiPoligono, passos: int = 32) -> Tuple[float, float, float, float]:
    """Retângulo envolvente na projeção da grade. As arestas são densificadas porque um paralelo vira arco."""
    xs, ys = [], []
    for pol in geom:
        for anel in pol:
            for (x1, y1), (x2, y2) in zip(anel, list(anel[1:]) + [anel[0]]):
                for k in range(passos):
                    t = k / passos
                    x, y = para_albers(x1 + (x2 - x1) * t, y1 + (y2 - y1) * t)
                    xs.append(x)
                    ys.append(y)
    if not xs:
        raise ValueError("geometria vazia")
    return min(xs), min(ys), max(xs), max(ys)


def celulas_no_poligono(geom: MultiPoligono, nivel: int) -> Iterator[str]:
    """Geocódigos das células do nível com centroide dentro do polígono (lon, lat), de oeste para leste e de sul para
    norte. A célula fica inteira: pode ultrapassar a borda, mas pertence a um só polígono de uma partição."""
    _descritor(nivel)
    xmin, ymin, xmax, ymax = _extensao_albers(geom)
    i0, i1 = math.floor((xmin - ORIGEM_E) / nivel) - 1, math.floor((xmax - ORIGEM_E) / nivel) + 1
    j0, j1 = math.floor((ymin - ORIGEM_N) / nivel) - 1, math.floor((ymax - ORIGEM_N) / nivel) + 1
    for j in range(j0, j1 + 1):
        for i in range(i0, i1 + 1):
            x0, y0 = ORIGEM_E + i * nivel, ORIGEM_N + j * nivel
            lon, lat = de_albers(x0 + nivel / 2, y0 + nivel / 2)
            if contem(geom, lon, lat):
                yield geocodigo(nivel, x0, y0)


# WKT mínimo (POLYGON e MULTIPOLYGON), para geometrias que chegam do banco como ST_AsText ------------------------------

_RE_ANEL = re.compile(r"\(([^()]+)\)")


def de_wkt(texto: str) -> MultiPoligono:
    """POLYGON ou MULTIPOLYGON em WKT -> lista de polígonos, cada um uma lista de anéis de (lon, lat)."""
    t = texto.strip()
    if ";" in t:  # EWKT: SRID=4674;...
        t = t.split(";", 1)[1].strip()
    tipo = t.split("(", 1)[0].strip().upper()
    corpo = t[len(tipo) :].strip() if t.upper().startswith(tipo) else t
    if tipo not in ("POLYGON", "MULTIPOLYGON"):
        raise ValueError(f"tipo de geometria não suportado: {tipo or texto[:20]}")
    poligonos_txt = [corpo[1:-1]] if tipo == "POLYGON" else _separar(corpo[1:-1])
    saida = []
    for ptxt in poligonos_txt:
        aneis = []
        for anel in _RE_ANEL.findall(ptxt):
            aneis.append([tuple(float(v) for v in par.split()[:2]) for par in anel.split(",")])
        saida.append(aneis)
    return saida


def _separar(texto: str) -> List[str]:
    """Separa '((...)),((...))' nos polígonos de primeiro nível."""
    partes, nivel, ini = [], 0, 0
    for i, ch in enumerate(texto):
        if ch == "(":
            if nivel == 0:
                ini = i
            nivel += 1
        elif ch == ")":
            nivel -= 1
            if nivel == 0:
                partes.append(texto[ini : i + 1])
    return partes
