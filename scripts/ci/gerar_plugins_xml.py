"""Gera os repositórios de plugins do QGIS a partir dos releases do GitHub.

plugins.xml recebe só versões finais; plugins-hml.xml recebe também as rc (experimentais).

Uso: python gerar_plugins_xml.py <owner/repo> <pasta_saida>
Lê os releases pela API (GITHUB_TOKEN opcional), procura o asset feixe-<versao>.zip e escreve os dois XMLs.
"""

from __future__ import annotations

import configparser
import json
import os
import re
import sys
import urllib.request
from xml.sax.saxutils import escape

_RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def metadata() -> dict:
    cfg = configparser.ConfigParser()
    cfg.read(os.path.join(_RAIZ, "feixe", "metadata.txt"), encoding="utf-8")
    return dict(cfg["general"])


def releases(repo: str) -> list:
    req = urllib.request.Request(f"https://api.github.com/repos/{repo}/releases?per_page=100")
    tok = os.environ.get("GITHUB_TOKEN")
    if tok:
        req.add_header("Authorization", f"Bearer {tok}")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def entrada(meta: dict, versao: str, url: str, data: str, experimental: bool) -> str:
    return f"""  <pyqgis_plugin name="{escape(meta["name"])}" version="{versao}">
    <description>{escape(meta["description"])}</description>
    <about>{escape(meta.get("about", ""))}</about>
    <version>{versao}</version>
    <qgis_minimum_version>{meta["qgisminimumversion"]}</qgis_minimum_version>
    <qgis_maximum_version>{meta.get("qgismaximumversion", "3.99")}</qgis_maximum_version>
    <homepage>{escape(meta.get("homepage", ""))}</homepage>
    <file_name>feixe-{versao}.zip</file_name>
    <icon>{escape(meta.get("icon", ""))}</icon>
    <author_name>{escape(meta["author"])}</author_name>
    <download_url>{escape(url)}</download_url>
    <update_date>{data}</update_date>
    <experimental>{"True" if experimental else "False"}</experimental>
    <deprecated>False</deprecated>
    <tracker>{escape(meta.get("tracker", ""))}</tracker>
    <repository>{escape(meta.get("repository", ""))}</repository>
    <tags>{escape(meta.get("tags", ""))}</tags>
  </pyqgis_plugin>
"""


def main(repo: str, saida: str) -> None:
    meta = metadata()
    estavel, hml = [], []
    for rel in releases(repo):
        tag = rel.get("tag_name", "")
        m = re.match(r"^v(\d+\.\d+\.\d+(?:-rc\.\d+)?)$", tag)
        if not m or rel.get("draft"):
            continue
        versao = m.group(1)
        zips = [a for a in rel.get("assets", []) if a["name"] == f"feixe-{versao}.zip"]
        if not zips:
            continue
        exp = "-rc." in versao
        item = entrada(meta, versao, zips[0]["browser_download_url"], rel["published_at"][:10], exp)
        hml.append(item)
        if not exp:
            estavel.append(item)
    os.makedirs(saida, exist_ok=True)
    for nome, itens in (("plugins.xml", estavel), ("plugins-hml.xml", hml)):
        with open(os.path.join(saida, nome), "w", encoding="utf-8") as f:
            f.write('<?xml version="1.0"?>\n<plugins>\n' + "".join(itens) + "</plugins>\n")
        print(f"{nome}: {len(itens)} versão(ões)")
    with open(os.path.join(saida, "index.html"), "w", encoding="utf-8") as f:
        f.write(
            "<!doctype html><meta charset='utf-8'><title>Feixe: repositório de plugins</title>"
            "<h1>Feixe</h1><p>Adicione no QGIS (Complementos &gt; Gerenciar &gt; Repositórios):</p>"
            "<ul><li>Produção: <code>plugins.xml</code></li>"
            "<li>Homologação (experimental): <code>plugins-hml.xml</code></li></ul>"
        )


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
