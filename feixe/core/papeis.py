"""Identidade e papéis do usuário no Feixe, só a partir do SGBC (mapcartctrl) e de mapcartacomp.usuario_feixe.

Nenhuma role do banco é consultada (D-57): quem é APM, avaliador, supervisor ou consulta sai do perfil do usuário
no projeto em `mapcartctrl.t_prd_perfil_usuarioprojeto`, gravado pelo SGBC; gerente e equipe são do Feixe.

- Perfis do SGBC: S = supervisor, O = APM, V = avaliador, C = consulta. O perfil I (iniciador) não tem papel no
  Feixe e aparece só como perfil bruto.
- UF (unidade) = `t_usuario.dsc_lotacao`, quando é uma sigla de duas letras. A lotação RJ é a unidade da GBC e é
  tratada como qualquer outra (D-76). Lotação vazia ou fora do padrão dá UF nula, e o usuário continua sendo
  identificado.
- Elegibilidade da conta (P-16): ativa, que não é conta de sistema nem super. É a única regra; quem precisar saber se
  alguém pode ser responsável por carga usa `elegivel`. Conta inelegível não recebe papel no Feixe.

Sem QGIS e sem banco: as consultas chegam por uma função `consultar(sql, params) -> [dict]`, como na API.
"""

from __future__ import annotations

import re
from typing import Callable, Dict, List, Optional

PAPEL_DO_PERFIL = {"S": "supervisor", "O": "apm", "V": "avaliador", "C": "consulta"}

# Do papel mais amplo ao mais restrito: o primeiro que a pessoa tem é o que o cabeçalho mostra.
PRECEDENCIA = ("gerente", "supervisor", "avaliador", "apm", "consulta")

ROTULO = {
    "gerente": "Gerente",
    "supervisor": "Supervisor",
    "avaliador": "Avaliador",
    "apm": "APM",
    "consulta": "Consulta",
}

_UF = re.compile(r"^[A-Z]{2}$")

Consultar = Callable[[str, Optional[tuple]], List[Dict]]

SQL_USUARIO = (
    "SELECT u.cod_usuario, u.nom_contausuario, u.nom_usuario, u.num_siape, u.dsc_lotacao, "
    "u.ind_contaativa, u.ind_contasistema, u.ind_contasuper "
    "FROM mapcartctrl.t_usuario u WHERE u.nom_contausuario = coalesce(%s, current_user)"
)
SQL_CONTA_ATUAL = "SELECT current_user AS conta"
SQL_PERFIS = (
    "SELECT p.cd_projeto AS cod_projeto, pr.nom_projeto AS projeto, p.cd_perfil AS perfil "
    "FROM mapcartctrl.t_prd_perfil_usuarioprojeto p "
    "JOIN mapcartctrl.t_projeto pr ON pr.cod_projeto = p.cd_projeto "
    "WHERE p.cd_usuario = %s ORDER BY pr.nom_projeto"
)
SQL_FEIXE = "SELECT equipe, gerente, ativo FROM mapcartacomp.usuario_feixe WHERE usuario = %s"


def elegivel(conta: Optional[Dict]) -> bool:
    """Regra única de elegibilidade (P-16): conta ativa, que não é de sistema nem super. Nulo conta como não."""
    if not conta:
        return False
    return conta.get("ind_contaativa") is True and not conta.get("ind_contasistema") and not conta.get("ind_contasuper")


def uf_da_lotacao(dsc_lotacao: Optional[str]) -> Optional[str]:
    """'DF' -> 'DF', ' rj ' -> 'RJ' (GBC), None ou fora do padrão -> None."""
    if dsc_lotacao is None:
        return None
    valor = str(dsc_lotacao).strip().upper()
    return valor if _UF.match(valor) else None


def papel_do_perfil(perfil: Optional[str]) -> Optional[str]:
    return PAPEL_DO_PERFIL.get((perfil or "").strip().upper())


def principal(papeis) -> Optional[str]:
    for p in PRECEDENCIA:
        if p in papeis:
            return p
    return None


def montar(conta: str, usuario: Optional[Dict], perfis: List[Dict], feixe: Optional[Dict]) -> Dict:
    """Junta o que vem do SGBC e do Feixe no objeto que a API devolve em GET /api/eu."""
    pode = elegivel(usuario)  # conta inelegível não recebe papel nenhum, nem o de gerente
    feixe_ativo = bool(feixe) and feixe.get("ativo") is not False
    gerente = pode and feixe_ativo and feixe.get("gerente") is True
    por_projeto = []
    papeis = set()
    for p in perfis:
        papel = papel_do_perfil(p.get("perfil"))
        por_projeto.append(
            {
                "cod_projeto": p.get("cod_projeto"),
                "projeto": p.get("projeto"),
                "perfil": (p.get("perfil") or "").strip() or None,
                "papel": papel,
            }
        )
        if papel and pode:
            papeis.add(papel)
    if gerente:
        papeis.add("gerente")
    lista = [p for p in PRECEDENCIA if p in papeis]
    papel = principal(papeis)
    return {
        "conta": conta,
        "cadastrada": usuario is not None,
        "nome": (usuario or {}).get("nom_usuario") or conta,
        "siape": (usuario or {}).get("num_siape"),
        "lotacao": (usuario or {}).get("dsc_lotacao"),
        "uf": uf_da_lotacao((usuario or {}).get("dsc_lotacao")),
        "elegivel": pode,
        "perfis": por_projeto,
        "papeis": lista,
        "papel": papel,
        "papel_rotulo": ROTULO.get(papel, "Sem papel"),
        "gerente": gerente,
        "equipe": (feixe or {}).get("equipe") if feixe_ativo else None,
    }


def carregar(consultar: Consultar, conta: Optional[str] = None) -> Dict:
    """Identidade e papéis de uma conta (padrão: a conta conectada ao banco, current_user)."""
    if conta is None:
        conta = consultar(SQL_CONTA_ATUAL, ())[0]["conta"]
    linhas = consultar(SQL_USUARIO, (conta,))
    usuario = linhas[0] if linhas else None
    perfis = consultar(SQL_PERFIS, (usuario["cod_usuario"],)) if usuario else []
    feixe_linhas = consultar(SQL_FEIXE, (conta,))
    return montar(conta, usuario, perfis, feixe_linhas[0] if feixe_linhas else None)
