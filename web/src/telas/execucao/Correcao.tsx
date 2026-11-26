import { useState } from 'react'
import { Play } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Barra, Bloco, COR, Colunas, Fichas, RotuloEstavel, Tabela as TabelaDS, Vazio } from '@/components/ds'
import type { FolhaCorrecao, Ocorrencia, OcorrenciaCorrecao, ResultadoTratar } from '@/lib/api'
import { useAvisar } from '@/lib/avisos'
import { diaMes, num, pc, plural } from '@/lib/formato'
import { navegar, useRota } from '@/lib/rotas'
import { useSessao } from '@/lib/sessao'
import { enviar } from '@/lib/useApi'

const primeiro = (n: string) => n.split(' ').slice(0, 2).join(' ')

function useTratar() {
  const avisar = useAvisar()
  const [ocupado, setOcupado] = useState<string | null>(null)
  async function rodar(chave: string, fn: () => Promise<string>) {
    setOcupado(chave)
    try {
      avisar(await fn())
    } catch (e) {
      avisar((e as Error).message, 'erro')
    } finally {
      setOcupado(null)
    }
  }
  return {
    ocupado,
    ver: (o: OcorrenciaCorrecao) =>
      rodar(o.uuid, async () => {
        await enviar(`/api/inspecoes/${o.uuid}/zoom`)
        return `${o.elemento ?? 'Ocorrência'} no mapa do QGIS.`
      }),
    tratar: (o: OcorrenciaCorrecao, tratado: boolean) =>
      rodar(o.uuid, async () => {
        const r = await enviar<ResultadoTratar>(`/api/inspecoes/${o.uuid}/tratar`, { tratado })
        const p = r.progresso
        const andamento = p ? ` · ${p.folha_revisao} ${num(p.tratadas)}/${num(p.total)}` : ''
        if (!tratado) return `Tratamento desfeito: ${o.elemento ?? 'ocorrência'}${andamento}.`
        const fila = r.fila ? ` O próximo lote da sua fila, ${r.fila.folha_revisao}, já está com você.` : ''
        if (p && p.pendentes === 0) return `Tratada${andamento}. Todas as ocorrências do lote estão tratadas: o supervisor decide o próximo passo.${fila}`
        return `Tratada: ${o.elemento ?? 'ocorrência'}${andamento}.${fila}`
      }),
  }
}

// "Continuar no QGIS" da correção: leva o QGIS à próxima ocorrência por tratar desta folha, como "Próxima ocorrência" da barra.
function ContinuarCorrecao({ idLote }: { idLote: number }) {
  const avisar = useAvisar()
  const { conectado } = useSessao()
  const [ocupado, setOcupado] = useState(false)
  async function ir() {
    setOcupado(true)
    try {
      const r = await enviar<{ ocorrencia: Ocorrencia | null }>('/api/inspecoes/proxima', { id_lote: idLote })
      avisar(r.ocorrencia ? `Ocorrência atual no QGIS: ${r.ocorrencia.elemento ?? 'ocorrência'} (${r.ocorrencia.folha_revisao}).` : 'Nenhuma ocorrência por tratar neste lote.')
    } catch (e) {
      avisar((e as Error).message, 'erro')
    } finally {
      setOcupado(false)
    }
  }
  return (
    <Button size="lg" onClick={ir} disabled={!conectado || ocupado}>
      <Play className="fill-current" /> Continuar no QGIS
    </Button>
  )
}

function ProximoPasso({ f }: { f: FolhaCorrecao }) {
  if (f.pendentes > 0)
    return (
      <>
        Corrija no QGIS cada ponto apontado pelo avaliador e marque <b>Tratada</b> (barra do Feixe, ou aqui).{' '}
        {f.cargas_pendentes > 0 ? <>Conclua também as {plural(f.cargas_pendentes, 'carga', 'cargas')} da etapa em Minhas cargas. </> : null}
        Com a última tratada, o lote vai para o supervisor.
      </>
    )
  if (f.cargas_pendentes > 0) return <>Ocorrências tratadas. Faltam {plural(f.cargas_pendentes, 'carga', 'cargas')} da etapa em Minhas cargas; depois o lote vai para o supervisor.</>
  return <>Todas as ocorrências do lote estão tratadas: a sua parte terminou. O lote está em Esperando você do supervisor, que decide o próximo passo. Até ele decidir, dá para desfazer uma marcação.</>
}

