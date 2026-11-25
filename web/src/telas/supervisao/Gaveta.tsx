import { useEffect, useState } from 'react'
import { Dialog as D } from 'radix-ui'
import { X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Select } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { Barra, COR } from '@/components/painel'
import type { EstadoLote, FluxoCompleto, Historico, LoteCompleto, PassagemLote, Preparo } from '@/lib/api'
import { useAvisar } from '@/lib/avisos'
import { diaMes, diasAtras, num, pc, plural } from '@/lib/formato'
import { useSessao } from '@/lib/sessao'
import { STATUS } from '@/lib/status'
import { enviar, useApi } from '@/lib/useApi'
import { cn } from '@/lib/utils'
import { comCargas, resumoPreparo } from '../folhas/preparo'

const ABERTAS = ['pendente', 'em_andamento']

const ACAO: Record<string, string> = {
  abrir: 'Abriu',
  repetir: 'Abriu de novo',
  iniciar: 'Iniciou',
  concluir: 'Concluiu',
  pular: 'Pulou',
  reabrir: 'Reabriu',
  gcq_aprovada: 'Aprovada pela GCQ:',
  gcq_devolvida: 'Devolvida pela GCQ:',
}

function Titulo({ children }: { children: React.ReactNode }) {
  return <h2 className="text-[13px] font-semibold tracking-[.04em] text-muted-foreground uppercase">{children}</h2>
}

// Trilho: as etapas do fluxo com o que a folha já fez em cada uma, onde está agora e a próxima sugerida.
function Trilho({ fluxo, lote, estado }: { fluxo: FluxoCompleto; lote: LoteCompleto; estado: EstadoLote | null }) {
  return (
    <ol className="flex flex-col">
      {fluxo.etapas.map((e) => {
        const ps = lote.passagens.filter((p) => p.id_fluxo_etapa === e.id)
        const aberta = ps.find((p) => ABERTAS.includes(p.situacao))
        const ultima = ps[ps.length - 1]
        const atual = ps.some((p) => p.id === lote.id_lote_etapa_atual)
        const proxima = estado?.sugestao?.id === e.id
        let lado = ''
        if (aberta) lado = aberta.situacao === 'pendente' ? 'agora · a iniciar' : `agora${aberta.cargas_total ? ` · ${pc(aberta.cargas_concluidas, aberta.cargas_total)}%` : ''}`
        else if (proxima) lado = 'próxima sugerida'
        else if (ultima?.situacao === 'concluida') lado = `concluída ${diaMes(ultima.concluida_em)}${ps.length > 1 ? ` · ${ps.length}×` : ''}`
        else if (ultima?.situacao === 'pulada') lado = 'pulada'
        return (
          <li key={e.id} className={cn('grid grid-cols-[22px_1fr_auto] items-center gap-2.5 border-b border-linha py-2.5 last:border-0', aberta && 'font-semibold')}>
            <span
              className={cn(
                'inline-block size-3 rounded-full border-2 border-[#C7D0DB]',
                ultima?.situacao === 'concluida' && !aberta && 'border-aco bg-aco',
                aberta && 'border-ibge shadow-[0_0_0_3px_var(--aco-claro)]',
                proxima && 'border-dashed border-ibge',
              )}
            />
            <span>
              {e.nome}
              {atual && !aberta && <span className="font-normal text-muted-foreground"> · terminou aqui</span>}
            </span>
            <span className={cn('text-[13px]', aberta || proxima ? 'font-medium text-ibge' : 'font-normal text-muted-foreground')}>{lado}</span>
          </li>
        )
      })}
    </ol>
  )
}

type Pedido = { titulo: string; passos: { caminho: string; corpo?: Record<string, unknown> }[]; escolher?: boolean }

