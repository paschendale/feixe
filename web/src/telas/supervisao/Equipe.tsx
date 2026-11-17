import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Select } from '@/components/ui/select'
import { COR, Carregando, Conteudo, Fichas } from '@/components/painel'
import type { Pessoa, ResultadoAtribuicao } from '@/lib/api'
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
  const p = painel.dados
  const ativa = rota.query.get('grupo') ?? 'todas'

  async function aplicar() {
    if (!passar || !lotes.dados) return
    const abertas = lotes.dados.itens.filter((l) => l.situacao === 'pendente' || l.situacao === 'em_andamento').map((l) => l.id_lote_etapa_atual)
    try {
      const r = await enviar<ResultadoAtribuicao>('/api/cargas/atribuir', { lote_etapas: abertas, de: passar.de, responsavel: passar.para === '-' ? null : passar.para })
      avisar(`${num(r.atribuidas)} cargas passadas.`)
      setPassar(null)
    } catch (e) {
      avisar((e as Error).message, 'erro')
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
    .sort((a, b) => Number(a.pendentes > 0) - Number(b.pendentes > 0) || (a.ultima ?? '').localeCompare(b.ultima ?? '') || a.nome.localeCompare(b.nome))
  const semCarga = linhas.filter((x) => !x.pendentes)
  const paradas = linhas.filter((x) => x.pendentes && parado(x.ultima))
  const destinoDarCargas = p.grupos.find((g) => g.fase !== 'cq' && g.a_atribuir > 0) ?? p.grupos.find((g) => g.a_atribuir > 0)

  return (
    <Conteudo>
      <Fichas
        rotulo="Atividade em produção"
        ativa={ativa}
        escolher={(id) => navegar(`supervisao/equipe${id === 'todas' ? '' : `?grupo=${id}`}`)}
        fichas={[...p.grupos.map((g) => ({ id: g.chave, rotulo: g.rotulo })), { id: 'todas', rotulo: 'Todas as atividades', todas: true }]}
      />
      <p className="max-w-[880px] text-base">
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

      <div className="overflow-x-auto rounded-[10px] border bg-card">
        <table className="w-full min-w-[900px] border-collapse text-sm">
          <thead>
            <tr className="text-left text-xs text-muted-foreground">
              <th className="border-b py-3 pr-2 pl-4 font-medium">Pessoa</th>
              <th className="border-b px-2 py-3 font-medium">Perfil no SGBC</th>
              <th className="border-b px-2 py-3 font-medium">Onde está</th>
              <th className="border-b px-2 py-3 text-right font-medium">Pendentes</th>
              <th className="border-b px-2 py-3 text-right font-medium">Concluídas em 7 dias</th>
              <th className="border-b px-2 py-3 font-medium">Última conclusão</th>
              <th className="border-b py-3 pr-4 pl-2" />
            </tr>
          </thead>
          <tbody>
            {linhas.map((x) => {
              const alerta = x.pendentes > 0 && parado(x.ultima)
              const onde = x.painel?.grupos.map((c) => (grupo(c) ? rotuloCurto(grupo(c)!) : c)) ?? []
              const folhas = x.painel?.lotes ?? []
              return (
                <tr key={x.conta} className="border-b border-[#EEF1F4] last:border-0">
                  <td className="py-3 pr-2 pl-4 font-medium">
                    {x.nome}
                    {x.conta === eu?.conta ? ' (você)' : ''}
                  </td>
                  <td className="px-2 py-3 text-muted-foreground">{perfis(x.perfis)}</td>
                  <td className="px-2 py-3">
                    {x.pendentes ? (
                      <>
                        {lista(onde)}
                        {folhas.length > 0 && <span className="text-muted-foreground"> · {folhas.length <= 2 ? lista(folhas.map(nomeLote)) : plural(folhas.length, 'folha', 'folhas')}</span>}
                      </>
                    ) : (
                      <span className="font-semibold" style={{ color: COR.alerta }}>
                        sem carga
                      </span>
                    )}
                  </td>
                  <td className="tab px-2 py-3 text-right">{num(x.pendentes)}</td>
                  <td className="tab px-2 py-3 text-right">{num(x.painel?.concluidas_7d ?? 0)}</td>
                  <td className={cn('px-2 py-3', alerta && 'font-semibold')} style={{ color: alerta ? COR.alerta : undefined }}>
                    {quando(x.ultima)}
                  </td>
                  <td className="py-3 pr-4 pl-2 text-right whitespace-nowrap">
                    {passar?.de === x.conta ? (
                      <span className="inline-flex items-center gap-2">
                        <Select className="h-8 w-52" value={passar.para} onChange={(e) => setPassar({ ...passar, para: e.target.value })} aria-label="Para quem">
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
                        <Button size="sm" disabled={!passar.para} onClick={aplicar}>
                          Passar
                        </Button>
                        <Button size="sm" variant="ghost" onClick={() => setPassar(null)}>
                          Cancelar
                        </Button>
                      </span>
                    ) : x.pendentes ? (
                      <Button size="sm" variant="outline" onClick={() => setPassar({ de: x.conta, para: '' })}>
                        Passar pendentes…
                      </Button>
                    ) : destinoDarCargas ? (
                      <a href={href('supervisao/folhas', { grupo: destinoDarCargas.chave, atribuir: 1 })} className="font-semibold text-ibge hover:underline">
                        Dar cargas →
                      </a>
                    ) : null}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <p className="text-[13px] text-muted-foreground">
        Quem pode receber cargas: conta ativa, lotação da UF e perfil de execução (O, V ou S) no SGBC; acertos de perfil se fazem lá. "Passar pendentes" muda só as pendentes; as concluídas ficam com quem fez.
      </p>
    </Conteudo>
  )
}
