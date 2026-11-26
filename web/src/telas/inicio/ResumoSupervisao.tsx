import { Barra, Bloco, COR, Legenda, LinkSeta, Metrica, Rotulo, Secao, Tabela, TituloBloco, Vazio } from '@/components/ds'
import type { GrupoAtividade, GrupoEsperando, Lote, PainelSupervisao, StatusNacional } from '@/lib/api'
import { lista, num, parado, pc, plural, quando } from '@/lib/formato'
import { href } from '@/lib/rotas'
import { useSessao } from '@/lib/sessao'
import { STATUS } from '@/lib/status'
import { useApi } from '@/lib/useApi'
import { cn } from '@/lib/utils'
import { useContagemConflitos } from '../supervisao/Conflitos'

const ehCq = (g: GrupoAtividade) => g.fase === 'cq'
export const rotuloCurto = (g: GrupoAtividade) => (ehCq(g) ? g.rotulo : g.tema)

// Os dados do painel da supervisão, usados pelo Início e pelas abas.
export function usePainel() {
  const { tem } = useSessao()
  const painel = useApi<PainelSupervisao>('/api/painel/supervisao', ['lote', 'carga'])
  const esperando = useApi<{ grupos: GrupoEsperando[] }>(tem('supervisor') ? '/api/painel/esperando' : null, ['lote'])
  const lotes = useApi<{ itens: Lote[] }>('/api/lotes', ['lote', 'carga'])
  return { painel, esperando, lotes }
}

export function fraseSupervisao(p: PainelSupervisao, esperando: GrupoEsperando[] | null, unidade: string) {
  const folhas = new Set(p.grupos.flatMap((g) => g.lotes)).size
  const nEsperando = (esperando ?? []).reduce((s, g) => s + g.folhas.length, 0)
  const aAtribuir = p.grupos.filter((g) => !ehCq(g) && g.a_atribuir > 0)
  const nAtribuir = aAtribuir.reduce((s, g) => s + g.a_atribuir, 0)
  const temas = [...new Set(aAtribuir.map((g) => g.tema.toLowerCase()))]
  return (
    <>
      {p.grupos.length ? (
        <>
          {unidade}, <b>{plural(p.grupos.length, 'atividade está', 'atividades estão')}</b> em produção em <b>{plural(folhas, 'folha', 'folhas')}</b>.
        </>
      ) : (
        <>{unidade}, nenhuma folha está em produção.</>
      )}
      {nEsperando > 0 && (
        <>
          {' '}
          <b>{plural(nEsperando, 'folha', 'folhas')}</b> {nEsperando === 1 ? 'terminou a etapa e espera' : 'terminaram a etapa e esperam'} você abrir a próxima
          {nAtribuir > 0 ? ', e ' : '.'}
        </>
      )}
      {nAtribuir > 0 && (
        <>
          {nEsperando > 0 ? '' : ' '}
          <b>{plural(nAtribuir, 'carga', 'cargas')}</b> de {lista(temas)} ainda {nAtribuir === 1 ? 'não tem' : 'não têm'} responsável.
        </>
      )}
    </>
  )
}