// Andar com a folha (B6): toda ação é do supervisor, com observação, e vai para o histórico. O Feixe só sugere.
function Andar({ lote, fluxo, estado, distribuir }: { lote: LoteCompleto; fluxo: FluxoCompleto | undefined; estado: EstadoLote | null; distribuir: (ids: number[]) => void }) {
  const avisar = useAvisar()
  const [obs, setObs] = useState('')
  const [outra, setOutra] = useState(false)
  const [etapa, setEtapa] = useState<number | null>(null)
  const [expor, setExpor] = useState(false)
  const [ocupado, setOcupado] = useState(false)
  useEffect(() => setEtapa(estado?.sugestao?.id ?? fluxo?.etapas[0]?.id ?? null), [estado, fluxo])

  const aberta = lote.passagens.find((p) => ABERTAS.includes(p.situacao))
  const etapaDe = (p: PassagemLote) => fluxo?.etapas.find((e) => e.id === p.id_fluxo_etapa)
  const naoPuladas = lote.passagens.filter((p) => p.situacao !== 'pulada')
  const ultima = naoPuladas.length ? naoPuladas.reduce((a, b) => (a.id > b.id ? a : b)) : null
  const eAberta = aberta ? etapaDe(aberta) : undefined
  const seguinte = eAberta ? fluxo?.etapas.find((e) => (e.ordem ?? 0) > (eAberta.ordem ?? 0)) : undefined
  const faltam = aberta ? aberta.cargas_total - aberta.cargas_concluidas : 0

  async function rodar(p: Pedido) {
    setOcupado(true)
    try {
      let r: EstadoLote | null = null
      for (const passo of p.passos) r = await enviar<EstadoLote>(passo.caminho, { ...passo.corpo, observacao: obs })
      avisar(`${lote.folha_revisao}: ${p.titulo.toLowerCase()}${r?.etapa ? ` · ${r.etapa}` : ''}. ${resumoPreparo(r?.preparo)}`.trim())
      setObs('')
      setOutra(false)
      // A etapa nova já tem cargas (D-109): o próximo passo é distribuir.
      if (comCargas(r?.preparo).size) distribuir([lote.id])
    } catch (e) {
      avisar((e as Error).message, 'erro')
    } finally {
      setOcupado(false)
    }
  }

  const botoes: Pedido[] = []
  if (aberta?.situacao === 'em_andamento') {
    if (aberta.fase === 'envio_gcq') {
      botoes.push({ titulo: 'Aprovada pela GCQ', passos: [{ caminho: `/api/lote_etapas/${aberta.id}/gcq`, corpo: { resultado: 'aprovada' } }] })
      botoes.push({ titulo: 'Devolvida pela GCQ', passos: [{ caminho: `/api/lote_etapas/${aberta.id}/gcq`, corpo: { resultado: 'devolvida' } }] })
    } else {
      if (seguinte)
        botoes.push({
          titulo: `Concluir e abrir ${seguinte.nome}`,
          passos: [{ caminho: `/api/lote_etapas/${aberta.id}/concluir` }, { caminho: `/api/lotes/${lote.id}/passagens`, corpo: { id_fluxo_etapa: seguinte.id } }],
        })
      botoes.push({ titulo: seguinte ? 'Só concluir' : 'Concluir etapa', passos: [{ caminho: `/api/lote_etapas/${aberta.id}/concluir` }] })
    }
  }
  // Etapa com cargas começa ao distribuir (D-109); só a sem cargas se inicia à mão.
  if (aberta?.situacao === 'pendente' && !aberta.cargas_total) botoes.push({ titulo: 'Iniciar etapa', passos: [{ caminho: `/api/lote_etapas/${aberta.id}/iniciar` }] })
  if (aberta && eAberta && !eAberta.obrigatoria) botoes.push({ titulo: 'Pular etapa', passos: [{ caminho: `/api/lote_etapas/${aberta.id}/pular` }] })
  if (!aberta) {
    if (estado?.sugestao) botoes.push({ titulo: `Abrir ${estado.sugestao.nome}`, passos: [{ caminho: `/api/lotes/${lote.id}/passagens`, corpo: { id_fluxo_etapa: estado.sugestao.id } }] })
    if (ultima?.situacao === 'concluida') botoes.push({ titulo: 'Reabrir a última', passos: [{ caminho: `/api/lote_etapas/${ultima.id}/reabrir` }] })
  }

  let sugestao: React.ReactNode = null
  if (aberta?.situacao === 'em_andamento' && seguinte && aberta.fase !== 'envio_gcq')
    sugestao =
      faltam > 0 ? (
        <>
          quando {faltam === 1 ? 'a' : 'as'} <b>{plural(faltam, 'carga restante', 'cargas restantes')}</b> {faltam === 1 ? 'for concluída' : 'forem concluídas'}, concluir {aberta.etapa} e abrir <b>{seguinte.nome}</b>.
        </>
      ) : (
        <>
          as cargas estão concluídas: concluir {aberta.etapa} e abrir <b>{seguinte.nome}</b>.
        </>
      )
  else if (aberta?.situacao === 'pendente' && aberta.cargas_total) sugestao = <>distribuir a folha: a etapa começa quando alguém receber as cargas.</>
  else if (aberta?.situacao === 'pendente') sugestao = <>a etapa não tem cargas; inicie quando a equipe começar.</>
  else if (!aberta && estado?.sugestao) sugestao = <>abrir <b>{estado.sugestao.nome}</b>, a etapa seguinte do fluxo.</>
  else if (!aberta) sugestao = <>a folha terminou a última etapa do fluxo; não há etapa seguinte.</>

  return (
    <section aria-labelledby="andar" className="flex flex-col gap-3">
      <Titulo>
        <span id="andar">Andar com a folha</span>
      </Titulo>
      {sugestao && (
        <p className="rounded-lg bg-[#EEF3FA] px-3.5 py-3 text-[#1C2F4A]">
          Sugestão do Feixe: {sugestao} Nada anda sozinho: a decisão é sua.
        </p>
      )}
      <label className="flex flex-col gap-1.5 text-[13px] text-texto-2">
        Observação (fica no histórico; obrigatória)
        <Textarea rows={3} value={obs} onChange={(e) => setObs(e.target.value)} placeholder="Ex.: aquisição conferida, segue para o CQ" className="text-sm text-foreground" />
      </label>
      {outra && (
        <div className="flex flex-col gap-2.5 rounded-lg border bg-[#F7F9FB] p-3">
          <label className="flex flex-col gap-1.5 text-[13px]">
            Etapa a abrir
            <Select value={etapa ?? ''} onChange={(e) => setEtapa(Number(e.target.value))}>
              {fluxo?.etapas.map((e) => (
                <option key={e.id} value={e.id}>
                  {e.ordem}. {e.nome}
                  {e.id === estado?.sugestao?.id ? ' (sugerida)' : ''}
                </option>
              ))}
            </Select>
          </label>
          <label className="flex items-start gap-2 text-sm">
            <input type="checkbox" className="mt-1" checked={expor} onChange={(e) => setExpor(e.target.checked)} />
            <span>
              Incluir as correções a fazer
              <span className="block text-xs text-muted-foreground">Mostra a quem executar as ocorrências das passagens anteriores. Sem isso, a revisão é às cegas.</span>
            </span>
          </label>
          <div className="flex justify-end gap-2">
            <Button size="sm" variant="ghost" onClick={() => setOutra(false)}>
              Cancelar
            </Button>
            <Button
              size="sm"
              disabled={ocupado || !obs.trim() || !etapa}
              onClick={() => rodar({ titulo: 'Abrir etapa', passos: [{ caminho: `/api/lotes/${lote.id}/passagens`, corpo: { id_fluxo_etapa: etapa, expor_ocorrencias: expor } }] })}
            >
              Abrir etapa
            </Button>
          </div>
        </div>
      )}
      {!outra && (
        <div className="flex flex-wrap gap-2">
          {botoes.map((b, i) => (
            <Button key={b.titulo} variant={i === 0 ? 'default' : 'outline'} className={i === 0 ? 'font-semibold' : ''} disabled={ocupado || !obs.trim()} onClick={() => rodar(b)}>
              {b.titulo}
            </Button>
          ))}
          {!aberta && (
            <Button variant="outline" onClick={() => setOutra(true)}>
              Outra etapa…
            </Button>
          )}
        </div>
      )}
      <span className="text-xs text-muted-foreground">
        {eAberta?.obrigatoria ? `Pular não aparece: ${eAberta.nome} é obrigatória neste fluxo. ` : ''}
        {aberta ? 'Para repetir ou voltar a uma etapa, conclua ou pule a atual; depois "Outra etapa…" abre qualquer etapa do fluxo.' : '"Outra etapa…" abre qualquer etapa do fluxo (repetir uma revisão, voltar).'}
      </span>
    </section>
  )
}

