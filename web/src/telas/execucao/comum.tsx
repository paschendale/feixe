import { useState } from 'react'
import { Play } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { COR } from '@/components/painel'
import type { Carga, Passagem } from '@/lib/api'
import { useAvisar } from '@/lib/avisos'
import { FUSO } from '@/lib/formato'
import { useSessao } from '@/lib/sessao'
import { enviar, useApi } from '@/lib/useApi'

export const ABERTAS = ['pendente', 'em_andamento']
export const pendentesDe = (p: Passagem) => p.total - p.concluidas

// Workspace ainda sem o primeiro pull (C3): no lugar da lista vazia, o aviso de que as cargas estão chegando.
export function Preparando() {
  return (
    <p className="text-sm text-muted-foreground" role="status">
      Preparando seu espaço de trabalho: o Feixe está trazendo as suas cargas da CCAR. Já, já fica pronto.
    </p>
  )
}

// Minhas conclusões por dia (fuso de quem olha), para as barras do Início e da Execução.
export function usePorDia() {
  const { dados } = useApi<{ por_dia: { dia: string; n: number }[] }>(`/api/painel/execucao?fuso=${encodeURIComponent(FUSO)}`, ['carga'])
  const mapa = new Map((dados?.por_dia ?? []).map((d) => [d.dia, d.n]))
  const hoje = new Date()
  const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
  const dias = Array.from({ length: 10 }, (_, i) => {
    const d = new Date(hoje.getFullYear(), hoje.getMonth(), hoje.getDate() - (9 - i))
    return { dia: iso(d), rotulo: d.toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' }), n: mapa.get(iso(d)) ?? 0 }
  })
  return { dias, hoje: dias[9].n, carregado: !!dados }
}

// Barras das minhas conclusões por dia; a de hoje em azul IBGE.
export function Producao({ dias, altura = 96 }: { dias: { dia: string; rotulo: string; n: number }[]; altura?: number }) {
  const max = Math.max(1, ...dias.map((d) => d.n))
  const descricao = dias.map((d) => `${d.rotulo}: ${d.n}`).join(', ')
  return (
    <div className="flex flex-col gap-1.5">
      <div role="img" aria-label={`Cargas concluídas por dia, ${descricao}`} className="flex items-end gap-1.5 border-b border-[#DCE2EA]" style={{ height: altura }}>
        {dias.map((d, i) => (
          <div
            key={d.dia}
            title={`${d.rotulo}: ${d.n}`}
            className="flex-1 rounded-t-[3px]"
            style={{ height: `${(100 * d.n) / max}%`, background: i === dias.length - 1 ? COR.concluida : COR.comAlguem }}
          />
        ))}
      </div>
      <div className="flex justify-between text-[11px] text-muted-foreground">
        <span>{dias[0]?.rotulo}</span>
        <span>hoje</span>
      </div>
    </div>
  )
}

// "Continuar no QGIS": leva o QGIS à próxima carga pendente (nesta folha, se dada), como o botão da barra.
export function Continuar({ idLote, disabled, grande }: { idLote?: number; disabled?: boolean; grande?: boolean }) {
  const avisar = useAvisar()
  const { conectado } = useSessao()
  const [ocupado, setOcupado] = useState(false)
  async function ir() {
    setOcupado(true)
    try {
      const r = await enviar<{ carga: Carga | null }>('/api/cargas/proxima', idLote ? { id_lote: idLote } : {})
      avisar(r.carga ? `Carga atual no QGIS: ${r.carga.folha_revisao}` : 'Você não tem carga pendente aqui.')
    } catch (e) {
      avisar((e as Error).message, 'erro')
    } finally {
      setOcupado(false)
    }
  }
  return (
    <Button size={grande ? 'lg' : 'default'} onClick={ir} disabled={disabled || !conectado || ocupado} className="font-semibold">
      <Play className="fill-current" /> Continuar no QGIS
    </Button>
  )
}
