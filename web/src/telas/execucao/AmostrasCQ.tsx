import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Textarea } from '@/components/ui/textarea'
import { Barra, Bloco, COR, Campo, Carregando, Colunas, Fichas, Legenda, Nota, RotuloEstavel, Segmentado, Selo, Tabela, TituloBloco, Vazio } from '@/components/ds'
import type { Amostra, Ocorrencia, ResumoCQ } from '@/lib/api'
import { useAvisar } from '@/lib/avisos'
import { dataHora, diaMes, hora, num, plural } from '@/lib/formato'
import { href, navegar, useRota } from '@/lib/rotas'
import { useSessao } from '@/lib/sessao'
import { enviar, useApi } from '@/lib/useApi'
import { ContinuarAmostra, fraseCQ, partesCQ } from './comum'

const chaveDe = (r: ResumoCQ) => String(r.id_atividade)
const nomeDe = (r: Pick<ResumoCQ, 'elemento' | 'atividade'>) => r.elemento ?? r.atividade ?? 'CQ'
const celula = (a: Pick<Amostra, 'geocodigo' | 'id_carga_trabalho'>) => a.geocodigo ?? `nº ${a.id_carga_trabalho}`

function SituacaoAmostra({ a }: { a: Amostra }) {
  if (a.status === null) return <span>pendente</span>
  return a.status === 1 ? <span>conforme</span> : <Selo tom="alerta">não conforme</Selo>
}

// Trocar a avaliação pela tabela (D-140): só de amostra já avaliada, com a etapa de CQ aberta. Popover ancorado no botão
// (D-131): a célula não muda.
function MudarAvaliacao({ a }: { a: Amostra }) {
  const avisar = useAvisar()
  const [aberto, setAberto] = useState(false)
  const [status, setStatus] = useState<0 | 1>(a.status ?? 1)
  const [obs, setObs] = useState(a.observacao ?? '')
  const [ocupado, setOcupado] = useState(false)
  async function salvar() {
    setOcupado(true)
    try {
      await enviar(`/api/amostras/${a.id}`, { status, observacao: obs })
      avisar(`${celula(a)}: ${status === 1 ? 'conforme' : 'não conforme'}${obs.trim() ? ', com observação' : ''}.`)
      setAberto(false)
    } catch (e) {
      avisar((e as Error).message, 'erro')
    } finally {
      setOcupado(false)
    }
  }
  return (
    <Popover
      open={aberto}
      onOpenChange={(v) => {
        setAberto(v)
        if (v) {
          setStatus(a.status ?? 1)
          setObs(a.observacao ?? '')
        }
      }}
    >
      <PopoverTrigger asChild>
        <Button size="sm" variant="ghost">
          Mudar…
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-80">
        <div className="flex flex-col gap-1">
          <p className="font-semibold">Avaliação de {celula(a)}</p>
          <p className="text-nota text-muted-foreground">Vale enquanto a etapa de CQ estiver aberta.</p>
        </div>
        <div role="radiogroup" aria-label="Avaliação" className="flex gap-4">
          {([1, 0] as const).map((v) => (
            <label key={v} className="inline-flex items-center gap-1.5">
              <input type="radio" name={`status-${a.id}`} checked={status === v} onChange={() => setStatus(v)} />
              {v === 1 ? 'Conforme' : 'Não conforme'}
            </label>
          ))}
        </div>
        <Campo rotulo="Observação">
          <Textarea rows={3} value={obs} onChange={(e) => setObs(e.target.value)} className="font-normal text-foreground" />
        </Campo>
        <div className="flex justify-end gap-2">
          <Button size="sm" variant="ghost" onClick={() => setAberto(false)}>
            Cancelar
          </Button>
          <Button size="sm" disabled={ocupado} onClick={salvar}>
            <RotuloEstavel ocupado={ocupado} rotulo="Salvar" rotuloOcupado="Salvando…" />
          </Button>
        </div>
      </PopoverContent>
    </Popover>
  )
}

type Aba = 'pendentes' | 'avaliadas'

