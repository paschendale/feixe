import { Button } from '@/components/ui/button'
import { Barra, Bloco, COR, Secao } from '@/components/painel'
import type { FolhaCorrecao, Passagem, ResumoCargas, ResumoCQ } from '@/lib/api'
import { lista, num, pc, plural } from '@/lib/formato'
import { href } from '@/lib/rotas'
import { useApi } from '@/lib/useApi'
import { ABERTAS, Continuar, ContinuarAmostra, Preparando, Producao, fraseCQ, partesCQ, pendentesDe, porPassagem, usePainelExecucao, usePorDia } from '../execucao/comum'
import { MeusConflitos } from '../execucao/MeusConflitos'
import { ParaCiencia } from '../execucao/ParaCiencia'

function CartaoFolha({ p, principal }: { p: Passagem; principal: boolean }) {
  const aberta = ABERTAS.includes(p.situacao)
  const falta = pendentesDe(p)
  return (
    <Bloco className={principal ? 'flex-[2_1_420px]' : 'flex-[1_1_260px]'}>
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="tab text-lg font-bold">{p.folha_revisao}</span>
        <span className="text-muted-foreground">
          {p.tema} · {p.etapa}
        </span>
      </div>
      <div className="flex flex-col gap-1.5">
        <div className="flex justify-between text-[13px]">
          <span>
            <b>{num(p.concluidas)}</b> de {num(p.total)} {principal ? 'das suas cargas concluídas' : 'concluídas'}
          </span>
          <span className="tab">{pc(p.concluidas, p.total)}%</span>
        </div>
        <Barra partes={[{ valor: p.concluidas, cor: COR.concluida }]} total={p.total} />
      </div>
      {falta > 0 && aberta && (
        <div className="mt-1 flex flex-wrap gap-2.5">
          <Continuar idLote={p.id_lote} />
          {principal && (
            <Button variant="outline" asChild>
              <a href={href('execucao/cargas', { folha: p.id_lote_etapa })}>Ver as cargas</a>
            </Button>
          )}
        </div>
      )}
      {falta > 0 && !aberta && <span className="text-[13px]">A etapa foi encerrada pelo supervisor com {plural(falta, 'carga pendente', 'cargas pendentes')} suas.</span>}
      {falta === 0 && <span className="text-[13px]">Sua parte terminou. A folha segue quando o supervisor abrir a próxima etapa.</span>}
    </Bloco>
  )
}

// Folha em CQ com amostras minhas (D3d): o andamento por elemento e "Continuar no QGIS" na próxima amostra.
function CartaoCQ({ linhas, principal }: { linhas: ResumoCQ[]; principal: boolean }) {
  const f = linhas[0]
  const pendentes = linhas.reduce((s, r) => s + r.pendentes, 0)
  return (
    <Bloco className={principal ? 'flex-[2_1_420px]' : 'flex-[1_1_260px]'}>
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="tab text-lg font-bold">{f.folha_revisao}</span>
        <span className="text-muted-foreground">{[f.tema, f.etapa].filter(Boolean).join(' · ')}</span>
      </div>
      <div className="flex flex-col gap-2">
        {linhas.map((r) => (
          <div key={r.id_atividade} className="flex flex-col gap-1">
            <span className="text-[13px]">
              <b>{r.elemento ?? r.atividade}</b>: {fraseCQ(r)}
            </span>
            <Barra partes={partesCQ(r)} total={r.minhas} altura={6} />
          </div>
        ))}
      </div>
      {f.aberta && pendentes > 0 && (
        <div className="mt-1 flex flex-wrap gap-2.5">
          <ContinuarAmostra idLote={f.id_lote} />
          <Button variant="outline" asChild>
            <a href={href('execucao/cq', { folha: f.id_lote_etapa })}>Ver as amostras</a>
          </Button>
        </div>
      )}
      {f.aberta && pendentes === 0 && <span className="text-[13px]">Folha avaliada: o supervisor decide aprovar ou nova revisão.</span>}
      {!f.aberta && <span className="text-[13px] text-muted-foreground">A etapa de CQ foi encerrada pelo supervisor.</span>}
    </Bloco>
  )
}

