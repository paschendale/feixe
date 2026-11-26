import type { Fluxo } from '@/lib/api'
import { Campo } from '@/components/ds'
import { Select } from '@/components/ui/select'
import { useApi } from '@/lib/useApi'

// Fluxo da unidade: decide projeto, tema e a etapa em que a folha começa.
export function EscolherFluxo({ valor, mudar }: { valor: number | null; mudar: (f: Fluxo | null) => void }) {
  const { dados, erro } = useApi<{ itens: Fluxo[] }>('/api/fluxos', ['fluxo'])
  const itens = dados?.itens ?? []
  const atual = itens.find((f) => f.id === valor)
  return (
    <Campo
      rotulo="Fluxo"
      dica={
        // A linha fica reservada antes da escolha: o diálogo não cresce ao escolher o fluxo.
        <span className="block h-4 truncate">
          {atual ? (atual.primeira_etapa ? `Começa em: ${atual.primeira_etapa}` : 'Este fluxo ainda não tem etapas.') : 'A folha começa na primeira etapa do fluxo.'}
        </span>
      }
    >
      <Select value={valor ?? ''} onChange={(e) => mudar(itens.find((f) => f.id === Number(e.target.value)) ?? null)}>
        <option value="">{erro ? 'não deu para carregar os fluxos' : 'Escolha o projeto, o tema e o fluxo'}</option>
        {itens.map((f) => (
          <option key={f.id} value={f.id}>
            {f.projeto} · {f.tema} · {f.nome}
          </option>
        ))}
      </Select>
    </Campo>
  )
}
