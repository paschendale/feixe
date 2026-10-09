"""Spike S-01: o QGIS desta máquina tem o que o feixe precisa?

Como rodar: abra o QGIS, menu Complementos > Console Python, cole o conteúdo deste arquivo e pressione Enter.
Copie a saída completa (inclusive a linha "resumo") e mande para o repositório/issue do feixe.
"""

import platform
import sys

linhas = []
try:
    from qgis.core import Qgis

    linhas.append(f"QGIS {Qgis.QGIS_VERSION} | Python {sys.version.split()[0]} | {platform.platform()}")
except Exception as e:  # noqa: BLE001
    linhas.append(f"QGIS ? (erro ao importar qgis.core: {e}) | Python {sys.version.split()[0]} | {platform.platform()}")
try:
    from PyQt5.QtCore import PYQT_VERSION_STR, QT_VERSION_STR

    linhas.append(f"Qt {QT_VERSION_STR} | PyQt {PYQT_VERSION_STR}")
except Exception as e:  # noqa: BLE001
    linhas.append(f"Qt ? ({e})")

modulos = [
    ("PyQt5.QtWebEngineWidgets", "webview moderno (Chromium): plano A do front"),
    ("PyQt5.QtWebChannel", "ponte Python <-> JavaScript"),
    ("PyQt5.QtWebKitWidgets", "webview antigo (WebKit): plano C"),
    ("psycopg2", "acesso ao PostgreSQL"),
    ("sqlite3", "workspace local"),
    ("osgeo.ogr", "GDAL/OGR para o GPKG"),
]
resultado = {}
for nome, para_que in modulos:
    try:
        __import__(nome)
        resultado[nome] = "OK"
        linhas.append(f"OK    {nome:<28} {para_que}")
    except Exception as e:  # noqa: BLE001
        resultado[nome] = f"FALHA ({e.__class__.__name__}: {e})"
        linhas.append(f"FALHA {nome:<28} {para_que} -> {e}")

if resultado.get("PyQt5.QtWebEngineWidgets") == "OK":
    try:
        from PyQt5.QtWebEngineWidgets import QWebEngineView

        v = QWebEngineView()
        v.setHtml(
            "<html><body><h1 id='t'>feixe</h1>"
            "<script>document.getElementById('t').textContent='feixe ok'</script></body></html>"
        )
        v.resize(10, 10)
        linhas.append("OK    QWebEngineView instanciado e renderizando HTML")
        v.deleteLater()
    except Exception as e:  # noqa: BLE001
        linhas.append(f"FALHA QWebEngineView instanciado -> {e}")

veredito = (
    "plano A (QtWebEngine)"
    if resultado.get("PyQt5.QtWebEngineWidgets") == "OK"
    else "plano B (servidor local + navegador)"
)
linhas.append(f"resumo: {veredito}")
print("\n".join(linhas))