function PrecisaDeVoce({ p, esperando, lotes }: { p: PainelSupervisao; esperando: GrupoEsperando[]; lotes: Lote[] }) {
  const { tem } = useSessao()
  const { dados: conflitos } = useContagemConflitos(tem('supervisor'))
  const nome = (id: number) => lotes.find((l) => l.id === id)?.folha_revisao ?? `#${id}`
  const nEsperando = esperando.reduce((s, g) => s + g.folhas.length, 0)
  const porTema = new Map<string, number>()
  esperando.forEach((g) => porTema.set(g.tema, (porTema.get(g.tema) ?? 0) + g.folhas.length))
  const producao = p.grupos.filter((g) => !ehCq(g) && g.a_atribuir > 0)
  const cq = p.grupos.filter((g) => ehCq(g) && g.a_atribuir > 0)
  const cartoes = []
  if (nEsperando)
    cartoes.push(
      <Metrica
        key="esp"
        valor={nEsperando}
        tom="info"
        rotulo={`${nEsperando === 1 ? 'folha terminou a etapa e espera' : 'folhas terminaram a etapa e esperam'} você abrir a próxima`}
        detalhe={lista([...porTema].map(([t, n]) => `${num(n)} de ${t}`))}
      >
        <LinkSeta href="#/supervisao/esperando" className="mt-2">
          Decidir
        </LinkSeta>
      </Metrica>,
    )
  for (const g of producao) {
    const comCargas = p.lotes.filter((l) => l.a_atribuir > 0 && g.lotes.includes(l.id_lote))
    cartoes.push(
      <Metrica
        key={g.chave}
        valor={g.a_atribuir}
        tom="alerta"
        rotulo={`cargas de ${g.tema.toLowerCase()} sem responsável`}
        detalhe={<>{comCargas.length <= 4 ? lista(comCargas.map((l) => `${nome(l.id_lote)} (${num(l.a_atribuir)})`)) : plural(comCargas.length, 'folha', 'folhas')} · {g.rotulo}</>}
      >
        <LinkSeta href={href('supervisao/folhas', { grupo: g.chave, distribuir: 1 })} className="mt-2">
          Distribuir
        </LinkSeta>
      </Metrica>,
    )
  }
  // Amostras de CQ sem avaliador (D3d): um cartão por tema, com as atividades (elementos) e as folhas. O Distribuir
  // entrega a folha inteira (todas as atividades de CQ dela) a um avaliador.
  for (const g of cq) {
    const porAtividade = (p.amostras_sem_avaliador ?? []).filter((a) => a.chave === g.chave)
    const folhas = [...new Set(porAtividade.flatMap((a) => a.lotes))]
    const total = porAtividade.reduce((s, a) => s + a.amostras, 0) || g.a_atribuir
    cartoes.push(
      <Metrica
        key={g.chave}
        valor={total}
        tom="alerta"
        rotulo={`amostras de ${g.rotulo} sem avaliador`}
        detalhe={
          <>
            {porAtividade.length ? lista(porAtividade.map((a) => `${a.elemento ?? a.atividade} (${num(a.amostras)})`)) : null}
            {porAtividade.length ? ' · ' : ''}
            {folhas.length && folhas.length <= 3 ? lista(folhas.map(nome)) : plural(folhas.length || g.lotes.length, 'folha', 'folhas')}
          </>
        }
      >
        <LinkSeta href={href('supervisao/folhas', { grupo: g.chave, distribuir: 1 })} className="mt-2">
          Distribuir as amostras
        </LinkSeta>
      </Metrica>,
    )
  }
  if (conflitos?.total)
    cartoes.push(
      <Metrica
        key="conflitos"
        valor={conflitos.total}
        tom="alerta"
        rotulo={`${conflitos.total === 1 ? 'alteração se cruzou com outra ou foi recusada' : 'alterações se cruzaram com outras ou foram recusadas'} ao sincronizar`}
        detalhe={<>{lista([...(conflitos.conflitos ? [plural(conflitos.conflitos, 'conflito', 'conflitos')] : []), ...(conflitos.recusas ? [plural(conflitos.recusas, 'recusa', 'recusas')] : [])])} nos últimos {conflitos.dias} dias</>}
      >
        <LinkSeta href="#/supervisao/conflitos" className="mt-2">
          Ver o que aconteceu
        </LinkSeta>
      </Metrica>,
    )
  return (
    <div className="flex flex-col gap-2.5">
      <Rotulo>Precisa de você</Rotulo>
      {cartoes.length ? <div className="grid grid-cols-[repeat(auto-fit,minmax(280px,1fr))] gap-4">{cartoes}</div> : <Bloco><Vazio>Nada esperando você: nenhuma folha parada, nenhuma carga sem responsável e nenhuma amostra sem avaliador.</Vazio></Bloco>}
    </div>
  )
}

