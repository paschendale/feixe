"""C3: a thread de sincronização em segundo plano (sem banco): junta rajadas, roda já quando pedido, não morre."""

from __future__ import annotations

import threading
import time

from feixe.sync.trabalhador import Trabalhador


class _Contador:
    def __init__(self, resultado=None):
        self.n = 0
        self.evento = threading.Event()
        self.resultado = resultado or {"estado": "ok"}

    def __call__(self):
        self.n += 1
        self.evento.set()
        r = self.resultado
        if callable(r):
            r = r(self.n)
        return r


def _esperar(cond, limite=3.0):
    fim = time.monotonic() + limite
    while time.monotonic() < fim:
        if cond():
            return True
        time.sleep(0.01)
    return False


def test_rajada_vira_uma_sincronizacao():
    c = _Contador()
    t = Trabalhador(c, atraso=0.15, atraso_max=2.0).iniciar()
    try:
        for _ in range(5):
            t.acordar()
            time.sleep(0.03)
        assert _esperar(lambda: c.n == 1)
        time.sleep(0.3)
        assert c.n == 1 and not t.pendente
    finally:
        t.parar()
    assert not t.vivo


def test_rajada_longa_nao_adia_alem_do_maximo():
    c = _Contador()
    t = Trabalhador(c, atraso=0.2, atraso_max=0.4).iniciar()
    try:
        inicio = time.monotonic()
        while not c.evento.is_set() and time.monotonic() - inicio < 2:
            t.acordar()
            time.sleep(0.05)
        assert c.evento.is_set() and time.monotonic() - inicio < 1.0
    finally:
        t.parar()


def test_acordar_ja_nao_espera_nem_e_adiado():
    c = _Contador()
    t = Trabalhador(c, atraso=5.0, atraso_max=10.0).iniciar()
    try:
        t.acordar(0)
        t.acordar()  # um pedido normal logo depois não adia o urgente
        assert c.evento.wait(1.0)
    finally:
        t.parar()


def test_em_andamento_tenta_de_novo_e_excecao_nao_mata_a_thread(monkeypatch):
    import feixe.sync.trabalhador as tr

    monkeypatch.setattr(tr, "REPETIR_EM_ANDAMENTO", 0.05)

    def resultado(n):
        if n == 1:
            return {"estado": "em_andamento"}
        if n == 2:
            raise RuntimeError("falhou")
        return {"estado": "ok"}

    c = _Contador(resultado)
    t = Trabalhador(c, atraso=0.01).iniciar()
    try:
        t.acordar(0)
        assert _esperar(lambda: c.n >= 2)  # repetiu sozinho depois do em_andamento
        assert t.vivo and t.ultimo["estado"] == "erro"
        t.acordar(0)
        assert _esperar(lambda: c.n >= 3) and t.ultimo["estado"] == "ok"
    finally:
        t.parar()
