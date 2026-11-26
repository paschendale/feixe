import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { Barra, Campo, Colunas, COR, LinkSeta, Nota, RotuloEstavel, Tabela } from '@/components/ds'
import type { PlanoCQ, PlanosCQ as Planos, PreviaCQ } from '@/lib/api'
import { useAvisar } from '@/lib/avisos'
import { lista, num, plural } from '@/lib/formato'
import { enviar, useApi } from '@/lib/useApi'
import { cn } from '@/lib/utils'
import { ElementoCQ, SeloResultado } from './ResultadoCQ'

// Parâmetros dos Quadros 5 e 6 do manual (core/cq/amostragem.py): níveis gerais de inspeção e colunas de LQA.
export const NIVEIS = ['I', 'II', 'III']
export const LQAS = [0.4, 0.65, 1, 1.5, 2.5, 4, 6.5, 10, 15, 25]
export const pct = (x: number | null | undefined) => (x == null ? '—' : `${x.toLocaleString('pt-BR')}%`)

type Linha = Pick<PlanoCQ, 'atividade' | 'elemento' | 'N' | 'nivel' | 'lqa' | 'letra' | 'n' | 'ac' | 'inspecao_completa'>

// "Comissão: N=113 células, nível II, LQA 4% → letra F, 20 amostras, aceita até 2"
// Planos convertidos do DF (antes do Feixe) podem vir sem N, letra ou Ac: a frase diz "—" em vez de quebrar a gaveta.
const qt = (n: number | null | undefined, um: string, varios: string) => (n == null ? `— ${varios}` : plural(n, um, varios))
const ou = (n: number | null | undefined) => (n == null ? '—' : num(n))

export function frasePlano(p: Linha) {
  const quanto = p.inspecao_completa
    ? `${p.letra ? `letra ${p.letra}, ` : ''}todas as ${qt(p.N, 'célula', 'células')} (n ≥ N)`
    : `letra ${p.letra ?? '—'}, ${qt(p.n, 'amostra', 'amostras')}`
  return `${p.elemento ?? p.atividade}: N=${qt(p.N, 'célula', 'células')}, nível ${p.nivel ?? '—'}, LQA ${pct(p.lqa)} → ${quanto}, aceita até ${ou(p.ac)}`
}

type Alvo = { id_atividade: number; nome: string }

