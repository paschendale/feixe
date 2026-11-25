"""Camada de acesso aos dados do Feixe.

Toda leitura e escrita das rotas passa por funções deste pacote. Elas recebem um `Executor` e não sabem o que há do
outro lado: na fase B é uma transação na CCAR (`core.db.transacao`); na fase C passa a ser o workspace local com a
outbox. Trocar a origem dos dados é trocar o executor, não as rotas.

Regras que valem para todas as funções daqui:
- uuid de linha nova é gerado no plugin (`novo_uuid`), nunca no banco;
- `atualizado_por` e `criado_por` ficam com os padrões do banco (current_user = conta conectada);
- SQL compatível com PostgreSQL 9.6.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any, Dict, List, Optional


class Executor:
    """Interface mínima que as funções de dados usam. Implementações: `ExecutorPg` e os falsos dos testes."""

    def todos(self, sql: str, params: Optional[tuple] = None) -> List[Dict[str, Any]]:
        raise NotImplementedError

    def um(self, sql: str, params: Optional[tuple] = None) -> Optional[Dict[str, Any]]:
        linhas = self.todos(sql, params)
        return linhas[0] if linhas else None

    def executar(self, sql: str, params: Optional[tuple] = None) -> int:
        """Comando sem retorno de linhas; devolve o número de linhas afetadas."""
        raise NotImplementedError


class ExecutorPg(Executor):
    """Executor sobre um cursor psycopg2 de dicionários (RealDictCursor), dentro de uma transação aberta."""

    def __init__(self, cur):
        self.cur = cur

    def todos(self, sql, params=None):
        self.cur.execute(sql, params)
        if self.cur.description is None:
            return []
        return [dict(r) for r in self.cur.fetchall()]

    def executar(self, sql, params=None):
        self.cur.execute(sql, params)
        return self.cur.rowcount


class ErroDados(Exception):
    """Recusa de regra de negócio com mensagem para o usuário. A API devolve como 409 (ou o status indicado)."""

    def __init__(self, mensagem: str, status: int = 409):
        super().__init__(mensagem)
        self.mensagem = mensagem
        self.status = status


def novo_uuid() -> str:
    return str(uuid.uuid4())


def fuso(nome: str) -> dt.tzinfo:
    """O fuso de quem olha (IANA). O Python do QGIS no Windows pode não ter a base de fusos (`tzdata`): aí vale o fuso
    da própria estação, que é o de quem está diante dela."""
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(nome)
    except Exception:  # noqa: BLE001
        return dt.datetime.now().astimezone().tzinfo