function CartaoAtividade({ g }: { g: GrupoAtividade }) {
  const cq = ehCq(g)
  const pendentes = g.com_alguem + g.a_atribuir + g.na_fila
  return (
    <Bloco>
      <div className="flex flex-col gap-0.5">
        <span className="text-titulo-3 font-semibold">{g.rotulo}</span>
        <span className="text-nota text-muted-foreground">
          {plural(g.lotes.length, 'folha', 'folhas')} · {plural(g.pessoas, cq ? 'avaliador' : 'pessoa', cq ? 'avaliadores' : 'pessoas')}
          {cq && g.atividades.length > 1 ? ` · ${g.atividades.length} medidas` : ''}
        </span>
      </div>
      <div className="flex flex-col gap-1.5">
        <div className="flex justify-between text-nota">
          <span>
            <b>{num(g.concluidas)}</b> de {num(g.total)} {cq ? 'amostras avaliadas' : 'cargas concluídas'}
          </span>
          <span className="tab">{pc(g.concluidas, g.total)}%</span>
        </div>
        <Barra
          total={g.total}
          partes={[
            { valor: g.concluidas, cor: COR.concluida, rotulo: cq ? 'avaliadas' : 'concluídas' },
            { valor: g.com_alguem, cor: COR.comAlguem, rotulo: cq ? 'com avaliador' : 'com alguém' },
            { valor: g.na_fila, cor: COR.naFila, rotulo: 'na fila' },
          ]}
        />
        <Legenda
          itens={[
            ...(g.concluidas ? [{ cor: COR.concluida, rotulo: cq ? 'avaliadas' : 'concluídas' }] : []),
            ...(g.com_alguem ? [{ cor: COR.comAlguem, rotulo: cq ? 'com avaliador' : 'com alguém' }] : []),
            ...(g.na_fila ? [{ cor: COR.naFila, rotulo: 'na fila' }] : []),
            ...(g.a_atribuir ? [{ cor: COR.vazio, rotulo: cq ? 'sem avaliador' : 'a atribuir' }] : []),
          ]}
        />
      </div>
      <div className="mt-auto flex flex-wrap gap-x-5 text-nota">
        <span>
          <b className={cn('tab', g.a_atribuir > 0 && 'text-alerta')}>{num(g.a_atribuir)}</b> {cq ? 'sem avaliador' : 'a atribuir'}
        </span>
        {g.na_fila > 0 && (
          <span>
            <b>{num(g.na_fila)}</b> na fila
          </span>
        )}
        {cq && !g.concluidas ? (
          <span className="text-muted-foreground">nenhuma avaliada ainda</span>
        ) : (
          <span>
            <b>{num(g.concluidas_7d)}</b> {cq ? 'avaliadas' : 'concluídas'} em 7 dias
          </span>
        )}
        {!cq && pendentes === 0 && g.total > 0 && <span className="text-muted-foreground">todas concluídas</span>}
      </div>
      <LinkSeta href={href('supervisao/folhas', { grupo: g.chave })}>{cq ? 'Ver folhas e amostras' : 'Ver folhas e cargas'}</LinkSeta>
    </Bloco>
  )
}

const ORDEM_STATUS: StatusNacional[] = ['PLANEJADA', 'EM_PRODUCAO', 'EM_CQ', 'ENTREGUE_GCQ', 'CONCLUIDA', 'DEVOLVIDA']

function StatusNacionalCartao({ p, nEsperando }: { p: PainelSupervisao; nEsperando: number }) {
  const total = ORDEM_STATUS.reduce((s, k) => s + (p.status[k] ?? 0), 0)
  const com = ORDEM_STATUS.filter((k) => p.status[k])
  const sem = ORDEM_STATUS.filter((k) => !p.status[k])
  return (
    <Bloco className="flex-[1_1_420px] gap-3.5">
      <TituloBloco titulo="Status nacional da unidade" sub={`${plural(total, 'folha', 'folhas')} · o que a CCAR vê`} />
      <div className="flex h-9 gap-0.5 overflow-hidden rounded-lg text-nota font-semibold">
        {com.map((k) => {
          return (
            <div
              key={k}
              className="flex min-w-0 items-center overflow-hidden px-3 whitespace-nowrap"
              style={{ flex: `${p.status[k]} 1 0`, background: STATUS[k].cor, color: STATUS[k].escuro ? 'var(--primary-foreground)' : COR.textoClaro }}
              title={`${STATUS[k].rotulo}: ${p.status[k]}`}
            >
              {STATUS[k].rotulo} · {num(p.status[k] ?? 0)}
            </div>
          )
        })}
      </div>
      {sem.length > 0 && (
        <div className="flex flex-wrap gap-x-4 gap-y-1.5 text-rodape text-muted-foreground">
          {sem.map((k) => (
            <span key={k}>{STATUS[k].rotulo} 0</span>
          ))}
        </div>
      )}
      {nEsperando > 0 && (
        <p className="text-nota text-muted-foreground">
          As {plural(nEsperando, 'folha parada', 'folhas paradas')} esperando a próxima etapa seguem no status da etapa que terminou: só mudam quando a seguinte abrir.
        </p>
      )}
    </Bloco>
  )
}

