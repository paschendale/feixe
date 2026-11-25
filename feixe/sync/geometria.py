"""Geometria do workspace em Python puro: WKB, blob do GeoPackage, envelope e centroide.

O workspace é um GeoPackage de verdade (o QGIS abre as camadas dele pelo OGR, C4), mas é escrito pelo `sqlite3` do
Python, que não tem funções espaciais. Por isso a geometria é montada aqui, byte a byte:

- WKB 2D da OGC (o que o `ST_AsBinary` do PostGIS devolve). EWKB com SRID ou Z/M também é lido, e regravado em 2D;
- blob do GeoPackage (requisito 19 da especificação 1.2): cabeçalho `GP`, versão 0, flags (little endian, envelope xy
  nos polígonos, sem envelope no ponto), `srs_id` e o WKB;
- envelope (xmin, ymin, xmax, ymax) e centroide (cx, cy) guardados em colunas da tabela, para zoom e "próxima carga"
  sem função espacial. O centroide é o de área (o mesmo do `ST_Centroid`); num polígono degenerado, o centro do
  envelope.
"""

from __future__ import annotations

import struct
from typing import List, Optional, Sequence, Tuple

SRID = 4674  # SIRGAS 2000 geográfico, o das tabelas da CCAR

PONTO, POLIGONO, MULTIPOLIGONO = 1, 3, 6

Anel = List[Tuple[float, float]]
Poligono = List[Anel]


class GeometriaInvalida(ValueError):
    pass


# --- WKB ------------------------------------------------------------------------------------------------------------


