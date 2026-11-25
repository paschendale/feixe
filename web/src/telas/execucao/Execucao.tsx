import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Barra, Bloco, COR, CabecalhoModulo, Carregando, Conteudo, Fichas } from '@/components/painel'
import type { Carga, Passagem, Progresso, ResumoCargas } from '@/lib/api'
import { useAvisar } from '@/lib/avisos'
import { diaMes, diasAtras, num, pc, plural } from '@/lib/formato'
import { href, navegar, useRota } from '@/lib/rotas'
import { useSessao } from '@/lib/sessao'
import { enviar, useApi } from '@/lib/useApi'
import { cn } from '@/lib/utils'
import { ABERTAS, Continuar, Producao, pendentesDe, usePorDia } from './comum'

const JANELA_DESFAZER_MS = 24 * 3600 * 1000
const chaveDe = (p: Passagem) => `${p.tema} · ${p.etapa}`
const hora = (iso: string | null) => (iso ? new Date(iso).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' }) : '')
const recente = (c: Carga) => !!c.concluido_em && Date.now() - new Date(c.concluido_em).getTime() < JANELA_DESFAZER_MS

function useAcoes() {
  const avisar = useAvisar()
  const [ocupado, setOcupado] = useState<number | null>(null)
  async function rodar(id: number, fn: () => Promise<unknown>, ok?: (r: unknown) => string) {
    setOcupado(id)
    try {
      const r = await fn()
      if (ok) avisar(ok(r))
    } catch (e) {
      avisar((e as Error).message, 'erro')
    } finally {
      setOcupado(null)
    }
  }
  return {
    ocupado,
    trabalhar: (c: Carga) => rodar(c.id, () => enviar(`/api/cargas/${c.id}/zoom`), () => `Carga atual no QGIS: ${c.geocodigo ?? `nº ${c.id}`}`),
    desfazer: (c: Carga) =>
      rodar(
        c.id,
        () => enviar<{ progresso: Progresso }>(`/api/cargas/${c.id}/desfazer`),
        (r) => `Conclusão desfeita · ${(r as { progresso: Progresso }).progresso.concluidas}/${(r as { progresso: Progresso }).progresso.total}`,
      ),
  }
}

type Aba = 'pendentes' | 'concluidas' | 'hoje'

function Cargas({ p }: { p: Passagem }) {
  const { conectado } = useSessao()
  const acoes = useAcoes()
  const [aba, setAba] = useState<Aba>(pendentesDe(p) > 0 ? 'pendentes' : 'concluidas')
  const { dados, erro } = useApi<{ itens: Carga[] }>(`/api/cargas?lote_etapa=${p.id_lote_etapa}`, ['carga'])
  const aberta = ABERTAS.includes(p.situacao)
  if (!dados) return <Carregando erro={erro} />
  const pendentes = dados.itens.filter((c) => !c.concluido)
  const concluidas = dados.itens.filter((c) => c.concluido).sort((a, b) => (b.concluido_em ?? '').localeCompare(a.concluido_em ?? ''))
  const hoje = concluidas.filter((c) => diasAtras(c.concluido_em) === 0)
  const variasAtividades = new Set(dados.itens.map((c) => c.atividade)).size > 1
  const lista = aba === 'pendentes' ? pendentes : aba === 'hoje' ? hoje : concluidas
  const abas: [Aba, string, number][] = [
    ['pendentes', 'Pendentes', pendentes.length],
    ['concluidas', 'Concluídas', concluidas.length],
    ['hoje', 'Hoje', hoje.length],
  ]
  return (
    <>
      <div role="tablist" aria-label="Situação" className="flex flex-wrap gap-1 border-b">
        {abas.map(([id, rotulo, n]) => (
          <button
            key={id}
            role="tab"
            aria-selected={aba === id}
            onClick={() => setAba(id)}
            className={cn('border-b-2 px-3.5 py-2.5', aba === id ? 'border-ibge font-semibold text-ibge' : 'border-transparent text-[#3D4B5C] hover:text-ibge')}
          >
            {rotulo} · {num(n)}
          </button>
        ))}
      </div>
      <div className="overflow-x-auto rounded-[10px] border bg-card">
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="text-left text-xs text-muted-foreground">
              <th className="border-b py-3 pr-2 pl-4 font-medium">Carga</th>
              {variasAtividades && <th className="border-b px-2 py-3 font-medium">Atividade</th>}
              <th className="border-b px-2 py-3 font-medium">Situação</th>
              <th className="border-b py-3 pr-4 pl-2" />
            </tr>
          </thead>
          <tbody>
            {lista.length === 0 && (
              <tr>
                <td colSpan={variasAtividades ? 4 : 3} className="p-4 text-muted-foreground">
                  {aba === 'pendentes' ? 'Nenhuma pendente: sua parte nesta folha terminou.' : aba === 'hoje' ? 'Nenhuma concluída hoje.' : 'Nenhuma concluída ainda.'}
                </td>
              </tr>
            )}
            {lista.slice(0, 300).map((c) => (
              <tr key={c.id} className="border-b border-[#EEF1F4] last:border-0">
                <td className="tab py-2.5 pr-2 pl-4 font-mono text-[13px]">{c.geocodigo ?? `nº ${c.id}`}</td>
                {variasAtividades && <td className="px-2 py-2.5 text-muted-foreground">{c.atividade}</td>}
                <td className="px-2 py-2.5">{c.concluido ? <span className="text-muted-foreground">concluída {diaMes(c.concluido_em)} {hora(c.concluido_em)}</span> : 'pendente'}</td>
                <td className="py-2.5 pr-4 pl-2 text-right whitespace-nowrap">
                  {!c.concluido && aberta && (
                    <Button size="sm" variant="outline" disabled={!conectado || acoes.ocupado === c.id} onClick={() => acoes.trabalhar(c)}>
                      Trabalhar nesta
                    </Button>
                  )}
                  {c.concluido && (
                    <Button size="sm" variant="ghost" disabled={!conectado || acoes.ocupado === c.id} onClick={() => acoes.trabalhar(c)}>
                      Ver no QGIS
                    </Button>
                  )}
                  {c.concluido && aberta && recente(c) && (
                    <Button size="sm" variant="ghost" disabled={acoes.ocupado === c.id} onClick={() => acoes.desfazer(c)}>
                      Desfazer
                    </Button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {lista.length > 300 && <p className="border-t px-4 py-2.5 text-[13px] text-muted-foreground">Mostrando 300 de {num(lista.length)}. No QGIS, a camada Minhas cargas mostra todas.</p>}
      </div>
      {hoje.length > 0 && aba !== 'hoje' && (
        <Bloco className="gap-2">
          <h2 className="font-semibold">Concluídas hoje</h2>
          <div className="flex flex-wrap gap-x-4 gap-y-1.5 text-[13px]">
            {hoje.slice(0, 6).map((c) => (
              <span key={c.id} className="tab inline-flex items-center gap-1.5">
                {c.geocodigo ?? `nº ${c.id}`} · {hora(c.concluido_em)}
                {aberta && (
                  <button className="text-ibge hover:underline" disabled={acoes.ocupado === c.id} onClick={() => acoes.desfazer(c)}>
                    Desfazer
                  </button>
                )}
              </span>
            ))}
            {hoje.length > 6 && <button className="text-ibge hover:underline" onClick={() => setAba('hoje')}>e mais {num(hoje.length - 6)}</button>}
          </div>
          <span className="text-xs text-muted-foreground">Desfazer vale por 24 horas, só para quem concluiu.</span>
        </Bloco>
      )}
    </>
  )
}

// Execução › Minhas cargas (D-103): o trabalho é no QGIS (barra do Feixe: próxima, pular, concluir). Aqui é o
// acompanhamento e o atalho para levar o QGIS até uma carga.
export default function Execucao() {
  const rota = useRota()
  const { dados, erro } = useApi<ResumoCargas>('/api/cargas/resumo', ['carga', 'lote'])
  const { dias, hoje } = usePorDia()
  const abasModulo = [
    { id: 'cargas', rotulo: 'Minhas cargas', href: href('execucao') },
    { id: 'amostras', rotulo: 'Minhas amostras · fase D', desabilitada: true },
  ]
  if (!dados)
    return (
      <>
        <CabecalhoModulo titulo="Execução" abas={abasModulo} ativa="cargas" />
        <Conteudo largura={1240}>
          <Carregando erro={erro} />
        </Conteudo>
      </>
    )

  const chaves = [...new Set(dados.passagens.map(chaveDe))]
  const pendentesDaChave = (k: string) => dados.passagens.filter((p) => chaveDe(p) === k && ABERTAS.includes(p.situacao)).reduce((s, p) => s + pendentesDe(p), 0)
  const folhaQ = Number(rota.query.get('folha')) || null
  const daFolha = dados.passagens.find((p) => p.id_lote_etapa === folhaQ)
  const chave = rota.query.get('atividade') ?? (daFolha ? chaveDe(daFolha) : chaves.find((k) => pendentesDaChave(k) > 0) ?? chaves[0])
  const passagens = dados.passagens.filter((p) => chaveDe(p) === chave)
  const atual = daFolha && chaveDe(daFolha) === chave ? daFolha : (passagens.find((p) => pendentesDe(p) > 0 && ABERTAS.includes(p.situacao)) ?? passagens[0])
  const terminadas = passagens.filter((p) => p !== atual && pendentesDe(p) === 0)
  const outras = passagens.filter((p) => p !== atual && pendentesDe(p) > 0)

  return (
    <>
      <CabecalhoModulo titulo="Execução" abas={abasModulo} ativa="cargas" />
      <Conteudo largura={1240}>
        {chaves.length === 0 ? (
          <Bloco className="text-muted-foreground">Nenhuma carga atribuída a você em folhas abertas. O supervisor atribui as cargas.</Bloco>
        ) : (
          <>
            <Fichas
              rotulo="Atividade"
              ativa={chave}
              escolher={(k) => navegar(`execucao?atividade=${encodeURIComponent(k)}`)}
              fichas={chaves.map((k) => ({ id: k, rotulo: k, contagem: pendentesDaChave(k) ? `${num(pendentesDaChave(k))} pendentes` : 'tudo concluído' }))}
            />
            {atual && (
              <Bloco className="flex-row flex-wrap items-center gap-x-5 gap-y-3 px-5 py-4">
                <div className="flex min-w-[300px] flex-1 flex-col gap-1.5">
                  <div className="flex flex-wrap items-baseline gap-x-3">
                    <span className="tab text-lg font-bold">{atual.folha_revisao}</span>
                    <span className="text-muted-foreground">
                      {atual.tema} · {atual.etapa} · {ABERTAS.includes(atual.situacao) ? (atual.situacao === 'pendente' ? 'a iniciar' : 'em andamento') : 'encerrada pelo supervisor'}
                    </span>
                  </div>
                  <div className="flex justify-between text-[13px]">
                    <span>
                      <b>{num(atual.concluidas)}</b> de {num(atual.total)} das suas cargas concluídas{hoje ? ` · ${num(hoje)} hoje` : ''}
                    </span>
                    <span className="tab">{pc(atual.concluidas, atual.total)}%</span>
                  </div>
                  <Barra partes={[{ valor: atual.concluidas, cor: COR.concluida }]} total={atual.total} />
                </div>
                {pendentesDe(atual) > 0 && ABERTAS.includes(atual.situacao) && <Continuar idLote={atual.id_lote} grande />}
              </Bloco>
            )}
            {outras.length > 0 && (
              <div className="flex flex-wrap gap-2 text-sm">
                <span className="text-muted-foreground">Outras folhas nesta atividade:</span>
                {outras.map((p) => (
                  <a key={p.id_lote_etapa} href={href('execucao', { atividade: chave, folha: p.id_lote_etapa })} className="tab text-ibge hover:underline">
                    {p.folha_revisao} ({num(pendentesDe(p))})
                  </a>
                ))}
              </div>
            )}
            {atual && <Cargas key={atual.id_lote_etapa} p={atual} />}
            <div className="flex flex-wrap items-stretch gap-4">
              {terminadas.map((p) => (
                <Bloco key={p.id_lote_etapa} className="flex-[1_1_280px] gap-1.5">
                  <h2 className="font-semibold">
                    {p.folha_revisao} · {p.tema}
                  </h2>
                  <span className="text-[13px] text-muted-foreground">
                    {plural(p.total, 'carga concluída', 'cargas concluídas')}. Sua parte terminou; a folha segue quando o supervisor abrir a próxima etapa.
                  </span>
                  <a href={href('execucao', { atividade: chave, folha: p.id_lote_etapa })} className="text-[13px] text-ibge hover:underline">
                    Ver as cargas
                  </a>
                </Bloco>
              ))}
              <Bloco className="flex-[1_1_300px]">
                <div className="flex items-baseline gap-2.5">
                  <h2 className="font-semibold">Suas conclusões</h2>
                  <span className="text-[13px] text-muted-foreground">últimos 10 dias, todas as atividades</span>
                </div>
                <Producao dias={dias} altura={80} />
              </Bloco>
            </div>
          </>
        )}
        <p className="text-[13px] text-muted-foreground">
          O trabalho é no QGIS (barra do Feixe: próxima, pular, concluir). Aqui é o acompanhamento e o atalho para levar o QGIS até uma carga. As cargas puladas no QGIS continuam aqui: o pulo só vale naquela sessão do QGIS.
        </p>
      </Conteudo>
    </>
  )
}
