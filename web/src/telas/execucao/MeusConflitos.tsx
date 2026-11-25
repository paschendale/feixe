import { useState } from 'react'
import { ChevronDown, ChevronUp } from 'lucide-react'
import { Bloco, COR } from '@/components/painel'
import type { MeuSyncLog } from '@/lib/api'
import { plural } from '@/lib/formato'
import { useApi } from '@/lib/useApi'

const FUSO = Intl.DateTimeFormat().resolvedOptions().timeZone || 'America/Sao_Paulo'

// O que não entrou na CCAR do que a pessoa fez (C5): recusas e conflitos perdidos dos últimos 7 dias, lidos do
// workspace (funciona offline). Só o próprio trabalho: nenhum nome de colega.
export function MeusConflitos() {
  const { dados } = useApi<{ itens: MeuSyncLog[]; dias: number }>(`/api/sync_log/meus?dias=7&fuso=${encodeURIComponent(FUSO)}`, ['sincronizacao'])
  const [aberto, setAberto] = useState(false)
  const itens = dados?.itens ?? []
  if (!itens.length) return null
  const mostrar = aberto ? itens : itens.slice(0, 2)
  return (
    <Bloco className="gap-2 border-[#F0D9B5]" style={{ background: '#FFFBF4' }}>
      <div className="flex flex-wrap items-baseline gap-x-2.5">
        <h3 className="font-semibold" style={{ color: COR.alerta }}>
          {itens.length === 1 ? 'Uma alteração sua não ficou na CCAR' : `${plural(itens.length, 'alteração sua', 'alterações suas')} não ficaram na CCAR`}
        </h3>
        <span className="text-[13px] text-muted-foreground">nos últimos {dados?.dias ?? 7} dias</span>
      </div>
      <ul className="flex flex-col gap-1.5 text-[14px]">
        {mostrar.map((i) => (
          <li key={i.id}>
            <b className="tab">{[i.alvo.folha, i.alvo.geocodigo ? `carga ${i.alvo.geocodigo}` : i.alvo.id ? `carga nº ${i.alvo.id}` : null].filter(Boolean).join(' · ') || 'Carga'}</b>
            {': '}
            {i.frase}
          </li>
        ))}
      </ul>
      {itens.length > 2 && (
        <button type="button" className="inline-flex w-fit items-center gap-1 text-[13px] font-semibold text-ibge hover:underline" onClick={() => setAberto(!aberto)}>
          {aberto ? <ChevronUp className="size-3.5" /> : <ChevronDown className="size-3.5" />}
          {aberto ? 'Mostrar menos' : `Ver todas (${itens.length})`}
        </button>
      )}
      <span className="text-[13px] text-muted-foreground">Na sua tela já está o que ficou na CCAR. Se precisar refazer algo, faça de novo ou fale com o supervisor.</span>
    </Bloco>
  )
}
