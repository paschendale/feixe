import { Barra, Bloco, COR, Legenda, LinkSeta, Numero, Rotulo, Secao } from '@/components/painel'
import type { GrupoAtividade, GrupoEsperando, Lote, PainelSupervisao, StatusNacional } from '@/lib/api'
import { lista, num, parado, pc, plural, quando } from '@/lib/formato'
import { href } from '@/lib/rotas'
import { useSessao } from '@/lib/sessao'
import { STATUS } from '@/lib/status'
import { useApi } from '@/lib/useApi'
import { cn } from '@/lib/utils'

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
      {unidade}, <b>{plural(p.grupos.length, 'atividade está', 'atividades estão')}</b> em produção em <b>{plural(folhas, 'folha', 'folhas')}</b>.
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
  const nome = (id: number) => lotes.find((l) => l.id === id)?.folha_revisao ?? `#${id}`
  const nEsperando = esperando.reduce((s, g) => s + g.folhas.length, 0)
  const porTema = new Map<string, number>()
  esperando.forEach((g) => porTema.set(g.tema, (porTema.get(g.tema) ?? 0) + g.folhas.length))
  const producao = p.grupos.filter((g) => !ehCq(g) && g.a_atribuir > 0)
  const cq = p.grupos.filter((g) => ehCq(g) && g.a_atribuir > 0)
  const cartoes = []
  if (nEsperando)
    cartoes.push(
      <Bloco key="esp" className="flex-[1_1_300px] gap-1.5">
        <Numero valor={nEsperando} />
        <span>{nEsperando === 1 ? 'folha terminou a etapa e espera' : 'folhas terminaram a etapa e esperam'} você abrir a próxima</span>
        <span className="text-[13px] text-muted-foreground">{lista([...porTema].map(([t, n]) => `${num(n)} de ${t}`))}</span>
        <LinkSeta href="#/supervisao/esperando" className="mt-2">
          Decidir
        </LinkSeta>
      </Bloco>,
    )
  for (const g of producao) {
    const comCargas = p.lotes.filter((l) => l.a_atribuir > 0 && g.lotes.includes(l.id_lote))
    cartoes.push(
      <Bloco key={g.chave} className="flex-[1_1_300px] gap-1.5">
        <Numero valor={g.a_atribuir} alerta />
        <span>cargas de {g.tema.toLowerCase()} sem responsável</span>
        <span className="text-[13px] text-muted-foreground">
          {comCargas.length <= 4 ? lista(comCargas.map((l) => `${nome(l.id_lote)} (${num(l.a_atribuir)})`)) : plural(comCargas.length, 'folha', 'folhas')} · {g.rotulo}
        </span>
        <LinkSeta href={href('supervisao/folhas', { grupo: g.chave, atribuir: 1 })} className="mt-2">
          Atribuir
        </LinkSeta>
      </Bloco>,
    )
  }
  for (const g of cq)
    cartoes.push(
      <Bloco key={g.chave} className="flex-[1_1_300px] gap-1.5">
        <Numero valor={g.a_atribuir} alerta />
        <span>amostras de {g.rotulo} sem avaliador</span>
        <span className="text-[13px] text-muted-foreground">em {plural(g.lotes.length, 'folha', 'folhas')}</span>
        <LinkSeta href={href('supervisao/folhas', { grupo: g.chave })} className="mt-2">
          Distribuir
        </LinkSeta>
      </Bloco>,
    )
  return (
    <div className="flex flex-col gap-2.5">
      <Rotulo>Precisa de você</Rotulo>
      {cartoes.length ? <div className="flex flex-wrap gap-4">{cartoes}</div> : <Bloco className="text-muted-foreground">Nada esperando você: nenhuma folha parada e nenhuma carga sem responsável.</Bloco>}
    </div>
  )
}