function Tabela({ f, acoes }: { f: FolhaCorrecao; acoes: ReturnType<typeof useTratar> }) {
  const { conectado } = useSessao()
  return (
    <TabelaDS fixa densa largura={900}>
      <Colunas larguras={[150, 90, undefined, 140, 120, 120, 230]} />
      <thead>
        <tr>
          <th>Elemento</th>
          <th>Revisão</th>
          <th>Anotação</th>
          <th>Avaliador</th>
          <th>Ciência do APM</th>
          <th>Situação</th>
          <th />
        </tr>
      </thead>
      <tbody>
        {f.ocorrencias.map((o) => (
          <tr key={o.uuid}>
            <td className="truncate font-medium" title={o.elemento ?? undefined}>
              {o.elemento ?? '—'}
            </td>
            <td className="tab">{o.folha_revisao}</td>
            <td className="truncate" title={o.anotacao ?? undefined}>
              {o.anotacao ?? <span className="text-muted-foreground">sem anotação</span>}
            </td>
            <td className="truncate text-muted-foreground" title={o.avaliador}>
              {primeiro(o.avaliador)}
            </td>
            <td className="tab text-muted-foreground">{o.ciente_em ? `ciente ${diaMes(o.ciente_em)}` : 'sem ciência'}</td>
            <td className="tab">{o.tratado ? <span className="text-muted-foreground">tratada {diaMes(o.tratado_em)}</span> : 'por tratar'}</td>
            <td className="py-1.5">
              <span className="flex justify-end gap-1.5">
                <Button size="sm" variant="outline" disabled={!conectado || acoes.ocupado === o.uuid} onClick={() => acoes.ver(o)}>
                  Ver no QGIS
                </Button>
                <Button size="sm" variant={o.tratado ? 'ghost' : 'default'} className="w-[92px]" disabled={acoes.ocupado === o.uuid || !o.pode_tratar} onClick={() => acoes.tratar(o, !o.tratado)}>
                  <RotuloEstavel ocupado={acoes.ocupado === o.uuid} rotulo={o.tratado ? 'Desfazer' : 'Tratada'} rotuloOcupado="…" />
                </Button>
              </span>
            </td>
          </tr>
        ))}
      </tbody>
    </TabelaDS>
  )
}

// Execução › Correção (D5): as folhas que estão com você na correção de inspeção. Você varre todas as ocorrências da
// folha (de todas as revisões) e marca cada uma como tratada; não há revisão às cegas aqui, é a varredura final.
export function Correcao({ folhas }: { folhas: FolhaCorrecao[] }) {
  const rota = useRota()
  const acoes = useTratar()
  if (!folhas.length)
    return (
      <Bloco>
        <Vazio>Nenhum lote com você na correção de inspeção. O supervisor distribui os lotes aprovados no CQ.</Vazio>
      </Bloco>
    )
  const pedida = Number(rota.query.get('folha')) || null
  const f = folhas.find((x) => x.id_lote === pedida) ?? folhas.find((x) => x.pendentes > 0) ?? folhas[0]
  return (
    <>
      {folhas.length > 1 && (
        <Fichas
          rotulo="Lote"
          ativa={String(f.id_lote)}
          escolher={(k) => navegar(`execucao/correcao?folha=${k}`)}
          fichas={folhas.map((x) => ({ id: String(x.id_lote), rotulo: x.folha_revisao, contagem: x.pendentes ? `${num(x.pendentes)} por tratar` : 'tudo tratado' }))}
        />
      )}
      <Bloco className="flex-row flex-wrap items-center gap-x-5 gap-y-3 px-5 py-4">
        <div className="flex min-w-[300px] flex-1 flex-col gap-1.5">
          <div className="flex flex-wrap items-baseline gap-x-3">
            <span className="tab text-titulo-2 font-bold">{f.folha_revisao}</span>
            <span className="text-muted-foreground">
              {f.tema} · {f.etapa} · {f.situacao === 'pendente' ? 'a iniciar' : 'em andamento'}
            </span>
          </div>
          <div className="flex justify-between text-nota">
            <span>
              <b>{num(f.tratadas)}</b> de {plural(f.total, 'ocorrência tratada', 'ocorrências tratadas')} · todas as revisões
            </span>
            <span className="tab">{pc(f.tratadas, f.total)}%</span>
          </div>
          <Barra partes={[{ valor: f.tratadas, cor: COR.concluida }]} total={Math.max(f.total, 1)} />
          <p className="text-nota text-texto-2">
            <ProximoPasso f={f} />
          </p>
        </div>
        {f.pendentes > 0 && <ContinuarCorrecao idLote={f.id_lote} />}
      </Bloco>
      <Tabela f={f} acoes={acoes} />
      <p className="text-nota text-muted-foreground">
        O trabalho é no QGIS: <b>Próxima ocorrência</b> leva o mapa ao ponto sem mudar a escala, e <b>Tratada</b> marca e já vai para a seguinte. Tudo funciona sem a conexão com a CCAR: vai quando a conexão voltar.
      </p>
    </>
  )
}
