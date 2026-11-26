#!/usr/bin/env python3
"""Verificação headless da fase C contra o banco de dev, sem abrir o QGIS. Cada item acrescenta a sua seção.

Uso (Mac, com o QGIS-LTR):
    /Applications/QGIS-LTR.app/Contents/MacOS/bin/python3 scripts/dev/verificar_fase_c.py [c4 ...]

Sem argumentos roda todas as seções. Lê o banco de config/ambientes.json (dev) e o usuário e a senha de FEIXE_CCAR no
.dev.env da raiz. Usa perfil do QGIS, banco de autenticação e workspace temporários, apagados no fim. A CCAR
inalcançável é simulada pelo próprio plugin (`FEIXE_DEV_SEM_CCAR=1`, só no ambiente dev): nenhum container é parado.
Tudo o que grava no banco é apagado no fim de cada seção.
"""

from __future__ import annotations

import datetime as dt
import os
import shutil
import sys
import tempfile
import urllib.parse

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TEMP = tempfile.mkdtemp(prefix="feixe-fase-c-")
os.environ["QGIS_CUSTOM_CONFIG_PATH"] = os.path.join(TEMP, "perfil")
os.environ["QGIS_AUTH_DB_DIR_PATH"] = os.path.join(TEMP, "auth")
os.makedirs(os.environ["QGIS_AUTH_DB_DIR_PATH"])
sys.path.insert(0, RAIZ)

_MACOS = os.path.dirname(os.path.dirname(os.path.abspath(sys.executable)))
_PROJ = os.path.join(os.path.dirname(_MACOS), "Resources", "proj")
if os.path.isdir(_PROJ):
    os.environ.setdefault("PROJ_LIB", _PROJ)
    os.environ.setdefault("PROJ_DATA", _PROJ)

from feixe.core import ambiente, config, db  # noqa: E402
from feixe.core.dados import novo_uuid  # noqa: E402
from qgis.core import QgsApplication  # noqa: E402
from scripts.dev.ambiente_dev import carregar as ambiente_dev_dict  # noqa: E402

SECOES = {}


def secao(nome):
    def registrar(fn):
        SECOES[nome] = fn
        return fn

    return registrar


def credencial_dev():
    with open(os.path.join(RAIZ, ".dev.env"), encoding="utf-8") as f:
        for linha in f:
            if linha.startswith("FEIXE_CCAR="):
                u = urllib.parse.urlparse(linha.split("=", 1)[1].strip().strip("'\""))
                return urllib.parse.unquote(u.username), urllib.parse.unquote(u.password)
    raise SystemExit("FEIXE_CCAR não está no .dev.env")


def ambiente_dev():
    return ambiente.de_dict(ambiente_dev_dict())


def ok(msg):
    print(f"  ok  {msg}")


class _Barra:
    """A barra de mensagens do QGIS, gravando o que o plugin diria à pessoa."""

    def __init__(self):
        self.mensagens = []

    def pushMessage(self, titulo, texto, nivel=0, duracao=0):  # noqa: N802 - API do QGIS
        self.mensagens.append(texto)


class _Iface:
    def __init__(self):
        self.barra = _Barra()

    def messageBar(self):  # noqa: N802 - API do QGIS
        return self.barra


