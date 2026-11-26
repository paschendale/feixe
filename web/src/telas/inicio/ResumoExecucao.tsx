import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Anel, Barra, BarrasDia, Bloco, COR, LinhaLista, Lista, Metrica, Rotulo, Secao, Segmentado, Selo, Vazio } from '@/components/ds'
import type { FolhaCorrecao, Passagem, ResumoCQ } from '@/lib/api'
import type { ResumoCargas } from '@/lib/api'
import { lista, num, pc, plural } from '@/lib/formato'
import { href } from '@/lib/rotas'
import { useApi } from '@/lib/useApi'
import { ABERTAS, Continuar, ContinuarAmostra, Preparando, fraseCQ, partesCQ, pendentesDe, porPassagem, usePainelExecucao, usePorDia } from '../execucao/comum'
import { MeusConflitos } from '../execucao/MeusConflitos'
import { ParaCiencia } from '../execucao/ParaCiencia'

// Uma folha com trabalho meu: produção (cargas), CQ (amostras, uma linha por elemento) ou correção de inspeção.
type Item = { tipo: 'carga'; p: Passagem } | { tipo: 'cq'; linhas: ResumoCQ[] } | { tipo: 'correcao'; f: FolhaCorrecao }
type Filtro = 'todas' | 'carga' | 'cq' | 'correcao'

const somaCQ = (ls: ResumoCQ[]) => ({
  minhas: ls.reduce((s, r) => s + r.minhas, 0),
  avaliadas: ls.reduce((s, r) => s + r.avaliadas, 0),
  naoConformes: ls.reduce((s, r) => s + r.nao_conformes, 0),
  pendentes: ls.reduce((s, r) => s + r.pendentes, 0),
})

const chave = (i: Item) => (i.tipo === 'carga' ? `c-${i.p.id_lote_etapa}` : i.tipo === 'cq' ? `q-${i.linhas[0].id_lote_etapa}` : `r-${i.f.id_lote_etapa}`)

function cabecalho(i: Item) {
  if (i.tipo === 'carga') return { folha: i.p.folha_revisao, sub: `${i.p.tema} · ${i.p.etapa}` }
  const x = i.tipo === 'cq' ? i.linhas[0] : i.f
  return { folha: x.folha_revisao, sub: [x.tema, x.etapa].filter(Boolean).join(' · ') }
}

// Andamento de um item em números: feito, total e as partes do anel.
function andamento(i: Item) {
  if (i.tipo === 'carga') return { feito: i.p.concluidas, total: i.p.total, partes: [{ valor: i.p.concluidas, cor: COR.concluida }], unidade: 'cargas' }
  if (i.tipo === 'correcao') return { feito: i.f.tratadas, total: i.f.total, partes: [{ valor: i.f.tratadas, cor: COR.concluida }], unidade: 'ocorrências' }
  const s = somaCQ(i.linhas)
  return { feito: s.avaliadas, total: s.minhas, partes: partesCQ({ avaliadas: s.avaliadas, nao_conformes: s.naoConformes }), unidade: 'amostras' }
}

function destino(i: Item) {
  if (i.tipo === 'carga') return href('execucao/cargas', { folha: i.p.id_lote_etapa })
  if (i.tipo === 'cq') return href('execucao/cq', { folha: i.linhas[0].id_lote_etapa })
  return href('execucao/correcao', { folha: i.f.id_lote })
}

// O que falta e o que o item espera, quando não há mais nada para a pessoa fazer.
function situacao(i: Item): string | null {
  if (i.tipo === 'carga') {
    const falta = pendentesDe(i.p)
    if (falta > 0 && !ABERTAS.includes(i.p.situacao)) return `A etapa foi encerrada pelo supervisor com ${plural(falta, 'carga pendente', 'cargas pendentes')} suas.`
    if (falta === 0) return 'Sua parte terminou. O lote segue quando o supervisor abrir a próxima etapa.'
    return null
  }
  if (i.tipo === 'cq') {
    const f = i.linhas[0]
    if (!f.aberta) return 'A etapa de CQ foi encerrada pelo supervisor.'
    if (somaCQ(i.linhas).pendentes === 0) return 'Lote avaliado: o supervisor decide aprovar ou nova revisão.'
    return null
  }
  return i.f.pendentes > 0 ? null : 'Todas as ocorrências tratadas: o supervisor decide o próximo passo.'
}

function pendente(i: Item) {
  if (i.tipo === 'carga') return pendentesDe(i.p) > 0 && ABERTAS.includes(i.p.situacao)
  if (i.tipo === 'cq') return i.linhas[0].aberta && somaCQ(i.linhas).pendentes > 0
  return i.f.pendentes > 0
}

function Acao({ i, compacto }: { i: Item; compacto?: boolean }) {
  if (!pendente(i)) return null
  if (i.tipo === 'carga') return <Continuar idLote={i.p.id_lote} compacto={compacto} />
  if (i.tipo === 'cq') return <ContinuarAmostra idLote={i.linhas[0].id_lote} compacto={compacto} />
  return compacto ? null : (
    <Button asChild>
      <a href={destino(i)}>Tratar as ocorrências</a>
    </Button>
  )
}

