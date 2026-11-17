import { CabecalhoModulo, type Aba } from '@/components/painel'
import type { GrupoEsperando } from '@/lib/api'
import { href, useRota } from '@/lib/rotas'
import { useSessao } from '@/lib/sessao'
import { useApi } from '@/lib/useApi'
import Equipe from './Equipe'
import Esperando from './Esperando'
import Fluxos from './Fluxos'
import Folhas from './Folhas'

// Supervisão (D-103): Folhas · Esperando você · Equipe · Fluxos. O gerente que não supervisiona vê Folhas e Fluxos.
export default function Supervisao() {
  const { tem } = useSessao()
  const rota = useRota()
  const supervisor = tem('supervisor')
  const { dados: esperando } = useApi<{ grupos: GrupoEsperando[] }>(supervisor ? '/api/painel/esperando' : null, ['lote'])
  const nEsperando = (esperando?.grupos ?? []).filter((g) => g.id_proxima !== null).reduce((s, g) => s + g.folhas.length, 0)
  const nFim = (esperando?.grupos ?? []).filter((g) => g.id_proxima === null).reduce((s, g) => s + g.folhas.length, 0)
  const abas: Aba[] = [
    { id: 'folhas', rotulo: 'Folhas', href: href('supervisao/folhas') },
    ...(supervisor ? [{ id: 'esperando', rotulo: 'Esperando você', href: href('supervisao/esperando'), contagem: nEsperando + nFim }] : []),
    ...(supervisor ? [{ id: 'equipe', rotulo: 'Equipe', href: href('supervisao/equipe') }] : []),
    { id: 'fluxos', rotulo: 'Fluxos', href: href('supervisao/fluxos') },
  ]
  const ativa = abas.some((a) => a.id === rota.partes[0]) ? rota.partes[0] : 'folhas'
  return (
    <>
      <CabecalhoModulo titulo="Supervisão" abas={abas} ativa={ativa} />
      {ativa === 'folhas' && <Folhas />}
      {ativa === 'esperando' && <Esperando grupos={esperando?.grupos ?? null} />}
      {ativa === 'equipe' && <Equipe />}
      {ativa === 'fluxos' && <Fluxos />}
    </>
  )
}