function EquipeCartao({ p }: { p: PainelSupervisao }) {
  const { eu } = useSessao()
  const grupo = (c: string) => p.grupos.find((g) => g.chave === c)
  const ordenadas = [...p.pessoas].filter((x) => x.pendentes > 0).sort((a, b) => Number(!a.ultima) - Number(!b.ultima) || (a.ultima ?? '').localeCompare(b.ultima ?? ''))
  const mostrar = ordenadas.slice(0, 5)
  return (
    <Bloco className="flex-[1_1_520px]">
      <TituloBloco
        titulo="Equipe"
        sub={plural(ordenadas.length, 'pessoa com carga', 'pessoas com carga')}
        acao={
          <LinkSeta href="#/supervisao/equipe" className="text-nota">
            Abrir Equipe
          </LinkSeta>
        }
      />
      <Tabela solta densa>
        <thead>
          <tr>
            <th>Pessoa</th>
            <th className="text-right">Pendentes</th>
            <th>Atividade</th>
            <th className="whitespace-nowrap">Última conclusão</th>
          </tr>
        </thead>
        <tbody>
          {mostrar.map((x) => (
            <tr key={x.conta}>
              <td>
                {x.nome}
                {x.conta === eu?.conta ? ' (você)' : ''}
              </td>
              <td className="tab text-right">{num(x.pendentes)}</td>
              <td>{lista(x.grupos.map((c) => (grupo(c) ? rotuloCurto(grupo(c)!) : c)))}</td>
              <td className={cn('whitespace-nowrap', parado(x.ultima) && 'font-semibold text-alerta')}>{quando(x.ultima)}</td>
            </tr>
          ))}
        </tbody>
      </Tabela>
      <span className="text-rodape text-muted-foreground">
        Por quem está há mais tempo sem concluir (quem ainda não concluiu nenhuma vem depois)
        {ordenadas.length > mostrar.length ? `; mais ${plural(ordenadas.length - mostrar.length, 'pessoa', 'pessoas')} no módulo` : ''}.
      </span>
    </Bloco>
  )
}

// Supervisão no Início: o que depende de você, o que está em produção, o status nacional e a equipe.
export function ResumoSupervisao({ dados }: { dados: ReturnType<typeof usePainel> }) {
  const { tem } = useSessao()
  const p = dados.painel.dados
  if (!p) return null
  const esperando = dados.esperando.dados?.grupos ?? []
  const nEsperando = esperando.reduce((s, g) => s + g.folhas.length, 0)
  return (
    <Secao titulo="Supervisão" sub="o que a sua unidade está produzindo e o que depende de você" link={{ href: '#/supervisao', rotulo: 'Abrir Supervisão' }}>
      {tem('supervisor') && <PrecisaDeVoce p={p} esperando={esperando} lotes={dados.lotes.dados?.itens ?? []} />}
      <div className="flex flex-col gap-2.5">
        <Rotulo>Em produção, por atividade</Rotulo>
        {p.grupos.length ? (
          <div className="grid grid-cols-[repeat(auto-fill,minmax(340px,1fr))] gap-4">
            {p.grupos.map((g) => (
              <CartaoAtividade key={g.chave} g={g} />
            ))}
          </div>
        ) : (
          <Bloco className="flex-row flex-wrap items-center justify-between text-muted-foreground">
            Nenhuma atividade em produção: nenhuma folha com etapa aberta.
            <LinkSeta href={href('supervisao/folhas', { grupo: 'todas' })}>Ver as folhas da unidade</LinkSeta>
          </Bloco>
        )}
      </div>
      <div className="flex flex-wrap items-start gap-4">
        <StatusNacionalCartao p={p} nEsperando={nEsperando} />
        {tem('supervisor') && <EquipeCartao p={p} />}
      </div>
    </Secao>
  )
}