export function CartaoAtividade({ g, link = true }: { g: GrupoAtividade; link?: boolean }) {
  const cq = ehCq(g)
  const pendentes = g.com_alguem + g.a_atribuir
  return (
    <Bloco className="flex-[1_1_340px]">
      <div className="flex flex-col gap-0.5">
        <span className="text-base font-semibold">{g.rotulo}</span>
        <span className="text-[13px] text-muted-foreground">
          {plural(g.lotes.length, 'folha', 'folhas')} · {plural(g.pessoas, cq ? 'avaliador' : 'pessoa', cq ? 'avaliadores' : 'pessoas')}
          {cq && g.atividades.length > 1 ? ` · ${g.atividades.length} medidas` : ''}
        </span>
      </div>
      <div className="flex flex-col gap-1.5">
        <div className="flex justify-between text-[13px]">
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
          ]}
        />
        <Legenda
          itens={[
            ...(g.concluidas ? [{ cor: COR.concluida, rotulo: cq ? 'avaliadas' : 'concluídas' }] : []),
            ...(g.com_alguem ? [{ cor: COR.comAlguem, rotulo: cq ? 'com avaliador' : 'com alguém' }] : []),
            ...(g.a_atribuir ? [{ cor: COR.vazio, rotulo: cq ? 'sem avaliador' : 'a atribuir' }] : []),
          ]}
        />
      </div>
      <div className="flex flex-wrap gap-x-5 text-[13px]">
        <span>
          <b style={{ color: g.a_atribuir ? COR.alerta : undefined }}>{num(g.a_atribuir)}</b> {cq ? 'sem avaliador' : 'a atribuir'}
        </span>
        {cq && !g.concluidas ? (
          <span className="text-muted-foreground">avaliação no QGIS na fase D</span>
        ) : (
          <span>
            <b>{num(g.concluidas_7d)}</b> {cq ? 'avaliadas' : 'concluídas'} em 7 dias
          </span>
        )}
        {!cq && pendentes === 0 && g.total > 0 && <span className="text-muted-foreground">todas concluídas</span>}
      </div>
      {link && <LinkSeta href={href('supervisao/folhas', { grupo: g.chave })}>{cq ? 'Ver folhas e amostras' : 'Ver folhas e cargas'}</LinkSeta>}
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
      <div className="flex flex-wrap items-baseline gap-2.5">
        <h3 className="text-base font-semibold">Status nacional da unidade</h3>
        <span className="text-[13px] text-muted-foreground">{plural(total, 'folha', 'folhas')} · o que a CCAR vê</span>
      </div>
      <div className="flex h-10 overflow-hidden rounded-lg text-[13px] font-semibold">
        {com.map((k) => {
          const escuro = ['ENTREGUE_GCQ', 'CONCLUIDA', 'DEVOLVIDA', 'EM_CQ'].includes(k)
          return (
            <div
              key={k}
              className="flex min-w-0 items-center overflow-hidden px-3 whitespace-nowrap"
              style={{ flex: `${p.status[k]} 1 0`, background: k === 'EM_CQ' ? '#3A66A3' : STATUS[k].cor, color: escuro ? '#fff' : '#1C2F4A' }}
              title={`${STATUS[k].rotulo}: ${p.status[k]}`}
            >
              {STATUS[k].rotulo} · {num(p.status[k] ?? 0)}
            </div>
          )
        })}
      </div>
      {sem.length > 0 && (
        <div className="flex flex-wrap gap-x-4 gap-y-1.5 text-xs text-muted-foreground">
          {sem.map((k) => (
            <span key={k}>{STATUS[k].rotulo} 0</span>
          ))}
        </div>
      )}
      {nEsperando > 0 && (
        <p className="text-[13px] text-muted-foreground">
          As {plural(nEsperando, 'folha parada', 'folhas paradas')} esperando a próxima etapa seguem no status da etapa que terminou: só mudam quando a seguinte abrir.
        </p>
      )}
    </Bloco>
  )
}

function EquipeCartao({ p }: { p: PainelSupervisao }) {
  const { eu } = useSessao()
  const grupo = (c: string) => p.grupos.find((g) => g.chave === c)
  const ordenadas = [...p.pessoas].filter((x) => x.pendentes > 0).sort((a, b) => (a.ultima ?? '').localeCompare(b.ultima ?? ''))
  const mostrar = ordenadas.slice(0, 5)
  return (
    <Bloco className="flex-[1_1_520px]">
      <div className="flex flex-wrap items-baseline gap-2.5">
        <h3 className="text-base font-semibold">Equipe</h3>
        <span className="text-[13px] text-muted-foreground">{plural(ordenadas.length, 'pessoa com carga', 'pessoas com carga')}</span>
        <LinkSeta href="#/supervisao/equipe" className="ml-auto text-[13px]">
          Abrir Equipe
        </LinkSeta>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-[13px]">
          <thead>
            <tr className="text-left text-muted-foreground">
              <th className="border-b py-1.5 pr-2 font-medium">Pessoa</th>
              <th className="border-b px-2 py-1.5 text-right font-medium">Pendentes</th>
              <th className="border-b px-2 py-1.5 font-medium">Atividade</th>
              <th className="border-b py-1.5 pl-2 font-medium">Última conclusão</th>
            </tr>
          </thead>
          <tbody>
            {mostrar.map((x) => (
              <tr key={x.conta} className="border-b border-[#EEF1F4] last:border-0">
                <td className="py-2 pr-2">
                  {x.nome}
                  {x.conta === eu?.conta ? ' (você)' : ''}
                </td>
                <td className="tab px-2 py-2 text-right">{num(x.pendentes)}</td>
                <td className="px-2 py-2">{lista(x.grupos.map((c) => (grupo(c) ? rotuloCurto(grupo(c)!) : c)))}</td>
                <td className={cn('py-2 pl-2', parado(x.ultima) && 'font-semibold')} style={{ color: parado(x.ultima) ? COR.alerta : undefined }}>
                  {quando(x.ultima)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <span className="text-xs text-muted-foreground">
        Por quem está há mais tempo sem concluir
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
          <div className="flex flex-wrap gap-4">
            {p.grupos.map((g) => (
              <CartaoAtividade key={g.chave} g={g} />
            ))}
          </div>
        ) : (
          <Bloco className="text-muted-foreground">Nenhuma atividade em produção: nenhuma folha com etapa aberta.</Bloco>
        )}
      </div>
      <div className="flex flex-wrap items-stretch gap-4">
        <StatusNacionalCartao p={p} nEsperando={nEsperando} />
        {tem('supervisor') && <EquipeCartao p={p} />}
      </div>
    </Secao>
  )
}
