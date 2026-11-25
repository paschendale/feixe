import json

import pytest
from feixe.core.ambiente import AmbienteInvalido, carregar, de_dict


def test_de_dict_valido():
    a = de_dict({"nome": "dev", "rotulo": "Dev", "cor": "#000", "host": "h", "porta": "5434", "banco": "b"})
    assert a.porta == 5434 and a.sslmode == "prefer"
    assert a.descricao_banco == "h:5434/b"


def test_de_dict_incompleto():
    with pytest.raises(AmbienteInvalido):
        de_dict({"nome": "producao", "host": "h"})
    with pytest.raises(AmbienteInvalido):
        de_dict({"nome": "x", "rotulo": "x", "cor": "x", "host": "h", "porta": "abc", "banco": "b"})


def test_carregar_arquivo(tmp_path):
    p = tmp_path / "ambiente.json"
    p.write_text(
        json.dumps({"nome": "producao", "rotulo": "Produção", "cor": "#1", "host": "h", "porta": 1, "banco": "b"})
    )
    assert carregar(str(p)).nome == "producao"
    with pytest.raises(AmbienteInvalido):
        carregar(str(tmp_path / "nao-existe.json"))


def test_config_dev_do_repositorio():
    with open("config/ambientes.json", encoding="utf-8") as f:
        dev = json.load(f)["dev"]
    assert de_dict(dev).nome == "dev"
