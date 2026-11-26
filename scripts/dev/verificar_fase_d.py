#!/usr/bin/env python3
"""Verificação headless da fase D contra o banco de dev, sem abrir o QGIS. Cada item acrescenta a sua seção.

Uso (Mac, com o QGIS-LTR):
    /Applications/QGIS-LTR.app/Contents/MacOS/bin/python3 scripts/dev/verificar_fase_d.py [d3a ...]

Sem argumentos roda todas as seções. Lê o banco de config/ambientes.json (dev) e o usuário e a senha de FEIXE_CCAR no
.dev.env da raiz. Usa perfil do QGIS, banco de autenticação e workspaces temporários, apagados no fim. A CCAR
inalcançável é simulada pelo próprio plugin (`FEIXE_DEV_SEM_CCAR=1`, só no ambiente dev): nenhum container é parado.
Tudo o que grava no banco é apagado no fim de cada seção.
"""

from __future__ import annotations

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
