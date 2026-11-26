"""Gera o manual do Feixe (GitHub Pages) a partir de manual/*.md.

Uso: python gerar_manual.py <pasta_saida>

Cada página é um Markdown com um cabeçalho simples (titulo, ordem). A página da barra recebe a tabela de botões e
atalhos lida do próprio código da barra (feixe/ui/barra.py), para não ficar desatualizada. Precisa do pacote
`markdown` (só no CI; o plugin não depende dele).
"""

from __future__ import annotations

import ast
import html
import os
import re
import shutil
import sys
from typing import Dict, List, Tuple

import markdown

_RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MANUAL = os.path.join(_RAIZ, "manual")
BARRA = os.path.join(_RAIZ, "feixe", "ui", "barra.py")
ICONES = os.path.join(_RAIZ, "feixe", "icones")

GRUPOS: List[Tuple[str, List[str]]] = [
    ("Conexão", ["conectar", "verificar"]),
    ("Camadas e modos", ["camadas", "modo_execucao", "modo_cq", "modo_supervisao"]),
    ("Painel", ["abrir"]),
    ("Execução", ["proxima", "concluir", "pular"]),
    ("Controle de qualidade", ["proxima_amostra", "conforme", "nao_conforme", "ocorrencia"]),
    ("Ciência e correção", ["ciente", "proxima_ocorrencia", "tratada"]),
]


def _ler(caminho: str) -> str:
    with open(caminho, encoding="utf-8") as f:
        return f.read()


def _texto(no, constantes: Dict[str, str]) -> str:
    if isinstance(no, ast.Constant) and isinstance(no.value, str):
        return no.value
    if isinstance(no, ast.Attribute) and no.attr in constantes:
        return constantes[no.attr]
    if isinstance(no, ast.Name) and no.id in constantes:
        return constantes[no.id]
    return ""


def acoes_da_barra() -> Dict[str, dict]:
    """{chave: {titulo, texto, icone, atalho}} lido do código da barra, sem importar o QGIS."""
    arvore = ast.parse(_ler(BARRA))
    constantes: Dict[str, str] = {}
    atalhos: Dict[str, str] = {}
    acoes: Dict[str, dict] = {}
    for no in ast.walk(arvore):
        alvo = None
        if isinstance(no, ast.Assign) and len(no.targets) == 1 and isinstance(no.targets[0], ast.Name):
            alvo, valor = no.targets[0].id, no.value
        elif isinstance(no, ast.AnnAssign) and isinstance(no.target, ast.Name) and no.value is not None:
            alvo, valor = no.target.id, no.value
        if alvo is None:
            continue
        if isinstance(valor, ast.Constant) and isinstance(valor.value, str):
            constantes[alvo] = valor.value
        elif alvo == "ATALHOS" and isinstance(valor, ast.Dict):
            atalhos = {k.value: v.value for k, v in zip(valor.keys, valor.values)}
        elif alvo == "MODOS" and isinstance(valor, ast.List):
            for t in valor.elts:
                chave, nome, icone, texto = (e.value for e in t.elts)
                acoes[f"modo_{chave}"] = {"titulo": nome, "texto": texto, "icone": icone}
    for no in ast.walk(arvore):
        if isinstance(no, ast.Call) and getattr(no.func, "attr", "") == "_acao" and len(no.args) >= 4:
            chave = no.args[0]
            if not (isinstance(chave, ast.Constant) and isinstance(chave.value, str)):
                continue
            acoes[chave.value] = {
                "titulo": _texto(no.args[2], constantes),
                "texto": _texto(no.args[3], constantes),
                "icone": _texto(no.args[1], constantes) or chave.value,
            }
    for chave, a in acoes.items():
        a["atalho"] = atalhos.get(chave, "")
    return acoes


def tabela_atalhos() -> str:
    acoes = acoes_da_barra()
    partes = []
    for grupo, chaves in GRUPOS:
        linhas = []
        for c in chaves:
            a = acoes.get(c)
            if not a:
                continue
            texto = a["texto"] or ("Abre o diálogo de usuário e senha." if c == "conectar" else "")
            teclas = "".join(f"<kbd>{html.escape(t)}</kbd>" for t in a["atalho"].split("+") if t)
            linhas.append(
                f'<tr><td class="ic"><img src="icones/{html.escape(a["icone"])}.svg" alt=""></td>'
                f"<td><strong>{html.escape(a['titulo'])}</strong><br>"
                f'<span class="dica">{html.escape(texto)}</span></td><td class="tecla">{teclas}</td></tr>'
            )
        if linhas:
            partes.append(f'<h2>{grupo}</h2>\n<table class="atalhos"><tbody>{"".join(linhas)}</tbody></table>')
    return "\n".join(partes)


def ler_paginas() -> List[dict]:
    paginas = []
    for nome in sorted(os.listdir(MANUAL)):
        if not nome.endswith(".md"):
            continue
        bruto = _ler(os.path.join(MANUAL, nome))
        meta: Dict[str, str] = {}
        m = re.match(r"^---\n(.*?)\n---\n", bruto, re.S)
        if m:
            for linha in m.group(1).splitlines():
                k, _, v = linha.partition(":")
                meta[k.strip()] = v.strip()
            bruto = bruto[m.end() :]
        paginas.append(
            {
                "arquivo": nome[:-3] + ".html",
                "titulo": meta.get("titulo", nome[:-3]),
                "ordem": int(meta.get("ordem", "99")),
                "md": bruto,
            }
        )
    return sorted(paginas, key=lambda p: p["ordem"])


def main(saida: str) -> None:
    paginas = ler_paginas()
    os.makedirs(saida, exist_ok=True)
    os.makedirs(os.path.join(saida, "icones"), exist_ok=True)
    for f in os.listdir(ICONES):
        if f.endswith(".svg"):
            shutil.copy(os.path.join(ICONES, f), os.path.join(saida, "icones", f))
    shutil.copy(os.path.join(MANUAL, "estilo.css"), os.path.join(saida, "estilo.css"))
    modelo = _ler(os.path.join(MANUAL, "_modelo.html"))
    for i, p in enumerate(paginas):
        atual = ' class="atual"'
        nav = "\n    ".join(
            f'<a href="{q["arquivo"]}"{atual if q is p else ""}>{html.escape(q["titulo"])}</a>' for q in paginas
        )
        md = p["md"].replace("{{atalhos}}", tabela_atalhos())
        conteudo = markdown.markdown(md, extensions=["tables", "sane_lists"], output_format="html")
        anterior = paginas[i - 1] if i > 0 else None
        seguinte = paginas[i + 1] if i + 1 < len(paginas) else None
        rodape = "<span></span>"
        if anterior:
            rodape = f'<a href="{anterior["arquivo"]}">← {html.escape(anterior["titulo"])}</a>'
        if seguinte:
            rodape += f'<a href="{seguinte["arquivo"]}">{html.escape(seguinte["titulo"])} →</a>'

        with open(os.path.join(saida, p["arquivo"]), "w", encoding="utf-8") as f:
            f.write(modelo.format(titulo=html.escape(p["titulo"]), nav=nav, conteudo=conteudo, rodape=rodape))
    print(f"manual: {len(paginas)} páginas em {saida}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