// A próxima coisa a fazer: a folha em destaque, com o anel, o detalhe (os elementos do CQ) e a única ação primária
// da tela.
function Proxima({ i }: { i: Item }) {
  const { folha, sub } = cabecalho(i)
  const a = andamento(i)
  const verRotulo = i.tipo === 'carga' ? 'Ver as cargas' : i.tipo === 'cq' ? 'Ver as amostras' : 'Ver as ocorrências'
  return (
    <Bloco className="gap-5 p-6">
      <div className="flex items-center gap-5">
        <Anel partes={a.partes} total={a.total} tamanho={64} espessura={7} centro={<span className="text-nota">{pc(a.feito, a.total)}%</span>} rotulo={`${num(a.feito)} de ${num(a.total)} ${a.unidade}`} />
        <div className="flex min-w-0 flex-1 flex-col gap-0.5">
          <Rotulo className="px-0">Continuar</Rotulo>
          <span className="tab text-titulo-1 font-bold">{folha}</span>
          <span className="text-muted-foreground">
            {sub} · <span className="tab">{num(a.feito)}</span> de <span className="tab">{num(a.total)}</span> {i.tipo === 'carga' ? 'das suas cargas concluídas' : i.tipo === 'cq' ? 'das suas amostras avaliadas' : 'ocorrências tratadas'}
          </span>
        </div>
        <div className="flex shrink-0 flex-wrap items-center justify-end gap-2">
          <Button variant="outline" asChild>
            <a href={destino(i)}>{verRotulo}</a>
          </Button>
          <Acao i={i} />
        </div>
      </div>
      {i.tipo === 'cq' && (
        <div className="grid grid-cols-[repeat(auto-fill,minmax(220px,1fr))] gap-x-6 gap-y-3 border-t border-linha pt-4">
          {i.linhas.map((r) => (
            <div key={r.id_atividade} className="flex flex-col gap-1.5" title={fraseCQ(r)}>
              <div className="flex items-baseline justify-between gap-2 text-nota">
                <span className="truncate font-medium">{r.elemento ?? r.atividade}</span>
                <span className="tab shrink-0 text-muted-foreground">
                  {num(r.avaliadas)}/{num(r.minhas)}
                  {r.plano.ac != null && <> · aceita {num(r.plano.ac)}</>}
                </span>
              </div>
              <Barra partes={partesCQ(r)} total={r.minhas} altura={4} />
              {r.nao_conformes > 0 && <Selo tom="alerta">{plural(r.nao_conformes, 'não conforme', 'não conformes')}</Selo>}
            </div>
          ))}
        </div>
      )}
    </Bloco>
  )
}

// Linha de uma folha na lista: anel, folha, tema · etapa, o andamento em números e "Continuar" compacto.
function Linha({ i }: { i: Item }) {
  const { folha, sub } = cabecalho(i)
  const a = andamento(i)
  const nc = i.tipo === 'cq' ? somaCQ(i.linhas).naoConformes : 0
  const obs = situacao(i)
  const dica = i.tipo === 'cq' ? i.linhas.map((r) => `${r.elemento ?? r.atividade}: ${fraseCQ(r)}`).join('\n') : undefined
  return (
    <LinhaLista
      href={destino(i)}
      inicio={<Anel partes={a.partes} total={a.total} tamanho={30} espessura={3.5} rotulo={`${pc(a.feito, a.total)}%`} />}
      titulo={<span className="tab">{folha}</span>}
      sub={obs ?? sub}
      fim={
        <span className="flex items-center gap-2.5" title={dica}>
          {nc > 0 && <Selo tom="alerta">{plural(nc, 'não conforme', 'não conformes')}</Selo>}
          {i.tipo === 'cq' && i.linhas.length > 1 && <span className="hidden sm:inline">{plural(i.linhas.length, 'elemento', 'elementos')}</span>}
          <span className="tab min-w-[84px] text-right">
            <span className="font-medium text-foreground">{num(a.feito)}</span>/{num(a.total)} {a.unidade}
          </span>
        </span>
      }
      acoes={<div className="w-8">{<Acao i={i} compacto />}</div>}
    />
  )
}

