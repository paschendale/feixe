"""Base da fase B (B0): guarda de papel nas rotas, recusas de regra, transação e validação de campos."""

from contextlib import contextmanager

from feixe.core import papeis
from feixe.core.dados import ErroDados, Executor
from feixe.server.api import Contexto, ErroApi, Requisicao, Roteador, campo, criar_roteador


def _ctx_com_papel(papel_sgbc, gerente=False):
    """Contexto com `consultar` falso que monta um usuário do DF com o perfil dado no BC100."""

    def consultar(sql, params):
        if sql == papeis.SQL_CONTA_ATUAL:
            return [{"conta": "u_1"}]
        if sql == papeis.SQL_USUARIO:
            return [
                {
                    "cod_usuario": 1,
                    "nom_contausuario": "u_1",
                    "nom_usuario": "Fulano",
                    "num_siape": 1,
                    "dsc_lotacao": "DF",
                    "ind_contaativa": True,
                    "ind_contasistema": False,
                    "ind_contasuper": False,
                }
            ]
        if sql == papeis.SQL_PERFIS:
            return [{"cod_projeto": 10, "projeto": "BC100", "perfil": papel_sgbc}] if papel_sgbc else []
        if sql == papeis.SQL_FEIXE:
            return [{"equipe": None, "gerente": gerente, "ativo": True}]
        return []

    return Contexto(consultar=consultar)


def _roteador(ctx):
    r = Roteador(papeis_atuais=ctx.papeis_atuais)

    @r.rota("POST", "/api/so-supervisor", exige=("supervisor",))
    def _sup(req):
        return 200, {"ok": True}

    @r.rota("POST", "/api/so-gerente", exige=("gerente",))
    def _ger(req):
        return 200, {"ok": True}

    @r.rota("POST", "/api/recusa")
    def _recusa(req):
        raise ErroDados("folha já existe neste projeto e tema")

    return r


def test_guarda_de_papel():
    apm = _roteador(_ctx_com_papel("O"))
    status, obj = apm.despachar("POST", "/api/so-supervisor", {}, None)
    assert status == 403 and "supervisor" in obj["erro"]
    sup = _roteador(_ctx_com_papel("S"))
    assert sup.despachar("POST", "/api/so-supervisor", {}, None) == (200, {"ok": True})
    assert sup.despachar("POST", "/api/so-gerente", {}, None)[0] == 403
    ger = _roteador(_ctx_com_papel(None, gerente=True))
    assert ger.despachar("POST", "/api/so-gerente", {}, None) == (200, {"ok": True})


def test_eu_fica_guardado_ate_esquecer():
    chamadas = []
    ctx = _ctx_com_papel("S")
    original = ctx.consultar

    def contando(sql, params):
        chamadas.append(sql)
        return original(sql, params)

    ctx.consultar = contando
    ctx.eu()
    ctx.eu()
    n = len(chamadas)
    ctx.esquecer_eu()
    ctx.eu()
    assert len(chamadas) == 2 * n


def test_recusa_de_regra_vira_409():
    r = _roteador(_ctx_com_papel("S"))
    assert r.despachar("POST", "/api/recusa", {}, None) == (409, {"erro": "folha já existe neste projeto e tema"})


class _ErroPg(Exception):
    """Imita psycopg2.Error: pgcode e diag.message_primary."""

    def __init__(self, pgcode, mensagem):
        super().__init__(mensagem)
        self.pgcode = pgcode
        self.diag = type("D", (), {"message_primary": mensagem})()


def test_erro_do_banco_com_codigo_de_regra_vira_recusa():
    r = Roteador()

    @r.rota("POST", "/api/regra")
    def _regra(req):
        raise _ErroPg("P0001", "carga com o centroide fora da folha")

    @r.rota("POST", "/api/bug")
    def _bug(req):
        raise _ErroPg("42P01", "relação não existe")

    assert r.despachar("POST", "/api/regra", {}, None) == (409, {"erro": "carga com o centroide fora da folha"})
    assert r.despachar("POST", "/api/bug", {}, None)[0] == 500


def test_tx_sem_banco_dá_503_e_com_banco_entrega_executor():
    ctx = Contexto()
    try:
        with ctx.tx():
            pass
        raise AssertionError("deveria ter recusado")
    except ErroApi as e:
        assert e.status == 503

    class Falso(Executor):
        def todos(self, sql, params=None):
            return [{"x": 1}]

    @contextmanager
    def transacao():
        yield Falso()

    ctx = Contexto(transacao=transacao)
    with ctx.tx() as ex:
        assert ex.um("SELECT 1") == {"x": 1}


def test_campo():
    req = Requisicao("POST", "/", {}, {"id": "7", "nome": "x"}, {})
    assert campo(req, "id", int) == 7
    assert campo(req, "falta", padrao=None) is None
    for nome, conv in (("falta", None), ("nome", int)):
        try:
            campo(req, nome, conv)
            raise AssertionError("deveria ter recusado")
        except ErroApi as e:
            assert e.status == 400 and nome in e.mensagem


def test_roteador_completo_continua_montando():
    r = criar_roteador(Contexto())
    assert r.despachar("GET", "/api/status", {}, None) == (200, {"online": False})
    assert r.despachar("GET", "/api/eu", {}, None)[0] == 503
