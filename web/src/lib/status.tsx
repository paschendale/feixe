import type { StatusNacional } from '@/lib/api'

// Status nacional: o que a CCAR vê. Cores do protótipo (escala do azul-aço ao azul IBGE; devolvida em vermelho).
export const STATUS: Record<StatusNacional, { rotulo: string; cor: string }> = {
  PLANEJADA: { rotulo: 'Planejada', cor: '#D6E0EE' },
  EM_PRODUCAO: { rotulo: 'Em produção', cor: '#9DB4D8' },
  EM_CQ: { rotulo: 'Em CQ', cor: '#7492C1' },
  ENTREGUE_GCQ: { rotulo: 'Entregue à GCQ', cor: '#3A66A3' },
  CONCLUIDA: { rotulo: 'Concluída', cor: '#004182' },
  DEVOLVIDA: { rotulo: 'Devolvida', cor: '#C8443A' },
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