@secao("c4")
def c4(amb, usuario, senha):
    """Offline de verdade: camadas do workspace, edição pela camada na outbox, CCAR fora e de volta."""
    from feixe.core import camadas
    from feixe.plugin import FeixePlugin
    from feixe.server.api import Contexto
    from feixe.server.rotas import camadas as rotas_camadas
    from feixe.server.rotas import cargas as rc
    from feixe.sync.sincronizar import Sincronizacao
    from feixe.sync.workspace import Workspace
    from qgis.core import QgsGeometry, QgsProject, QgsVectorLayer

    # A conta de dev não tem cargas: cinco cópias numa passagem aberta do DF, quatro pendentes e uma concluída há 30 h
    # (desfazer pela camada tem de ser recusado: passou da janela de 24 h).
    copias = []
    antiga = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=30)
    with db.transacao(amb, usuario, senha) as ex:
        origem = ex.todos(
            "SELECT c.id_lote_etapa, c.id_atividade, c.uf, c.geom FROM mapcartacomp.carga_trabalho c "
            "JOIN mapcartacomp.lote_etapa le ON le.id = c.id_lote_etapa AND le.situacao = 'em_andamento' "
            "WHERE c.uf = 'DF' AND c.id_cq_plano IS NULL AND c.geocodigo IS NULL "
            "AND c.id_lote_etapa = (SELECT min(id_lote_etapa) FROM mapcartacomp.carga_trabalho c2 "
            "JOIN mapcartacomp.lote_etapa le2 ON le2.id = c2.id_lote_etapa AND le2.situacao = 'em_andamento' "
            "WHERE c2.uf = 'DF' AND c2.id_cq_plano IS NULL) ORDER BY c.id LIMIT 5"
        )
        assert len(origem) == 5, "o dev precisa da conversão do DF (A3)"
        for i, o in enumerate(origem):
            u = novo_uuid()
            ex.executar(
                "INSERT INTO mapcartacomp.carga_trabalho (uuid, id_lote_etapa, id_atividade, uf, responsavel, geom, "
                "concluido, concluido_em) VALUES (%s, %s, %s, %s, current_user, %s, %s, %s)",
                (u, o["id_lote_etapa"], o["id_atividade"], o["uf"], o["geom"], i == 4, antiga if i == 4 else None),
            )
            copias.append(u)
        ids = {
            r["uuid"]: r["id"]
            for r in ex.todos(
                "SELECT uuid::text AS uuid, id FROM mapcartacomp.carga_trabalho WHERE uuid::text = ANY(%s)", (copias,)
            )
        }
    a, b, c, d, velha = (ids[u] for u in copias)

    ws = Workspace.abrir(amb.nome, usuario, "DF", raiz=os.path.join(TEMP, "workspace"))
    sinc = Sincronizacao(
        lambda: ws, lambda: db.transacao(amb, usuario, senha, timeout_conexao=5), alcancavel=lambda: db.alcancavel(amb)
    )
    projeto = QgsProject.instance()
    try:
        assert sinc.sincronizar()["estado"] == "ok"
        with ws.leitura() as ex:
            n = ex.um("SELECT count(*) AS n FROM carga_trabalho WHERE id IN (?, ?, ?, ?, ?)", (a, b, c, d, velha))["n"]
        assert n == 5, n
        ok(f"workspace preparado pelo pull ({ws.caminho})")

        # --- a CCAR some ---------------------------------------------------------------------------------------
        os.environ["FEIXE_DEV_SEM_CCAR"] = "1"
        db.esquecer()
        r = sinc.sincronizar()
        assert r["estado"] == "offline" and sinc.online is False, r
        ok("CCAR inalcançável (simulada no plugin, FEIXE_DEV_SEM_CCAR): sincronizar volta offline")

        # O plugin, como no QGIS: as rotas pelo Contexto e o gancho de edição de Minhas cargas. A identidade vem do
        # workspace (a da última vez que a CCAR respondeu), como ao abrir o QGIS sem rede.
        plugin = FeixePlugin(_Iface())
        plugin.amb = amb
        plugin.servidor = True  # as rotas são chamadas direto, sem o servidor HTTP
        guardado = {"conta": usuario, "uf": "DF", "papeis": ["supervisor", "operador"], "perfis": []}
        ctx = Contexto(
            transacao=lambda: db.transacao(amb, usuario, senha),
            consultar=lambda sql, p=None: db.consultar(amb, sql, p),
            workspace=lambda: ws,
            online=lambda: sinc.online,
            eu_guardado=lambda: guardado,
            qgis=lambda nome, *args: {
                "montar_camadas": lambda eu, resp, sup, exe, gpkg: camadas.montar(
                    amb, config.authcfg_id(amb), eu, resp, sup, exe, gpkg
                ),
                "cargas_mudaram": plugin.cargas_mudaram,
                "focar_carga": lambda carga, progresso: camadas.definir_atual(carga["id"]),
            }[nome](*args),
        )
        plugin.ctx = ctx
        assert ctx.eu()["offline"] is True
        projeto.layersAdded.connect(plugin._ligar_edicao)

        m = rotas_camadas.montar(ctx)
        feixe = projeto.layerTreeRoot().findGroup("Feixe")
        assert [g.name() for g in feixe.children()] == ["Execução"], [g.name() for g in feixe.children()]
        assert m["modo"] == "execucao" and m["avisos"] == [rotas_camadas.SUPERVISAO_SEM_CCAR], m
        minhas = camadas.camada_minhas()
        assert minhas.providerType() == "ogr" and minhas.source().startswith(ws.caminho), minhas.source()
        assert all(camadas.do_workspace(no.layer()) for no in feixe.findLayers())
        assert set(plugin._edicao) == {minhas.id()}, plugin._edicao
        resumo = ", ".join("{} ({})".format(x["nome"], x["feicoes"]) for x in m["camadas"])
        ok(f"camadas montadas offline, do workspace: {resumo}")

        def feicao(id_carga):
            return next(minhas.getFeatures(f'"id" = {id_carga}'))

        f = feicao(a)
        assert f["folha_revisao"] and f["etapa"] and f["situacao_txt"] == "pendente", dict(zip(f.fields().names(), f))
        assert " concluídas (" in f["progresso_txt"] and "Eval Error" not in f["progresso_txt"], f["progresso_txt"]
        ok(f"formulário com folha, etapa e progresso da view juntada: {f['folha_revisao']} · {f['progresso_txt']}")

        rotas_camadas.montar(ctx)  # de novo: substitui, não duplica (nem a view juntada, nem o gancho de edição)
        minhas = camadas.camada_minhas()
        assert len(projeto.mapLayers()) == 3, projeto.mapLayers()  # Minhas cargas, Minhas folhas e a view juntada
        assert set(plugin._edicao) == {minhas.id()}, plugin._edicao
        prox = rc.proxima(ctx)["carga"]
        assert prox is not None and camadas.carga_atual() == prox["id"], prox
        ok(f"montar de novo substitui o grupo; a próxima carga anda offline (#{prox['id']})")

        # Concluir pela API (a barra e o painel): a camada mostra na hora, sem esperar o push.
        rc.concluir(ctx, a)
        assert feicao(a)["concluido"] in (True, 1), feicao(a)["concluido"]
        ok(f"carga {a} concluída pela API: a camada do workspace mostra na hora, offline")

        # Concluir pela tabela de atributos: edição + commit. Junto, uma recusa (desfazer a de 30 h) e uma mudança
        # que não se faz pelo QGIS (geometria).
        i = minhas.fields().indexOf("concluido")
        assert minhas.startEditing()
        assert minhas.changeAttributeValue(feicao(b).id(), i, True)
        assert minhas.changeAttributeValue(feicao(velha).id(), i, False)
        geom_c = feicao(c).geometry().asWkt()
        assert minhas.changeGeometry(feicao(c).id(), QgsGeometry.fromWkt("MULTIPOLYGON(((0 0,1 0,1 1,0 0)))"))
        plugin.iface.barra.mensagens.clear()
        assert minhas.commitChanges(), minhas.commitErrors()
        QgsApplication.processEvents()
        msgs = plugin.iface.barra.mensagens
        assert any(x.startswith("Carga concluída · ") for x in msgs), msgs
        assert any(x.startswith(f"Carga {velha} ") and "24 horas" in x and "desfeita" in x for x in msgs), msgs
        assert any("só a situação (Concluída)" in x for x in msgs), msgs
        assert feicao(b)["concluido"] in (True, 1) and feicao(velha)["concluido"] in (True, 1)
        assert feicao(c).geometry().asWkt() == geom_c
        ok(f"carga {b} concluída pela tabela de atributos; desfazer a de 30 h recusado e a geometria desfeita: {msgs}")

        with ws.leitura() as ex:
            itens = ex.pendentes()
            concl = {
                r["id"]: r["concluido"]
                for r in ex.todos("SELECT id, concluido FROM carga_trabalho WHERE id IN (?, ?, ?)", (a, b, velha))
            }
        por_uuid = {it["uuid"]: it for it in itens}
        assert set(por_uuid) == {copias[0], copias[1]}, itens  # a e b, nada mais
        assert all(it["campos"]["concluido"] is True and it["campos"]["concluido_em"] for it in itens), itens
        assert concl == {a: 1, b: 1, velha: 1}, concl
        ok("as duas conclusões estão no workspace e na outbox, com a hora explícita; a recusada não entrou")

        # A garantia no arquivo: uma camada da mesma tabela sem o gancho do Feixe (aberta à mão) não grava.
        crua = QgsVectorLayer(f"{ws.caminho}|layername=carga_trabalho", "crua", "ogr")
        fc = next(crua.getFeatures(f'"id" = {c}'))
        crua.startEditing()
        crua.changeAttributeValue(fc.id(), crua.fields().indexOf("concluido"), True)
        assert not crua.commitChanges()
        assert any("só muda pelas ações do Feixe" in e for e in crua.commitErrors()), crua.commitErrors()
        crua.rollBack()
        with ws.leitura() as ex:
            assert ex.um("SELECT concluido FROM carga_trabalho WHERE id = ?", (c,))["concluido"] == 0
            assert len(ex.pendentes()) == 2
        ok("gravar pelo OGR por fora do Feixe é recusado pelo gatilho do workspace (nada escapa da outbox)")

        # Projeto salvo e aberto de novo: a junção volta e a edição continua ligada à outbox.
        arquivo = os.path.join(TEMP, "projeto.qgz")
        assert projeto.write(arquivo)
        projeto.clear()
        assert projeto.read(arquivo)
        minhas = camadas.camada_minhas()
        assert set(plugin._edicao) == {minhas.id()} and feicao(b)["folha_revisao"], plugin._edicao
        ok("projeto salvo e reaberto: Minhas cargas volta com a junção e com a edição ligada à outbox")

        # --- a CCAR volta ---------------------------------------------------------------------------------------
        del os.environ["FEIXE_DEV_SEM_CCAR"]
        r = sinc.sincronizar()
        assert r["estado"] == "ok" and r["push"]["resultados"].get("aplicado") == 2, r
        assert r["pendentes"] == 0, r
        plugin._aplicar_sincronizacao({**sinc.estado(), "mudou": True, "avisos": []})
        with db.transacao(amb, usuario, senha) as ex:
            na_ccar = {
                x["id"]: (x["concluido"], x["concluido_em"] is not None)
                for x in ex.todos(
                    "SELECT id, concluido, concluido_em FROM mapcartacomp.carga_trabalho WHERE id = ANY(%s)", ([a, b],)
                )
            }
            log = ex.todos(
                "SELECT uuid::text AS uuid, resultado FROM mapcartacomp.sync_log WHERE uuid::text = ANY(%s)",
                ([copias[0], copias[1]],),
            )
        assert na_ccar == {a: (True, True), b: (True, True)}, na_ccar
        assert sorted((x["uuid"], x["resultado"]) for x in log) == sorted(
            [(copias[0], "aplicado"), (copias[1], "aplicado")]
        ), log
        assert feicao(a)["concluido"] in (True, 1) and feicao(b)["concluido"] in (True, 1)
        ok(f"CCAR de volta: o push aplicou as duas, concluídas na CCAR e no sync_log ({len(log)} linhas)")
    finally:
        os.environ.pop("FEIXE_DEV_SEM_CCAR", None)
        projeto.clear()
        ws.fechar()
        with db.transacao(amb, usuario, senha) as ex:
            ex.executar("DELETE FROM mapcartacomp.sync_log WHERE uuid::text = ANY(%s)", (copias,))
            ex.executar("DELETE FROM mapcartacomp.carga_trabalho WHERE uuid::text = ANY(%s)", (copias,))


def main():
    pedidas = sys.argv[1:] or list(SECOES)
    QgsApplication.setPrefixPath(_MACOS, True)
    app = QgsApplication([], False)
    app.initQgis()
    try:
        if not QgsApplication.authManager().setMasterPassword("feixe-verificacao", True):
            raise SystemExit("não foi possível iniciar o Authentication Manager temporário")
        amb = ambiente_dev()
        usuario, senha = credencial_dev()
        config.salvar_credenciais(amb, usuario, senha)
        for nome in pedidas:
            print(f"{nome}: {SECOES[nome].__doc__.strip()}")
            SECOES[nome](amb, usuario, senha)
        print("tudo certo")
    finally:
        app.exitQgis()
        shutil.rmtree(TEMP, ignore_errors=True)


if __name__ == "__main__":
    main()
