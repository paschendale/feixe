import { useEffect, useMemo, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { Barra, Bloco, COR, Carregando, Colunas, Conteudo, Fichas } from '@/components/painel'
import type { FluxoCompleto, GrupoAtividade, LotePainel } from '@/lib/api'
import { diasAtras, lista, num, parado, pc, plural, quando } from '@/lib/formato'
import { href, navegar, useRota } from '@/lib/rotas'
import { useSessao } from '@/lib/sessao'
import { SITUACAO, Status } from '@/lib/status'
import { useApi } from '@/lib/useApi'
import { cn } from '@/lib/utils'
import { Distribuir } from '../folhas/Distribuir'
import { NovaFolha } from '../folhas/NovaFolha'
import { NovoLoteLivre } from '../folhas/NovoLoteLivre'
import { ProximaEtapa } from '../folhas/ProximaEtapa'
import { usePainel } from '../inicio/ResumoSupervisao'
import { Gaveta } from './Gaveta'

const ABERTAS = ['pendente', 'em_andamento']

// Ficha que abre sem escolha: a atividade de produção com mais folhas (o CQ é avaliado no QGIS na fase D).
const padrao = (gs: GrupoAtividade[]) => [...gs].sort((a, b) => Number(a.fase === 'cq') - Number(b.fase === 'cq') || b.lotes.length - a.lotes.length)[0] ?? null
type Filtro = '' | 'pendente' | 'em_andamento' | 'parado' | 'esperando'

// Supervisão › Folhas: escolher a atividade em produção (como os subgrupos do QGIS), ver as folhas e decidir para as
// marcadas: distribuir (uma folha por pessoa) ou abrir a próxima etapa. As cargas saem sozinhas quando a etapa abre
// (D-109). Clicar na folha abre a gaveta, onde ela anda pelo fluxo.
export default function Folhas() {
  const { tem } = useSessao()
  const supervisor = tem('supervisor')
  const rota = useRota()
  const { painel, lotes } = usePainel()
  const { dados: fluxos } = useApi<{ itens: FluxoCompleto[] }>('/api/fluxos/completos', ['fluxo'])
  const p = painel.dados
  const todos = useMemo(() => lotes.dados?.itens ?? [], [lotes.dados])
  const grupoQ = rota.query.get('grupo')
  const grupo = grupoQ === 'todas' ? null : (p?.grupos.find((g) => g.chave === grupoQ) ?? (grupoQ ? null : padrao(p?.grupos ?? [])))
  const chaveAtiva = grupo?.chave ?? 'todas'
  const selecionado = rota.partes[1] ? Number(rota.partes[1]) : null

  const [busca, setBusca] = useState('')
  const [filtro, setFiltro] = useState<Filtro>('')
  const [quem, setQuem] = useState('')
  const [marcados, setMarcados] = useState<Set<number>>(new Set())
  const [distribuir, setDistribuir] = useState<number[]>([])
  const [avancar, setAvancar] = useState<number[]>([])
  const [dialogo, setDialogo] = useState<'folha' | 'livre' | null>(null)
  const [fluxoNovas, setFluxoNovas] = useState<number | null>(null)

  const extra = useMemo(() => new Map<number, LotePainel>((p?.lotes ?? []).map((l) => [l.id_lote, l])), [p])
  const aAtribuir = useMemo(() => Object.fromEntries((p?.lotes ?? []).map((l) => [l.id_lote, l.a_atribuir])), [p])
  const doGrupo = useMemo(() => (grupo ? todos.filter((l) => grupo.lotes.includes(l.id)) : todos), [grupo, todos])
  const responsaveis = useMemo(() => [...new Set(doGrupo.flatMap((l) => extra.get(l.id)?.responsaveis ?? []))].sort(), [doGrupo, extra])
  const itens = doGrupo.filter((l) => {
    const x = extra.get(l.id)
    const aberta = ABERTAS.includes(l.situacao ?? '')
    if (busca && !l.folha_revisao.toLowerCase().includes(busca.toLowerCase()) && !l.nome.toLowerCase().includes(busca.toLowerCase())) return false
    if (quem && !(x?.responsaveis ?? []).includes(quem)) return false
    if (filtro === 'pendente' || filtro === 'em_andamento') return l.situacao === filtro
    if (filtro === 'parado') return aberta && (l.cargas_total ?? 0) > 0 && parado(x?.ultima ?? x?.iniciada_em ?? null)
    if (filtro === 'esperando') return !aberta
    return true
  })

  // Vindo do Início ou de Fluxos: ?distribuir=1 abre a distribuição das folhas da atividade com cargas a atribuir (o
  // ?atribuir=1 de antes também); ?novas=<fluxo> abre Novas folhas já com o fluxo.
  useEffect(() => {
    const q = rota.query
    if ((q.get('distribuir') || q.get('atribuir')) && todos.length && p) {
      const alvo = todos.filter((l) => (grupo ? grupo.lotes.includes(l.id) : true) && (aAtribuir[l.id] ?? 0) > 0)
      setDistribuir(alvo.map((l) => l.id))
      navegar(`supervisao/folhas${grupoQ ? `?grupo=${grupoQ}` : ''}`)
    } else if (q.get('novas')) {
      setFluxoNovas(Number(q.get('novas')) || null)
      setDialogo('folha')
      navegar(`supervisao/folhas${grupoQ ? `?grupo=${grupoQ}` : ''}`)
    }
  }, [rota.query, grupo, grupoQ, todos, p, aAtribuir])
  useEffect(() => setMarcados(new Set()), [chaveAtiva])

  const marcar = (id: number) =>
    setMarcados((m) => {
      const n = new Set(m)
      if (n.has(id)) n.delete(id)
      else n.add(id)
      return n
    })
  const marcadosLotes = itens.filter((l) => marcados.has(l.id))
  const todosMarcados = itens.length > 0 && itens.every((l) => marcados.has(l.id))
  const fluxosDoGrupo = grupo ? [...new Set(doGrupo.map((l) => l.id_fluxo))].map((id) => fluxos?.itens.find((f) => f.id === id)).filter(Boolean) : []
  const descricao = grupo
    ? fluxosDoGrupo.map((f) => `Fluxo ${f!.nome}: ${f!.etapas.map((e) => e.nome).join(' → ')}`).join(' · ') || grupo.tema
    : 'em produção, esperando a próxima etapa e encerradas, de todos os temas'

  if (!p || !lotes.dados)
    return (
      <Conteudo>
        <Carregando erro={painel.erro ?? lotes.erro} />
      </Conteudo>
    )

  return (
    <Conteudo>
      <Fichas
        rotulo="Atividade em produção"
        ativa={chaveAtiva}
        escolher={(id) => navegar(`supervisao/folhas?grupo=${id}`)}
        fichas={[
          ...p.grupos.map((g) => ({ id: g.chave, rotulo: g.rotulo, contagem: num(g.lotes.length) })),
          { id: 'todas', rotulo: 'Todas as folhas', contagem: num(todos.length), todas: true },
        ]}
      />

      <Bloco className="min-h-[100px] flex-row flex-wrap items-center gap-x-7 gap-y-3 px-5 py-4">
        <div className="flex min-w-[300px] flex-[1_1_360px] flex-col gap-0.5">
          <span className="text-base font-semibold">{grupo ? grupo.rotulo : 'Todas as folhas da unidade'}</span>
          <span className="line-clamp-2 text-[13px] text-muted-foreground" title={descricao}>
            {descricao}
          </span>
        </div>
        {grupo && (
          <div className="flex min-w-[260px] flex-[1_1_280px] flex-col gap-1.5">
            <span className="text-[13px]">
              <b>{num(grupo.concluidas)}</b> de {num(grupo.total)} {grupo.fase === 'cq' ? 'amostras avaliadas' : 'cargas concluídas'} · {pc(grupo.concluidas, grupo.total)}% ·{' '}
              <span style={{ color: grupo.a_atribuir ? COR.alerta : undefined }}>{num(grupo.a_atribuir)} {grupo.fase === 'cq' ? 'sem avaliador' : 'a atribuir'}</span> · {grupo.fase === 'cq' ? plural(grupo.pessoas, 'avaliador', 'avaliadores') : plural(grupo.pessoas, 'pessoa', 'pessoas')}
            </span>
            <Barra
              total={grupo.total}
              partes={[
                { valor: grupo.concluidas, cor: COR.concluida, rotulo: grupo.fase === 'cq' ? 'avaliadas' : 'concluídas' },
                { valor: grupo.com_alguem, cor: COR.comAlguem, rotulo: grupo.fase === 'cq' ? 'com avaliador' : 'com alguém' },
              ]}
            />
          </div>
        )}
        {supervisor && (
          <div className="flex gap-2">
            <Button variant="outline" className="border-ibge font-semibold text-ibge" onClick={() => setDialogo('folha')}>
              Novas folhas
            </Button>
            <Button variant="outline" onClick={() => setDialogo('livre')}>
              Lote livre
            </Button>
          </div>
        )}
      </Bloco>

      {/* Barra das marcadas: flutua sobre a lista, sem empurrar os filtros e a tabela para baixo do ponteiro. */}
      {supervisor && marcadosLotes.length > 0 && (
        <div role="region" aria-label="Folhas marcadas" className="fixed inset-x-0 bottom-5 z-40 mx-auto flex w-fit max-w-[calc(100%-2rem)] items-center gap-3 rounded-xl border border-[#C9D7EA] bg-[#EEF3FA]/95 px-4 py-3 shadow-lg backdrop-blur">
          <b className="whitespace-nowrap">{plural(marcadosLotes.length, 'folha marcada', 'folhas marcadas')}</b>
          <span className="max-w-[360px] truncate text-texto-2">{marcadosLotes.length <= 5 ? lista(marcadosLotes.map((l) => l.folha_revisao)) : ''}</span>
          <div className="flex shrink-0 gap-2">
            <Button className="font-semibold" onClick={() => setDistribuir(marcadosLotes.map((l) => l.id))}>
              Distribuir
            </Button>
            <Button variant="outline" className="bg-card" onClick={() => setAvancar(marcadosLotes.map((l) => l.id))}>
              Abrir a próxima etapa
            </Button>
            <button type="button" className="h-9 px-3 text-texto-2 hover:underline" onClick={() => setMarcados(new Set())}>
              Limpar
            </button>
          </div>
        </div>
      )}

      <div className="flex flex-wrap items-end gap-2.5">
        <label className="flex flex-col gap-1 text-xs text-muted-foreground">
          Buscar folha
          <Input type="search" className="h-9 w-60 bg-card" placeholder="MI ou nome (ex.: 2573)" value={busca} onChange={(e) => setBusca(e.target.value)} />
        </label>
        <label className="flex flex-col gap-1 text-xs text-muted-foreground">
          Situação
          <Select className="w-56 bg-card" value={filtro} onChange={(e) => setFiltro(e.target.value as Filtro)}>
            <option value="">Todas</option>
            <option value="pendente">A iniciar</option>
            <option value="em_andamento">Em andamento</option>
            <option value="parado">Sem conclusão há 7 dias</option>
            {!grupo && <option value="esperando">Esperando a próxima etapa ou encerradas</option>}
          </Select>
        </label>
        <label className="flex flex-col gap-1 text-xs text-muted-foreground">
          Responsável
          <Select className="w-56 bg-card" value={quem} onChange={(e) => setQuem(e.target.value)}>
            <option value="">Todos</option>
            {responsaveis.map((r) => (
              <option key={r}>{r}</option>
            ))}
          </Select>
        </label>
        <span className="pb-2 text-sm text-muted-foreground">{plural(itens.length, 'folha', 'folhas')}</span>
      </div>

      <div className="overflow-x-auto rounded-[10px] border bg-card">
        <table className="w-full min-w-[900px] table-fixed border-collapse text-sm">
          <Colunas larguras={[...(supervisor ? [40] : []), 96, undefined, 300, '17%', 140, 130]} />
          <thead>
            <tr className="text-left text-xs text-muted-foreground">
              {supervisor && (
                <th className="border-b py-3 pr-2 pl-4">
                  <input
                    type="checkbox"
                    aria-label="Marcar todas"
                    checked={todosMarcados}
                    onChange={() => setMarcados(todosMarcados ? new Set() : new Set(itens.map((l) => l.id)))}
                  />
                </th>
              )}
              <th className={cn('border-b px-2 py-3 font-medium', !supervisor && 'pl-4')}>Folha</th>
              <th className="border-b px-2 py-3 font-medium">Etapa</th>
              <th className="border-b px-2 py-3 font-medium">Cargas concluídas</th>
              <th className="border-b px-2 py-3 font-medium">Responsáveis</th>
              <th className="border-b px-2 py-3 font-medium">Última conclusão</th>
              <th className="border-b py-3 pr-4 pl-2 text-right font-medium">{grupo ? 'Na etapa' : 'Status'}</th>
            </tr>
          </thead>
          <tbody>
            {itens.length === 0 && (
              <tr>
                <td colSpan={7} className="px-4 py-3 text-muted-foreground">
                  {todos.length ? 'Nenhuma folha com esses filtros.' : supervisor ? 'A unidade ainda não tem folhas no Feixe: use "Novas folhas" acima.' : 'A unidade ainda não tem folhas no Feixe.'}
                </td>
              </tr>
            )}
            {itens.map((l) => {
              const x = extra.get(l.id)
              const aberta = ABERTAS.includes(l.situacao ?? '')
              const alerta = grupo?.fase !== 'cq' && aberta && (l.cargas_total ?? 0) > 0 && l.situacao === 'em_andamento' && parado(x?.ultima ?? x?.iniciada_em ?? null)
              const dias = diasAtras(x?.iniciada_em ?? null)
              return (
                <tr key={l.id} className={cn('border-b border-linha last:border-0 hover:bg-[#F7F9FB]', (marcados.has(l.id) || selecionado === l.id) && 'bg-[#F4F8FD]')}>
                  {supervisor && (
                    <td className="py-3 pr-2 pl-4">
                      <input type="checkbox" aria-label={`Marcar ${l.folha_revisao}`} checked={marcados.has(l.id)} onChange={() => marcar(l.id)} />
                    </td>
                  )}
                  <td className={cn('px-2 py-3', !supervisor && 'pl-4')}>
                    <a href={href(`supervisao/folhas/${l.id}`, { grupo: grupoQ })} className="tab font-semibold text-ibge hover:underline">
                      {l.folha_revisao}
                    </a>
                  </td>
                  <td className="truncate px-2 py-3" title={[!grupo && l.tema, l.etapa, l.situacao && (aberta ? SITUACAO[l.situacao] : 'esperando a próxima')].filter(Boolean).join(' · ')}>
                    {!grupo && <span className="text-muted-foreground">{l.tema} · </span>}
                    {l.etapa ?? '—'}
                    {l.situacao && <span className="text-muted-foreground"> · {aberta ? SITUACAO[l.situacao] : 'esperando a próxima'}</span>}
                  </td>
                  <td className="px-2 py-3">
                    {l.cargas_total ? (
                      <div className="flex min-w-0 items-center gap-2.5">
                        <Barra className="w-[90px] shrink-0" altura={6} total={l.cargas_total} partes={[{ valor: l.cargas_concluidas ?? 0, cor: COR.concluida }]} />
                        <span className="tab">
                          {num(l.cargas_concluidas ?? 0)}/{num(l.cargas_total)}
                        </span>
                        <span className="min-w-0 truncate">
                          {!!x?.a_atribuir && <span style={{ color: COR.alerta }}>· {num(x.a_atribuir)} {grupo?.fase === 'cq' ? 'sem avaliador' : 'a atribuir'} </span>}
                          {!!x?.na_fila && <span className="text-muted-foreground">· na fila de {(x.fila_de ?? '').split(' ')[0]}</span>}
                        </span>
                      </div>
                    ) : (
                      <span className="text-muted-foreground">{grupo?.fase === 'cq' && aberta ? 'sem amostras: veja na folha o próximo passo' : 'sem cargas'}</span>
                    )}
                  </td>
                  <td className="truncate px-2 py-3" title={x?.responsaveis.join(', ')}>{x?.responsaveis.length ? lista(x.responsaveis.map((n) => n.split(' ')[0])) : <span className="text-muted-foreground">—</span>}</td>
                  <td className={cn('truncate px-2 py-3', alerta && 'font-semibold')} style={{ color: alerta ? COR.alerta : x?.ultima ? undefined : 'var(--muted-foreground)' }}>
                    {aberta ? quando(x?.ultima ?? null) : '—'}
                  </td>
                  <td className="tab py-3 pr-4 pl-2 text-right">
                    {grupo ? (dias !== null ? plural(dias, 'dia', 'dias') : '—') : <Status s={l.status_nacional} />}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <p className="text-[13px] text-muted-foreground">Em laranja: em andamento e sem conclusão há mais de 7 dias. Clicar na folha abre a gaveta com o andamento e as ações do fluxo.</p>

      {selecionado && (
        <Gaveta
          key={selecionado}
          id={selecionado}
          fluxos={fluxos?.itens ?? []}
          fechar={() => navegar(`supervisao/folhas${grupoQ ? `?grupo=${grupoQ}` : ''}`)}
          distribuir={(ids) => setDistribuir(ids)}
        />
      )}

      <Distribuir
        lotes={distribuir}
        fechar={(feito) => {
          setDistribuir([])
          if (feito) setMarcados(new Set())
        }}
      />
      <ProximaEtapa
        lotes={avancar}
        fechar={(abertas) => {
          setAvancar([])
          if (abertas) setMarcados(new Set())
          if (abertas?.length) setDistribuir(abertas)
        }}
      />
      <NovaFolha
        aberto={dialogo === 'folha'}
        fluxoInicial={fluxoNovas}
        fechar={(criados) => {
          setDialogo(null)
          setFluxoNovas(null)
          if (criados?.length) setDistribuir(criados)
        }}
      />
      <NovoLoteLivre
        aberto={dialogo === 'livre'}
        fechar={(criados) => {
          setDialogo(null)
          if (criados?.length) setDistribuir(criados)
        }}
      />
    </Conteudo>
  )
}
