"""Todo `self.x` usado numa classe própria do plugin existe: método ou atributo definido na própria classe.

Pega o caso em que uma ação é registrada (ex.: em acoes_qgis) mas o método não chegou ao arquivo: o QGIS só
descobre ao carregar o plugin, no classFactory. Classes que herdam de Qt, QGIS ou da stdlib ficam de fora: os
atributos herdados não dá para conferir sem importá-las.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

RAIZ = pathlib.Path(__file__).resolve().parent.parent / "feixe"
ARQUIVOS = sorted(p for p in RAIZ.rglob("*.py") if "web" not in p.parts)


def _propria(cls: ast.ClassDef) -> bool:
    return all(isinstance(b, ast.Name) and b.id == "object" for b in cls.bases)


@pytest.mark.parametrize("arquivo", ARQUIVOS, ids=lambda p: str(p.relative_to(RAIZ)))
def test_self_referencia_o_que_existe(arquivo):
    arvore = ast.parse(arquivo.read_text(encoding="utf-8"))
    faltando = []
    for cls in (n for n in ast.walk(arvore) if isinstance(n, ast.ClassDef) and _propria(n)):
        definidos = set()
        for n in cls.body:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                definidos.add(n.name)
            elif isinstance(n, ast.Assign):
                definidos |= {t.id for t in n.targets if isinstance(t, ast.Name)}
            elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
                definidos.add(n.target.id)
        usados = []
        for n in ast.walk(cls):
            if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "self":
                if isinstance(n.ctx, ast.Store):
                    definidos.add(n.attr)
                else:
                    usados.append((n.attr, n.lineno))
        faltando += [f"{cls.name}.{a} (linha {ln})" for a, ln in usados if a not in definidos and a[:2] != "__"]
    assert not faltando, faltando
