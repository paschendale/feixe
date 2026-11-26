import { useState } from 'react'
import { ChevronDown, ChevronUp } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { COR, Colunas } from '@/components/painel'
import type { OcorrenciaDaFolha, OcorrenciasDaFolha } from '@/lib/api'
import { useAvisar } from '@/lib/avisos'
import { diaMes, num, plural } from '@/lib/formato'
import { useSessao } from '@/lib/sessao'
import { enviar, useApi } from '@/lib/useApi'

const primeiro = (n: string | null) => (n ?? '').split(' ').slice(0, 2).join(' ')
const MOSTRAR = 8

// Ciência do APM e tratamento (correção de inspeção, D5): o que já aconteceu com a ocorrência.
function Estado({ o }: { o: OcorrenciaDaFolha }) {
  const partes = []
  if (o.tratado) partes.push(<span key="t">tratada {diaMes(o.tratado_em)}</span>)
  if (o.ciente_em) partes.push(<span key="c">ciente {diaMes(o.ciente_em)}</span>)
  else if (o.autor) partes.push(<span key="s" style={{ color: COR.alerta }}>sem ciência</span>)
  if (!partes.length) return <span className="text-muted-foreground">—</span>
  return <span className="flex flex-wrap gap-x-1.5">{partes.reduce<React.ReactNode[]>((a, p, i) => (i ? [...a, ' · ', p] : [p]), [])}</span>
}

// Gaveta da folha (D3d): as ocorrências de todas as revisões, para o supervisor (quem planeja vê tudo, sem a regra do
// D-66), com quem registrou, de quem é a carga apontada, ciência e tratamento. Lê a CCAR.
export function OcorrenciasFolha({ idLote }: { idLote: number }) {
  const avisar = useAvisar()
  const { conectado } = useSessao()
  const { dados, erro } = useApi<OcorrenciasDaFolha>(`/api/lotes/${idLote}/ocorrencias`, ['cq', 'lote'])
  const [todas, setTodas] = useState(false)
  if (!dados) return erro ? <p className="text-[13px] text-destructive">{erro}</p> : null
  if (!dados.total) return null
  // As da revisão mais recente primeiro: é delas que a decisão de agora trata.
  const itens = [...dados.itens].sort((a, b) => (b.revisao ?? -1) - (a.revisao ?? -1) || (b.instancia ?? 0) - (a.instancia ?? 0))
  const mostrar = todas ? itens : itens.slice(0, MOSTRAR)
  return (
    <section aria-labelledby="ocorrencias" className="flex flex-col gap-2.5">
      <div className="flex flex-wrap items-baseline gap-x-2.5">
        <h2 id="ocorrencias" className="text-[13px] font-semibold tracking-[.04em] text-muted-foreground uppercase">
          Ocorrências
        </h2>
        <span className="text-[13px] text-muted-foreground">
          {plural(dados.total, 'ocorrência', 'ocorrências')} · {num(dados.pendentes)} não {dados.pendentes === 1 ? 'tratada' : 'tratadas'}
          {dados.sem_ciente ? ` · ${num(dados.sem_ciente)} sem ciência` : ''}
        </span>
      </div>
      <table className="w-full table-fixed border-collapse text-[13px]">
        <Colunas larguras={[64, undefined, 104, 100, 112]} />
        <thead>
          <tr className="text-left text-xs text-muted-foreground">
            <th className="border-b py-1.5 pr-2 font-medium">Folha</th>
            <th className="border-b px-2 py-1.5 font-medium">Elemento e anotação</th>
            <th className="border-b px-2 py-1.5 font-medium">Quem</th>
            <th className="border-b px-2 py-1.5 font-medium">Situação</th>
            <th className="border-b py-1.5 pl-2" />
          </tr>
        </thead>
        <tbody>
          {mostrar.map((o) => (
            <tr key={o.uuid} className="border-b border-linha align-top last:border-0">
              <td className="tab truncate py-1.5 pr-2" title={o.etapa ?? undefined}>
                {o.folha_revisao}
              </td>
              <td className="px-2 py-1.5" title={o.anotacao ?? undefined}>
                <span className="block truncate font-medium">{o.elemento ?? '—'}</span>
                <span className="block truncate text-muted-foreground">{o.anotacao ?? 'sem anotação'}</span>
              </td>
              <td className="px-2 py-1.5" title={`Registrada por ${o.responsavel_nome}${o.autor_nome ? `; carga de ${o.autor_nome}` : ''}`}>
                <span className="block truncate">{primeiro(o.responsavel_nome)}</span>
                <span className="block truncate text-muted-foreground">{o.autor_nome ? `carga de ${primeiro(o.autor_nome)}` : 'sem carga apontada'}</span>
              </td>
              <td className="px-2 py-1.5">
                <Estado o={o} />
              </td>
              <td className="py-1 pl-2 text-right">
                <Button
                  size="sm"
                  variant="ghost"
                  className="px-2"
                  disabled={!conectado}
                  onClick={() => enviar(`/api/lotes/${idLote}/ocorrencias/${o.uuid}/zoom`).catch((e) => avisar((e as Error).message, 'erro'))}
                >
                  Ver no QGIS
                </Button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {itens.length > MOSTRAR && (
        <button type="button" className="inline-flex w-fit items-center gap-1 text-[13px] font-semibold text-ibge hover:underline" onClick={() => setTodas(!todas)}>
          {todas ? <ChevronUp className="size-3.5" /> : <ChevronDown className="size-3.5" />}
          {todas ? 'Mostrar menos' : `Ver todas (${num(itens.length)})`}
        </button>
      )}
    </section>
  )
}
