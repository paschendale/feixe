import type { Preparo } from '@/lib/api'
import { lista, num, plural } from '@/lib/formato'

// Frase do que o Feixe fez sozinho depois de abrir passagens (D-109), para o aviso.
export function resumoPreparo(p?: Preparo) {
  if (!p) return ''
  const partes: string[] = []
  // CQ (D-136): os planos saem com o padrão da etapa e cada amostra sorteada é uma carga.
  const producao = p.geradas.filter((g) => !g.planos)
  const cq = p.geradas.filter((g) => g.planos)
  const total = producao.reduce((s, g) => s + g.gravadas, 0)
  if (total) partes.push(`${plural(total, 'carga gerada', 'cargas geradas')} em ${plural(producao.length, 'folha', 'folhas')}.`)
  const amostras = cq.reduce((s, g) => s + g.gravadas, 0)
  const planos = cq.reduce((s, g) => s + (g.planos ?? 0), 0)
  if (cq.length) partes.push(`CQ: ${plural(planos, 'plano de amostragem', 'planos de amostragem')} com o padrão da etapa, ${plural(amostras, 'amostra sorteada', 'amostras sorteadas')} em ${plural(cq.length, 'folha', 'folhas')}.`)
  if (p.iniciadas.length) partes.push(`${lista([...new Set(p.iniciadas.map((i) => i.etapa))])} sem atividade: já em andamento em ${plural(p.iniciadas.length, 'folha', 'folhas')}.`)
  if (p.avisos.length) partes.push(`Sem cargas: ${lista(p.avisos.slice(0, 3).map((a) => `${a.folha_revisao} (${a.aviso})`))}${p.avisos.length > 3 ? ` e mais ${num(p.avisos.length - 3)}` : ''}.`)
  if (p.erro) partes.push(`As cargas não foram geradas: ${p.erro}.`)
  return partes.join(' ')
}

// Passagens que ganharam cargas: é o que vai para o Distribuir.
export const comCargas = (p?: Preparo) => new Set((p?.geradas ?? []).map((g) => g.id_lote_etapa))
