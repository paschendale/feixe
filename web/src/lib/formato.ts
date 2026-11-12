// Formatos de número e data em pt-BR, no fuso de quem está olhando (o banco guarda UTC).
export const num = (n: number) => n.toLocaleString('pt-BR')

export function dataHora(iso: string | null) {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('pt-BR', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })
}

export function mesAno(iso: string | null) {
  if (!iso) return ''
  return new Date(iso).toLocaleDateString('pt-BR', { month: 'long', year: 'numeric' })
}

export const plural = (n: number, um: string, varios: string) => `${num(n)} ${n === 1 ? um : varios}`
