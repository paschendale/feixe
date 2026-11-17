"""Os módulos de camadas da rota são os mesmos do QGIS (core.camadas importa o QGIS; a rota não pode)."""

import ast
import pathlib

RAIZ = pathlib.Path(__file__).resolve().parent.parent / "feixe"


def _modulos(arquivo):
    for n in ast.parse((RAIZ / arquivo).read_text(encoding="utf-8")).body:
        if isinstance(n, ast.Assign) and any(getattr(t, "id", None) == "MODULOS" for t in n.targets):
            return ast.literal_eval(n.value)
    raise AssertionError(f"MODULOS não está em {arquivo}")


def test_mesmos_modulos():
    assert _modulos("server/rotas/camadas.py") == _modulos("core/camadas.py")