// Execução no Início: as métricas do dia, a próxima folha em destaque e a lista de todas as folhas com trabalho meu.
export function ResumoExecucao({ comTitulo }: { comTitulo: boolean }) {
  const { dados } = useApi<ResumoCargas>('/api/cargas/resumo', ['carga', 'lote'])
  const { dados: painel } = usePainelExecucao()
  const { dias, hoje } = usePorDia()
  const [filtro, setFiltro] = useState<Filtro>('todas')
  if (!dados || !painel) return null
  if (dados.preparando || painel.preparando) return comTitulo ? <Secao titulo="Execução" sub="as cargas que estão com você"><Preparando /></Secao> : <Preparando />

  // As passagens de CQ aparecem como amostras, não como cargas.
  const cqSet = new Set([...painel.cq.map((c) => c.id_lote_etapa), ...painel.correcao.filter((c) => c.so_folha).map((c) => c.id_lote_etapa)])
  const passagens = dados.passagens.filter((p) => !cqSet.has(p.id_lote_etapa))
  const folhasCQ = porPassagem(painel.cq).filter((ls) => ls[0].aberta)
  const itens: Item[] = [
    ...painel.correcao.map((f) => ({ tipo: 'correcao' as const, f })),
    ...passagens.map((p) => ({ tipo: 'carga' as const, p })),
    ...folhasCQ.map((linhas) => ({ tipo: 'cq' as const, linhas })),
  ]
  // Pendentes primeiro (na ordem: correção, produção, CQ), depois o que espera o supervisor.
  const ordenados = [...itens.filter(pendente), ...itens.filter((i) => !pendente(i))]
  const proxima = ordenados.find(pendente) ?? null
  const resto = ordenados.filter((i) => i !== proxima)

  const pendentesProducao = passagens.filter((p) => ABERTAS.includes(p.situacao)).reduce((s, p) => s + pendentesDe(p), 0)
  const folhasProducao = passagens.filter((p) => pendentesDe(p) > 0 && ABERTAS.includes(p.situacao))
  const cqComPendentes = folhasCQ.filter((ls) => somaCQ(ls).pendentes > 0)
  const amostrasPendentes = cqComPendentes.reduce((s, ls) => s + somaCQ(ls).pendentes, 0)
  const aTratar = painel.correcao.reduce((s, f) => s + f.pendentes, 0)
  const ciencia = painel.ciencia.pendentes.length

  const contagem = (t: Filtro) => (t === 'todas' ? resto.length : resto.filter((i) => i.tipo === t).length)
  const opcoes = (
    [
      { id: 'todas', rotulo: 'Todas' },
      { id: 'carga', rotulo: 'Produção' },
      { id: 'cq', rotulo: 'CQ' },
      { id: 'correcao', rotulo: 'Correção' },
    ] as { id: Filtro; rotulo: string }[]
  )
    .filter((o) => o.id === 'todas' || contagem(o.id) > 0)
    .map((o) => ({ ...o, contagem: num(contagem(o.id)) }))
  const tiposPresentes = opcoes.length - 1
  const visiveis = filtro === 'todas' ? resto : resto.filter((i) => i.tipo === filtro)

  const corpo = (
    <>
      <div className="grid grid-cols-[repeat(auto-fit,minmax(220px,1fr))] gap-4">
        <Metrica
          valor={pendentesProducao}
          rotulo={pendentesProducao === 1 ? 'carga pendente' : 'cargas pendentes'}
          detalhe={folhasProducao.length ? (folhasProducao.length <= 3 ? lista(folhasProducao.map((p) => p.folha_revisao)) : plural(folhasProducao.length, 'lote', 'lotes')) : 'nenhum lote de produção com você'}
        />
        {(amostrasPendentes > 0 || folhasCQ.length > 0) && (
          <Metrica valor={amostrasPendentes} rotulo={amostrasPendentes === 1 ? 'amostra de CQ para avaliar' : 'amostras de CQ para avaliar'} detalhe={plural(cqComPendentes.length, 'lote', 'lotes')} />
        )}
        {aTratar > 0 && <Metrica valor={aTratar} tom="alerta" rotulo={aTratar === 1 ? 'ocorrência para tratar' : 'ocorrências para tratar'} detalhe="na correção de inspeção" />}
        <Metrica valor={hoje} rotulo={hoje === 1 ? 'concluída hoje' : 'concluídas hoje'}>
          <div className="mt-2 flex items-end gap-3">
            <BarrasDia dias={dias} altura={28} className="flex-1" />
            <span className="text-legenda text-muted-foreground">10 dias</span>
          </div>
        </Metrica>
      </div>

      <MeusConflitos />
      {ciencia > 0 && (
        <div className="flex flex-col gap-2">
          <div className="flex flex-wrap items-baseline gap-x-3">
            <Rotulo>Para ciência</Rotulo>
            <span className="text-nota text-muted-foreground">o retorno do controle de qualidade sobre as suas cargas; não pede correção</span>
          </div>
          <ParaCiencia dados={painel.ciencia} limite={2} />
        </div>
      )}

      {proxima ? <Proxima i={proxima} /> : !itens.length && <Bloco><Vazio>Nenhuma carga com você agora. O supervisor atribui as cargas.</Vazio></Bloco>}

      {resto.length > 0 && (
        <div className="flex flex-col gap-2.5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <Rotulo>{proxima ? 'Os outros lotes' : 'Seus lotes'}</Rotulo>
            {tiposPresentes > 1 && <Segmentado rotulo="Tipo de trabalho" opcoes={opcoes} ativa={filtro} escolher={setFiltro} />}
          </div>
          <Lista>
            {visiveis.map((i) => (
              <Linha key={chave(i)} i={i} />
            ))}
          </Lista>
        </div>
      )}
    </>
  )
  if (!comTitulo) return <section aria-label="Seus lotes" className="flex flex-col gap-6">{corpo}</section>
  return (
    <Secao titulo="Execução" sub="as cargas que estão com você" link={{ href: '#/execucao', rotulo: 'Abrir Execução' }}>
      {corpo}
    </Secao>
  )
}