// Folha na correção de inspeção (D5): as ocorrências tratadas de todas as revisões e o caminho para a varredura.
function CartaoCorrecao({ f, principal }: { f: FolhaCorrecao; principal: boolean }) {
  return (
    <Bloco className={principal ? 'flex-[2_1_420px]' : 'flex-[1_1_260px]'}>
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="tab text-lg font-bold">{f.folha_revisao}</span>
        <span className="text-muted-foreground">{[f.tema, f.etapa].filter(Boolean).join(' · ')}</span>
      </div>
      <div className="flex flex-col gap-1.5">
        <div className="flex justify-between text-[13px]">
          <span>
            <b>{num(f.tratadas)}</b> de {plural(f.total, 'ocorrência tratada', 'ocorrências tratadas')}
          </span>
          <span className="tab">{pc(f.tratadas, f.total)}%</span>
        </div>
        <Barra partes={[{ valor: f.tratadas, cor: COR.concluida }]} total={Math.max(f.total, 1)} />
      </div>
      {f.pendentes > 0 ? (
        <div className="mt-1 flex flex-wrap gap-2.5">
          <Button asChild className="font-semibold">
            <a href={href('execucao/correcao', { folha: f.id_lote })}>Tratar as ocorrências</a>
          </Button>
        </div>
      ) : (
        <span className="text-[13px]">Todas as ocorrências tratadas: o supervisor decide o próximo passo.</span>
      )}
    </Bloco>
  )
}

