import type { Preparo } from '@/lib/api'
import { lista, num, plural } from '@/lib/formato'

// Frase do que o Feixe fez sozinho depois de abrir passagens (D-109), para o aviso.
export function resumoPreparo(p?: Preparo) {
  if (!p) return ''
  const partes: string[] = []
  // CQ (D-136): os planos saem com o padrão da etapa e cada amostra sorteada é uma carga.
  // Correção de inspeção (D5): a carga é a folha inteira, e quem a receber trata as ocorrências dela.
  const correcao = p.geradas.filter((g) => g.ocorrencias != null)
  const producao = p.geradas.filter((g) => !g.planos && g.ocorrencias == null)
  const cq = p.geradas.filter((g) => g.planos)
  const total = producao.reduce((s, g) => s + g.gravadas, 0)
  if (total) partes.push(`${plural(total, 'carga gerada', 'cargas geradas')} em ${plural(producao.length, 'folha', 'folhas')}.`)
  const amostras = cq.reduce((s, g) => s + g.gravadas, 0)
  const planos = cq.reduce((s, g) => s + (g.planos ?? 0), 0)
  if (cq.length) partes.push(`CQ: ${plural(planos, 'plano de amostragem', 'planos de amostragem')} com o padrão da etapa, ${plural(amostras, 'amostra sorteada', 'amostras sorteadas')} em ${plural(cq.length, 'folha', 'folhas')}.`)
  if (correcao.length)
    partes.push(
      `Correção de inspeção: ${correcao.length === 1 ? `a ${correcao[0].folha_revisao} vai` : `${plural(correcao.length, 'folha vai', 'folhas vão')}`} inteira a quem você distribuir, com ${plural(
        correcao.reduce((s, g) => s + (g.ocorrencias ?? 0), 0),
        'ocorrência a tratar',
        'ocorrências a tratar',
      )}.`,
    )
  const semAtividade = p.iniciadas.filter((i) => !i.nada_a_tratar)
  const nada = p.iniciadas.filter((i) => i.nada_a_tratar)
  if (semAtividade.length) partes.push(`${lista([...new Set(semAtividade.map((i) => i.etapa))])} sem atividade: já em andamento em ${plural(semAtividade.length, 'folha', 'folhas')}.`)
  if (nada.length) partes.push(`Correção de inspeção sem ocorrência a tratar: ${plural(nada.length, 'folha já está', 'folhas já estão')} em Esperando você.`)
  if (p.avisos.length) partes.push(`Sem cargas: ${lista(p.avisos.slice(0, 3).map((a) => `${a.folha_revisao} (${a.aviso})`))}${p.avisos.length > 3 ? ` e mais ${num(p.avisos.length - 3)}` : ''}.`)
  if (p.erro) partes.push(`As cargas não foram geradas: ${p.erro}.`)
  return partes.join(' ')
}

// Passagens que ganharam cargas: é o que vai para o Distribuir.
export const comCargas = (p?: Preparo) => new Set((p?.geradas ?? []).map((g) => g.id_lote_etapa))