function Amostras({ r }: { r: ResumoCQ }) {
  const { conectado } = useSessao()
  const avisar = useAvisar()
  const [ocupado, setOcupado] = useState<number | null>(null)
  const [aba, setAba] = useState<Aba>(r.pendentes > 0 ? 'pendentes' : 'avaliadas')
  const { dados, erro } = useApi<{ itens: Amostra[] }>(`/api/amostras?lote_etapa=${r.id_lote_etapa}`, ['carga', 'cq'])
  if (!dados) return <Carregando erro={erro} />
  const doElemento = dados.itens.filter((a) => a.atividade === r.atividade)
  const pendentes = doElemento.filter((a) => !a.avaliada)
  const avaliadas = doElemento.filter((a) => a.avaliada).sort((x, y) => (y.avaliado_em ?? '').localeCompare(x.avaliado_em ?? ''))
  const itens = aba === 'pendentes' ? pendentes : avaliadas
  async function trabalhar(a: Amostra) {
    setOcupado(a.id)
    try {
      await enviar(`/api/amostras/${a.id}/zoom`)
      avisar(`Amostra atual no QGIS: ${celula(a)}`)
    } catch (e) {
      avisar((e as Error).message, 'erro')
    } finally {
      setOcupado(null)
    }
  }
  const abas: { id: Aba; rotulo: string; contagem: string }[] = [
    { id: 'pendentes', rotulo: 'Pendentes', contagem: num(pendentes.length) },
    { id: 'avaliadas', rotulo: 'Avaliadas', contagem: num(avaliadas.length) },
  ]
  return (
    <section aria-label="Amostras" className="flex flex-col gap-3">
      <Segmentado rotulo="Situação das amostras" opcoes={abas} ativa={aba} escolher={setAba} />
      <Tabela fixa largura={760}>
        <Colunas larguras={[190, 130, undefined, 110, 130, 220]} />
        <thead>
          <tr>
            <th>Célula</th>
            <th>Situação</th>
            <th>Observação</th>
            <th className="text-right">Ocorrências</th>
            <th>Avaliada</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {itens.length === 0 && (
            <tr>
              <td colSpan={6} className="text-muted-foreground">
                {aba === 'pendentes' ? `Nenhuma pendente: as suas amostras de ${nomeDe(r)} neste lote estão avaliadas.` : 'Nenhuma avaliada ainda. A avaliação é no QGIS, pela barra do Feixe.'}
              </td>
            </tr>
          )}
          {itens.map((a) => (
            <tr key={a.id}>
              <td className="tab font-mono text-nota">{celula(a)}</td>
              <td>
                <SituacaoAmostra a={a} />
              </td>
              <td className="truncate text-muted-foreground" title={a.observacao ?? undefined}>
                {a.observacao ?? (a.avaliada ? '—' : '')}
              </td>
              <td className="tab text-right">{a.ocorrencias ? num(a.ocorrencias) : '—'}</td>
              <td className="tab truncate text-muted-foreground" title={a.avaliado_em ? dataHora(a.avaliado_em) : undefined}>
                {a.avaliado_em ? `${diaMes(a.avaliado_em)} ${hora(a.avaliado_em)}` : ''}
              </td>
              <td className="py-2">
                <span className="flex justify-end gap-1.5">
                  {a.avaliada && r.aberta && <MudarAvaliacao a={a} />}
                  {(a.avaliada || r.aberta) && (
                    <Button size="sm" variant="outline" className="w-[124px]" disabled={!conectado || ocupado === a.id} onClick={() => trabalhar(a)}>
                      {a.avaliada ? 'Ver no QGIS' : 'Trabalhar nesta'}
                    </Button>
                  )}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </Tabela>
    </section>
  )
}

// Editar a anotação de uma ocorrência minha (popover no botão, D-131).
function EditarAnotacao({ o }: { o: Ocorrencia }) {
  const avisar = useAvisar()
  const [aberto, setAberto] = useState(false)
  const [texto, setTexto] = useState(o.anotacao ?? '')
  const [ocupado, setOcupado] = useState(false)
  async function salvar() {
    setOcupado(true)
    try {
      await enviar(`/api/inspecoes/${o.uuid}`, { anotacao: texto })
      avisar('Anotação da ocorrência salva.')
      setAberto(false)
    } catch (e) {
      avisar((e as Error).message, 'erro')
    } finally {
      setOcupado(false)
    }
  }
  return (
    <Popover
      open={aberto}
      onOpenChange={(v) => {
        setAberto(v)
        if (v) setTexto(o.anotacao ?? '')
      }}
    >
      <PopoverTrigger asChild>
        <Button size="sm" variant="ghost">
          Editar…
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-80">
        <p className="font-semibold">Anotação da ocorrência</p>
        <Textarea rows={4} value={texto} onChange={(e) => setTexto(e.target.value)} aria-label="Anotação" />
        <div className="flex justify-end gap-2">
          <Button size="sm" variant="ghost" onClick={() => setAberto(false)}>
            Cancelar
          </Button>
          <Button size="sm" disabled={ocupado} onClick={salvar}>
            <RotuloEstavel ocupado={ocupado} rotulo="Salvar" rotuloOcupado="Salvando…" />
          </Button>
        </div>
      </PopoverContent>
    </Popover>
  )
}

// As ocorrências que eu registrei nesta folha e neste elemento: ver no QGIS, editar a anotação, apagar.
function MinhasOcorrencias({ r }: { r: ResumoCQ }) {
  const avisar = useAvisar()
  const { conectado } = useSessao()
  const [ocupado, setOcupado] = useState<string | null>(null)
  const { dados, erro } = useApi<{ itens: Ocorrencia[] }>(`/api/inspecoes?id_lote_etapa=${r.id_lote_etapa}`, ['cq'])
  const { dados: amostras } = useApi<{ itens: Amostra[] }>(`/api/amostras?lote_etapa=${r.id_lote_etapa}`, ['carga', 'cq'])
  const geo = new Map((amostras?.itens ?? []).map((a) => [a.id_carga_trabalho, celula(a)]))
  const itens = (dados?.itens ?? []).filter((o) => o.minha && o.elemento === r.elemento)
  async function rodar(o: Ocorrencia, fn: () => Promise<unknown>, ok: string) {
    setOcupado(o.uuid)
    try {
      await fn()
      avisar(ok)
    } catch (e) {
      avisar((e as Error).message, 'erro')
    } finally {
      setOcupado(null)
    }
  }
  return (
    <Bloco className="gap-2.5">
      <TituloBloco titulo="Ocorrências que você registrou" sub={`${nomeDe(r)} · ${r.folha_revisao}`} />
      {!dados ? (
        <Carregando erro={erro} />
      ) : itens.length === 0 ? (
        <span className="text-nota text-muted-foreground">Nenhuma ainda. No QGIS, "Registrar ocorrência" na barra do Feixe marca o ponto na amostra atual.</span>
      ) : (
        <Tabela solta densa fixa largura={720}>
          <Colunas larguras={[170, undefined, 150, 250]} />
          <thead>
            <tr>
              <th>Célula</th>
              <th>Anotação</th>
              <th>Registrada</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {itens.map((o) => (
              <tr key={o.uuid}>
                <td className="tab truncate font-mono">{(o.id_carga_trabalho && geo.get(o.id_carga_trabalho)) ?? '—'}</td>
                <td className="truncate" title={o.anotacao ?? undefined}>
                  {o.anotacao ?? <span className="text-muted-foreground">sem anotação</span>}
                </td>
                <td className="truncate text-muted-foreground" title={o.enviada ? undefined : 'Vai para a CCAR na próxima sincronização'}>
                  {diaMes(o.criado_em)} {hora(o.criado_em)}
                  {!o.enviada && ' · a enviar'}
                </td>
                <td className="py-1.5">
                  <span className="flex justify-end gap-1">
                    {o.pode_editar && <EditarAnotacao o={o} />}
                    {o.pode_editar && (
                      <Button
                        size="sm"
                        variant="ghost"
                        disabled={ocupado === o.uuid}
                        onClick={() => {
                          if (window.confirm('Apagar esta ocorrência? Ela some do lote e do QGIS.')) rodar(o, () => enviar(`/api/inspecoes/${o.uuid}`, undefined, 'DELETE'), 'Ocorrência apagada.')
                        }}
                      >
                        Apagar
                      </Button>
                    )}
                    <Button size="sm" variant="outline" disabled={!conectado || ocupado === o.uuid} onClick={() => rodar(o, () => enviar(`/api/inspecoes/${o.uuid}/zoom`), 'Ocorrência no mapa do QGIS.')}>
                      Ver no QGIS
                    </Button>
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </Tabela>
      )}
    </Bloco>
  )
}

// O próximo passo da história (D-136) quando a folha (ou este elemento nela) termina.
function ProximoPasso({ r, daFolha }: { r: ResumoCQ; daFolha: ResumoCQ[] }) {
  if (!r.aberta) return <p className="text-nota text-muted-foreground">A etapa de CQ deste lote foi encerrada pelo supervisor.</p>
  if (r.pendentes > 0) return null
  const faltam = daFolha.filter((x) => x.pendentes > 0)
  const outras = daFolha.reduce((s, x) => s + x.outras, 0)
  if (faltam.length)
    return (
      <Nota tom="info" titulo={`${nomeDe(r)} avaliado neste lote.`}>
        Faltam{' '}
        {faltam.map((x, i) => (
          <span key={x.id_atividade}>
            {i > 0 && (i === faltam.length - 1 ? ' e ' : ', ')}
            {plural(x.pendentes, 'amostra', 'amostras')} de{' '}
            <a className="font-medium text-primary hover:underline" href={href('execucao/cq', { atividade: chaveDe(x), folha: x.id_lote_etapa })}>
              {nomeDe(x)}
            </a>
          </span>
        ))}
        .
      </Nota>
    )
  return (
    <Nota tom="info" titulo="Lote avaliado: o supervisor decide aprovar ou nova revisão.">
      {outras > 0
        ? `As suas amostras de ${r.folha_revisao} estão todas avaliadas; ${plural(outras, 'amostra do plano está', 'amostras do plano estão')} com outro avaliador.`
        : `Todas as amostras de ${r.folha_revisao} estão avaliadas. Nada mais a fazer aqui; o lote segue quando o supervisor decidir.`}
    </Nota>
  )
}

// Execução › CQ (D3d): as fichas por elemento, a folha com o andamento do plano, as amostras e as ocorrências que a
// pessoa registrou. A avaliação é no QGIS (barra do Feixe); aqui é o acompanhamento e a troca de uma avaliação.
export function AmostrasCQ({ cq }: { cq: ResumoCQ[] }) {
  const rota = useRota()
  if (cq.length === 0)
    return (
      <Bloco>
        <Vazio>Nenhuma amostra de CQ com você. O supervisor distribui as amostras dos lotes em controle de qualidade.</Vazio>
      </Bloco>
    )
  const chaves = [...new Set(cq.map(chaveDe))]
  const temas = (k: string) => new Set(cq.filter((r) => chaveDe(r) === k).map((r) => r.tema)).size
  const elementoRepetido = (k: string) => {
    const r = cq.find((x) => chaveDe(x) === k)!
    return chaves.some((o) => o !== k && nomeDe(cq.find((x) => chaveDe(x) === o)!) === nomeDe(r))
  }
  const rotulo = (k: string) => {
    const r = cq.find((x) => chaveDe(x) === k)!
    return elementoRepetido(k) && temas(k) === 1 ? `${nomeDe(r)} · ${r.tema}` : nomeDe(r)
  }
  const pendentesDa = (k: string) => cq.filter((r) => chaveDe(r) === k && r.aberta).reduce((s, r) => s + r.pendentes, 0)
  const folhaQ = Number(rota.query.get('folha')) || null
  const chaveQ = rota.query.get('atividade')
  const daFolhaQ = cq.find((r) => r.id_lote_etapa === folhaQ && (!chaveQ || chaveDe(r) === chaveQ))
  const chave = chaveQ && chaves.includes(chaveQ) ? chaveQ : daFolhaQ ? chaveDe(daFolhaQ) : (chaves.find((k) => pendentesDa(k) > 0) ?? chaves[0])
  const linhas = cq.filter((r) => chaveDe(r) === chave)
  const atual = linhas.find((r) => r.id_lote_etapa === folhaQ) ?? linhas.find((r) => r.aberta && r.pendentes > 0) ?? linhas[0]
  const daFolha = cq.filter((r) => r.id_lote_etapa === atual.id_lote_etapa)
  const outras = linhas.filter((r) => r !== atual)

  return (
    <>
      <Fichas
        rotulo="Elemento"
        ativa={chave}
        escolher={(k) => navegar(`execucao/cq?atividade=${encodeURIComponent(k)}`)}
        fichas={chaves.map((k) => ({ id: k, rotulo: rotulo(k), contagem: pendentesDa(k) ? `${num(pendentesDa(k))} pendentes` : 'tudo avaliado' }))}
      />
      <Bloco className="flex-row flex-wrap items-center gap-x-5 gap-y-3 px-5 py-4">
        <div className="flex min-w-[300px] flex-1 flex-col gap-1.5">
          <div className="flex flex-wrap items-baseline gap-x-3">
            <span className="tab text-titulo-2 font-bold">{atual.folha_revisao}</span>
            <span className="text-muted-foreground">
              {[atual.tema, atual.etapa, nomeDe(atual)].filter(Boolean).join(' · ')} · {atual.aberta ? (atual.situacao === 'pendente' ? 'a iniciar' : 'em andamento') : 'encerrada pelo supervisor'}
            </span>
          </div>
          <span className="text-nota">{fraseCQ(atual)}</span>
          <Barra partes={partesCQ(atual)} total={atual.minhas} />
          <div className="flex flex-wrap items-center justify-between gap-2">
            <Legenda
              itens={[
                { cor: COR.concluida, rotulo: 'conformes' },
                { cor: COR.naoConforme, rotulo: 'não conformes' },
                { cor: COR.vazio, rotulo: 'pendentes' },
              ]}
            />
            <span className="text-rodape text-muted-foreground">
              Plano: nível {atual.plano.nivel ?? '—'}
              {atual.plano.letra ? `, letra ${atual.plano.letra}` : ''}
              {atual.plano.lqa != null ? `, LQA ${atual.plano.lqa.toLocaleString('pt-BR')}%` : ''}
            </span>
          </div>
        </div>
        {atual.aberta && daFolha.some((r) => r.pendentes > 0) && <ContinuarAmostra idLote={atual.id_lote} grande />}
      </Bloco>
      <ProximoPasso r={atual} daFolha={daFolha} />
      {outras.length > 0 && (
        <div className="flex flex-wrap gap-2">
          <span className="text-muted-foreground">Outros lotes em {nomeDe(atual)}:</span>
          {outras.map((r) => (
            <a key={r.id_lote_etapa} href={href('execucao/cq', { atividade: chave, folha: r.id_lote_etapa })} className="tab font-medium text-primary hover:underline">
              {r.folha_revisao} ({r.aberta ? (r.pendentes ? `${num(r.pendentes)} pendentes` : 'avaliado') : 'encerrado'})
            </a>
          ))}
        </div>
      )}
      <Amostras key={`${atual.id_lote_etapa}-${atual.id_atividade}`} r={atual} />
      <MinhasOcorrencias key={`o-${atual.id_lote_etapa}-${atual.id_atividade}`} r={atual} />
      <p className="text-nota text-muted-foreground">
        A avaliação é no QGIS (barra do Feixe: próxima amostra, conforme, não conforme, registrar ocorrência). Aqui é o acompanhamento: enquanto a etapa de CQ estiver aberta, dá para trocar a avaliação de uma amostra já avaliada e editar ou apagar as suas ocorrências.
      </p>
    </>
  )
}
