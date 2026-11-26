import type { StatusNacional } from '@/lib/api'

// Status nacional: o que a CCAR vê. Escala do azul-aço ao azul IBGE, devolvida em vermelho (tokens --dado-status-*).
// `escuro`: o texto por cima da cor vai em branco.
export const STATUS: Record<StatusNacional, { rotulo: string; cor: string; escuro?: boolean }> = {
  PLANEJADA: { rotulo: 'Planejada', cor: 'var(--dado-status-planejada)' },
  EM_PRODUCAO: { rotulo: 'Em produção', cor: 'var(--dado-status-producao)' },
  EM_CQ: { rotulo: 'Em CQ', cor: 'var(--dado-status-cq)', escuro: true },
  ENTREGUE_GCQ: { rotulo: 'Entregue à GCQ', cor: 'var(--dado-status-gcq)', escuro: true },
  CONCLUIDA: { rotulo: 'Concluída', cor: 'var(--dado-status-concluida)', escuro: true },
  DEVOLVIDA: { rotulo: 'Devolvida', cor: 'var(--dado-status-devolvida)', escuro: true },
}

export const SITUACAO: Record<string, string> = {
  pendente: 'a iniciar',
  em_andamento: 'em andamento',
  concluida: 'concluída',
  pulada: 'pulada',
}

export function Status({ s }: { s: StatusNacional }) {
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap">
      <span className="size-2 rounded-full" style={{ background: STATUS[s].cor }} />
      {STATUS[s].rotulo}
    </span>
  )
}
