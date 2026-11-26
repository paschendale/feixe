import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Select } from '@/components/ui/select'
import { Carregando, Colunas, Conteudo, Fichas, RotuloEstavel, Selo, Tabela } from '@/components/ds'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import type { Pessoa, ResultadoPassar } from '@/lib/api'
import { useAvisar } from '@/lib/avisos'
import { lista, num, parado, plural, quando } from '@/lib/formato'
import { href, navegar, useRota } from '@/lib/rotas'
import { useSessao } from '@/lib/sessao'
import { enviar, useApi } from '@/lib/useApi'
import { cn } from '@/lib/utils'
import { unidadeDe } from '../inicio/Inicio'
import { rotuloCurto, usePainel } from '../inicio/ResumoSupervisao'

const PERFIL: Record<string, string> = { O: 'APM', V: 'Avaliador', S: 'Supervisor', C: 'Consulta', I: 'Consulta' }

// "BC100:O, BC250:S" -> "APM, Supervisor"
const perfis = (s: string) => [...new Set(s.split(',').map((x) => PERFIL[x.trim().split(':').pop() ?? ''] ?? x.trim()))].join(', ')

// Supervisão › Equipe: quem pode receber cargas, onde está e há quanto tempo não conclui. Quem está sem carga vem
// primeiro, depois quem está há mais tempo sem concluir.
export default function Equipe() {
  const avisar = useAvisar()
  const { eu } = useSessao()
  const rota = useRota()
  const { painel, lotes } = usePainel()
  const { dados: equipe, erro } = useApi<{ itens: Pessoa[] }>('/api/equipe', ['carga'])
  const [passar, setPassar] = useState<{ de: string; para: string } | null>(null)
  const [enviando, setEnviando] = useState(false)
  const p = painel.dados
  const ativa = rota.query.get('grupo') ?? 'todas'

  async function aplicar() {
    if (!passar || !equipe) return
    const para = passar.para === '-' ? null : passar.para
    const nome = equipe.itens.find((y) => y.conta === para)?.nome.split(' ')[0]
    setEnviando(true)
    try {
      const r = await enviar<ResultadoPassar>('/api/equipe/passar', { de: passar.de, para })
      if (!para) avisar(`${plural(r.liberadas, 'carga ficou', 'cargas ficaram')} a atribuir.`)
      else
        avisar(
          [
            r.agora > 0 && `${plural(r.agora, 'carga passou', 'cargas passaram')} para ${nome} agora`,
            r.na_fila.length > 0 && `${lista(r.na_fila.map((f) => f.folha_revisao))} ${r.na_fila.length === 1 ? 'entrou' : 'entraram'} na fila de ${nome}`,
          ]
            .filter(Boolean)
            .join('; ') + '.',
        )
      setPassar(null)
    } catch (e) {
      avisar((e as Error).message, 'erro')
    } finally {
      setEnviando(false)
    }
  }

  if (!equipe || !p)
    return (
      <Conteudo>
        <Carregando erro={erro ?? painel.erro} />
      </Conteudo>
    )

  const doPainel = new Map(p.pessoas.map((x) => [x.conta, x]))
  const grupo = (c: string) => p.grupos.find((g) => g.chave === c)
  const nomeLote = (id: number) => lotes.dados?.itens.find((l) => l.id === id)?.folha_revisao ?? `#${id}`
  const linhas = equipe.itens
    .map((x) => ({ ...x, painel: doPainel.get(x.conta) }))
    .filter((x) => ativa === 'todas' || x.painel?.grupos.includes(ativa))
    .sort((a, b) => Number(a.pendentes > 0) - Number(b.pendentes > 0) || Number(!a.ultima) - Number(!b.ultima) || (a.ultima ?? '').localeCompare(b.ultima ?? '') || a.nome.localeCompare(b.nome))
  const semCarga = linhas.filter((x) => !x.pendentes)
  const paradas = linhas.filter((x) => x.pendentes && parado(x.ultima))
  // "Dar cargas" leva à produção com cargas a atribuir; para quem só avalia (perfil V), às amostras sem avaliador.
  const producaoAAtribuir = p.grupos.find((g) => g.fase !== 'cq' && g.a_atribuir > 0)
  const cqSemAvaliador = p.grupos.find((g) => g.fase === 'cq' && g.a_atribuir > 0)
  const soAvalia = (s: string) => {
    const ps = s.split(',').map((x) => x.trim().split(':').pop())
    return ps.includes('V') && !ps.includes('O')
  }
  const destinoDe = (x: Pessoa) => (soAvalia(x.perfis) ? cqSemAvaliador : (producaoAAtribuir ?? cqSemAvaliador))
  // "CQ · Hidrografia (12 amostras)": no CQ, as pendentes são amostras; na produção, só a atividade, como antes.
  const ondeDe = (c: string, por: Record<string, number> | undefined) => {
    const g = grupo(c)
    if (!g) return c
    return g.fase === 'cq' && por?.[c] ? `${rotuloCurto(g)} (${plural(por[c], 'amostra', 'amostras')})` : rotuloCurto(g)
  }

  return (
    <Conteudo>
      <Fichas
        rotulo="Atividade em produção"
        ativa={ativa}
        escolher={(id) => navegar(`supervisao/equipe${id === 'todas' ? '' : `?grupo=${id}`}`)}
        fichas={[...p.grupos.map((g) => ({ id: g.chave, rotulo: g.rotulo })), { id: 'todas', rotulo: 'Todas as atividades', todas: true }]}
      />
      <p className="min-h-12 max-w-[880px] text-lede text-texto-2 [&_b]:font-semibold [&_b]:text-foreground">
        {ativa === 'todas' ? (
          <>
            <b>{plural(linhas.length, 'pessoa pode', 'pessoas podem')}</b> receber cargas {unidadeDe(eu?.uf).replace(/^Na /, 'na ')}.{' '}
          </>
        ) : (
          <>
            <b>{plural(linhas.length, 'pessoa', 'pessoas')}</b> com carga em {grupo(ativa)?.rotulo}.{' '}
          </>
        )}
        {ativa === 'todas' && (
          <>
            <b>{num(linhas.length - semCarga.length)}</b> {linhas.length - semCarga.length === 1 ? 'tem' : 'têm'} cargas pendentes
            {semCarga.length > 0 && semCarga.length <= 3 && (
              <>
                ; <b>{lista(semCarga.map((x) => x.nome.split(' ').slice(0, 2).join(' ')))}</b> {semCarga.length === 1 ? 'está' : 'estão'} sem nenhuma
              </>
            )}
            {semCarga.length > 3 && <>; {plural(semCarga.length, 'está sem nenhuma', 'estão sem nenhuma')}</>}.{' '}
          </>
        )}
        {paradas.length > 0 && (
          <>
            <b>{plural(paradas.length, 'pessoa', 'pessoas')}</b> com carga {paradas.length === 1 ? 'não conclui' : 'não concluem'} há mais de 7 dias.
          </>
        )}
      </p>

      <Tabela fixa largura={900}>
          <Colunas larguras={[undefined, 130, '24%', 96, 150, 150, 184]} />
          <thead>
            <tr>
              <th>Pessoa</th>
              <th>Perfil no SGBC</th>
              <th>Onde está</th>
              <th className="text-right">Pendentes</th>
              <th className="text-right whitespace-nowrap">Concluídas em 7 dias</th>
              <th>Última conclusão</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {linhas.map((x) => {
              const alerta = x.pendentes > 0 && parado(x.ultima)
              const onde = x.painel?.grupos.map((c) => ondeDe(c, x.painel?.por_grupo)) ?? []
              const destino = destinoDe(x)
              const folhas = x.painel?.lotes ?? []
              const textoOnde = `${lista(onde)}${folhas.length > 0 ? ` · ${folhas.length <= 2 ? lista(folhas.map(nomeLote)) : plural(folhas.length, 'folha', 'folhas')}` : ''}`
              const nome = `${x.nome}${x.conta === eu?.conta ? ' (você)' : ''}`
              return (
                <tr key={x.conta}>
                  <td className="truncate font-medium" title={nome}>
                    {nome}
                  </td>
                  <td className="truncate text-muted-foreground" title={perfis(x.perfis)}>
                    {perfis(x.perfis)}
                  </td>
                  <td className="truncate" title={x.pendentes ? textoOnde : undefined}>
                    {x.pendentes ? (
                      <>
                        {lista(onde)}
                        {folhas.length > 0 && <span className="text-muted-foreground"> · {folhas.length <= 2 ? lista(folhas.map(nomeLote)) : plural(folhas.length, 'folha', 'folhas')}</span>}
                      </>
                    ) : (
                      <Selo tom="alerta">sem carga</Selo>
                    )}
                  </td>
                  <td className="tab text-right">{num(x.pendentes)}</td>
                  <td className="tab text-right">{num(x.painel?.concluidas_7d ?? 0)}</td>
                  <td className={cn('truncate', alerta && 'font-semibold text-alerta')}>
                    {quando(x.ultima)}
                  </td>
                  <td className="text-right">
                    {x.pendentes ? (
                      <Popover open={passar?.de === x.conta} onOpenChange={(v) => setPassar(v ? { de: x.conta, para: '' } : null)}>
                        <PopoverTrigger asChild>
                          <Button size="sm" variant="outline" className="w-full">
                            Passar pendentes…
                          </Button>
                        </PopoverTrigger>
                        <PopoverContent>
                          <div className="flex flex-col gap-1">
                            <p className="font-semibold">Passar as {plural(x.pendentes, 'pendente', 'pendentes')}</p>
                            <p className="text-nota text-muted-foreground">Uma folha por pessoa: o que não couber agora entra na fila de quem recebe. As concluídas ficam com {x.nome.split(' ')[0]}.</p>
                          </div>
                          <Select value={passar?.para ?? ''} onChange={(e) => passar && setPassar({ ...passar, para: e.target.value })} aria-label="Para quem">
                            <option value="">Para quem?</option>
                            <option value="-">Ninguém (a atribuir)</option>
                            {equipe.itens
                              .filter((y) => y.conta !== x.conta)
                              .map((y) => (
                                <option key={y.conta} value={y.conta}>
                                  {y.nome}
                                </option>
                              ))}
                          </Select>
                          <div className="flex justify-end gap-2">
                            <Button size="sm" variant="ghost" onClick={() => setPassar(null)}>
                              Cancelar
                            </Button>
                            <Button size="sm" disabled={!passar?.para || enviando} onClick={aplicar}>
                              <RotuloEstavel ocupado={enviando} rotulo="Passar" rotuloOcupado="Passando…" />
                            </Button>
                          </div>
                        </PopoverContent>
                      </Popover>
                    ) : destino ? (
                      <Button size="sm" variant="outline" className="w-full" asChild>
                        <a href={href('supervisao/folhas', { grupo: destino.chave, atribuir: 1 })}>{destino.fase === 'cq' ? 'Dar amostras' : 'Dar cargas'}</a>
                      </Button>
                    ) : null}
                  </td>
                </tr>
              )
            })}
          </tbody>
      </Tabela>
      <p className="text-nota text-muted-foreground">
        Ordem: quem está sem carga, depois quem está há mais tempo sem concluir e, por último, quem ainda não concluiu nenhuma. Quem pode receber cargas: conta ativa, lotação da UF e perfil de execução (O, V ou S) no SGBC; acertos de perfil se fazem lá. No CQ, as pendentes do avaliador são amostras. "Passar pendentes" muda só as pendentes; as concluídas ficam com quem fez.
      </p>
    </Conteudo>
  )
}
