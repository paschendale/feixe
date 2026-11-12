import type { Fluxo } from '@/lib/api'
import { Label } from '@/components/ui/label'
import { Select } from '@/components/ui/select'
import { useApi } from '@/lib/useApi'

// Fluxo da unidade: decide projeto, tema e a etapa em que a folha começa.
export function EscolherFluxo({ valor, mudar }: { valor: number | null; mudar: (f: Fluxo | null) => void }) {
  const { dados, erro } = useApi<{ itens: Fluxo[] }>('/api/fluxos', ['fluxo'])
  const itens = dados?.itens ?? []
  const atual = itens.find((f) => f.id === valor)
  return (
    <div className="grid gap-1.5">
      <Label htmlFor="fluxo">Fluxo</Label>
      <Select
        id="fluxo"
        value={valor ?? ''}
        onChange={(e) => mudar(itens.find((f) => f.id === Number(e.target.value)) ?? null)}
      >
        <option value="">{erro ? 'não deu para carregar os fluxos' : 'Escolha o projeto, o tema e o fluxo'}</option>
        {itens.map((f) => (
          <option key={f.id} value={f.id}>
            {f.projeto} · {f.tema} · {f.nome}
          </option>
        ))}
      </Select>
      {atual && (
        <p className="text-xs text-muted-foreground">
          {atual.primeira_etapa ? `Começa em: ${atual.primeira_etapa}` : 'Este fluxo ainda não tem etapas.'}
        </p>
      )}
    </div>
  )
}
