import { Button } from '@/components/ui/button'
import { Barra, Bloco, COR, Secao } from '@/components/painel'
import type { Passagem, ResumoCargas } from '@/lib/api'
import { lista, num, pc, plural } from '@/lib/formato'
import { href } from '@/lib/rotas'
import { useApi } from '@/lib/useApi'
import { ABERTAS, Continuar, Preparando, Producao, pendentesDe, usePorDia } from '../execucao/comum'
import { MeusConflitos } from '../execucao/MeusConflitos'

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
              <a href={href('execucao', { folha: p.id_lote_etapa })}>Ver as cargas</a>
            </Button>
          )}
        </div>
      )}
      {falta > 0 && !aberta && <span className="text-[13px]">A etapa foi encerrada pelo supervisor com {plural(falta, 'carga pendente', 'cargas pendentes')} suas.</span>}
      {falta === 0 && <span className="text-[13px]">Sua parte terminou. A folha segue quando o supervisor abrir a próxima etapa.</span>}
    </Bloco>
  )
}

// Execução no Início: frase, as folhas com "Continuar no QGIS" e as conclusões dos últimos dias.
export function ResumoExecucao({ comTitulo }: { comTitulo: boolean }) {
  const { dados } = useApi<ResumoCargas>('/api/cargas/resumo', ['carga', 'lote', 'sincronizacao'])
  const { dias, hoje } = usePorDia()
  if (!dados) return null
  if (dados.preparando) return comTitulo ? <Secao titulo="Execução" sub="as cargas que estão com você"><Preparando /></Secao> : <Preparando />
  const comPendentes = dados.passagens.filter((p) => pendentesDe(p) > 0 && ABERTAS.includes(p.situacao))
  const outras = dados.passagens.filter((p) => !comPendentes.includes(p))
  const cartoes = [...comPendentes, ...outras].slice(0, 4)
  const frase = (
    <p className={comTitulo ? 'text-[17px]' : 'max-w-[820px] text-[19px] leading-normal'}>
      {dados.pendentes > 0 ? (
        <>
          Você tem <b>{plural(dados.pendentes, 'carga pendente', 'cargas pendentes')}</b>{' '}
          {comPendentes.length <= 3 ? `na${comPendentes.length > 1 ? 's folhas' : ''} ${lista(comPendentes.map((p) => p.folha_revisao))}` : `em ${num(comPendentes.length)} folhas`}
        </>
      ) : (
        'Você não tem carga pendente'
      )}
      {hoje > 0 ? (
        <>
          {' '}
          e concluiu <b>{num(hoje)} hoje</b>.
        </>
      ) : (
        '.'
      )}
    </p>
  )
  const corpo = (
    <>
      {comTitulo && frase}
      <MeusConflitos />
      <div className="flex flex-wrap items-stretch gap-4">
        {cartoes.length === 0 && <Bloco className="flex-[2_1_420px] text-muted-foreground">Nenhuma carga com você agora. O supervisor atribui as cargas.</Bloco>}
        {cartoes.map((p, i) => (
          <CartaoFolha key={p.id_lote_etapa} p={p} principal={i === 0 && comPendentes.includes(p)} />
        ))}
        <Bloco className="flex-[1_1_300px]">
          <div className="flex items-baseline gap-2.5">
            <h3 className="font-semibold">Suas conclusões</h3>
            <span className="text-[13px] text-muted-foreground">últimos 10 dias</span>
          </div>
          <Producao dias={dias} />
        </Bloco>
      </div>
      {dados.passagens.length > cartoes.length && (
        <a href="#/execucao" className="text-sm text-ibge hover:underline">
          e mais {plural(dados.passagens.length - cartoes.length, 'folha', 'folhas')} em Minhas cargas
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
    <Secao titulo="Execução" sub="as cargas que estão com você" link={{ href: '#/execucao', rotulo: 'Abrir Minhas cargas' }}>
      {corpo}
    </Secao>
  )
}
