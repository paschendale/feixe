import json

from feixe.server.sse import Broker


def test_broker_publica_para_todos_e_cancela():
    b = Broker()
    q1, q2 = b.inscrever(), b.inscrever()
    b.publicar("x", {"a": 1})
    assert q1.get_nowait()[0] == "x" and json.loads(q2.get_nowait()[1])["dados"] == {"a": 1}
    b.cancelar(q1)
    b.publicar("y")
    assert q1.empty() and q2.get_nowait()[0] == "y"
    assert b.conectados == 1


def test_formatar_sse():
    assert Broker.formatar("e", "{}") == b"event: e\ndata: {}\n\n"
