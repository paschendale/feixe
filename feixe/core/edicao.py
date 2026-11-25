"""Edição das camadas da execução pelo QGIS (C4): a tabela de atributos e o formulário de Minhas cargas.

A camada abre a `carga_trabalho` do workspace pelo OGR. Se o commit do QGIS gravasse por ali, a linha mudaria sem
item na outbox e sem as regras da execução (D-94), e a mudança nunca chegaria à CCAR. Então, no `beforeCommitChanges`
(antes de o QGIS mandar o buffer ao OGR), o plugin:

1. lê do buffer de edição o que a pessoa mudou em `concluido`, por carga (`ler`);
2. esvazia o buffer pela pilha de desfazer (`esvaziar`): o commit segue sem nada a gravar, e o OGR não escreve;
3. aplica cada mudança pelo mesmo caminho da barra (`rotas.cargas.editar`: concluir ou desfazer no workspace, com a
   outbox na mesma transação, as regras e a fila), e a recusa de uma (etapa encerrada, mais de 24 h, carga de outra
   pessoa) vira aviso na barra de mensagens, sem gravar nada dela;
4. depois do commit, recarrega as camadas do workspace, que mostram o que ficou valendo.

Geometria, outros campos, feições novas ou apagadas: o formulário e a tabela não deixam editar, mas a calculadora de
campos e as ferramentas de edição de geometria deixariam; tudo isso também sai do buffer, com um aviso. Se algo
escapasse, os gatilhos de guarda do workspace (`sync/esquema.py`) recusariam a escrita do OGR no próprio arquivo: a
garantia de que nada muda o workspace sem passar pela outbox não depende deste módulo.

Roda na thread principal (é chamado pelo sinal da camada).
"""

from __future__ import annotations

from typing import Dict, Tuple

from qgis.core import QgsVectorLayer
from qgis.PyQt.QtCore import QVariant

CAMPO = "concluido"


def _valor(v):
    if isinstance(v, QVariant):
        return None if v.isNull() else v.value()
    return v


def ler(camada: QgsVectorLayer) -> Tuple[Dict[int, bool], bool]:
    """O que o buffer de edição muda: {id da carga: concluído} e se há mais alguma mudança (outro campo, geometria,
    feição nova ou apagada)."""
    eb = camada.editBuffer()
    if eb is None:
        return {}, False
    i_concluido = camada.fields().indexOf(CAMPO)
    desejadas: Dict[int, bool] = {}
    outras = False
    for fid, atributos in eb.changedAttributeValues().items():
        for i, v in atributos.items():
            if i != i_concluido:
                outras = True
                continue
            f = camada.getFeature(fid)
            id_carga = _valor(f["id"]) if f.isValid() else None
            if id_carga is not None:
                desejadas[int(id_carga)] = bool(_valor(v))
    outras = outras or bool(
        eb.changedGeometries() or eb.addedFeatures() or eb.deletedFeatureIds() or eb.addedAttributes()
        or eb.deletedAttributeIds()
    )  # fmt: skip
    return desejadas, outras


def esvaziar(camada: QgsVectorLayer) -> bool:
    """Desfaz tudo o que está no buffer (cada mudança do QGIS é um comando na pilha de desfazer da camada). Volta
    True se o buffer ficou vazio."""
    camada.undoStack().setIndex(0)
    eb = camada.editBuffer()
    return eb is None or not eb.isModified()