class _Leitor:
    def __init__(self, dados: bytes):
        self.dados = bytes(dados)
        self.pos = 0

    def _ler(self, fmt: str):
        n = struct.calcsize(fmt)
        if self.pos + n > len(self.dados):
            raise GeometriaInvalida("WKB truncado")
        v = struct.unpack_from(fmt, self.dados, self.pos)
        self.pos += n
        return v

    def geometria(self):
        (ordem,) = self._ler("B")
        e = "<" if ordem == 1 else ">"
        (tipo,) = self._ler(e + "I")
        dims = 2
        if tipo & 0x20000000:  # EWKB com SRID
            self._ler(e + "I")
        if tipo & 0x80000000:
            dims += 1
        if tipo & 0x40000000:
            dims += 1
        tipo &= 0x0FFFFFFF
        if tipo >= 1000:  # ISO: 1001 = Point Z, 2001 = Point M, 3001 = Point ZM
            dims = 2 + (tipo // 1000 in (1, 2)) + 2 * (tipo // 1000 == 3)
            tipo %= 1000
        if tipo == PONTO:
            return PONTO, self._ponto(e, dims)
        if tipo == POLIGONO:
            return POLIGONO, self._poligono(e, dims)
        if tipo == MULTIPOLIGONO:
            (n,) = self._ler(e + "I")
            partes = []
            for _ in range(n):
                t, p = self.geometria()
                if t != POLIGONO:
                    raise GeometriaInvalida("multipolígono com parte que não é polígono")
                partes.append(p)
            return MULTIPOLIGONO, partes
        raise GeometriaInvalida(f"tipo de geometria não suportado no workspace: {tipo}")

    def _ponto(self, e, dims):
        c = self._ler(e + "d" * dims)
        return (c[0], c[1])

    def _poligono(self, e, dims):
        (n_aneis,) = self._ler(e + "I")
        aneis = []
        for _ in range(n_aneis):
            (n,) = self._ler(e + "I")
            aneis.append([self._ponto(e, dims) for _ in range(n)])
        return aneis


def ler_wkb(wkb: bytes):
    """(tipo, coordenadas): PONTO -> (x, y); POLIGONO -> [anel, ...]; MULTIPOLIGONO -> [polígono, ...]."""
    return _Leitor(wkb).geometria()


def wkb_ponto(x: float, y: float) -> bytes:
    return struct.pack("<BIdd", 1, PONTO, x, y)


def _wkb_poligono(p: Poligono) -> bytes:
    partes = [struct.pack("<BII", 1, POLIGONO, len(p))]
    for anel in p:
        partes.append(struct.pack("<I", len(anel)))
        partes.append(b"".join(struct.pack("<dd", x, y) for x, y in anel))
    return b"".join(partes)


def wkb_multipoligono(poligonos: Sequence[Poligono]) -> bytes:
    return struct.pack("<BII", 1, MULTIPOLIGONO, len(poligonos)) + b"".join(_wkb_poligono(p) for p in poligonos)


def retangulo(xmin: float, ymin: float, xmax: float, ymax: float) -> bytes:
    """Multipolígono de um retângulo (testes e células simples)."""
    anel = [(xmin, ymin), (xmax, ymin), (xmax, ymax), (xmin, ymax), (xmin, ymin)]
    return wkb_multipoligono([[anel]])


# --- envelope e centroide -------------------------------------------------------------------------------------------


def _pontos(tipo, coords):
    if tipo == PONTO:
        return [coords]
    polis = [coords] if tipo == POLIGONO else coords
    return [pt for p in polis for anel in p for pt in anel]


def envelope(tipo, coords) -> Tuple[float, float, float, float]:
    pts = _pontos(tipo, coords)
    if not pts:
        raise GeometriaInvalida("geometria vazia")
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def centroide(tipo, coords) -> Tuple[float, float]:
    """Centroide de área (fórmula do polígono, furos com sinal contrário, como o ST_Centroid)."""
    if tipo == PONTO:
        return coords
    polis = [coords] if tipo == POLIGONO else coords
    area = sx = sy = 0.0
    for p in polis:
        for i, anel in enumerate(p):
            a = cx = cy = 0.0
            for (x0, y0), (x1, y1) in zip(anel, anel[1:]):
                f = x0 * y1 - x1 * y0
                a += f
                cx += (x0 + x1) * f
                cy += (y0 + y1) * f
            # O anel externo soma e os furos subtraem, qualquer que seja o sentido em que vieram.
            sinal = 1.0 if i == 0 else -1.0
            if a < 0:
                a, cx, cy = -a, -cx, -cy
            area += sinal * a
            sx += sinal * cx
            sy += sinal * cy
    if abs(area) < 1e-18:
        xmin, ymin, xmax, ymax = envelope(tipo, coords)
        return (xmin + xmax) / 2, (ymin + ymax) / 2
    return sx / (3 * area), sy / (3 * area)


# --- blob do GeoPackage ---------------------------------------------------------------------------------------------


def _wkb_2d(tipo, coords) -> bytes:
    if tipo == PONTO:
        return wkb_ponto(*coords)
    if tipo == POLIGONO:
        return wkb_multipoligono([coords])  # as tabelas da CCAR são MultiPolygon
    return wkb_multipoligono(coords)


class Geometria:
    """Geometria pronta para gravar: o blob do GeoPackage e as colunas de envelope e centroide."""

    __slots__ = ("blob", "xmin", "ymin", "xmax", "ymax", "cx", "cy")

    def __init__(self, blob, xmin, ymin, xmax, ymax, cx, cy):
        self.blob, self.xmin, self.ymin, self.xmax, self.ymax, self.cx, self.cy = blob, xmin, ymin, xmax, ymax, cx, cy


def de_wkb(wkb: Optional[bytes], srid: int = SRID) -> Optional[Geometria]:
    if wkb is None:
        return None
    tipo, coords = ler_wkb(wkb)
    xmin, ymin, xmax, ymax = envelope(tipo, coords)
    cx, cy = centroide(tipo, coords)
    corpo = _wkb_2d(tipo, coords)
    if tipo == PONTO:
        cabecalho = b"GP" + struct.pack("<BBi", 0, 0b00000001, srid)  # little endian, sem envelope
    else:
        cabecalho = b"GP" + struct.pack("<BBi", 0, 0b00000011, srid) + struct.pack("<dddd", xmin, xmax, ymin, ymax)
    return Geometria(cabecalho + corpo, xmin, ymin, xmax, ymax, cx, cy)


def wkb_do_blob(blob: bytes) -> bytes:
    """O WKB de dentro de um blob do GeoPackage (para o push, C3)."""
    blob = bytes(blob)
    if blob[:2] != b"GP":
        raise GeometriaInvalida("blob sem o cabeçalho GP do GeoPackage")
    flags = blob[3]
    tamanho_env = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}.get((flags >> 1) & 0b111)
    if tamanho_env is None:
        raise GeometriaInvalida("envelope inválido no blob do GeoPackage")
    return blob[8 + tamanho_env :]


def envelope_do_blob(blob: bytes) -> Optional[Tuple[float, float, float, float]]:
    """(xmin, xmax, ymin, ymax) do blob; None se vazio. Serve às funções ST_* que os gatilhos do rtree do OGR chamam."""
    if blob is None:
        return None
    blob = bytes(blob)
    if blob[:2] != b"GP" or blob[3] & 0b00010000:
        return None
    if (blob[3] >> 1) & 0b111:
        e = "<" if blob[3] & 1 else ">"
        return struct.unpack_from(e + "dddd", blob, 8)
    tipo, coords = ler_wkb(wkb_do_blob(blob))
    xmin, ymin, xmax, ymax = envelope(tipo, coords)
    return xmin, xmax, ymin, ymax
