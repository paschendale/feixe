import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Barra, Bloco, COR, CabecalhoModulo, Carregando, Colunas, Conteudo, Fichas, LinkSeta, Segmentado, Tabela, TituloBloco, Vazio } from '@/components/ds'
import type { Carga, Passagem, Progresso, ResumoCargas } from '@/lib/api'
import { useAvisar } from '@/lib/avisos'
import { diaMes, diasAtras, hora, num, pc, plural } from '@/lib/formato'
import { href, navegar, useRota } from '@/lib/rotas'
import { useSessao } from '@/lib/sessao'
import { enviar, useApi } from '@/lib/useApi'
import { AmostrasCQ } from './AmostrasCQ'
import { Correcao } from './Correcao'
import { ABERTAS, Continuar, Preparando, Producao, pendentesDe, usePainelExecucao, usePorDia } from './comum'
import { MeusConflitos } from './MeusConflitos'
import { ParaCiencia } from './ParaCiencia'

const JANELA_DESFAZER_MS = 24 * 3600 * 1000
const chaveDe = (p: Passagem) => `${p.tema} · ${p.etapa}`
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
  const abas: { id: Aba; rotulo: string; contagem: string }[] = [
    { id: 'pendentes', rotulo: 'Pendentes', contagem: num(pendentes.length) },
    { id: 'concluidas', rotulo: 'Concluídas', contagem: num(concluidas.length) },
    { id: 'hoje', rotulo: 'Hoje', contagem: num(hoje.length) },
  ]
  return (
    <>
      <Segmentado rotulo="Situação" opcoes={abas} ativa={aba} escolher={setAba} />
      <Tabela fixa>
        <Colunas larguras={[200, ...(variasAtividades ? ['26%'] : []), undefined, 240]} />
        <thead>
          <tr>
            <th>Carga</th>
            {variasAtividades && <th>Atividade</th>}
            <th>Situação</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {lista.length === 0 && (
            <tr>
              <td colSpan={variasAtividades ? 4 : 3} className="text-muted-foreground">
                {aba === 'pendentes' ? 'Nenhuma pendente: sua parte neste lote terminou.' : aba === 'hoje' ? 'Nenhuma concluída hoje.' : 'Nenhuma concluída ainda.'}
              </td>
            </tr>
          )}
          {lista.slice(0, 300).map((c) => (
            <tr key={c.id}>
              <td className="tab font-mono text-nota">{c.geocodigo ?? `nº ${c.id}`}</td>
              {variasAtividades && (
                <td className="truncate text-muted-foreground" title={c.atividade}>
                  {c.atividade}
                </td>
              )}
              <td>{c.concluido ? <span className="text-muted-foreground">concluída {diaMes(c.concluido_em)} {hora(c.concluido_em)}</span> : 'pendente'}</td>
              <td className="py-2">
                <span className="flex justify-end gap-1.5">
                  {c.concluido && aberta && recente(c) && (
                    <Button size="sm" variant="ghost" disabled={acoes.ocupado === c.id} onClick={() => acoes.desfazer(c)}>
                      Desfazer
                    </Button>
                  )}
                  {(c.concluido || aberta) && (
                    <Button size="sm" variant="outline" className="w-[124px]" disabled={!conectado || acoes.ocupado === c.id} onClick={() => acoes.trabalhar(c)}>
                      {c.concluido ? 'Ver no QGIS' : 'Trabalhar nesta'}
                    </Button>
                  )}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
        {lista.length > 300 && (
          <tfoot>
            <tr>
              <td colSpan={variasAtividades ? 4 : 3}>Mostrando 300 de {num(lista.length)}. No QGIS, a camada Minhas cargas mostra todas.</td>
            </tr>
          </tfoot>
        )}
      </Tabela>
      {hoje.length > 0 && aba !== 'hoje' && (
        <Bloco className="gap-2">
          <TituloBloco titulo="Concluídas hoje" />
          <div className="flex flex-wrap gap-x-4 gap-y-1.5 text-nota">
            {hoje.slice(0, 6).map((c) => (
              <span key={c.id} className="tab inline-flex items-center gap-1.5">
                {c.geocodigo ?? `nº ${c.id}`} · {hora(c.concluido_em)}
                {aberta && (
                  <button className="font-medium text-primary hover:underline" disabled={acoes.ocupado === c.id} onClick={() => acoes.desfazer(c)}>
                    Desfazer
                  </button>
                )}
              </span>
            ))}
            {hoje.length > 6 && <button className="font-medium text-primary hover:underline" onClick={() => setAba('hoje')}>e mais {num(hoje.length - 6)}</button>}
          </div>
          <span className="text-rodape text-muted-foreground">Desfazer vale por 24 horas, só para quem concluiu.</span>
        </Bloco>
      )}
    </>
  )
}

// Execução (D-103, D3d, D5): Minhas cargas (produção), Minhas amostras (CQ do avaliador), Correção (as folhas na
// correção de inspeção) e Para ciência (ocorrências nas cargas da pessoa, D-66). O trabalho é no QGIS (barra do Feixe); aqui é o acompanhamento e o atalho para levar o QGIS
// até uma carga, uma amostra ou uma ocorrência.
export default function Execucao() {
  const rota = useRota()
  const { tem } = useSessao()
  const { dados: cargas, erro } = useApi<ResumoCargas>('/api/cargas/resumo', ['carga', 'lote'])
  const { dados: painel, erro: erroPainel } = usePainelExecucao()
  const nCiencia = painel?.ciencia.pendentes.length ?? 0
  const temCQ = tem('avaliador') || !!painel?.cq.length
  const temCiencia = tem('apm') || nCiencia > 0 || !!painel?.ciencia.cientes.length
  // Passagens de CQ e as de correção de inspeção em que a minha parte é só a varredura (a carga da folha, D5) ficam
  // nas abas delas.
  const fora = painel ? new Set([...painel.cq.map((c) => c.id_lote_etapa), ...painel.correcao.filter((c) => c.so_folha).map((c) => c.id_lote_etapa)]) : null
  const producao = cargas && fora ? cargas.passagens.filter((p) => !fora.has(p.id_lote_etapa)) : []
  const temCorrecao = !!painel?.correcao.length
  const nCorrecao = painel?.correcao.reduce((s, f) => s + f.pendentes, 0) ?? 0
  // Sem aba no endereço: a de produção; quem só tem amostras (avaliador) cai direto no CQ, e quem só tem a correção,
  // na correção.
  const pedida = rota.partes[0]
  const soCorrecao = !pedida && temCorrecao && cargas && painel && producao.length === 0 && painel.cq.length === 0
  const ativa =
    pedida === 'cq' && temCQ
      ? 'cq'
      : pedida === 'ciencia' && temCiencia
        ? 'ciencia'
        : (pedida === 'correcao' && temCorrecao) || soCorrecao
          ? 'correcao'
          : !pedida && temCQ && cargas && painel && producao.length === 0 && painel.cq.length > 0
            ? 'cq'
            : 'cargas'
  const abasModulo = [
    { id: 'cargas', rotulo: 'Minhas cargas', href: href('execucao/cargas') },
    ...(temCQ ? [{ id: 'cq', rotulo: 'Minhas amostras', href: href('execucao/cq') }] : []),
    ...(temCorrecao ? [{ id: 'correcao', rotulo: 'Correção', href: href('execucao/correcao'), contagem: nCorrecao }] : []),
    ...(temCiencia ? [{ id: 'ciencia', rotulo: 'Para ciência', href: href('execucao/ciencia'), contagem: nCiencia }] : []),
  ]
  const preparando = cargas?.preparando || painel?.preparando
  if (!cargas || !painel || preparando)
    return (
      <>
        <CabecalhoModulo titulo="Execução" abas={abasModulo} ativa={ativa} />
        <Conteudo largura={1240}>{preparando ? <Preparando /> : <Carregando erro={erro ?? erroPainel} />}</Conteudo>
      </>
    )
  return (
    <>
      <CabecalhoModulo titulo="Execução" abas={abasModulo} ativa={ativa} />
      <Conteudo largura={1240}>
        <MeusConflitos />
        {ativa === 'cargas' && <MinhasCargas passagens={producao} temCQ={painel.cq.some((c) => c.aberta && c.pendentes > 0)} />}
        {ativa === 'cq' && <AmostrasCQ cq={painel.cq} />}
        {ativa === 'correcao' && <Correcao folhas={painel.correcao} />}
        {ativa === 'ciencia' && (
          <>
            <p className="max-w-[880px] text-texto-2">
              O avaliador apontou estas ocorrências nas suas cargas. Veja cada uma no QGIS e marque <b>Ciente</b>: é o retorno do controle de qualidade, não um pedido de correção. A correção, quando houver, vem numa etapa própria.
            </p>
            <ParaCiencia dados={painel.ciencia} comCientes />
          </>
        )}
      </Conteudo>
    </>
  )
}

// Execução › Minhas cargas: as cargas de produção (as amostras de CQ ficam na aba delas).
function MinhasCargas({ passagens: todas, temCQ }: { passagens: Passagem[]; temCQ: boolean }) {
  const rota = useRota()
  const { dias, hoje } = usePorDia()
  const dados = { passagens: todas }
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
      {chaves.length === 0 ? (
        <Bloco>
          <Vazio>
            {temCQ ? (
              <>
                Nenhuma carga de produção com você agora. As suas amostras de CQ estão em <a className="font-medium text-primary hover:underline" href={href('execucao/cq')}>Minhas amostras</a>.
              </>
            ) : (
              'Nenhuma carga atribuída a você em lotes abertos. O supervisor atribui as cargas.'
            )}
          </Vazio>
        </Bloco>
      ) : (
        <>
          <Fichas
            rotulo="Atividade"
            ativa={chave}
            escolher={(k) => navegar(`execucao/cargas?atividade=${encodeURIComponent(k)}`)}
            fichas={chaves.map((k) => ({ id: k, rotulo: k, contagem: pendentesDaChave(k) ? `${num(pendentesDaChave(k))} pendentes` : 'tudo concluído' }))}
          />
          {atual && (
            <Bloco className="flex-row flex-wrap items-center gap-x-5 gap-y-3 px-5 py-4">
              <div className="flex min-w-[300px] flex-1 flex-col gap-1.5">
                <div className="flex flex-wrap items-baseline gap-x-3">
                  <span className="tab text-titulo-2 font-bold">{atual.folha_revisao}</span>
                  <span className="text-muted-foreground">
                    {atual.tema} · {atual.etapa} · {ABERTAS.includes(atual.situacao) ? (atual.situacao === 'pendente' ? 'a iniciar' : 'em andamento') : 'encerrada pelo supervisor'}
                  </span>
                </div>
                <div className="flex justify-between text-nota">
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
            <div className="flex flex-wrap gap-2">
              <span className="text-muted-foreground">Outros lotes nesta atividade:</span>
              {outras.map((p) => (
                <a key={p.id_lote_etapa} href={href('execucao/cargas', { atividade: chave, folha: p.id_lote_etapa })} className="tab font-medium text-primary hover:underline">
                  {p.folha_revisao} ({num(pendentesDe(p))})
                </a>
              ))}
            </div>
          )}
          {atual && <Cargas key={atual.id_lote_etapa} p={atual} />}
          <div className="grid grid-cols-[repeat(auto-fill,minmax(280px,1fr))] gap-4">
            {terminadas.map((p) => (
              <Bloco key={p.id_lote_etapa} className="gap-1.5">
                <TituloBloco titulo={`${p.folha_revisao} · ${p.tema}`} />
                <span className="text-nota text-muted-foreground">
                  {plural(p.total, 'carga concluída', 'cargas concluídas')}. Sua parte terminou; o lote segue quando o supervisor abrir a próxima etapa.
                </span>
                <LinkSeta href={href('execucao/cargas', { atividade: chave, folha: p.id_lote_etapa })} className="text-nota">
                  Ver as cargas
                </LinkSeta>
              </Bloco>
            ))}
            <Bloco>
              <TituloBloco titulo="Suas conclusões" sub="últimos 10 dias, todas as atividades" />
              <Producao dias={dias} altura={80} />
            </Bloco>
          </div>
        </>
      )}
      <p className="text-nota text-muted-foreground">
        O trabalho é no QGIS (barra do Feixe: próxima, pular, concluir). Aqui é o acompanhamento e o atalho para levar o QGIS até uma carga. As cargas puladas no QGIS continuam aqui: o pulo só vale naquela sessão do QGIS.
      </p>
    </>
  )
}
