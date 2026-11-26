"""Funções da execução sobre o workspace local (D-111, C1).

Mesmos nomes, mesmos parâmetros e o mesmo formato de retorno de `core/dados/cargas.py` e `core/dados/filas.py`, para
as rotas da execução trocarem de origem (CCAR -> workspace) mudando só o import e o executor (C3). Não é tradução do
SQL da CCAR: é uma implementação própria em SQLite, só do que a execução precisa (minhas cargas, concluir, desfazer,
próxima, pular e a fila), com as mesmas regras de negócio. A supervisão continua só na CCAR.

O executor é o `sync.workspace.ExecutorLocal` (duck typing, sem importar o pacote `sync`): além de `todos`/`um`/
`executar`, ele dá `usuario` (o `current_user` da CCAR), `uf`, `agora` (hora da ação) e `atualizar`/`inserir`, que
gravam a linha e o item da outbox na mesma transação. Toda escrita daqui passa por eles.

Datas voltam como `datetime` com fuso (UTC) e booleanos como `bool`, como o psycopg2 devolve, para o JSON das rotas
sair igual.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Dict, Iterable, Optional

ABERTAS = ("pendente", "em_andamento")
SQL_ABERTAS = "('pendente', 'em_andamento')"


def rotulo(l: str = "l", le: str = "le") -> str:  # noqa: E741
    """`mapcartacomp.f_rotulo` em SQLite: "2534-3" na folha, só o nome no lote livre."""
    return f"(CASE WHEN {l}.tipo = 'folha' THEN {l}.nome || '-' || coalesce({le}.revisao, 0) ELSE {l}.nome END)"


def data(v: Optional[str]) -> Optional[dt.datetime]:
    if v is None:
        return None
    t = v.replace("Z", "+00:00")
    d = dt.datetime.fromisoformat(t)
    return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)


def converter(linha: Optional[Dict[str, Any]], datas: Iterable[str] = (), bools: Iterable[str] = ()):
    """Datas (texto ISO) para datetime e 0/1 para bool, nas colunas indicadas."""
    if linha is None:
        return None
    for c in datas:
        if c in linha:
            linha[c] = data(linha[c])
    for c in bools:
        if c in linha and linha[c] is not None:
            linha[c] = bool(linha[c])
    return linha


def carga_da_folha(c: str = "c") -> str:
    """Condição SQL (SQLite) da carga que é a folha inteira na correção de inspeção (D5): numa passagem de correção, a
    carga de atividade que não é pela grade. Ela não se conclui à mão: conclui quando todas as ocorrências da folha
    estão tratadas (como `mapcartacomp.f_correcao_derivar_um`). `c` vazio: colunas sem prefixo (filtro de camada)."""
    p = f"{c}." if c else ""
    return (
        f"({p}id_lote_etapa IN (SELECT le_f.id FROM lote_etapa le_f JOIN fluxo_etapa fe_f "
        "ON fe_f.id = le_f.id_fluxo_etapa WHERE fe_f.fase = 'correcao_inspecao') "
        f"AND {p}id_atividade IN (SELECT a_f.id FROM atividade a_f WHERE coalesce(a_f.geracao, 'manual') <> 'grade'))"
    )
