import { useEffect, useMemo, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { Barra, Bloco, COR, Campo, Carregando, Colunas, Conteudo, Fichas, Tabela } from '@/components/ds'
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
          <span className="text-titulo-3 font-semibold">{grupo ? grupo.rotulo : 'Todas as folhas da unidade'}</span>
          <span className="line-clamp-2 text-nota text-muted-foreground" title={descricao}>
            {descricao}
          </span>
        </div>
        {grupo && (
          <div className="flex min-w-[260px] flex-[1_1_280px] flex-col gap-1.5">
            <span className="text-nota">
              <b>{num(grupo.concluidas)}</b> de {num(grupo.total)} {grupo.fase === 'cq' ? 'amostras avaliadas' : 'cargas concluídas'} · {pc(grupo.concluidas, grupo.total)}% ·{' '}
              <span className={grupo.a_atribuir ? 'text-alerta' : undefined}>{num(grupo.a_atribuir)} {grupo.fase === 'cq' ? 'sem avaliador' : 'a atribuir'}</span> · {grupo.fase === 'cq' ? plural(grupo.pessoas, 'avaliador', 'avaliadores') : plural(grupo.pessoas, 'pessoa', 'pessoas')}
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
            <Button variant="tinted" onClick={() => setDialogo('folha')}>
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
        <div role="region" aria-label="Folhas marcadas" className="fixed inset-x-0 bottom-5 z-40 mx-auto flex w-fit max-w-[calc(100%-2rem)] items-center gap-3 rounded-xl bg-card/90 px-4 py-3 shadow-flutuante backdrop-blur">
          <b className="whitespace-nowrap">{plural(marcadosLotes.length, 'folha marcada', 'folhas marcadas')}</b>
          <span className="max-w-[360px] truncate text-texto-2">{marcadosLotes.length <= 5 ? lista(marcadosLotes.map((l) => l.folha_revisao)) : ''}</span>
          <div className="flex shrink-0 gap-2">
            <Button onClick={() => setDistribuir(marcadosLotes.map((l) => l.id))}>
              Distribuir
            </Button>
            <Button variant="outline" onClick={() => setAvancar(marcadosLotes.map((l) => l.id))}>
              Abrir a próxima etapa
            </Button>
            <Button variant="ghost" onClick={() => setMarcados(new Set())}>
              Limpar
            </Button>
          </div>
        </div>
      )}

      <div className="flex flex-wrap items-end gap-2.5">
        <Campo rotulo="Buscar folha">
          <Input type="search" className="w-60" placeholder="MI ou nome (ex.: 2573)" value={busca} onChange={(e) => setBusca(e.target.value)} />
        </Campo>
        <Campo rotulo="Situação">
          <Select className="w-56" value={filtro} onChange={(e) => setFiltro(e.target.value as Filtro)}>
            <option value="">Todas</option>
            <option value="pendente">A iniciar</option>
            <option value="em_andamento">Em andamento</option>
            <option value="parado">Sem conclusão há 7 dias</option>
            {!grupo && <option value="esperando">Esperando a próxima etapa ou encerradas</option>}
          </Select>
        </Campo>
        <Campo rotulo="Responsável">
          <Select className="w-56" value={quem} onChange={(e) => setQuem(e.target.value)}>
            <option value="">Todos</option>
            {responsaveis.map((r) => (
              <option key={r}>{r}</option>
            ))}
          </Select>
        </Campo>
        <span className="pb-2 text-muted-foreground">{plural(itens.length, 'folha', 'folhas')}</span>
      </div>

      <Tabela fixa largura={900}>
          <Colunas larguras={[...(supervisor ? [40] : []), 96, undefined, 300, '17%', 140, 130]} />
          <thead>
            <tr>
              {supervisor && (
                <th className="pr-2">
                  <input
                    type="checkbox"
                    aria-label="Marcar todas"
                    checked={todosMarcados}
                    onChange={() => setMarcados(todosMarcados ? new Set() : new Set(itens.map((l) => l.id)))}
                  />
                </th>
              )}
              <th className={cn(supervisor && 'pl-2')}>Folha</th>
              <th>Etapa</th>
              <th>Cargas concluídas</th>
              <th>Responsáveis</th>
              <th>Última conclusão</th>
              <th className="text-right">{grupo ? 'Na etapa' : 'Status'}</th>
            </tr>
          </thead>
          <tbody>
            {itens.length === 0 && (
              <tr>
                <td colSpan={7} className="text-muted-foreground">
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
                <tr key={l.id} className={cn((marcados.has(l.id) || selecionado === l.id) && 'bg-primary-suave/60')}>
                  {supervisor && (
                    <td className="pr-2">
                      <input type="checkbox" aria-label={`Marcar ${l.folha_revisao}`} checked={marcados.has(l.id)} onChange={() => marcar(l.id)} />
                    </td>
                  )}
                  <td className={cn(supervisor && 'pl-2')}>
                    <a href={href(`supervisao/folhas/${l.id}`, { grupo: grupoQ })} className="tab font-semibold text-primary hover:underline">
                      {l.folha_revisao}
                    </a>
                  </td>
                  <td className="truncate" title={[!grupo && l.tema, l.etapa, l.situacao && (aberta ? SITUACAO[l.situacao] : 'esperando a próxima')].filter(Boolean).join(' · ')}>
                    {!grupo && <span className="text-muted-foreground">{l.tema} · </span>}
                    {l.etapa ?? '—'}
                    {l.situacao && <span className="text-muted-foreground"> · {aberta ? SITUACAO[l.situacao] : 'esperando a próxima'}</span>}
                  </td>
                  <td>
                    {l.cargas_total ? (
                      <div className="flex min-w-0 items-center gap-2.5">
                        <Barra className="w-[90px] shrink-0" altura={6} total={l.cargas_total} partes={[{ valor: l.cargas_concluidas ?? 0, cor: COR.concluida }]} />
                        <span className="tab">
                          {num(l.cargas_concluidas ?? 0)}/{num(l.cargas_total)}
                        </span>
                        <span className="min-w-0 truncate">
                          {!!x?.a_atribuir && <span className="text-alerta">· {num(x.a_atribuir)} {grupo?.fase === 'cq' ? 'sem avaliador' : 'a atribuir'} </span>}
                          {!!x?.na_fila && <span className="text-muted-foreground">· na fila de {(x.fila_de ?? '').split(' ')[0]}</span>}
                        </span>
                      </div>
                    ) : (
                      <span className="text-muted-foreground">{grupo?.fase === 'cq' && aberta ? 'sem amostras: veja na folha o próximo passo' : 'sem cargas'}</span>
                    )}
                  </td>
                  <td className="truncate" title={x?.responsaveis.join(', ')}>{x?.responsaveis.length ? lista(x.responsaveis.map((n) => n.split(' ')[0])) : <span className="text-muted-foreground">—</span>}</td>
                  <td className={cn('truncate', alerta ? 'font-semibold text-alerta' : !x?.ultima && 'text-muted-foreground')}>
                    {aberta ? quando(x?.ultima ?? null) : '—'}
                  </td>
                  <td className="tab text-right">
                    {grupo ? (dias !== null ? plural(dias, 'dia', 'dias') : '—') : <Status s={l.status_nacional} />}
                  </td>
                </tr>
              )
            })}
          </tbody>
      </Tabela>
      <p className="text-nota text-muted-foreground">Em laranja: em andamento e sem conclusão há mais de 7 dias. Clicar na folha abre a gaveta com o andamento e as ações do fluxo.</p>

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
