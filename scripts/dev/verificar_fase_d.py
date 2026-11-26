#!/usr/bin/env python3
"""Verificação headless da fase D contra o banco de dev, sem abrir o QGIS. Cada item acrescenta a sua seção.

Uso (Mac, com o QGIS-LTR):
    /Applications/QGIS-LTR.app/Contents/MacOS/bin/python3 scripts/dev/verificar_fase_d.py [d3a d3c ...]

Sem argumentos roda todas as seções. Lê o banco de config/ambientes.json (dev) e o usuário e a senha de FEIXE_CCAR no
.dev.env da raiz. Usa perfil do QGIS, banco de autenticação e workspaces temporários, apagados no fim. A CCAR
inalcançável é simulada pelo próprio plugin (`FEIXE_DEV_SEM_CCAR=1`, só no ambiente dev): nenhum container é parado.
Tudo o que grava no banco é apagado no fim de cada seção.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import sys
import tempfile
import urllib.parse
import uuid as uuid_mod

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TEMP = tempfile.mkdtemp(prefix="feixe-fase-d-")
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
from feixe.core.dados import ErroDados, novo_uuid  # noqa: E402
from qgis.core import QgsApplication  # noqa: E402

SECOES = {}
S = "mapcartacomp"


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


class Folha:
    """Tema, atividades e fluxo próprios (aquisição > CQ com o padrão nível II e LQA 4%), na folha 2534 do DF: a
    aquisição da revisão 1 concluída, a passagem de CQ aberta e a aquisição da revisão 2 (a revisão seguinte)."""

    def __init__(self, ex, tag):
        def um(sql, params=()):
            return next(iter(ex.um(sql, params).values()))

        self.tema = um(f"INSERT INTO {S}.tema (nome) VALUES (%s) RETURNING id", (f"verificar_d3a_{tag}",))
        self.aq = um(
            f"INSERT INTO {S}.atividade (cod_projeto, id_tema, fase, nome) VALUES (5, %s, 'aquisicao', %s) "
            "RETURNING id",
            (self.tema, f"aquisição d3a {tag}"),
        )
        self.cq = um(
            f"INSERT INTO {S}.atividade (cod_projeto, id_tema, fase, nome, geracao, grade_nivel, id_medidadequalidade) "
            "SELECT 5, %s, 'cq', %s, 'amostra_area', 5000, id FROM mapcartctrl.t_qua_medidadequalidade "
            "WHERE nome = 'Omissão' RETURNING id",
            (self.tema, f"CQ d3a {tag} - Omissão"),
        )
        self.fluxo = um(
            f"INSERT INTO {S}.fluxo (cod_projeto, id_tema, uf, nome) VALUES (5, %s, 'DF', %s) RETURNING id",
            (self.tema, f"DF d3a {tag}"),
        )
        self.etapa_aq = um(
            f"INSERT INTO {S}.fluxo_etapa (id_fluxo, ordem, fase, nome, conta_revisao, repetivel) "
            "VALUES (%s, 1, 'aquisicao', 'Aquisição', true, true) RETURNING id",
            (self.fluxo,),
        )
        self.etapa_cq = um(
            f"INSERT INTO {S}.fluxo_etapa (id_fluxo, ordem, fase, nome, conta_revisao, repetivel, nivel_inspecao, lqa) "
            "VALUES (%s, 2, 'cq', 'CQ', false, true, 'II', 4) RETURNING id",
            (self.fluxo,),
        )
        for etapa, ativ in ((self.etapa_aq, self.aq), (self.etapa_cq, self.cq)):
            ex.executar(
                f"INSERT INTO {S}.fluxo_etapa_atividade (id_fluxo_etapa, id_atividade) VALUES (%s, %s)", (etapa, ativ)
            )
        self.lote = um(
            f"INSERT INTO {S}.lote (uuid, cod_projeto, id_tema, id_fluxo, uf, tipo, id_articulacao_scn, nome) "
            "SELECT %s, 5, %s, %s, 'DF', 'folha', id_articulacao_scn, '2534' FROM mapcartctrl.v_articulacao_scn_100000 "
            "WHERE cd_mi = '2534' RETURNING id",
            (novo_uuid(), self.tema, self.fluxo),
        )

    def passagem(self, ex, etapa, situacao, instancia=1):
        return ex.um(
            f"INSERT INTO {S}.lote_etapa (uuid, id_lote, id_fluxo_etapa, instancia, situacao, iniciada_em) "
            "VALUES (%s, %s, %s, %s, %s, CASE WHEN %s = 'pendente' THEN NULL ELSE now() END) RETURNING id",
            (novo_uuid(), self.lote, etapa, instancia, situacao, situacao),
        )["id"]

    def apagar(self, ex):
        ex.executar(f"DELETE FROM {S}.lote WHERE id = %s", (self.lote,))
        ex.executar(f"DELETE FROM {S}.fluxo WHERE id = %s", (self.fluxo,))
        ex.executar(f"DELETE FROM {S}.atividade WHERE id = ANY(%s)", ([self.aq, self.cq],))
        ex.executar(f"DELETE FROM {S}.tema WHERE id = %s", (self.tema,))


@secao("d3a")
def d3a(amb, usuario, senha):
    """Avaliar amostra e registrar ocorrência offline, sincronizar, ciência do APM autor e a revisão seguinte às cegas
    (e com "incluir correções a serem feitas")."""
    from feixe.core.dados import cargas as dc
    from feixe.core.dados.local import cq as lq
    from feixe.server.api import Contexto, criar_roteador
    from feixe.sync import pull, push
    from feixe.sync.sincronizar import Sincronizacao
    from feixe.sync.workspace import Workspace

    tag = uuid_mod.uuid4().hex[:8]
    apm, rev = f"t_d3a_apm_{tag}", f"t_d3a_rev_{tag}"

    def tx():
        return db.transacao(amb, usuario, senha, timeout_conexao=5)

    with tx() as ex:
        f = Folha(ex, tag)
        le_aq = f.passagem(ex, f.etapa_aq, "concluida")
        le_cq = f.passagem(ex, f.etapa_cq, "pendente")
    workspaces = []
    try:
        # --- abrir a passagem de CQ: os planos e as amostras saem sozinhos, com o padrão da etapa (D-136) ----------
        with tx() as ex:
            r = dc.preparar(ex, "DF", [le_cq])
            (g,) = r["geradas"]
            plano = ex.um(f"SELECT * FROM {S}.cq_plano WHERE id_lote_etapa = %s", (le_cq,))
            amostras = ex.todos(
                f"SELECT c.id, c.uuid::text AS uuid, a.id AS amostra, ST_X(ST_Centroid(c.geom)) AS x, "
                f"ST_Y(ST_Centroid(c.geom)) AS y FROM {S}.carga_trabalho c JOIN {S}.cq_amostra a "
                "ON a.id_carga_trabalho = c.id WHERE c.id_lote_etapa = %s ORDER BY c.geocodigo LIMIT 2",
                (le_cq,),
            )
        ok(
            f"passagem de CQ aberta: plano {plano['letra_codigo']}, N={plano['tamanho_lote_n']}, "
            f"n={plano['tamanho_amostra_n']}, Ac={plano['numero_aceitacao_ac']} ({g['gravadas']} amostras)"
        )
        a1, a2 = amostras
        # As cargas da aquisição que o CQ avalia: as mesmas células, do APM autor (feitas na revisão 1).
        with tx() as ex:
            for a in amostras:
                ex.executar(
                    f"INSERT INTO {S}.carga_trabalho (uuid, id_lote_etapa, id_atividade, responsavel, geom, concluido) "
                    f"SELECT %s, %s, %s, %s, geom, true FROM {S}.carga_trabalho WHERE id = %s",
                    (novo_uuid(), le_aq, f.aq, apm, a["id"]),
                )
            producao = {
                r["x"]: r["id"]
                for r in ex.todos(
                    f"SELECT id, ST_X(ST_Centroid(geom)) AS x FROM {S}.carga_trabalho WHERE id_lote_etapa = %s",
                    (le_aq,),
                )
            }
            try:
                dc.atribuir(ex, "DF", usuario, ids=[a1["id"], a2["id"]])
                como = "pelo Distribuir"
            except ErroDados:
                ex.executar(f"UPDATE {S}.carga_trabalho SET responsavel = %s WHERE id = ANY(%s)",
                            (usuario, [a1["id"], a2["id"]]))  # fmt: skip
                ex.executar(f"UPDATE {S}.lote_etapa SET situacao = 'em_andamento', iniciada_em = now() WHERE id = %s",
                            (le_cq,))  # fmt: skip
                como = "direto (a conta de dev não tem o perfil V no projeto)"
            le_rev = f.passagem(ex, f.etapa_aq, "em_andamento", instancia=2)
            ex.executar(
                f"INSERT INTO {S}.carga_trabalho (uuid, id_lote_etapa, id_atividade, responsavel, geom) "
                f"SELECT %s, %s, %s, %s, geom FROM {S}.carga_trabalho WHERE id = %s",
                (novo_uuid(), le_rev, f.aq, rev, a1["id"]),
            )
        ok(f"duas amostras com o avaliador ({usuario}), {como}; revisão 2 aberta com o revisor")

        # --- o avaliador (a conta de dev), como no plugin ---------------------------------------------------------
        ws = Workspace.abrir(amb.nome, usuario, "DF", raiz=os.path.join(TEMP, "aval"))
        workspaces.append(ws)
        sinc = Sincronizacao(lambda: ws, tx, alcancavel=lambda: db.alcancavel(amb))
        assert sinc.sincronizar()["estado"] == "ok"
        eventos = []
        ctx = Contexto(transacao=tx, workspace=lambda: ws, online=lambda: sinc.online,
                       publicar=lambda e, d: eventos.append(e))  # fmt: skip
        ctx._eu = {"conta": usuario, "uf": "DF", "papeis": ["supervisor", "avaliador"], "perfis": []}
        api = criar_roteador(ctx)
        st, obj = api.despachar("GET", "/api/amostras", {"lote_etapa": str(le_cq)}, None)
        assert st == 200 and {x["id"] for x in obj["itens"]} == {a1["amostra"], a2["amostra"]}, obj
        assert {x["elemento"] for x in obj["itens"]} == {"Omissão"} and obj["itens"][0]["plano"]["n"]
        ok("o pull trouxe as amostras com o plano e o elemento")

        os.environ["FEIXE_DEV_SEM_CCAR"] = "1"
        db.esquecer()
        assert sinc.sincronizar()["estado"] == "offline"
        st, obj = api.despachar("POST", f"/api/amostras/{a1['amostra']}", {}, {"status": 0, "observacao": "omissão"})
        assert st == 200 and obj["carga"]["concluido"] and obj["proxima"]["amostra"]["id"] == a2["amostra"], obj
        st, obj = api.despachar(
            "POST", "/api/inspecoes", {}, {"x": a1["x"], "y": a1["y"], "id_carga_trabalho": a1["id"],
                                           "anotacao": "trecho de drenagem omitido"},
        )  # fmt: skip
        assert st == 200 and obj["ocorrencia"]["enviada"] is False, obj
        oc = obj["ocorrencia"]["uuid"]
        ok("offline: amostra avaliada (a carga de CQ concluiu e a resposta aponta a próxima) e ocorrência registrada")

        del os.environ["FEIXE_DEV_SEM_CCAR"]
        r = sinc.sincronizar()
        assert r["estado"] == "ok" and r["push"]["resultados"]["aplicado"] == 2, r
        with tx() as ex:
            am = ex.um(f"SELECT status, avaliado_em FROM {S}.cq_amostra WHERE id = %s", (a1["amostra"],))
            carga = ex.um(f"SELECT concluido, concluido_em FROM {S}.carga_trabalho WHERE id = %s", (a1["id"],))
            linha = ex.um(f"SELECT * FROM {S}.cq_inspecao WHERE uuid = %s", (oc,))
        assert am["status"] == 0 and carga["concluido"] and carga["concluido_em"] == am["avaliado_em"], (am, carga)
        assert linha["id_lote_etapa"] == le_cq and linha["id_carga_avaliada"] == producao[a1["x"]], linha
        ok(f"CCAR de volta: na CCAR, carga de CQ concluída na hora da avaliação e a ocorrência aponta a carga {apm}")

        # --- o APM autor recebe e dá ciência ---------------------------------------------------------------------
        def puxar(w, conta):
            with tx() as ex:
                return pull.puxar(w, ex, usuario=conta)

        w_apm = Workspace.abrir(amb.nome, apm, "DF", raiz=os.path.join(TEMP, "apm"))
        workspaces.append(w_apm)
        puxar(w_apm, apm)
        with w_apm.transacao() as ex:
            (vista,) = lq.ocorrencias(ex, id_lote=f.lote)
            assert vista["uuid"] == oc and vista["motivo"] == "minha_carga" and vista["pode_ciente"], vista
            lq.ciente(ex, oc)
        r = push.enviar(w_apm, tx, usuario=apm)
        assert r["resultados"]["aplicado"] == 1, r
        with tx() as ex:
            assert ex.um(f"SELECT ciente_por FROM {S}.cq_inspecao WHERE uuid = %s", (oc,))["ciente_por"] == apm
        ok("o APM autor recebeu a ocorrência e deu ciência; a ciência chegou à CCAR")

        # --- a revisão seguinte -----------------------------------------------------------------------------------
        w_rev = Workspace.abrir(amb.nome, rev, "DF", raiz=os.path.join(TEMP, "rev"))
        workspaces.append(w_rev)
        puxar(w_rev, rev)
        with w_rev.leitura() as ex:
            assert lq.ocorrencias(ex, id_lote=f.lote) == []
            assert ex.um("SELECT count(*) AS n FROM cq_inspecao")["n"] == 0
        ok("o revisor da revisão 2 não recebe a ocorrência (às cegas)")
        with tx() as ex:
            ex.executar(f"UPDATE {S}.lote_etapa SET expor_ocorrencias = true WHERE id = %s", (le_rev,))
        puxar(w_rev, rev)
        with w_rev.leitura() as ex:
            vistas = lq.ocorrencias(ex, id_lote=f.lote)
        assert [(o["uuid"], o["motivo"]) for o in vistas] == [(oc, "correcao")], vistas
        ok('com "incluir correções a serem feitas", o revisor recebe a ocorrência como lista de correção')

        st, obj = api.despachar("GET", f"/api/lotes/{f.lote}/ocorrencias", {}, None)
        assert st == 200 and obj["total"] == 1 and obj["itens"][0]["ciente_por"] == apm, obj
        ok("o supervisor vê a ocorrência da folha na CCAR, com a ciência")
    finally:
        os.environ.pop("FEIXE_DEV_SEM_CCAR", None)
        for w in workspaces:
            w.fechar()
        with tx() as ex:
            ex.executar(
                f"DELETE FROM {S}.sync_log WHERE uuid IN (SELECT uuid FROM {S}.cq_inspecao WHERE id_lote = %s "
                f"UNION SELECT a.uuid FROM {S}.cq_amostra a JOIN {S}.carga_trabalho c ON c.id = a.id_carga_trabalho "
                f"JOIN {S}.lote_etapa le ON le.id = c.id_lote_etapa WHERE le.id_lote = %s "
                f"UNION SELECT c.uuid FROM {S}.carga_trabalho c JOIN {S}.lote_etapa le ON le.id = c.id_lote_etapa "
                f"WHERE le.id_lote = %s UNION SELECT uuid FROM {S}.lote_etapa WHERE id_lote = %s)",
                (f.lote,) * 4,
            )
            f.apagar(ex)


class _Barra:
    """A barra de mensagens do QGIS, gravando o que o plugin diria à pessoa."""

    def __init__(self):
        self.mensagens = []

    def pushMessage(self, titulo, texto, nivel=0, duracao=0):  # noqa: N802 - API do QGIS
        self.mensagens.append(texto)


class _Canvas:
    """O mapa, sem janela (o headless não cria widgets): a extensão, o centro pedido e as piscadas."""

    def __init__(self):
        from qgis.core import QgsCoordinateReferenceSystem, QgsMapSettings, QgsRectangle
        from qgis.PyQt.QtCore import QSize

        self.s = QgsMapSettings()
        self.s.setDestinationCrs(QgsCoordinateReferenceSystem("EPSG:4674"))
        self.s.setOutputSize(QSize(800, 600))
        self.s.setExtent(QgsRectangle(-60, -30, -59.9, -29.9))  # longe de tudo: o primeiro zoom centraliza
        self.centros, self.piscadas, self.ferramenta = [], [], None

    def mapSettings(self):  # noqa: N802
        return self.s

    def extent(self):
        return self.s.extent()

    def setCenter(self, p):  # noqa: N802
        from qgis.core import QgsRectangle

        e = self.s.extent()
        w, h = e.width() / 2, e.height() / 2
        self.s.setExtent(QgsRectangle(p.x() - w, p.y() - h, p.x() + w, p.y() + h))
        self.centros.append((p.x(), p.y()))

    def refresh(self):
        pass

    def flashFeatureIds(self, camada, ids):  # noqa: N802
        self.piscadas.append((camada.name(), list(ids)))

    def mapTool(self):  # noqa: N802
        return self.ferramenta


class _Iface:
    def __init__(self):
        self.barra = _Barra()
        self.canvas = _Canvas()

    def messageBar(self):  # noqa: N802 - API do QGIS
        return self.barra

    def mapCanvas(self):  # noqa: N802
        return self.canvas

    def mainWindow(self):  # noqa: N802
        return None


class _Rotulo:
    texto = ""

    def setText(self, t):  # noqa: N802
        self.texto = t


@secao("d3c")
def d3c(amb, usuario, senha):
    """Camadas, formulários e barra do CQ no QGIS: o grupo do avaliador (amostras e ocorrências por elemento) e o do
    APM (para ciência e correções), avaliar e registrar pela barra com a camada relendo, e o Ciente."""
    from feixe.core import camadas, config
    from feixe.core.dados import cargas as dc
    from feixe.core.dados.local import grupos as lg
    from feixe.plugin import FeixePlugin
    from feixe.server.api import Contexto
    from feixe.server.rotas import camadas as rotas_camadas
    from feixe.sync import pull, push
    from feixe.sync.sincronizar import Sincronizacao
    from feixe.sync.workspace import Workspace
    from feixe.ui import regras
    from qgis.core import QgsProject, QgsRuleBasedRenderer

    tag = uuid_mod.uuid4().hex[:8]
    apm = f"t_d3c_apm_{tag}"
    projeto = QgsProject.instance()

    def tx():
        return db.transacao(amb, usuario, senha, timeout_conexao=5)

    with tx() as ex:
        f = Folha(ex, tag)
        # Um segundo elemento (Comissão) na mesma etapa de CQ: um par de camadas por elemento, só o primeiro ligado.
        f.cq2 = next(iter(ex.um(
            f"INSERT INTO {S}.atividade (cod_projeto, id_tema, fase, nome, geracao, grade_nivel, id_medidadequalidade) "
            "SELECT 5, %s, 'cq', %s, 'amostra_area', 5000, id FROM mapcartctrl.t_qua_medidadequalidade "
            "WHERE nome = 'Comissão' RETURNING id",
            (f.tema, f"CQ d3c {tag} - Comissão"),
        ).values()))  # fmt: skip
        ex.executar(f"INSERT INTO {S}.fluxo_etapa_atividade (id_fluxo_etapa, id_atividade) VALUES (%s, %s)",
                    (f.etapa_cq, f.cq2))  # fmt: skip
        le_aq = f.passagem(ex, f.etapa_aq, "concluida")
        le_cq = f.passagem(ex, f.etapa_cq, "pendente")
    workspaces = []
    try:
        with tx() as ex:
            dc.preparar(ex, "DF", [le_cq])
            amostras = ex.todos(
                f"SELECT c.id, c.id_atividade, a.id AS amostra, ST_X(ST_Centroid(c.geom)) AS x, "
                f"ST_Y(ST_Centroid(c.geom)) AS y FROM {S}.carga_trabalho c JOIN {S}.cq_amostra a "
                "ON a.id_carga_trabalho = c.id WHERE c.id_lote_etapa = %s ORDER BY c.id_atividade, c.geocodigo",
                (le_cq,),
            )
            omissao = [a for a in amostras if a["id_atividade"] == f.cq][:3]
            comissao = [a for a in amostras if a["id_atividade"] == f.cq2][:1]
            minhas = omissao + comissao
            ids = [a["id"] for a in minhas]
            ex.executar(f"UPDATE {S}.carga_trabalho SET responsavel = %s WHERE id = ANY(%s)", (usuario, ids))
            ex.executar(f"UPDATE {S}.lote_etapa SET situacao = 'em_andamento', iniciada_em = now() WHERE id = %s",
                        (le_cq,))  # fmt: skip
            # As cargas do APM autor (revisão 1, concluídas) nas células das amostras, e a revisão 2 dele, planejada
            # com "incluir correções a serem feitas".
            for a in minhas:
                ex.executar(
                    f"INSERT INTO {S}.carga_trabalho (uuid, id_lote_etapa, id_atividade, responsavel, geom, concluido) "
                    f"SELECT %s, %s, %s, %s, geom, true FROM {S}.carga_trabalho WHERE id = %s",
                    (novo_uuid(), le_aq, f.aq, apm, a["id"]),
                )
            le_rev = f.passagem(ex, f.etapa_aq, "em_andamento", instancia=2)
            ex.executar(f"UPDATE {S}.lote_etapa SET expor_ocorrencias = true WHERE id = %s", (le_rev,))
            ex.executar(
                f"INSERT INTO {S}.carga_trabalho (uuid, id_lote_etapa, id_atividade, responsavel, geom) "
                f"SELECT %s, %s, %s, %s, geom FROM {S}.carga_trabalho WHERE id = %s",
                (novo_uuid(), le_rev, f.aq, apm, omissao[0]["id"]),
            )
        a1, a2, a3 = omissao
        ok(f"passagem de CQ aberta com dois elementos; {len(omissao)} amostras de Omissão e {len(comissao)} de "
           f"Comissão com o avaliador ({usuario}); revisão 2 do APM com correções expostas")  # fmt: skip

        # --- o avaliador no QGIS --------------------------------------------------------------------------------
        ws = Workspace.abrir(amb.nome, usuario, "DF", raiz=os.path.join(TEMP, "aval"))
        workspaces.append(ws)
        sinc = Sincronizacao(lambda: ws, tx, alcancavel=lambda: db.alcancavel(amb))
        assert sinc.sincronizar()["estado"] == "ok"

        def plugin_de(w, eu):
            p = FeixePlugin(_Iface())
            p.amb = amb
            p.servidor = True  # as rotas são chamadas direto, sem o servidor HTTP
            p._ws = w
            p.rotulo_status = _Rotulo()
            c = Contexto(
                transacao=tx, workspace=lambda: w, online=lambda: True, eu_guardado=lambda: eu,
                publicar=lambda e, d: None,
                qgis=lambda nome, *args: {
                    "montar_camadas": lambda eu_, resp, sup, exe, gpkg: camadas.montar(
                        amb, config.authcfg_id(amb), eu_, resp, sup, exe, gpkg
                    ),
                    "cargas_mudaram": p.cargas_mudaram,
                    "focar_carga": p.focar_carga,
                    "focar_amostra": p.focar_amostra,
                }[nome](*args),
            )  # fmt: skip
            c._eu = eu
            p.ctx = c
            return p

        plugin = plugin_de(ws, {"conta": usuario, "uf": "DF", "papeis": ["avaliador"], "perfis": []})
        projeto.layersAdded.connect(plugin._ligar_edicao)
        rotas_camadas.montar(plugin.ctx)
        plugin._atualizar_cq()  # no plugin, a montagem pelo QGIS já faz (`_montar_no_qgis`)
        execucao = projeto.layerTreeRoot().findGroup("Feixe").findGroup("Execução")
        (sub,) = [g for g in execucao.children() if g.name() == f"CQ · verificar_d3a_{tag}"]
        nomes = [(n.name(), n.itemVisibilityChecked()) for n in sub.children()]
        assert nomes == [
            ("Ocorrências - Comissão", True),
            ("Amostras - Comissão", True),
            ("Ocorrências - Omissão", False),
            ("Amostras - Omissão", False),
            ("Minhas folhas", True),
        ], nomes
        ok(f"subgrupo {sub.name()}: {nomes} (só o primeiro elemento ligado)")  # fmt: skip

        am = next(c for c in camadas.camadas_amostras() if c.name() == "Amostras - Omissão")
        oc = next(c for c in camadas.camadas_do_papel("ocorrencias") if c.name() == "Ocorrências - Omissão")
        assert camadas.do_workspace(am) and am.readOnly() and not oc.readOnly() and oc.id() in plugin._edicao
        assert sorted(int(x["id"]) for x in am.getFeatures()) == sorted(a["id"] for a in omissao)
        assert isinstance(am.renderer(), QgsRuleBasedRenderer)
        regras_estilo = [r.label() for r in am.renderer().rootRule().children()]
        assert regras_estilo == ["Amostra atual", "Pendente", "Conforme", "Não conforme"], regras_estilo

        def feicao(id_carga):
            return next(am.getFeatures(f'"id" = {int(id_carga)}'))

        x = feicao(a1["id"])
        textos = {k: x[k] for k in ("status_txt", "folha_txt", "plano_txt", "progresso_txt", "ocorrencias_txt")}
        assert x["elemento"] == "Omissão" and textos["status_txt"] == "pendente", textos
        assert all(v and "Eval" not in str(v) for v in textos.values()), textos
        assert textos["plano_txt"].startswith("n = ") and " de 4 avaliadas" in textos["progresso_txt"], textos
        acoes = {a.name() for a in am.actions().actions()}
        assert acoes == {"Trabalhar nesta amostra", "Conforme", "Não conforme…"}, acoes
        ok(f"Amostras: só leitura, estilo por status e formulário sem erro: {textos}")
        assert regras.acoes_visiveis(plugin._cq)["conforme"] and plugin._cq["pendentes"] == 4, plugin._cq
        ok(f"a barra mostra as ações do avaliador ({plugin._cq})")

        # --- próxima, conforme, não conforme pela barra ------------------------------------------------------------
        r = plugin.proxima_amostra()
        primeira = camadas.amostra_atual()
        assert r["carga"]["id"] == primeira and plugin.iface.canvas.piscadas[-1][0].startswith("Amostras - "), r
        assert plugin.rotulo_status.texto.startswith("Feixe · CQ ") and "/4 amostras" in plugin.rotulo_status.texto
        ok(f"próxima amostra: #{primeira} é a atual, o mapa foi até ela e piscou; {plugin.rotulo_status.texto!r}")

        plugin.iface.barra.mensagens.clear()
        r = plugin.avaliar_amostra(None, 1)
        assert r["amostra"]["status"] == 1 and camadas.amostra_atual() not in (None, primeira), r
        assert plugin.iface.barra.mensagens[-1].startswith("Amostra conforme"), plugin.iface.barra.mensagens
        camada_1 = camadas.camada_com_amostra(primeira)
        f1 = next(camada_1.getFeatures(f'"id" = {primeira}'))
        assert int(f1["status"]) == 1 and f1["status_txt"].startswith("conforme em "), f1["status_txt"]
        ok(f"conforme pela barra: a camada releu ({f1['status_txt']}) e a atual passou para #{camadas.amostra_atual()}")

        segunda = camadas.amostra_atual()
        plugin.pedir_observacao = lambda atual="": "faltou um trecho de drenagem"
        r = plugin.nao_conforme(None)
        assert r["amostra"]["status"] == 0 and r["amostra"]["observacao"] == "faltou um trecho de drenagem", r
        plugin.pedir_observacao = lambda atual="": None
        assert plugin.nao_conforme(None) is None  # cancelar não avalia
        ok(f"não conforme com observação (#{segunda}); cancelar o diálogo não avalia nada")

        # --- ocorrência no ponto ---------------------------------------------------------------------------------
        plugin.pedir_anotacao = lambda elemento="", folha="": "trecho de drenagem omitido"
        plugin.iface.barra.mensagens.clear()
        assert plugin.ocorrencia_no_ponto(-40.0, -10.0) is None
        assert plugin.iface.barra.mensagens == [regras.FORA_DAS_AMOSTRAS], plugin.iface.barra.mensagens
        antes = sum(1 for _ in oc.getFeatures())
        r = plugin.ocorrencia_no_ponto(a3["x"], a3["y"])
        assert r["ocorrencia"]["id_carga_trabalho"] == a3["id"] and camadas.amostra_atual() == a3["id"], r
        assert sum(1 for _ in oc.getFeatures()) == antes + 1
        po = next(oc.getFeatures(f"\"uuid\" = '{r['ocorrencia']['uuid']}'"))
        assert po["folha_txt"].startswith("2534-") and po["amostra_txt"].startswith("célula "), po["amostra_txt"]
        ok(f"ocorrência no ponto: fora das amostras recusada; dentro, gravada na amostra #{a3['id']} e na camada "
           f"({po['folha_txt']} · {po['amostra_txt']})")  # fmt: skip

        # Anotação pela camada (D-127): sai do buffer e vai pela outbox.
        assert oc.startEditing()
        assert oc.changeAttributeValue(po.id(), oc.fields().indexOf("anotacao"), "drenagem omitida no trecho norte")
        plugin.iface.barra.mensagens.clear()
        assert oc.commitChanges(), oc.commitErrors()
        QgsApplication.processEvents()
        assert "Anotação gravada." in plugin.iface.barra.mensagens, plugin.iface.barra.mensagens
        with ws.leitura() as ex:
            anot = ex.um("SELECT anotacao FROM cq_inspecao WHERE uuid = ?", (r["ocorrencia"]["uuid"],))["anotacao"]
        assert anot == "drenagem omitida no trecho norte", anot
        ok("anotação editada no formulário da camada: gravada pelo caminho do plugin (outbox), não pelo OGR")

        # --- até a última: o Feixe diz que acabou e o que vem depois --------------------------------------------
        # A ocorrência fez da amostra dela a atual (pode ser a não conforme): segue da próxima pendente.
        plugin.proxima_amostra()
        while camadas.amostra_atual() is not None:
            plugin.avaliar_amostra(None, 1)
        assert regras.FIM_DAS_AMOSTRAS in plugin.iface.barra.mensagens[-1], plugin.iface.barra.mensagens[-1]
        assert plugin._cq["pendentes"] == 0 and plugin.proxima_amostra()["carga"] is None
        ok(f"última amostra avaliada: {plugin.iface.barra.mensagens[-2]!r}")

        r = sinc.sincronizar()
        assert r["estado"] == "ok" and r["pendentes"] == 0, r
        with tx() as ex:
            na_ccar = ex.todos(
                f"SELECT status FROM {S}.cq_amostra WHERE id = ANY(%s)", ([a["amostra"] for a in minhas],)
            )
            oc_ccar = ex.um(f"SELECT anotacao, id_carga_avaliada FROM {S}.cq_inspecao WHERE uuid = %s",
                            (r_uuid := po["uuid"],))  # fmt: skip
        assert sorted(x["status"] for x in na_ccar) == [0, 1, 1, 1] and oc_ccar["id_carga_avaliada"], (na_ccar, oc_ccar)
        ok("sincronizado: as quatro avaliações e a ocorrência (com a carga do APM derivada) estão na CCAR")

        # --- o APM: para ciência e correções ---------------------------------------------------------------------
        projeto.clear()
        w_apm = Workspace.abrir(amb.nome, apm, "DF", raiz=os.path.join(TEMP, "apm"))
        workspaces.append(w_apm)
        with tx() as ex:
            pull.puxar(w_apm, ex, usuario=apm)
        p2 = plugin_de(w_apm, {"conta": apm, "uf": "DF", "papeis": ["apm"], "perfis": []})
        rotas_camadas.montar(p2.ctx)
        p2._atualizar_cq()
        execucao = projeto.layerTreeRoot().findGroup("Feixe").findGroup("Execução")
        nomes = [(n.name(), n.itemVisibilityChecked()) for n in execucao.children()]
        assert nomes[0] == ("Ocorrências para ciência", True) and ("Correções a fazer", True) in nomes, nomes
        ok(f"APM: {nomes}")
        ciencia = camadas.camada_ciencia()
        (fc,) = list(ciencia.getFeatures())
        assert ciencia.readOnly() and fc["uuid"] == r_uuid and fc["anotacao"] == "drenagem omitida no trecho norte"
        assert fc["folha_txt"].startswith("2534-") and fc["responsavel"] == usuario, fc["folha_txt"]
        assert {a.name() for a in ciencia.actions().actions()} == {"Ciente"}
        assert regras.acoes_visiveis(p2._cq) == {**dict.fromkeys(regras.ACOES_AVALIADOR, False), "ciente": True}
        ok(f"Ocorrências para ciência com anotação, elemento, folha e avaliador ({fc['folha_txt']}) e a ação Ciente")

        assert p2.ciente(None) is None and ciencia.selectedFeatureIds() == [fc.id()]
        assert "Ciente de novo" in p2.iface.barra.mensagens[-1], p2.iface.barra.mensagens
        r = p2.ciente(None)
        assert r["ocorrencia"]["ciente_em"] is not None and sum(1 for _ in ciencia.getFeatures()) == 0, r
        assert p2.iface.barra.mensagens[-1].endswith("Não há mais ocorrências esperando a sua ciência.")
        with tx() as ex:
            assert push.enviar(w_apm, tx, usuario=apm)["resultados"]["aplicado"] == 1
        with tx() as ex:
            assert ex.um(f"SELECT ciente_por FROM {S}.cq_inspecao WHERE uuid = %s", (r_uuid,))["ciente_por"] == apm
        with w_apm.leitura() as ex:
            assert lg.estado_cq(ex)["ciencia"] == 0
        ok("Ciente: sem seleção mostra a primeira para ler; com ela, dá ciência, a camada relê e a CCAR recebe")
    finally:
        with contextlib.suppress(Exception):
            projeto.layersAdded.disconnect()
        projeto.clear()
        for w in workspaces:
            w.fechar()
        with tx() as ex:
            ex.executar(
                f"DELETE FROM {S}.sync_log WHERE uuid IN (SELECT uuid FROM {S}.cq_inspecao WHERE id_lote = %s "
                f"UNION SELECT a.uuid FROM {S}.cq_amostra a JOIN {S}.carga_trabalho c ON c.id = a.id_carga_trabalho "
                f"JOIN {S}.lote_etapa le ON le.id = c.id_lote_etapa WHERE le.id_lote = %s "
                f"UNION SELECT c.uuid FROM {S}.carga_trabalho c JOIN {S}.lote_etapa le ON le.id = c.id_lote_etapa "
                f"WHERE le.id_lote = %s UNION SELECT uuid FROM {S}.lote_etapa WHERE id_lote = %s)",
                (f.lote,) * 4,
            )
            ex.executar(f"DELETE FROM {S}.lote WHERE id = %s", (f.lote,))
            ex.executar(f"DELETE FROM {S}.fluxo WHERE id = %s", (f.fluxo,))
            ex.executar(f"DELETE FROM {S}.atividade WHERE id = ANY(%s)", ([f.aq, f.cq, f.cq2],))
            ex.executar(f"DELETE FROM {S}.tema WHERE id = %s", (f.tema,))


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
