"""Regras e textos da barra do Feixe que não dependem do QGIS (D3c), para testar sem ele: que ações do CQ aparecem,
o texto da barra de status e as mensagens depois de avaliar, registrar ocorrência e dar ciência."""

from __future__ import annotations

from typing import Dict, Optional

# Ações da barra (e do menu Complementos > Feixe) que só aparecem para quem tem o que fazer com elas.
ACOES_AVALIADOR = ("proxima_amostra", "conforme", "nao_conforme", "ocorrencia")
ACAO_CIENTE = "ciente"
ACOES_CORRECAO = ("proxima_ocorrencia", "tratada")  # correção de inspeção (D5)
ACOES_EXECUCAO = ("proxima", "pular", "concluir")  # as cargas de produção (B2)


def acoes_visiveis(estado: Optional[Dict], modo: Optional[str] = None) -> Dict[str, bool]:
    """As do avaliador só para quem tem amostras em passagens abertas (avaliadas ou não: trocar a avaliação e
    registrar ocorrência valem enquanto a passagem está aberta) e está no modo Avaliar, com o grupo Controle de
    qualidade ligado (D-148); as da execução (cargas, Ciente e correção) só no modo Executar, com o grupo Execução
    ligado (D-150); o Ciente só com ocorrência à espera da ciência. Sem o grupo Feixe (modo None), nenhuma."""
    estado = estado or {}
    avaliador = (estado.get("amostras") or 0) > 0 and modo == "cq"
    execucao = modo == "execucao"
    vis = dict.fromkeys(ACOES_AVALIADOR, avaliador)
    vis.update(dict.fromkeys(ACOES_EXECUCAO, execucao))
    vis[ACAO_CIENTE] = (estado.get("ciencia") or 0) > 0 and execucao
    # Correção de inspeção: para quem está com uma folha na correção aberta (mesmo com tudo tratado: desmarcar vale
    # enquanto a etapa está aberta).
    for chave in ACOES_CORRECAO:
        vis[chave] = (estado.get("correcao") or 0) > 0 and execucao
    return vis


def texto_status(progresso: Optional[Dict], cq: bool = False) -> str:
    """Barra de status do QGIS: "Feixe · 2534-1 · 35/93" nas cargas, "Feixe · CQ 2534-1 · 7/20 amostras" no CQ e
    "Feixe · Correção 2534-3 · 12/40 tratadas" na correção de inspeção (o andamento traz `tratadas`)."""
    if not progresso:
        return "Feixe"
    p = progresso
    if "tratadas" in p:
        return f"Feixe · Correção {p['folha_revisao']} · {p['tratadas']}/{p['total']} tratadas"
    if cq:
        return f"Feixe · CQ {p['folha_revisao']} · {p['concluidas']}/{p['total']} amostras"
    return f"Feixe · {p['folha_revisao']} · {p['concluidas']}/{p['total']}"


STATUS = {1: "conforme", 0: "não conforme"}

FIM_DAS_AMOSTRAS = (
    "Você avaliou todas as suas amostras. Agora é com o supervisor: ele vê o resultado do plano no Feixe e decide o "
    "próximo passo da folha."
)


def mensagem_avaliada(r: Dict) -> str:
    """Depois de avaliar: o que ficou e para onde o Feixe levou (a próxima amostra) ou que acabou e o que vem depois."""
    a = r.get("amostra") or {}
    p = r.get("progresso") or {}
    partes = [f"Amostra {STATUS.get(a.get('status'), 'avaliada')}"]
    if a.get("elemento"):
        partes.append(a["elemento"])
    if p:
        partes.append(f"{p['folha_revisao']} {p['concluidas']}/{p['total']}")
    texto = " · ".join(partes) + "."
    proxima = r.get("proxima")
    if proxima and proxima.get("amostra"):
        prox = proxima["amostra"]
        return f"{texto} Próxima: {prox.get('elemento') or 'amostra'} na {prox.get('folha_revisao')}."
    if proxima:
        return f"{texto} Indo para a próxima amostra."
    return f"{texto} {FIM_DAS_AMOSTRAS}"


def mensagem_ocorrencia(r: Dict) -> str:
    """Depois de registrar: a ocorrência e, com a amostra ainda pendente, o lembrete da decisão (que é do avaliador)."""
    o = r.get("ocorrencia") or {}
    a = r.get("amostra") or {}
    texto = f"Ocorrência registrada · {o.get('elemento') or 'sem elemento'} · {o.get('folha_revisao') or ''}".rstrip(
        " ·"
    )
    if a and a.get("status") is None:
        return f"{texto}. Ao terminar esta amostra, marque Conforme ou Não conforme."
    return f"{texto}."


def mensagem_ciente(o: Dict, restantes: int) -> str:
    texto = f"Ciente · {o.get('elemento') or 'ocorrência'} · {o.get('folha_revisao') or ''}".rstrip(" ·") + "."
    if restantes:
        return f"{texto} {'Falta' if restantes == 1 else 'Faltam'} {restantes} para dar ciência."
    return f"{texto} Não há mais ocorrências esperando a sua ciência."


FORA_DAS_AMOSTRAS = (
    "O ponto ficou fora das suas amostras: a ocorrência vai dentro de uma amostra sua de uma passagem de CQ aberta. "
    "Clique dentro da amostra (contorno em Amostras)."
)


# --- correção de inspeção (D5) ----------------------------------------------------------------------------------------

FIM_DA_CORRECAO = (
    "Todas as ocorrências da folha estão tratadas: a sua parte na correção terminou. Agora é com o supervisor: a folha "
    "aparece para ele em Esperando você, e ele decide o próximo passo."
)


def mensagem_tratada(r: Dict) -> str:
    """Depois de marcar (ou desmarcar): o andamento da folha e a próxima, ou que a folha terminou e quem decide."""
    o = r.get("ocorrencia") or {}
    p = r.get("progresso") or {}
    feito = "Tratada" if o.get("tratado") else "Tratamento desfeito"
    partes = [feito, o.get("elemento") or "ocorrência"]
    if p:
        partes.append(f"{p['folha_revisao']} {p['tratadas']}/{p['total']}")
    texto = " · ".join(partes) + "."
    f = r.get("fila")
    if f:
        texto += f" A próxima folha da sua fila é a {f['folha_revisao']} ({f['atribuidas']} cargas), já com você."
    if p and not p.get("pendentes"):
        return f"{texto} {FIM_DA_CORRECAO}"
    prox = r.get("proxima")
    if prox:
        return f"{texto} Próxima: {prox.get('elemento') or 'ocorrência'} na {prox.get('folha_revisao')}."
    return texto


def mensagem_ocorrencia_atual(o: Dict, p: Optional[Dict]) -> str:
    """Ao chegar numa ocorrência (Próxima ocorrência): o que corrigir ali, para a pessoa ler sem abrir o formulário."""
    anotacao = o.get("anotacao") or "(sem anotação)"
    onde = f" · {p['tratadas']}/{p['total']} tratadas" if p else ""
    elemento = o.get("elemento") or "Ocorrência"
    return f"{elemento} ({o.get('folha_revisao')}): {anotacao}{onde}. Corrija e marque Tratada."
