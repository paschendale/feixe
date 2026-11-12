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
    from feixe.core.dados import cargas, lotes
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
            resp = cargas.responsaveis_atuais(ex, "DF")
            temas = lotes.temas_com_lotes(ex, "DF")
            por_tema = {
                f"Folhas · {r['nome']}": r["n"]
                for r in ex.todos(
                    "SELECT t.nome, count(*) AS n FROM mapcartacomp.ctrl_lote c JOIN mapcartacomp.tema t "
                    "ON t.id = c.id_tema WHERE c.uf = 'DF' GROUP BY t.nome"
                )
            }
            esperado = ex.um(
                "SELECT count(*) FILTER (WHERE responsavel IS NOT NULL) AS atribuidas, "
                "count(*) FILTER (WHERE responsavel IS NULL) AS disponiveis FROM mapcartacomp.carga_trabalho "
                "WHERE uf = 'DF' AND id_lote_etapa IN (" + cargas.SQL_PASSAGENS_ATUAIS + " AND l.uf = 'DF')"
            )
        authcfg = config.authcfg_id(amb)
        camadas.montar(amb, authcfg, eu, resp, temas)
        r = camadas.montar(amb, authcfg, eu, resp, temas)  # de novo: substitui, não duplica
        raiz = QgsProject.instance().layerTreeRoot()
        assert [g.name() for g in raiz.children()].count("Feixe") == 1
        assert len(QgsProject.instance().mapLayers()) == 3 + len(temas), QgsProject.instance().mapLayers()
        assert len(temas) > 1, temas
        n = {c["nome"]: c["feicoes"] for c in r["camadas"]}
        assert n == {
            "Minhas cargas": 5,
            "Cargas por responsável": esperado["atribuidas"],
            "Cargas disponíveis": esperado["disponiveis"],
            **por_tema,
        }, n
        ok(f"grupo único, contagens conferem: {n}")
        assert len(resp) > 1, resp
        cats = QgsProject.instance().mapLayersByName("Cargas por responsável")[0].renderer().categories()
        assert len(cats) == len(resp) and all(c.label() for c in cats)
        ligadas = [n.name() for n in raiz.findGroup("Feixe").findGroup("Folhas").findLayers() if n.isVisible()]
        assert ligadas == ["Folhas · Hidrografia"], ligadas
        ok("subgrupo Folhas com um tema ligado: o de mais folhas")
        ok(f"{len(cats)} responsáveis com cor e nome, ex.: {cats[0].label()}")

        minhas = QgsProject.instance().mapLayersByName("Minhas cargas")[0]
        assert minhas.renderer().type() == "categorizedSymbol"
        cfg = minhas.editFormConfig()
        editaveis = [f.name() for i, f in enumerate(minhas.fields()) if not cfg.readOnly(i)]
        assert editaveis == ["concluido"], editaveis
        ok("Minhas cargas com o estilo do DF e só concluido editável")

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

        caminho = _renderizar(os.path.join(SAIDA, "feixe-b1-camadas.png"), "Folhas · Hidrografia")
        ok(f"imagem das camadas em {caminho}")
    finally:
        QgsProject.instance().clear()
        with db.transacao(amb, usuario, senha) as ex:
            ex.executar("DELETE FROM mapcartacomp.carga_trabalho WHERE uuid::text = ANY(%s)", (copias,))


@secao("b2")
def b2(amb, usuario, senha):
    """Minhas cargas: próxima e concluir pelo caminho da barra, com seleção e recarga da camada no QGIS."""
    from feixe.core import camadas
    from feixe.core.dados import cargas as dc
    from feixe.server.api import Contexto
    from feixe.server.rotas import cargas as rc
    from qgis.core import QgsProject

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
        camadas.montar(amb, config.authcfg_id(amb), {"uf": "DF", "papeis": ["apm"]}, [], [])
        focadas = []
        ctx = Contexto(
            transacao=lambda: db.transacao(amb, usuario, senha),
            qgis=lambda nome, *a: {
                "focar_carga": lambda c, p: (camadas.selecionar_carga(c["id"]), focadas.append(c["id"])),
                "cargas_mudaram": lambda p: camadas.recarregar_cargas(),
            }[nome](*a),
        )
        r = rc.proxima(ctx)
        assert r["carga"] is not None and camadas.carga_selecionada() == r["carga"]["id"] == focadas[-1]
        ok(f"próxima carga selecionada na camada: {r['carga']['folha_revisao']} #{r['carga']['id']}")
        alvo = camadas.carga_selecionada()
        r = rc.concluir(ctx, alvo)
        assert r["progresso"]["concluidas"] == 1 and r["progresso"]["total"] == 4, r["progresso"]
        minhas = camadas.camada_minhas()
        feicao = next(minhas.getFeatures(f'"id_carga_trabalho" = {alvo}'))
        assert feicao["concluido"] is True or feicao["concluido"] == 1, feicao["concluido"]
        ok("concluir grava, recarrega a camada e devolve o progresso 1/4")
        seguinte = rc.proxima(ctx, alvo)["carga"]
        assert seguinte["id"] != alvo and not seguinte["concluido"]
        ok("a seguinte é outra carga pendente")
        with db.transacao(amb, usuario, senha) as ex:
            assert not dc.desfazer(ex, alvo)["carga"]["concluido"]
        ok("desfazer dentro de 24 horas")
    finally:
        QgsProject.instance().clear()
        with db.transacao(amb, usuario, senha) as ex:
            ex.executar("DELETE FROM mapcartacomp.carga_trabalho WHERE uuid::text = ANY(%s)", (copias,))


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
