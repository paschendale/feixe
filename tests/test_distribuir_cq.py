"""D-147: a partilha das amostras de CQ entre avaliadores, sem banco (maiores restos e repartir)."""

from __future__ import annotations

from feixe.core.dados.distribuir_cq import maiores_restos, repartir


def _amostras(elementos, por_elemento, folhas=("2534-1",)):
    out, i = [], 0
    for e in elementos:
        for f in folhas:
            for g in range(por_elemento):
                i += 1
                out.append({"id": i, "id_lote_etapa": f, "id_atividade": e, "folha_revisao": f,
                            "geocodigo": f"G{g:03d}", "responsavel": None, "concluido": False})  # fmt: skip
    return out


def test_maiores_restos():
    assert maiores_restos(20, [("a", 50), ("b", 30), ("c", 20)]) == {"a": 10, "b": 6, "c": 4}
    assert maiores_restos(10, [("a", 1), ("b", 1), ("c", 1)]) == {"a": 4, "b": 3, "c": 3}  # empate: a ordem
    assert maiores_restos(7, [("a", 2), ("b", 0)]) == {"a": 7, "b": 0}
    assert maiores_restos(0, [("a", 1)]) == {"a": 0}
    r = maiores_restos(74, [("a", 37.0), ("b", 18.5), ("c", 18.5)])
    assert sum(r.values()) == 74 and r["a"] == 37


def test_fatia_de_todos_os_elementos_em_blocos_continuos():
    amostras = _amostras([1, 2, 3], 8, folhas=("2534-1", "2535-1"))  # 16 por elemento, duas folhas juntas
    novo = repartir(amostras, [("ana", 3), ("bia", 1)])
    for e in (1, 2, 3):
        do_elem = [a for a in amostras if a["id_atividade"] == e]
        donos = [novo[a["id"]] for a in do_elem]
        assert donos.count("ana") == 12 and donos.count("bia") == 4
        # Blocos contínuos na ordem da folha e da grade: primeiro tudo de uma pessoa, depois da outra.
        assert donos == ["ana"] * 12 + ["bia"] * 4


def test_redistribuir_mantem_o_que_cada_um_tem_e_as_avaliadas():
    amostras = _amostras([1], 12)
    for a in amostras[:6]:
        a["responsavel"] = "ana"
    for a in amostras[6:]:
        a["responsavel"] = "bia"
    for a in amostras[:4]:
        a["concluido"] = True  # ana já avaliou 4
    # Entra a caio, partes iguais: 4 para cada. Ana fica com as 4 avaliadas; bia mantém 4 das 6; caio recebe 4.
    novo = repartir(amostras, [("ana", 1), ("bia", 1), ("caio", 1)])
    assert all(a["id"] not in novo for a in amostras[:4])  # avaliadas não mudam de mão
    final = [novo.get(a["id"], a["responsavel"]) for a in amostras]
    assert (final.count("ana"), final.count("bia"), final.count("caio")) == (4, 4, 4)
    assert sum(1 for a in amostras[6:] if novo[a["id"]] == "bia") == 4  # bia não troca as suas por outras


def test_quem_avaliou_alem_da_cota_nao_perde_nada():
    amostras = _amostras([1], 10)
    for a in amostras[:6]:
        a["responsavel"], a["concluido"] = "ana", True
    novo = repartir(amostras, [("ana", 1), ("bia", 1)])  # cota 5 e 5, mas ana já avaliou 6
    assert [novo[a["id"]] for a in amostras[6:]] == ["bia"] * 4


def test_quem_sai_da_divisao_perde_as_pendentes():
    amostras = _amostras([1], 6)
    for a in amostras:
        a["responsavel"] = "ana"
    amostras[0]["concluido"] = True
    novo = repartir(amostras, [("bia", 1)])
    assert amostras[0]["id"] not in novo and [novo[a["id"]] for a in amostras[1:]] == ["bia"] * 5


def test_quem_executou_a_folha_fica_so_fora_dela():
    # Duas folhas (passagens 1 e 2), um elemento, 8 amostras em cada; a ana executou a folha 1.
    amostras = []
    for le, f in ((1, "2534-1"), (2, "2535-1")):
        for g in range(8):
            amostras.append({"id": len(amostras) + 1, "id_lote_etapa": le, "id_atividade": 1, "folha_revisao": f,
                             "geocodigo": f"G{g:03d}", "responsavel": None, "concluido": False})  # fmt: skip
    novo = repartir(amostras, [("ana", 1), ("bia", 1)], {"ana": {1}})
    assert all(novo[a["id"]] == "bia" for a in amostras if a["id_lote_etapa"] == 1)
    assert all(novo[a["id"]] == "ana" for a in amostras if a["id_lote_etapa"] == 2)  # cota 8 e 8, cada um na sua
    # Só a ana: a folha 1 fica sem avaliador.
    so = repartir(amostras, [("ana", 1)], {"ana": {1}})
    assert all(so[a["id"]] is None for a in amostras if a["id_lote_etapa"] == 1)
    assert all(so[a["id"]] == "ana" for a in amostras if a["id_lote_etapa"] == 2)