// Execução no Início: frase, as folhas com "Continuar no QGIS" (produção e CQ), o que está para ciência e as
// conclusões dos últimos dias.
export function ResumoExecucao({ comTitulo }: { comTitulo: boolean }) {
  const { dados } = useApi<ResumoCargas>('/api/cargas/resumo', ['carga', 'lote'])
  const { dados: painel } = usePainelExecucao()
  const { dias, hoje } = usePorDia()
  if (!dados || !painel) return null
  if (dados.preparando || painel.preparando) return comTitulo ? <Secao titulo="Execução" sub="as cargas que estão com você"><Preparando /></Secao> : <Preparando />
  // As passagens de CQ aparecem como amostras (CartaoCQ), não como cargas.
  const cqSet = new Set([...painel.cq.map((c) => c.id_lote_etapa), ...painel.correcao.filter((c) => c.so_folha).map((c) => c.id_lote_etapa)])
  const passagens = dados.passagens.filter((p) => !cqSet.has(p.id_lote_etapa))
  const correcao = painel.correcao
  const aTratar = correcao.reduce((s, f) => s + f.pendentes, 0)
  const comPendentes = passagens.filter((p) => pendentesDe(p) > 0 && ABERTAS.includes(p.situacao))
  const outras = passagens.filter((p) => !comPendentes.includes(p))
  const pendentesProducao = passagens.reduce((s, p) => s + pendentesDe(p), 0)
  const folhasCQ = porPassagem(painel.cq)
  const cqComPendentes = folhasCQ.filter((ls) => ls[0].aberta && ls.some((r) => r.pendentes > 0))
  const cqOutras = folhasCQ.filter((ls) => ls[0].aberta && !cqComPendentes.includes(ls))
  const amostrasPendentes = cqComPendentes.reduce((s, ls) => s + ls.reduce((t, r) => t + r.pendentes, 0), 0)
  const cartoes: ({ tipo: 'carga'; p: Passagem } | { tipo: 'cq'; linhas: ResumoCQ[] } | { tipo: 'correcao'; f: FolhaCorrecao })[] = [
    ...correcao.filter((f) => f.pendentes > 0).map((f) => ({ tipo: 'correcao' as const, f })),
    ...comPendentes.map((p) => ({ tipo: 'carga' as const, p })),
    ...cqComPendentes.map((linhas) => ({ tipo: 'cq' as const, linhas })),
    ...outras.map((p) => ({ tipo: 'carga' as const, p })),
    ...cqOutras.map((linhas) => ({ tipo: 'cq' as const, linhas })),
    ...correcao.filter((f) => f.pendentes === 0).map((f) => ({ tipo: 'correcao' as const, f })),
  ].slice(0, 4)
  const total = passagens.length + cqComPendentes.length + cqOutras.length + correcao.length
  const temPendente = (c: (typeof cartoes)[number]) => (c.tipo === 'carga' ? comPendentes.includes(c.p) : c.tipo === 'cq' ? cqComPendentes.includes(c.linhas) : c.f.pendentes > 0)
  const ciencia = painel.ciencia.pendentes.length
  const frase = (
    <p className={comTitulo ? 'text-[17px]' : 'max-w-[820px] text-[19px] leading-normal'}>
      {pendentesProducao > 0 ? (
        <>
          Você tem <b>{plural(pendentesProducao, 'carga pendente', 'cargas pendentes')}</b>{' '}
          {comPendentes.length <= 3 ? `na${comPendentes.length > 1 ? 's folhas' : ''} ${lista(comPendentes.map((p) => p.folha_revisao))}` : `em ${num(comPendentes.length)} folhas`}
        </>
      ) : amostrasPendentes > 0 || aTratar > 0 ? (
        'Você não tem carga de produção pendente'
      ) : (
        'Você não tem carga pendente'
      )}
      {amostrasPendentes > 0 && (
        <>
          {pendentesProducao > 0 ? ', ' : ', mas '}
          <b>{plural(amostrasPendentes, 'amostra de CQ', 'amostras de CQ')}</b> para avaliar
        </>
      )}
      {aTratar > 0 && (
        <>
          {pendentesProducao > 0 || amostrasPendentes > 0 ? ', ' : ', mas '}
          <b>{plural(aTratar, 'ocorrência', 'ocorrências')}</b> para tratar na correção de inspeção
        </>
      )}
      {hoje > 0 ? (
        <>
          {' '}
          e concluiu <b>{num(hoje)} hoje</b>.
        </>
      ) : (
        '.'
      )}
      {ciencia > 0 && (
        <>
          {' '}
          {ciencia === 1 ? 'Uma ocorrência nas suas cargas espera' : `${plural(ciencia, 'ocorrência', 'ocorrências')} nas suas cargas esperam`} a sua ciência.
        </>
      )}
    </p>
  )
  const corpo = (
    <>
      {comTitulo && frase}
      <MeusConflitos />
      {ciencia > 0 && (
        <div className="flex flex-col gap-2.5">
          <div className="flex flex-wrap items-baseline gap-x-3">
            <h3 className="text-[13px] font-semibold tracking-[.04em] text-muted-foreground uppercase">Para ciência</h3>
            <span className="text-[13px] text-muted-foreground">o retorno do controle de qualidade sobre as suas cargas; não pede correção</span>
          </div>
          <ParaCiencia dados={painel.ciencia} limite={2} />
        </div>
      )}
      <div className="flex flex-wrap items-stretch gap-4">
        {cartoes.length === 0 && <Bloco className="flex-[2_1_420px] text-muted-foreground">Nenhuma carga com você agora. O supervisor atribui as cargas.</Bloco>}
        {cartoes.map((c, i) =>
          c.tipo === 'carga' ? (
            <CartaoFolha key={c.p.id_lote_etapa} p={c.p} principal={i === 0 && temPendente(c)} />
          ) : c.tipo === 'correcao' ? (
            <CartaoCorrecao key={`corr-${c.f.id_lote_etapa}`} f={c.f} principal={i === 0 && temPendente(c)} />
          ) : (
            <CartaoCQ key={`cq-${c.linhas[0].id_lote_etapa}`} linhas={c.linhas} principal={i === 0 && temPendente(c)} />
          ),
        )}
        <Bloco className="flex-[1_1_300px]">
          <div className="flex items-baseline gap-2.5">
            <h3 className="font-semibold">Suas conclusões</h3>
            <span className="text-[13px] text-muted-foreground">últimos 10 dias</span>
          </div>
          <Producao dias={dias} />
        </Bloco>
      </div>
      {total > cartoes.length && (
        <a href="#/execucao" className="text-sm text-ibge hover:underline">
          e mais {plural(total - cartoes.length, 'folha', 'folhas')} em Execução
        </a>
      )}
    </>
  )
  if (!comTitulo)
    return (
      <>
        {frase}
        <section aria-label="Suas folhas" className="flex flex-col gap-4">
          {corpo}
        </section>
      </>
    )
  return (
    <Secao titulo="Execução" sub="as cargas que estão com você" link={{ href: '#/execucao', rotulo: 'Abrir Execução' }}>
      {corpo}
    </Secao>
  )
}
