#!/usr/bin/env python3
"""Verificação headless da fase B contra o banco de dev, sem abrir o QGIS. Cada item acrescenta a sua seção.

Uso (Mac, com o QGIS-LTR):
    /Applications/QGIS-LTR.app/Contents/MacOS/bin/python3 scripts/dev/verificar_fase_b.py [b0 b1 ...]

Sem argumentos roda todas as seções. Lê o banco de config/ambientes.json (dev) e o usuário e a senha de FEIXE_CCAR no
.dev.env da raiz. Usa perfil do QGIS e banco de autenticação temporários, apagados no fim. Tudo o que grava no banco é
desfeito ou apagado no fim de cada seção.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import urllib.parse

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TEMP = tempfile.mkdtemp(prefix="feixe-fase-b-")
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

# Imagens e saídas para conferir a olho (capturas do PR): FEIXE_SAIDA ou a pasta temporária do sistema.
SAIDA = os.environ.get("FEIXE_SAIDA") or tempfile.gettempdir()

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
    with open(os.path.join(RAIZ, "config", "ambientes.json"), encoding="utf-8") as f:
        return ambiente.de_dict(json.load(f)["dev"])


def ok(msg):
    print(f"  ok  {msg}")


@secao("b0")
def b0(amb, usuario, senha):
    """Transação da camada de dados: commit ao sair, rollback em erro."""
    tabela = "public.feixe_verificar_b0"
    with db.transacao(amb, usuario, senha) as ex:
        ex.executar(f"CREATE TABLE {tabela} (x int)")
    try:
        try:
            with db.transacao(amb, usuario, senha) as ex:
                ex.executar(f"INSERT INTO {tabela} VALUES (1)")
                raise RuntimeError("erro de propósito")
        except RuntimeError:
            pass
        with db.transacao(amb, usuario, senha) as ex:
            assert ex.um(f"SELECT count(*) AS n FROM {tabela}")["n"] == 0
        ok("rollback em erro")
        with db.transacao(amb, usuario, senha) as ex:
            ex.executar(f"INSERT INTO {tabela} VALUES (1)")
        with db.transacao(amb, usuario, senha) as ex:
            assert ex.um(f"SELECT count(*) AS n FROM {tabela}")["n"] == 1
        ok("commit ao sair")
    finally:
        with db.transacao(amb, usuario, senha) as ex:
            ex.executar(f"DROP TABLE IF EXISTS {tabela}")


@secao("b1")
def b1(amb, usuario, senha):
    """Camadas do Feixe: grupo, estilos, filtros por UF e passagem atual, edição de concluido."""
    from feixe.core import camadas
    from feixe.core.dados import cargas, grupos
    from qgis.core import QgsProject

    # A conta de dev (postgres) não tem cargas: copia 5 cargas pendentes de uma passagem atual do DF para ela.
    copias = []
    with db.transacao(amb, usuario, senha) as ex:
        origem = ex.todos(
            "SELECT c.id_lote_etapa, c.id_atividade, c.uf, c.geom FROM mapcartacomp.carga_trabalho c "
            "JOIN mapcartacomp.lote l ON l.id_lote_etapa_atual = c.id_lote_etapa "
            "JOIN mapcartacomp.lote_etapa le ON le.id = c.id_lote_etapa AND le.situacao = 'em_andamento' "
            "WHERE l.uf = 'DF' AND c.id_cq_plano IS NULL AND c.geocodigo IS NULL ORDER BY c.id LIMIT 5"
        )
        assert len(origem) == 5, "o dev precisa da conversão do DF (A3)"
        for o in origem:
            u = novo_uuid()
            ex.executar(
                "INSERT INTO mapcartacomp.carga_trabalho (uuid, id_lote_etapa, id_atividade, uf, responsavel, geom) "
                "VALUES (%s, %s, %s, %s, current_user, %s)",
                (u, o["id_lote_etapa"], o["id_atividade"], o["uf"], o["geom"]),
            )
            copias.append(u)
    try:
        eu = {"uf": "DF", "papeis": ["supervisor"]}
        with db.transacao(amb, usuario, senha) as ex:
            sup = grupos.supervisao(ex, "DF")
            exe = grupos.execucao(ex)
            resp = grupos.responsaveis(ex, "DF")
            esperado = {}
            for g in sup:
                ids = list(g["atividades"])
                esperado[g["rotulo"]] = ex.um(
                    "SELECT (SELECT count(*) FROM mapcartacomp.lote l JOIN mapcartacomp.lote_etapa le "
                    "ON le.id = l.id_lote_etapa_atual WHERE l.uf = 'DF' "
                    "AND le.situacao IN ('pendente', 'em_andamento') "
                    "AND EXISTS (SELECT 1 FROM mapcartacomp.fluxo_etapa_atividade fa WHERE fa.id_fluxo_etapa = "
                    "le.id_fluxo_etapa AND fa.id_atividade = ANY(%s))) AS folhas, "
                    "count(*) FILTER (WHERE c.responsavel IS NOT NULL) AS atribuidas, "
                    "count(*) FILTER (WHERE c.responsavel IS NULL AND NOT c.concluido) AS a_atribuir "
                    "FROM mapcartacomp.carga_trabalho c WHERE c.uf = 'DF' AND c.id_atividade = ANY(%s) "
                    "AND c.id_lote_etapa IN (" + cargas.SQL_PASSAGENS_ATUAIS + " AND l.uf = 'DF')",
                    (ids, ids),
                )
        assert len(sup) > 1 and len(exe) == 1, (sup, exe)
        assert any(g["rotulo"].startswith("CQ · ") and len(g["atividades"]) > 1 for g in sup), sup
        authcfg = config.authcfg_id(amb)
        camadas.montar(amb, authcfg, eu, resp, sup, exe)
        r = camadas.montar(amb, authcfg, eu, resp, sup, exe)  # de novo: substitui, não duplica
        raiz = QgsProject.instance().layerTreeRoot()
        assert [g.name() for g in raiz.children()].count("Feixe") == 1
        assert len(QgsProject.instance().mapLayers()) == 2 + 3 * len(sup), QgsProject.instance().mapLayers()

        def arvore(no):
            return [(f.name(), arvore(f)) if f.children() else f.name() for f in no.children()]

        feixe = raiz.findGroup("Feixe")
        trio = ["Folhas", "Cargas por responsável", "Cargas a atribuir"]
        assert arvore(feixe) == [
            ("Execução", ["Minhas cargas", "Minhas folhas"]),
            ("Supervisão", [(g["rotulo"], trio) for g in sup]),
        ], arvore(feixe)
        ok(f"subgrupos por atividade em produção (CQ de um tema junto): {[g['rotulo'] for g in sup]}")
        for g in sup:
            sub = feixe.findGroup("Supervisão").findGroup(g["rotulo"])
            n = {no.name(): no.layer().featureCount() for no in sub.findLayers()}
            e = esperado[g["rotulo"]]
            assert n == {"Folhas": e["folhas"], "Cargas por responsável": e["atribuidas"],
                         "Cargas a atribuir": e["a_atribuir"]}, (g["rotulo"], n, e)  # fmt: skip
        n = {c["nome"]: c["feicoes"] for c in r["camadas"][:2]}
        assert n == {"Minhas cargas": 5, "Minhas folhas": 1}, n
        ok(f"contagens por subgrupo conferem com o banco: {esperado}")
        ligados = [s_.name() for s_ in feixe.findGroup("Supervisão").children() if s_.itemVisibilityChecked()]
        maior = max(sup, key=lambda g: esperado[g["rotulo"]]["folhas"])["rotulo"]
        assert ligados == [maior], ligados
        ok(f"só o subgrupo com mais folhas vem ligado: {maior}")
        assert r["modo"] == "supervisao" == camadas.modo_atual()
        assert not feixe.findGroup("Execução").itemVisibilityChecked() and feixe.findGroup("Supervisão").isVisible()
        assert camadas.modo("execucao") == "execucao" == camadas.modo_atual()
        assert feixe.findGroup("Execução").isVisible() and not feixe.findGroup("Supervisão").itemVisibilityChecked()
        camadas.modo("supervisao")
        ok("modos: supervisor começa em supervisão; trocar só troca a visibilidade")

        por_resp = [no.layer() for no in feixe.findLayers() if no.name() == "Cargas por responsável"]
        for camada in por_resp:
            gerente = camada.styleManager()
            assert sorted(gerente.styles()) == ["Por responsável", "Por situação"], gerente.styles()
            assert gerente.currentStyle() == "Por responsável"
            regras = camada.renderer().rootRule().children()
            assert regras[-1].label() == "Concluídas" and not regras[-1].active()
            assert all(x.active() for x in regras[:-1])
        cores = {}
        for camada in por_resp:
            for x in camada.renderer().rootRule().children()[:-2]:
                conta = x.filterExpression().split("'")[1]
                cores.setdefault(conta, x.symbol().color().name())
        assert len(set(cores.values())) == len(cores) == len({x["conta"] for x in resp}), cores
        ok(f"cargas por responsável: concluídas desmarcadas, estilo alternativo por situação, "
           f"{len(cores)} pessoas com cores diferentes")  # fmt: skip

        # Formulários, dicas e ações por usuário (D-102).
        from qgis.core import QgsExpression, QgsExpressionContext, QgsExpressionContextUtils

        def avaliar(camada, f, texto):
            ctx = QgsExpressionContext(QgsExpressionContextUtils.globalProjectLayerScopes(camada))
            ctx.setFeature(f)
            return QgsExpression.replaceExpressionText(texto, ctx)

        minhas, mfolhas = [no.layer() for no in feixe.findGroup("Execução").findLayers()]
        f = next(minhas.getFeatures())
        assert f["situacao_txt"] in ("pendente",) or f["situacao_txt"].startswith("concluída em"), f["situacao_txt"]
        assert " de 5 concluídas" in f["progresso_txt"], f["progresso_txt"]
        dica = avaliar(minhas, f, minhas.mapTipTemplate())
        assert "Eval Error" not in dica and "de 5" in dica, dica
        assert [a.name() for a in minhas.actions().actions()] == ["Trabalhar nesta carga", "Pular esta carga"]
        ff = next(mfolhas.getFeatures())
        assert ff["minhas_txt"].endswith("de 5 concluídas"), ff["minhas_txt"]
        assert [a.name() for a in mfolhas.actions().actions()] == ["Próxima carga nesta folha"]
        for camada in [no.layer() for no in feixe.findGroup("Supervisão").findLayers()]:
            f = next(camada.getFeatures(), None)
            if f is None:
                continue
            dica = avaliar(camada, f, camada.mapTipTemplate())
            assert dica and "Eval Error" not in dica, (camada.name(), dica)
            assert all(f[c] is not None for c in ("etapa_txt",)), camada.name()
            assert len(camada.actions().actions()) == 1, camada.name()
            cfg = camada.editFormConfig()
            assert all(cfg.readOnly(i) for i in range(len(camada.fields()))), camada.name()
        ok("formulários, dicas e ações: APM com situação e progresso; supervisor só leitura, com abrir no Feixe")

        apm = camadas.montar(amb, authcfg, {"uf": "DF", "papeis": ["apm"]}, [], [], exe)
        assert apm["modo"] == "execucao" and [c["nome"] for c in apm["camadas"]] == ["Minhas cargas", "Minhas folhas"]
        try:
            camadas.modo("supervisao")
            raise AssertionError("APM entrou no modo supervisão")
        except RuntimeError:
            pass
        r = camadas.montar(amb, authcfg, eu, resp, sup, exe)
        feixe = raiz.findGroup("Feixe")
        ok("APM só tem Execução; o modo supervisão é recusado")

        minhas = camadas.camada_minhas()
        assert minhas.renderer().type() == "RuleRenderer"
        rotulos = [x.label() for x in minhas.renderer().rootRule().children()]
        assert rotulos == ["Carga atual", "Pendente", "Concluída nos últimos 3 dias", "Concluída há mais de 3 dias"]
        cfg = minhas.editFormConfig()
        editaveis = [f.name() for i, f in enumerate(minhas.fields()) if not cfg.readOnly(i)]
        assert editaveis == ["concluido"], editaveis
        ok("Minhas cargas com o estilo do executor (carga atual, pendente, concluídas) e só concluido editável")

        alvo = next(minhas.getFeatures())
        minhas.startEditing()
        minhas.changeAttributeValue(alvo.id(), minhas.fields().indexOf("concluido"), True)
        assert minhas.commitChanges(), minhas.commitErrors()
        with db.transacao(amb, usuario, senha) as ex:
            linha = ex.um(
                "SELECT concluido, concluido_em FROM mapcartacomp.carga_trabalho WHERE id = %s",
                (alvo["id_carga_trabalho"],),
            )
        assert linha["concluido"] and linha["concluido_em"] is not None, linha
        ok("concluir pela tabela de atributos grava no banco e preenche concluido_em")

        caminho = _renderizar(os.path.join(SAIDA, "feixe-b1-camadas.png"), "Folhas")
        ok(f"imagem das camadas em {caminho}")
    finally:
        QgsProject.instance().clear()
        with db.transacao(amb, usuario, senha) as ex:
            ex.executar("DELETE FROM mapcartacomp.carga_trabalho WHERE uuid::text = ANY(%s)", (copias,))


@secao("b2")
def b2(amb, usuario, senha):
    """Minhas cargas: próxima e concluir pelo caminho da barra, com a carga atual, o estilo e a recarga da camada."""
    from feixe.core import camadas
    from feixe.core.dados import cargas as dc
    from feixe.server.api import Contexto
    from feixe.server.rotas import cargas as rc
    from qgis.core import QgsExpressionContextUtils, QgsProject, QgsRenderContext

    copias = []
    with db.transacao(amb, usuario, senha) as ex:
        origem = ex.todos(
            "SELECT c.id_lote_etapa, c.id_atividade, c.uf, c.geom FROM mapcartacomp.carga_trabalho c "
            "JOIN mapcartacomp.lote_etapa le ON le.id = c.id_lote_etapa AND le.situacao = 'em_andamento' "
            "WHERE c.uf = 'DF' AND c.id_cq_plano IS NULL AND c.geocodigo IS NULL "
            "AND c.id_lote_etapa = (SELECT min(id_lote_etapa) FROM mapcartacomp.carga_trabalho c2 "
            "JOIN mapcartacomp.lote_etapa le2 ON le2.id = c2.id_lote_etapa AND le2.situacao = 'em_andamento' "
            "WHERE c2.uf = 'DF' AND c2.id_cq_plano IS NULL) ORDER BY c.id LIMIT 4"
        )
        for o in origem:
            u = novo_uuid()
            ex.executar(
                "INSERT INTO mapcartacomp.carga_trabalho (uuid, id_lote_etapa, id_atividade, uf, responsavel, geom) "
                "VALUES (%s, %s, %s, %s, current_user, %s)",
                (u, o["id_lote_etapa"], o["id_atividade"], o["uf"], o["geom"]),
            )
            copias.append(u)
    try:
        camadas.montar(amb, config.authcfg_id(amb), {"uf": "DF", "papeis": ["apm"]}, [], [], [])
        focadas = []
        ctx = Contexto(
            transacao=lambda: db.transacao(amb, usuario, senha),
            qgis=lambda nome, *a: {
                "focar_carga": lambda c, p: (camadas.definir_atual(c["id"]), focadas.append(c["id"])),
                "cargas_mudaram": lambda p: camadas.recarregar_cargas(),
            }[nome](*a),
        )
        r = rc.proxima(ctx)
        assert r["carga"] is not None and camadas.carga_atual() == r["carga"]["id"] == focadas[-1]
        assert camadas.carga_selecionada() is None  # a atual não usa a seleção (amarela por cima do contorno)
        minhas = camadas.camada_minhas()
        rctx = QgsRenderContext()
        rctx.expressionContext().appendScopes(
            [
                QgsExpressionContextUtils.projectScope(QgsProject.instance()),
                QgsExpressionContextUtils.layerScope(minhas),
            ]
        )
        rend = minhas.renderer().clone()
        rend.startRender(rctx, minhas.fields())

        def regra(f):  # rótulos das regras de estilo em que a feição cai
            rctx.expressionContext().setFeature(f)
            chaves = rend.legendKeysForFeature(f, rctx)
            return [x.label() for x in rend.rootRule().children() if x.ruleKey() in chaves]

        regras = {f["id_carga_trabalho"]: regra(f) for f in minhas.getFeatures()}
        rend.stopRender(rctx)
        assert regras[r["carga"]["id"]] == ["Carga atual"], regras
        assert all(v == ["Pendente"] for k, v in regras.items() if k != r["carga"]["id"]), regras
        ok(f"próxima carga vira a carga atual (só contorno), as outras pendentes: #{r['carga']['id']}")
        alvo = camadas.carga_atual()
        r = rc.concluir(ctx, alvo)
        assert r["progresso"]["concluidas"] == 1 and r["progresso"]["total"] == 4, r["progresso"]
        feicao = next(minhas.getFeatures(f'"id_carga_trabalho" = {alvo}'))
        assert feicao["concluido"] is True or feicao["concluido"] == 1, feicao["concluido"]
        ok("concluir grava, recarrega a camada e devolve o progresso 1/4")
        seguinte = rc.proxima(ctx, alvo)["carga"]
        assert seguinte["id"] != alvo and not seguinte["concluido"] and camadas.carga_atual() == seguinte["id"]
        ok("a seguinte é outra carga pendente e vira a atual")
        with db.transacao(amb, usuario, senha) as ex:
            assert not dc.desfazer(ex, alvo)["carga"]["concluido"]
        ok("desfazer dentro de 24 horas")
    finally:
        QgsProject.instance().clear()
        with db.transacao(amb, usuario, senha) as ex:
            ex.executar("DELETE FROM mapcartacomp.carga_trabalho WHERE uuid::text = ANY(%s)", (copias,))


@secao("b3")
def b3(amb, usuario, senha):
    """Folhas e lotes livres: rota de criar, folha pelo clique no mapa e lote livre pela seleção de uma camada."""
    from feixe.core.dados import lotes as dl
    from feixe.server.api import Contexto, criar_roteador
    from feixe.ui.ferramentas import FerramentaFolha, selecao_wkt
    from qgis.core import QgsCoordinateReferenceSystem, QgsFeature, QgsGeometry, QgsPointXY, QgsVectorLayer
    from qgis.gui import QgsMapCanvas

    with db.transacao(amb, usuario, senha) as ex:
        fluxo = ex.um("SELECT id FROM mapcartacomp.fluxo WHERE uf = 'DF' AND nome = 'DF Hidrografia'")["id"]
        livre = ex.um(  # uma folha sem lote de hidrografia, para criar e apagar
            "SELECT a.id_articulacao_scn AS id, a.cd_mi FROM mapcartctrl.v_articulacao_scn_100000 a "
            "WHERE NOT EXISTS (SELECT 1 FROM mapcartacomp.lote l JOIN mapcartacomp.fluxo f ON f.id = l.id_fluxo "
            "WHERE l.id_articulacao_scn = a.id_articulacao_scn AND f.id = %s) AND a.cd_mi LIKE '25__' "
            "ORDER BY a.cd_mi LIMIT 1",
            (fluxo,),
        )
        centro = ex.um(
            "SELECT ST_X(ST_PointOnSurface(geom)) AS x, ST_Y(ST_PointOnSurface(geom)) AS y "
            "FROM mapcartctrl.v_articulacao_scn_100000 WHERE id_articulacao_scn = %s",
            (livre["id"],),
        )
    criados = []
    ctx = Contexto(transacao=lambda: db.transacao(amb, usuario, senha), publicar=lambda e, d: None)
    ctx._eu = {"papeis": ["supervisor"], "uf": "DF", "perfis": [{"cod_projeto": 5, "papel": "supervisor"}]}
    r = criar_roteador(ctx)
    try:
        status, obj = r.despachar(
            "POST", "/api/lotes", {}, {"tipo": "folha", "id_fluxo": fluxo, "folhas": [livre["id"]]}
        )
        assert status == 200 and obj["criados"][0]["cd_mi"] == livre["cd_mi"], obj
        criados.append(obj["criados"][0]["id_lote"])
        status, lote = r.despachar("GET", f"/api/lotes/{criados[0]}", {}, None)
        assert status == 200 and lote["passagens"][0]["situacao"] == "pendente", lote
        ok(f"folha {livre['cd_mi']} criada na primeira etapa ({lote['passagens'][0]['etapa']}), pendente")
        status, obj = r.despachar(
            "POST", "/api/lotes", {}, {"tipo": "folha", "id_fluxo": fluxo, "folhas": [livre["id"]]}
        )
        assert status == 200 and not obj["criados"] and obj["existentes"][0]["cd_mi"] == livre["cd_mi"], obj
        ok("criar de novo a mesma folha no mesmo projeto e tema não duplica: volta como existente")

        # Clique no mapa num canvas em Web Mercator: a ferramenta devolve SIRGAS e o banco acha a folha.
        canvas = QgsMapCanvas()
        canvas.setDestinationCrs(QgsCoordinateReferenceSystem("EPSG:3857"))
        recebidos = []
        ferramenta = FerramentaFolha(canvas, lambda x, y: recebidos.append((x, y)))
        from qgis.core import QgsCoordinateTransform, QgsProject
        from qgis.PyQt.QtCore import Qt

        para_3857 = QgsCoordinateTransform(
            QgsCoordinateReferenceSystem("EPSG:4674"), QgsCoordinateReferenceSystem("EPSG:3857"), QgsProject.instance()
        )
        ferramenta._clicou(para_3857.transform(QgsPointXY(centro["x"], centro["y"])), Qt.LeftButton)
        with db.transacao(amb, usuario, senha) as ex:
            achada = dl.folha_no_ponto(ex, *recebidos[0])
        assert achada["cd_mi"] == livre["cd_mi"], achada
        ok(f"clique no mapa em EPSG:3857 acha a folha {achada['cd_mi']}")

        # Lote livre a partir de duas feições selecionadas numa camada em EPSG:3857.
        camada = QgsVectorLayer("Polygon?crs=EPSG:3857", "bacias", "memory")
        feicoes = []
        for dx in (0, 0.05):
            f = QgsFeature()
            g = QgsGeometry.fromWkt(
                f"POLYGON(({-47.9 + dx} -15.9, {-47.85 + dx} -15.9, {-47.85 + dx} -15.85, {-47.9 + dx} -15.85, "
                f"{-47.9 + dx} -15.9))"
            )
            g.transform(
                QgsCoordinateTransform(QgsCoordinateReferenceSystem("EPSG:4674"), camada.crs(), QgsProject.instance())
            )
            f.setGeometry(g)
            feicoes.append(f)
        camada.dataProvider().addFeatures(feicoes)
        camada.selectAll()
        sel = selecao_wkt(camada)
        assert sel["feicoes"] == 2 and sel["wkt"].startswith("Polygon"), sel["wkt"][:40]
        status, obj = r.despachar(
            "POST", "/api/lotes", {}, {"tipo": "livre", "id_fluxo": fluxo, "nome": "teste_b3 bacia", "wkt": sel["wkt"]}
        )
        assert status == 200, obj
        criados.append(obj["criados"][0]["id_lote"])
        with db.transacao(amb, usuario, senha) as ex:
            area = ex.um(
                "SELECT round(ST_Area(geom)::numeric, 4) AS a FROM mapcartacomp.lote WHERE id = %s", (criados[-1],)
            )
        assert float(area["a"]) == 0.005, area  # 0,1 x 0,05 grau: as duas feições unidas, de volta em SIRGAS
        ok("lote livre da seleção de duas feições em EPSG:3857, unidas e em SIRGAS 2000")
    finally:
        with db.transacao(amb, usuario, senha) as ex:
            ex.executar("DELETE FROM mapcartacomp.lote WHERE id = ANY(%s)", (criados,))


@secao("b4")
def b4(amb, usuario, senha):
    """Gerar cargas pela grade: prévia numa camada temporária do QGIS, gravar, e recusar gravar de novo."""
    from feixe.core import camadas
    from feixe.core.dados import lotes as dl
    from feixe.server.api import Contexto
    from feixe.server.rotas import cargas as rc
    from qgis.core import QgsProject

    with db.transacao(amb, usuario, senha) as ex:
        fluxo = ex.um("SELECT id FROM mapcartacomp.fluxo WHERE uf = 'DF' AND nome = 'DF Hidrografia'")["id"]
        folha = ex.um(
            "SELECT a.id_articulacao_scn AS id FROM mapcartctrl.v_articulacao_scn_100000 a WHERE a.cd_mi LIKE '25__' "
            "AND NOT EXISTS (SELECT 1 FROM mapcartacomp.lote l WHERE l.id_articulacao_scn = a.id_articulacao_scn "
            "AND l.id_fluxo = %s) ORDER BY a.cd_mi LIMIT 1",
            (fluxo,),
        )["id"]
        lote = dl.criar_folhas(ex, "DF", fluxo, [folha])["criados"][0]["id_lote"]
        le = ex.um("SELECT id FROM mapcartacomp.lote_etapa WHERE id_lote = %s", (lote,))["id"]
    try:
        ctx = Contexto(
            transacao=lambda: db.transacao(amb, usuario, senha),
            qgis=lambda nome, *a: {
                "previa_cargas": lambda c: camadas.mostrar_previa(c),
                "cargas_geradas": lambda: camadas.remover_previa(),
            }[nome](*a),
        )
        r = rc.gerar(ctx, [le], True, "DF")
        n = r["resultados"][0]["celulas"]
        previa = QgsProject.instance().mapLayersByName(camadas.NOME_PREVIA)
        assert len(previa) == 1 and previa[0].featureCount() == n and previa[0].isValid(), previa
        ok(f"prévia de {n} células numa camada temporária do QGIS; nada gravado")
        r = rc.gerar(ctx, [le], False, "DF")
        assert r["resultados"][0]["gravadas"] == n and not QgsProject.instance().mapLayersByName(camadas.NOME_PREVIA)
        with db.transacao(amb, usuario, senha) as ex:
            k = ex.um(
                "SELECT count(DISTINCT geocodigo) AS n FROM mapcartacomp.carga_trabalho WHERE id_lote_etapa = %s", (le,)
            )
        assert k["n"] == n, k
        ok(f"{n} cargas gravadas, uma por célula, e a prévia some do QGIS")
        r = rc.gerar(ctx, [le], False, "DF")
        assert not r["resultados"] and "já tem cargas" in r["erros"][0]["erro"], r
        ok("gravar de novo é recusado com mensagem")
    finally:
        QgsProject.instance().clear()
        with db.transacao(amb, usuario, senha) as ex:
            ex.executar("DELETE FROM mapcartacomp.lote WHERE id = %s", (lote,))


def _renderizar(caminho, camada_extensao):
    """Renderiza as camadas do projeto num PNG, na extensão da camada indicada (para conferir os estilos)."""
    from qgis.core import QgsMapRendererParallelJob, QgsMapSettings, QgsProject
    from qgis.PyQt.QtCore import QSize

    projeto = QgsProject.instance()
    ordem = [n.layer() for n in projeto.layerTreeRoot().findLayers() if n.isVisible()]
    ms = QgsMapSettings()
    ms.setLayers(ordem)
    ms.setDestinationCrs(ordem[0].crs())
    ms.setExtent(projeto.mapLayersByName(camada_extensao)[0].extent())
    ms.setOutputSize(QSize(1600, 1200))
    job = QgsMapRendererParallelJob(ms)
    job.start()
    job.waitForFinished()
    job.renderedImage().save(caminho, "PNG")
    return caminho


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
