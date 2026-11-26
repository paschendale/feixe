import { useState } from 'react'
import { ChevronDown, ChevronUp } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Colunas, Nota, Tabela } from '@/components/ds'
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
  else if (o.autor) partes.push(<span key="s" className="text-alerta">sem ciência</span>)
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
  if (!dados) return erro ? <Nota tom="perigo">{erro}</Nota> : null
  if (!dados.total) return null
  // As da revisão mais recente primeiro: é delas que a decisão de agora trata.
  const itens = [...dados.itens].sort((a, b) => (b.revisao ?? -1) - (a.revisao ?? -1) || (b.instancia ?? 0) - (a.instancia ?? 0))
  const mostrar = todas ? itens : itens.slice(0, MOSTRAR)
  return (
    <section aria-labelledby="ocorrencias" className="flex flex-col gap-2.5">
      <div className="flex flex-wrap items-baseline gap-x-2.5">
        <h2 id="ocorrencias" className="text-nota font-semibold tracking-[.04em] text-muted-foreground uppercase">
          Ocorrências
        </h2>
        <span className="text-nota text-muted-foreground">
          {plural(dados.total, 'ocorrência', 'ocorrências')} · {num(dados.pendentes)} não {dados.pendentes === 1 ? 'tratada' : 'tratadas'}
          {dados.sem_ciente ? ` · ${num(dados.sem_ciente)} sem ciência` : ''}
        </span>
      </div>
      <Tabela solta densa fixa>
        <Colunas larguras={[64, undefined, 104, 100, 112]} />
        <thead>
          <tr>
            <th>Folha</th>
            <th>Elemento e anotação</th>
            <th>Quem</th>
            <th>Situação</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {mostrar.map((o) => (
            <tr key={o.uuid} className="[&>td]:align-top">
              <td className="tab truncate" title={o.etapa ?? undefined}>
                {o.folha_revisao}
              </td>
              <td title={o.anotacao ?? undefined}>
                <span className="block truncate font-medium">{o.elemento ?? '—'}</span>
                <span className="block truncate text-muted-foreground">{o.anotacao ?? 'sem anotação'}</span>
              </td>
              <td title={`Registrada por ${o.responsavel_nome}${o.autor_nome ? `; carga de ${o.autor_nome}` : ''}`}>
                <span className="block truncate">{primeiro(o.responsavel_nome)}</span>
                <span className="block truncate text-muted-foreground">{o.autor_nome ? `carga de ${primeiro(o.autor_nome)}` : 'sem carga apontada'}</span>
              </td>
              <td>
                <Estado o={o} />
              </td>
              <td className="py-1 text-right">
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
      </Tabela>
      {itens.length > MOSTRAR && (
        <button type="button" className="inline-flex w-fit items-center gap-1 text-nota font-medium text-primary hover:underline" onClick={() => setTodas(!todas)}>
          {todas ? <ChevronUp className="size-3.5" /> : <ChevronDown className="size-3.5" />}
          {todas ? 'Mostrar menos' : `Ver todas (${num(itens.length)})`}
        </button>
      )}
    </section>
  )
}