// Gaveta da folha (D-72, D-103): abre por cima da lista, sem trocar de página; é onde a folha anda pelo fluxo.
export function Gaveta({ id, fluxos, fechar, distribuir }: { id: number; fluxos: FluxoCompleto[]; fechar: () => void; distribuir: (ids: number[]) => void }) {
  const avisar = useAvisar()
  const { conectado, tem, eu } = useSessao()
  const { dados: lote, erro } = useApi<LoteCompleto>(`/api/lotes/${id}`, ['lote', 'carga'])
  const { dados: estado } = useApi<EstadoLote>(`/api/lotes/${id}/estado`, ['lote'])
  const { dados: hist } = useApi<{ itens: Historico[] }>(`/api/lotes/${id}/historico`, ['lote'])
  const fluxo = fluxos.find((f) => f.id === lote?.id_fluxo)
  const atual = lote?.passagens.find((p) => p.id === lote.id_lote_etapa_atual) ?? lote?.passagens.find((p) => ABERTAS.includes(p.situacao))
  const aberta = !!atual && ABERTAS.includes(atual.situacao)
  const supervisor = tem('supervisor') && lote?.uf === eu?.uf

  // Diálogo do Radix (como os outros): prende e devolve o foco, e o Esc fecha só a camada de cima (o Distribuir aberto
  // daqui fecha sem fechar a gaveta).
  return (
    <D.Root open onOpenChange={(v) => !v && fechar()}>
      <D.Portal>
        <D.Overlay className="fixed inset-0 z-40 bg-[#1C2733]/10" />
        <D.Content
          aria-describedby={undefined}
          className="fixed inset-y-0 right-0 z-40 flex w-full max-w-[620px] flex-col gap-6 overflow-auto border-l bg-card px-7 pt-6 pb-10 shadow-[-12px_0_32px_rgba(28,39,51,.08)] outline-none"
        >
        <div className="flex items-start gap-3">
          <div className="flex flex-1 flex-col gap-1">
            <D.Title className="tab text-[26px] font-bold">{lote?.folha_revisao ?? '…'}</D.Title>
            {lote && (
              <span className="text-muted-foreground">
                {lote.tema} · {lote.projeto}
                {fluxo ? ` · fluxo ${fluxo.nome}` : ''}
              </span>
            )}
          </div>
          {lote && (
            <span className="rounded-full px-2.5 py-1 text-xs font-semibold" style={{ background: STATUS[lote.status_nacional].cor, color: ['EM_PRODUCAO', 'PLANEJADA'].includes(lote.status_nacional) ? '#1C2F4A' : '#fff' }}>
              {STATUS[lote.status_nacional].rotulo}
            </span>
          )}
          <button onClick={fechar} aria-label="Fechar" className="grid size-9 place-items-center rounded-lg border hover:bg-accent">
            <X className="size-3.5" />
          </button>
        </div>
        {erro && <p className="text-sm text-destructive">{erro}</p>}
        {lote && (
          <>
            <div className="flex flex-wrap gap-2">
              <Button variant="outline" disabled={!conectado} onClick={() => enviar(`/api/lotes/${id}/zoom`).catch((e) => avisar((e as Error).message, 'erro'))}>
                Ver no QGIS
              </Button>
              {supervisor && aberta && lote.pessoas.some((p) => !p.conta && p.total > p.concluidas) && (
                <Button onClick={() => distribuir([lote.id])}>Distribuir</Button>
              )}
              {supervisor && aberta && (atual?.cargas_total ?? 0) > atual!.cargas_concluidas && (
                <Button
                  variant="outline"
                  disabled={!conectado}
                  title="Para as células sobre o mar ou fora da área a mapear: selecione no QGIS, numa camada de cargas do grupo Feixe, as que não devem existir"
                  onClick={async () => {
                    try {
                      const sel = await enviar<{ ids: number[] }>('/api/qgis/selecao_cargas')
                      if (!sel.ids.length) return avisar('Selecione no QGIS as cargas a tirar (camada de cargas do grupo Feixe).', 'erro')
                      if (!window.confirm(`Tirar ${plural(sel.ids.length, 'carga selecionada', 'cargas selecionadas')} no QGIS? Elas deixam de existir; as concluídas ficam.`)) return
                      const r = await enviar<{ tiradas: number; ficaram: number }>('/api/cargas/descartar', { ids: sel.ids })
                      avisar(`${plural(r.tiradas, 'carga tirada', 'cargas tiradas')}${r.ficaram ? `; ${plural(r.ficaram, 'ficou', 'ficaram')} (concluída ou de outra etapa)` : ''}.`)
                    } catch (e) {
                      avisar((e as Error).message, 'erro')
                    }
                  }}
                >
                  Tirar cargas selecionadas no QGIS
                </Button>
              )}
            </div>

            {fluxo && (
              <section className="flex flex-col gap-2.5">
                <Titulo>Fluxo</Titulo>
                <Trilho fluxo={fluxo} lote={lote} estado={estado} />
              </section>
            )}

            {atual && (
              <section className="flex flex-col gap-3 rounded-[10px] border bg-[#F7F9FB] p-4">
                <div className="flex flex-wrap items-baseline gap-x-2.5 gap-y-1">
                  <h2 className="text-base font-semibold">
                    {atual.etapa}
                    {atual.instancia > 1 ? ` (${atual.instancia}ª)` : ''}
                  </h2>
                  <span className="text-[13px] text-muted-foreground">
                    {atual.situacao === 'em_andamento' && atual.iniciada_em && `em andamento desde ${diaMes(atual.iniciada_em)} · ${plural(diasAtras(atual.iniciada_em) ?? 0, 'dia', 'dias')}`}
                    {atual.situacao === 'pendente' && 'a iniciar'}
                    {atual.situacao === 'concluida' && `concluída em ${diaMes(atual.concluida_em)}, esperando a próxima etapa`}
                    {atual.situacao === 'pulada' && 'pulada, esperando a próxima etapa'}
                  </span>
                </div>
                {atual.cargas_total > 0 ? (
                  <>
                    <div className="flex flex-col gap-1.5">
                      <div className="flex justify-between text-[13px]">
                        <span>
                          <b>{num(atual.cargas_concluidas)}</b> de {num(atual.cargas_total)} cargas concluídas
                        </span>
                        <span style={{ color: lote.pessoas.some((p) => !p.conta) ? COR.alerta : undefined }}>
                          {num(lote.pessoas.filter((p) => !p.conta).reduce((s, p) => s + p.total - p.concluidas, 0))} a atribuir
                        </span>
                      </div>
                      <Barra total={atual.cargas_total} partes={[{ valor: atual.cargas_concluidas, cor: COR.concluida }]} />
                    </div>
                    <table className="w-full border-collapse text-[13px]">
                      <tbody>
                        {lote.pessoas
                          .filter((p) => p.conta)
                          .map((p) => (
                            <tr key={p.conta}>
                              <td className="border-t py-1.5">
                                {p.nome}
                                {p.conta === eu?.conta ? ' (você)' : ''}
                              </td>
                              <td className="tab border-t py-1.5 text-right">
                                {num(p.concluidas)} de {num(p.total)}
                              </td>
                              <td className="border-t py-1.5 pl-3 text-right text-muted-foreground">{p.ultima ? diaMes(p.ultima) : 'ainda não'}</td>
                            </tr>
                          ))}
                      </tbody>
                    </table>
                  </>
                ) : (
                  <div className="flex flex-wrap items-center gap-3 text-[13px] text-muted-foreground">
                    <span>Sem cargas nesta etapa.</span>
                    {aberta && supervisor && atual && (
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={async () => {
                          try {
                            const r = await enviar<Preparo>('/api/lotes/preparar', { lote_etapas: [atual.id] })
                            avisar(resumoPreparo(r) || 'Nada a gerar: a etapa não tem atividade pela grade.')
                            if (comCargas(r).size) distribuir([lote.id])
                          } catch (e) {
                            avisar((e as Error).message, 'erro')
                          }
                        }}
                      >
                        Gerar as cargas
                      </Button>
                    )}
                  </div>
                )}
              </section>
            )}

            {supervisor && <Andar lote={lote} fluxo={fluxo} estado={estado} distribuir={distribuir} />}

            {hist && hist.itens.length > 0 && (
              <section className="flex flex-col gap-2.5">
                <Titulo>Histórico</Titulo>
                <ol className="flex flex-col text-[13px]">
                  {hist.itens.slice(0, 20).map((h, i) => (
                    <li key={i} className="flex flex-col gap-0.5 border-b border-linha py-2.5 last:border-0">
                      <span>
                        <b>{ACAO[h.acao] ?? h.acao}</b> {h.etapa}
                        {h.instancia > 1 ? ` (${h.instancia}ª)` : ''}
                      </span>
                      <span className="text-muted-foreground">
                        {diaMes(h.em)} · {h.por_nome.split(' ')[0]}
                        {h.observacao ? ` · “${h.observacao}”` : ''}
                      </span>
                    </li>
                  ))}
                </ol>
              </section>
            )}
          </>
        )}
        </D.Content>
      </D.Portal>
    </D.Root>
  )
}
