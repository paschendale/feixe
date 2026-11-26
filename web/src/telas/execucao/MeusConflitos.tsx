import { useState } from 'react'
import { ChevronDown, ChevronUp } from 'lucide-react'
import { Nota } from '@/components/ds'
import type { MeuSyncLog } from '@/lib/api'
import { FUSO, plural } from '@/lib/formato'
import { useApi } from '@/lib/useApi'


// O que não entrou na CCAR do que a pessoa fez (C5): recusas e conflitos perdidos dos últimos 7 dias, lidos do
// workspace (funciona offline). Só o próprio trabalho: nenhum nome de colega.
export function MeusConflitos() {
  const { dados } = useApi<{ itens: MeuSyncLog[]; dias: number }>(`/api/sync_log/meus?dias=7&fuso=${encodeURIComponent(FUSO)}`, ['sincronizacao'])
  const [aberto, setAberto] = useState(false)
  const itens = dados?.itens ?? []
  if (!itens.length) return null
  const mostrar = aberto ? itens : itens.slice(0, 2)
  return (
    <Nota
      tom="alerta"
      titulo={
        <>
          {itens.length === 1 ? 'Uma alteração sua não ficou na CCAR' : `${plural(itens.length, 'alteração sua', 'alterações suas')} não ficaram na CCAR`}{' '}
          <span className="font-normal text-muted-foreground">nos últimos {dados?.dias ?? 7} dias</span>
        </>
      }
    >
      <div className="flex flex-col gap-2 pt-1">
        <ul className="flex flex-col gap-1.5 text-foreground">
          {mostrar.map((i) => (
            <li key={i.id}>
              <b className="tab">{[i.alvo.folha, i.alvo.geocodigo ? `carga ${i.alvo.geocodigo}` : i.alvo.id ? `carga nº ${i.alvo.id}` : null].filter(Boolean).join(' · ') || 'Carga'}</b>
              {': '}
              {i.frase}
            </li>
          ))}
        </ul>
        {itens.length > 2 && (
          <button type="button" className="inline-flex w-fit items-center gap-1 font-medium text-primary hover:underline" onClick={() => setAberto(!aberto)}>
            {aberto ? <ChevronUp className="size-3.5" /> : <ChevronDown className="size-3.5" />}
            {aberto ? 'Mostrar menos' : `Ver todas (${itens.length})`}
          </button>
        )}
        <span>Na sua tela já está o que ficou na CCAR. Se precisar refazer algo, faça de novo ou fale com o supervisor.</span>
      </div>
    </Nota>
  )
}