// Criar ou refazer planos: os parâmetros (padrão da etapa já preenchido), a prévia com N, letra, n e Ac por atividade e
// a confirmação. Confirmar grava o mesmo sorteio da prévia (a semente vai junto) e gera as cargas das amostras.
function Parametros({
  idLoteEtapa,
  alvos,
  refazer,
  inicial,
  onde,
  fechar,
}: {
  idLoteEtapa: number
  alvos: Alvo[]
  onde: string
  refazer: boolean
  inicial: { nivel: string | null; lqa: number | null; fracao_critica: number | null }
  fechar: (feito?: boolean) => void
}) {
  const avisar = useAvisar()
  const [nivel, setNivel] = useState(inicial.nivel ?? '')
  const [lqa, setLqa] = useState(inicial.lqa != null ? String(inicial.lqa) : '')
  const [fracao, setFracao] = useState(inicial.fracao_critica != null ? String(inicial.fracao_critica) : '')
  const [previas, setPrevias] = useState<PreviaCQ[] | null>(null)
  const [erro, setErro] = useState<string | null>(null)
  const [ocupado, setOcupado] = useState(false)
  useEffect(() => {
    setPrevias(null)
    setErro(null)
  }, [nivel, lqa, fracao])

  const corpo = (a: Alvo, extra: Record<string, unknown>) => ({
    id_atividade: a.id_atividade,
    nivel,
    lqa: Number(lqa),
    fracao_critica: fracao.trim() ? fracao.replace(',', '.') : null,
    refazer,
    ...extra,
  })

  async function verPrevia() {
    setOcupado(true)
    setErro(null)
    try {
      setPrevias(await Promise.all(alvos.map((a) => enviar<PreviaCQ>(`/api/lote_etapas/${idLoteEtapa}/cq_plano`, corpo(a, { previa: true })))))
    } catch (e) {
      setErro((e as Error).message)
    } finally {
      setOcupado(false)
    }
  }

  async function confirmar() {
    if (!previas) return
    setOcupado(true)
    const feitos: PreviaCQ[] = []
    try {
      for (const [i, a] of alvos.entries()) feitos.push(await enviar<PreviaCQ>(`/api/lote_etapas/${idLoteEtapa}/cq_plano`, corpo(a, { previa: false, semente: previas[i].semente })))
    } catch (e) {
      setErro((e as Error).message)
    } finally {
      setOcupado(false)
    }
    if (feitos.length) {
      const amostras = feitos.reduce((s, f) => s + f.n, 0)
      avisar(`${refazer ? 'Plano refeito' : plural(feitos.length, 'plano criado', 'planos criados')}: ${plural(amostras, 'amostra sorteada', 'amostras sorteadas')}, uma carga por célula. Próximo passo: distribuir as amostras.`)
      if (feitos.length === alvos.length) fechar(true)
    }
  }

  const titulo = refazer ? `Trocar parâmetros · ${alvos[0]?.nome}` : 'Criar os planos de CQ'
  return (
    <Dialog open onOpenChange={(v) => !v && fechar()}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{titulo}</DialogTitle>
          <DialogDescription>
            {refazer
              ? 'As amostras atuais deste plano saem e o sorteio é refeito com os novos parâmetros. Só dá enquanto nenhuma amostra foi avaliada ou distribuída.'
              : `Um plano por atividade (${lista(alvos.map((a) => a.nome))}). Ao confirmar, o Feixe sorteia as células e gera as cargas das amostras, sem responsável.`}
          </DialogDescription>
        </DialogHeader>
        <div className="grid grid-cols-3 gap-3">
          <Campo rotulo="Nível de inspeção">
            <Select value={nivel} onChange={(e) => setNivel(e.target.value)}>
              <option value="">Escolha…</option>
              {NIVEIS.map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </Select>
          </Campo>
          <Campo rotulo="LQA">
            <Select value={lqa} onChange={(e) => setLqa(e.target.value)}>
              <option value="">Escolha…</option>
              {LQAS.map((x) => (
                <option key={x} value={String(x)}>
                  {pct(x)}
                </option>
              ))}
            </Select>
          </Campo>
          <Campo rotulo="Fração crítica (%)">
            <Input value={fracao} onChange={(e) => setFracao(e.target.value)} placeholder="a do elemento" inputMode="decimal" />
          </Campo>
        </div>
        <div className="min-h-[112px] rounded-xl bg-preenchimento-2 p-3 text-nota">
          {!previas && !erro && <span className="text-muted-foreground">Escolha o nível e o LQA e veja a prévia: o tamanho do universo (N), a letra-código, quantas amostras e quantas não conformes o plano aceita.</span>}
          {erro && <span className="text-perigo">{erro}</span>}
          {previas && (
            <Tabela solta densa fixa>
              <Colunas larguras={[undefined, 70, 60, 80, 80]} />
              <thead>
                <tr>
                  <th>Atividade</th>
                  <th className="text-right">N</th>
                  <th className="text-right">Letra</th>
                  <th className="text-right">Amostras</th>
                  <th className="text-right">Aceita até</th>
                </tr>
              </thead>
              <tbody className="tab">
                {previas.map((p) => (
                  <tr key={p.id_atividade}>
                    <td className="truncate" title={`${p.atividade}\n${p.universo}`}>
                      {p.elemento ?? p.atividade}
                    </td>
                    <td className="text-right">{num(p.N)}</td>
                    <td className="text-right">{p.letra ?? '—'}</td>
                    <td className="text-right">{p.inspecao_completa ? `todas (${num(p.n)})` : num(p.n)}</td>
                    <td className="text-right">{num(p.ac)}</td>
                  </tr>
                ))}
              </tbody>
            </Tabela>
          )}
          {previas?.some((p) => p.ja_sorteadas > 0) && (
            <p className="mt-2 text-rodape text-muted-foreground">As células já sorteadas em passagens anteriores {onde}, na mesma atividade, ficam fora do universo.</p>
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => fechar()}>
            Cancelar
          </Button>
          {previas ? (
            <Button disabled={ocupado} onClick={confirmar}>
              <RotuloEstavel ocupado={ocupado} rotulo={refazer ? 'Refazer o plano' : 'Criar e sortear'} rotuloOcupado="Sorteando…" />
            </Button>
          ) : (
            <Button disabled={ocupado || !nivel || !lqa} onClick={verPrevia}>
              <RotuloEstavel ocupado={ocupado} rotulo="Ver prévia" rotuloOcupado="Calculando…" />
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// Gaveta da folha, etapa de CQ (D2): os planos de amostragem da passagem e o próximo passo. Os planos saem sozinhos
// quando a etapa abre com nível e LQA padrão (D-136); sem padrão, aqui se criam. Depois: distribuir as amostras.
export function PlanosCQ({ idLoteEtapa, folha, distribuir }: { idLoteEtapa: number; folha: boolean; distribuir: () => void }) {
  const { dados, erro } = useApi<Planos>(`/api/lote_etapas/${idLoteEtapa}/cq_planos`, ['lote', 'carga'])
  const [dialogo, setDialogo] = useState<{ alvos: Alvo[]; refazer: boolean; inicial: Planos['padrao'] } | null>(null)
  const onde = folha ? 'desta folha' : 'deste lote'

  if (!dados) return <div className="min-h-[72px] text-nota text-muted-foreground">{erro ?? 'Carregando os planos de CQ…'}</div>
  const aberta = ['pendente', 'em_andamento'].includes(dados.situacao)
  const porArea = dados.sem_plano.filter((a) => !a.por_feicao)
  const porFeicao = dados.sem_plano.filter((a) => a.por_feicao)
  // Sem avaliador = ainda sem avaliação e sem responsável (a amostra avaliada já não pede distribuição).
  const semAvaliador = dados.resultado.sem_avaliador
  const temPadrao = !!dados.padrao.nivel && dados.padrao.lqa != null

  return (
    <div className="flex flex-col gap-2.5">
      <span className="text-nota font-semibold">Planos de amostragem</span>
      {dados.planos.length > 0 && (
        <Tabela solta densa fixa>
          <Colunas larguras={[undefined, 196, 156]} />
          <tbody>
            {dados.planos.map((p) => (
              <tr key={p.id}>
                <td title={`${frasePlano(p)}\n${p.atividade}${p.universo ? `\n${p.universo}` : ''}\nfração crítica ${pct(p.fracao_critica)} · semente ${p.semente}`}>
                  <span className="block truncate font-medium">{p.elemento ?? p.atividade}</span>
                  <span className="block truncate text-rodape text-muted-foreground">{frasePlano(p).replace(/^[^:]*: /, '')}</span>
                </td>
                {/* Andamento do plano (D3d): avaliadas/n e não conformes x Ac. A decisão (aprovar, nova revisão) é do supervisor, no D4. */}
                <td className="tab">
                  <span className="block truncate">
                    {num(p.avaliadas)} de {num(p.amostras)} avaliadas
                  </span>
                  <span className={cn('block truncate text-rodape', p.ac != null && p.nao_conformes > p.ac && 'text-alerta')}>
                    <b>{num(p.nao_conformes)}</b> {p.nao_conformes === 1 ? 'não conforme' : 'não conformes'} · aceita até {ou(p.ac)}
                  </span>
                  <Barra
                    className="mt-1"
                    altura={4}
                    total={p.amostras}
                    partes={[
                      { valor: p.avaliadas - p.nao_conformes, cor: COR.concluida, rotulo: 'conformes' },
                      { valor: p.nao_conformes, cor: COR.naoConforme, rotulo: 'não conformes' },
                    ]}
                  />
                </td>
                <td className="text-right">
                  {aberta && p.pode_refazer ? (
                    <Button size="sm" variant="outline" onClick={() => setDialogo({ alvos: [{ id_atividade: p.id_atividade, nome: p.elemento ?? p.atividade }], refazer: true, inicial: { nivel: p.nivel, lqa: p.lqa, fracao_critica: p.fracao_critica } })}>
                      Trocar parâmetros
                    </Button>
                  ) : (
                    <span className="text-rodape text-muted-foreground" title={p.motivo_refazer ?? undefined}>
                      plano fechado
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </Tabela>
      )}
      {dados.planos.length > 0 && (
        <div className="flex flex-col gap-3 rounded-xl bg-preenchimento-2 px-4 py-3" aria-label="Resultado do CQ">
          <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1 text-nota">
            <b>Resultado</b>
            <SeloResultado resultado={dados.resultado.resultado} />
            <span className="text-muted-foreground">
              {dados.resultado.faltam > 0
                ? `faltam ${plural(dados.resultado.faltam, 'amostra', 'amostras')} (${num(dados.resultado.avaliadas)} de ${num(dados.resultado.amostras)} avaliadas)`
                : `todas as ${plural(dados.resultado.amostras, 'amostra avaliada', 'amostras avaliadas')}`}
            </span>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            {dados.planos.map((p) => (
              <ElementoCQ key={p.id} p={p} compacto />
            ))}
          </div>
          {/* Com amostras sem avaliador, o próximo passo (Distribuir) vem logo abaixo, com o botão. */}
          {aberta && dados.resultado.faltam > 0 && semAvaliador === 0 && (
            <span className="text-nota text-texto-2">
              <b className="text-foreground">Próximo passo: esperar os avaliadores.</b> {folha ? 'A folha aparece' : 'O lote aparece'} em Esperando você, com o resultado, quando todas as amostras forem avaliadas.
            </span>
          )}
          {aberta && dados.resultado.faltam === 0 && (
            <span className="text-nota text-texto-2">
              <b className="text-foreground">Próximo passo: decidir</b> em {folha ? '“Andar com a folha”' : '“Andar com o lote”'} (abaixo): Aprovar ou Nova revisão.
            </span>
          )}
        </div>
      )}
      {aberta && porArea.length > 0 && (
        <Nota
          tom="info"
          acao={
            <Button size="sm" onClick={() => setDialogo({ alvos: porArea.map((a) => ({ id_atividade: a.id_atividade, nome: a.elemento ?? a.atividade })), refazer: false, inicial: dados.padrao })}>
              Criar os planos de CQ
            </Button>
          }
        >
          <span>
            <b className="text-foreground">Próximo passo: criar os planos de CQ</b> de {lista(porArea.map((a) => a.elemento ?? a.atividade))}.{' '}
            {temPadrao
              ? 'Os parâmetros padrão da etapa já vêm preenchidos.'
              : 'A etapa não tem nível de inspeção e LQA padrão: escolha agora. Com o padrão no fluxo (Supervisão › Fluxos), os próximos CQs já abrem com as amostras sorteadas.'}
          </span>
        </Nota>
      )}
      {aberta && !dados.planos.length && !dados.sem_plano.length && (
        <Nota
          tom="info"
          acao={
            <LinkSeta href="#/supervisao/fluxos" className="text-nota">
              Abrir os fluxos
            </LinkSeta>
          }
        >
          <span>
            <b className="text-foreground">Próximo passo: escolher as medidas de CQ desta etapa.</b> A etapa não tem atividade de CQ no fluxo, então não há o que sortear. Em Supervisão › Fluxos, acrescente as medidas a inspecionar; depois, os planos se criam aqui.
          </span>
        </Nota>
      )}
      {porFeicao.length > 0 && (
        <span className="text-rodape text-alerta">
          {lista(porFeicao.map((a) => a.elemento ?? a.atividade))}: inspeção por feição ainda não tem plano no Feixe.
        </span>
      )}
      {aberta && porArea.length === 0 && semAvaliador > 0 && (
        <Nota
          tom="info"
          acao={
            <Button size="sm" onClick={distribuir}>
              Distribuir as amostras
            </Button>
          }
        >
          <span>
            <b className="text-foreground">Próximo passo: distribuir as amostras.</b> {plural(semAvaliador, 'amostra está', 'amostras estão')} sem avaliador; a etapa começa quando um avaliador as receber.
          </span>
        </Nota>
      )}
      {dialogo && (
        <Parametros
          idLoteEtapa={idLoteEtapa}
          alvos={dialogo.alvos}
          refazer={dialogo.refazer}
          inicial={dialogo.inicial}
          onde={onde}
          fechar={(feito) => {
            setDialogo(null)
            if (feito) distribuir()
          }}
        />
      )}
    </div>
  )
}
