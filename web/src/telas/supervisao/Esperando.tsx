import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Bloco, Campo, Carregando, Conteudo, Nota, RotuloEstavel, Selo, TituloBloco, Vazio } from '@/components/ds'
import type { DecisaoCQ, GrupoEsperando, ResultadoAvanco } from '@/lib/api'
import { useAvisar } from '@/lib/avisos'
import { contarLotes, diaMes, num, plural, soFolhas } from '@/lib/formato'
import { href } from '@/lib/rotas'
import { enviar } from '@/lib/useApi'
import { cn } from '@/lib/utils'
import { Distribuir } from '../folhas/Distribuir'
import { comCargas, resumoPreparo } from '../folhas/preparo'
import { DecidirCQ, ElementoCQ, RESULTADO, SeloResultado } from './ResultadoCQ'

const VISIVEIS = 12

function periodo(g: GrupoEsperando) {
  if (!g.desde) return ''
  return diaMes(g.desde) === diaMes(g.ate) ? `desde ${diaMes(g.desde)}` : `de ${diaMes(g.desde)} a ${diaMes(g.ate)}`
}

// Recusas agrupadas pelo motivo, para não virar um aviso com uma linha por folha.
function resumirRecusas(erros: { id_lote: number; erro: string }[], nome: (id: number) => string, tipo: (id: number) => string | undefined) {
  const porMotivo = new Map<string, number[]>()
  for (const e of erros) {
    const motivo = e.erro.replace(/^(a folha|o lote) /, '')
    porMotivo.set(motivo, [...(porMotivo.get(motivo) ?? []), e.id_lote])
  }
  return [...porMotivo]
    .map(([motivo, ids]) => `${contarLotes(ids.map((id) => ({ tipo: tipo(id) })))} não ${ids.length === 1 ? 'abriu' : 'abriram'}: ${motivo} (${ids.slice(0, 4).map(nome).join(', ')}${ids.length > 4 ? ', …' : ''})`)
    .join(' · ')
}

// Folhas com o CQ avaliado (D4), agrupadas pelo resultado: por folha, a frase por elemento e, no detalhe, o nível de
// conformidade com o velocímetro. Marque as que vão juntas e decida: Aprovar (abre a etapa seguinte) ou Nova revisão
// (abre a revisão seguinte por outra pessoa). Cada folha numa transação; a confirmação mostra o que vai acontecer.
function GrupoCQ({ g, recarregar, distribuir }: { g: GrupoEsperando; recarregar: () => void; distribuir: (ids: number[]) => void }) {
  const [marcadas, setMarcadas] = useState<Set<number>>(new Set())
  const [detalhe, setDetalhe] = useState<number | null>(null)
  const [decidir, setDecidir] = useState<DecisaoCQ | null>(null)
  const tudo = marcadas.size === g.folhas.length
  const r = g.resultado ?? 'pendente'
  const reprovadas = r === 'reprovado'
  const acoes: DecisaoCQ[] = reprovadas ? ['nova_revisao', 'aprovar'] : ['aprovar', 'nova_revisao']
  // Rótulos fixos (a barra não muda de largura ao marcar); quantas folhas, a confirmação diz.
  const rotulo = (d: DecisaoCQ) => (d === 'nova_revisao' ? 'Nova revisão…' : reprovadas ? 'Aprovar mesmo assim…' : `Aprovar${g.proxima ? ` e abrir ${g.proxima}` : ''}…`)
  return (
    <Bloco className="gap-4">
      <TituloBloco
        titulo={
          <>
            {g.tema} · {g.etapa} avaliado
          </>
        }
        sub={
          <>
            {contarLotes(g.folhas)} com todas as amostras avaliadas {periodo(g)}
          </>
        }
        acao={<SeloResultado resultado={r} />}
      />
      <p className="text-nota text-texto-2">
        {reprovadas
          ? 'Os não conformes passaram do aceito em pelo menos um elemento. O caminho sugerido é uma nova revisão por outra pessoa; aprovar mesmo assim pede a sua confirmação.'
          : r === 'aprovado'
            ? `Todos os elementos ficaram dentro do aceito. O caminho sugerido é aprovar${g.proxima ? ` e abrir ${g.proxima}` : ''}.`
            : 'Os planos não têm Ac (convertidos do DF): o Feixe não tem a régua. Confira os não conformes e decida.'}
      </p>
      <ul className="flex flex-col">
        {g.folhas.map((f) => (
          <li key={f.id_lote} className="border-t border-linha py-2 first:border-0">
            <div className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-3">
              <label className={cn('tab inline-flex w-[104px] cursor-pointer items-center gap-1.5 rounded-md px-2.5 py-1', marcadas.has(f.id_lote) ? 'bg-primary-suave text-primary' : 'bg-preenchimento-2 hover:bg-preenchimento')}>
                <input
                  type="checkbox"
                  checked={marcadas.has(f.id_lote)}
                  onChange={() =>
                    setMarcadas((m) => {
                      const n = new Set(m)
                      if (n.has(f.id_lote)) n.delete(f.id_lote)
                      else n.add(f.id_lote)
                      return n
                    })
                  }
                />
                {f.folha_revisao}
              </label>
              <span className="truncate text-nota text-texto-2" title={f.cq?.frase}>
                {f.cq?.frase}
              </span>
              <button className="px-1 text-nota font-medium text-primary hover:underline" aria-expanded={detalhe === f.id_lote} onClick={() => setDetalhe(detalhe === f.id_lote ? null : f.id_lote)}>
                <RotuloEstavel ocupado={detalhe === f.id_lote} rotulo="Ver detalhe" rotuloOcupado="Fechar detalhe" />
              </button>
            </div>
            {detalhe === f.id_lote && f.cq && (
              <div className="mt-2.5 flex flex-col gap-3 rounded-xl bg-preenchimento-2 p-3">
                <div className="grid gap-3 sm:grid-cols-2">
                  {f.cq.planos.map((p) => (
                    <ElementoCQ key={p.id} p={p} compacto />
                  ))}
                </div>
                <a className="self-start text-nota font-medium text-primary hover:underline" href={href(`supervisao/folhas/${f.id_lote}`, { grupo: 'todas' })}>
                  Abrir {f.tipo === 'folha' ? 'a folha' : 'o lote'} (ocorrências e histórico)
                </a>
              </div>
            )}
          </li>
        ))}
      </ul>
      <div className="flex flex-wrap items-center gap-2.5 border-t border-linha pt-4">
        {acoes.map((d, i) => (
          <Button key={d} variant={i === 0 ? 'default' : 'outline'} disabled={!marcadas.size} onClick={() => setDecidir(d)}>
            {rotulo(d)}
          </Button>
        ))}
        <Button variant="outline" onClick={() => setMarcadas(tudo ? new Set() : new Set(g.folhas.map((f) => f.id_lote)))}>
          <RotuloEstavel ocupado={tudo} rotulo={`Marcar ${soFolhas(g.folhas) ? 'as' : 'os'} ${num(g.folhas.length)}`} rotuloOcupado="Desmarcar" />
        </Button>
        <span className="text-rodape text-muted-foreground">{RESULTADO[r].rotulo === 'Reprovada' ? 'A observação e o resultado vão para o histórico de cada lote.' : 'A confirmação mostra o que acontece em cada lote.'}</span>
      </div>
      <DecidirCQ
        lotes={decidir ? [...marcadas] : []}
        decisao={decidir}
        fechar={(abertas) => {
          setDecidir(null)
          if (abertas) {
            setMarcadas(new Set())
            if (abertas.length) distribuir(abertas)
          }
          recarregar()
        }}
      />
    </Bloco>
  )
}

function Grupo({ g, recarregar, distribuir }: { g: GrupoEsperando; recarregar: () => void; distribuir: (ids: number[]) => void }) {
  const avisar = useAvisar()
  const [marcadas, setMarcadas] = useState<Set<number>>(new Set())
  const [todas, setTodas] = useState(false)
  const [obs, setObs] = useState('')
  const [ocupado, setOcupado] = useState(false)
  const fim = g.id_proxima === null
  const visiveis = todas ? g.folhas : g.folhas.slice(0, VISIVEIS)
  const tudo = marcadas.size === g.folhas.length

  // Fim do fluxo (D-153): a folha passa a concluída para a CCAR; abrir outra etapa depois a reabre. Primeiro a prévia
  // (o que encerra e o que fica de fora, com o motivo); a confirmação grava. Antes do fim do fluxo (D-161, `antecipar`)
  // é o modo de segurança: a prévia mostra as etapas que ficam puladas, e gravar pede o motivo e a confirmação.
  const [previa, setPrevia] = useState<{ id_lote: number; folha_revisao: string; pula: string[]; erro: string | null }[] | null>(null)
  const [antecipar, setAntecipar] = useState(false)
  const [motivo, setMotivo] = useState('')
  const [ciente, setCiente] = useState(false)
  const puladas = [...new Set((previa ?? []).filter((i) => !i.erro).flatMap((i) => i.pula))]
  const nEncerra = previa?.filter((i) => !i.erro).length ?? 0
  const tipoDe = (id: number) => g.folhas.find((f) => f.id_lote === id)?.tipo
  const marcadosLotes = [...marcadas].map((id) => ({ tipo: tipoDe(id) }))
  const encerraLotes = (previa ?? []).filter((i) => !i.erro).map((i) => ({ tipo: tipoDe(i.id_lote) }))
  const fem = soFolhas(encerraLotes)
  async function prever(antes: boolean) {
    setOcupado(true)
    try {
      const r = await enviar<{ itens: { id_lote: number; folha_revisao: string; pula: string[]; erro: string | null }[] }>('/api/lotes/encerrar', { lotes: [...marcadas], previa: true, antecipar: antes })
      setAntecipar(antes)
      setMotivo(obs)
      setCiente(false)
      setPrevia(r.itens)
    } catch (e) {
      avisar((e as Error).message, 'erro')
    } finally {
      setOcupado(false)
    }
  }
  async function encerrar() {
    setOcupado(true)
    try {
      const r = await enviar<{ encerradas: { id_lote: number }[]; erros: { id_lote: number; erro: string }[] }>('/api/lotes/encerrar', { lotes: [...marcadas], observacao: antecipar ? motivo : obs, previa: false, antecipar })
      const nome = (id: number) => g.folhas.find((f) => f.id_lote === id)?.folha_revisao ?? `#${id}`
      if (r.encerradas.length) {
        const ls = r.encerradas.map((e) => ({ tipo: tipoDe(e.id_lote) }))
        const um = ls.length === 1
        avisar(`${contarLotes(ls)} ${soFolhas(ls) ? (um ? 'encerrada' : 'encerradas') : um ? 'encerrado' : 'encerrados'}: a CCAR passa a ${soFolhas(ls) ? (um ? 'vê-la como concluída' : 'vê-las como concluídas') : um ? 'vê-lo como concluído' : 'vê-los como concluídos'}.`)
      }
      if (r.erros.length) avisar(resumirRecusas(r.erros, nome, tipoDe), 'erro')
      setMarcadas(new Set())
      setObs('')
      setPrevia(null)
    } catch (e) {
      avisar((e as Error).message, 'erro')
    } finally {
      setOcupado(false)
      recarregar()
    }
  }

  async function abrir() {
    setOcupado(true)
    try {
      // Conclui a etapa das que terminaram as cargas e abre a seguinte; as cargas saem na hora (D-109).
      const r = await enviar<ResultadoAvanco>('/api/lotes/avancar', { lotes: [...marcadas], observacao: obs, previa: false })
      const nome = (id: number) => g.folhas.find((f) => f.id_lote === id)?.folha_revisao ?? `#${id}`
      if (r.abertas.length) avisar(`${g.proxima} aberta em ${contarLotes(r.abertas.map((a) => ({ tipo: tipoDe(a.id_lote) })))}. ${resumoPreparo(r.preparo)}`.trim())
      if (r.erros.length) avisar(resumirRecusas(r.erros, nome, tipoDe), 'erro')
      const prontas = comCargas(r.preparo)
      const paraDistribuir = r.abertas.filter((a) => prontas.has(a.id_lote_etapa)).map((a) => a.id_lote)
      if (paraDistribuir.length) distribuir(paraDistribuir)
      setMarcadas(new Set())
      setObs('')
    } catch (e) {
      avisar((e as Error).message, 'erro')
    } finally {
      setOcupado(false)
      // Sempre relê a lista: mesmo com recusa, ou se a resposta não chegou, o banco pode ter mudado.
      recarregar()
    }
  }

  return (
    <Bloco className="gap-4">
      <TituloBloco
        titulo={
          <>
            {g.tema} · {fim ? 'fim do fluxo' : `${g.etapa} terminada`}
          </>
        }
        sub={
          <>
            {contarLotes(g.folhas)} · {fim ? `última etapa (${g.etapa}) concluída` : soFolhas(g.folhas) ? 'paradas' : 'parados'} {periodo(g)}
          </>
        }
        acao={<Selo tom={fim ? 'alerta' : 'info'}>{fim ? 'precisa de decisão' : `próxima: ${g.proxima}`}</Selo>}
      />

      {fim && (
        <Nota tom="alerta">
          Não há etapa seguinte no fluxo {g.fluxo}, e a CCAR ainda vê estes lotes no status da última etapa. Marque os que terminaram e encerre: eles passam a concluídos para a CCAR. Se algum ainda precisa de trabalho, abra outra etapa pela gaveta do lote (isso também reabre um lote encerrado).
        </Nota>
      )}

      <div className="flex flex-wrap gap-2">
        {visiveis.map((f) => (
            <label
              key={f.id_lote}
              title={`${f.situacao === 'pulada' ? 'pulada' : f.ocorrencias_tratadas != null && f.situacao === 'em_andamento' ? `${plural(f.ocorrencias_tratadas, 'ocorrência tratada', 'ocorrências tratadas')}` : f.situacao === 'em_andamento' ? 'cargas concluídas' : 'concluída'} em ${diaMes(f.desde)}`}
              className={cn('tab inline-flex cursor-pointer items-center gap-1.5 rounded-md px-2.5 py-1', marcadas.has(f.id_lote) ? 'bg-primary-suave text-primary' : 'bg-preenchimento-2 hover:bg-preenchimento')}
            >
              <input
                type="checkbox"
                checked={marcadas.has(f.id_lote)}
                onChange={() =>
                  setMarcadas((m) => {
                    const n = new Set(m)
                    if (n.has(f.id_lote)) n.delete(f.id_lote)
                    else n.add(f.id_lote)
                    return n
                  })
                }
              />
              {f.folha_revisao}
            </label>
        ))}
        {g.folhas.length > VISIVEIS && (
          <button className="px-2 font-medium text-primary hover:underline" onClick={() => setTodas(!todas)}>
            <RotuloEstavel ocupado={todas} rotulo={`mais ${num(g.folhas.length - VISIVEIS)}`} rotuloOcupado="ver menos" />
          </button>
        )}
      </div>

      {fim && (
        <div className="flex flex-wrap items-end gap-2.5 border-t border-linha pt-4">
          <Campo rotulo="Observação (opcional, vai para o histórico de cada lote)" className="min-w-[280px] flex-1">
            <Input value={obs} onChange={(e) => setObs(e.target.value)} placeholder="Ex.: revisão pontual feita, lote concluído" className="text-corpo font-normal text-foreground" />
          </Campo>
          <Button variant="destructive-tinted" disabled={ocupado || !marcadas.size} onClick={() => prever(false)}>
            {marcadas.size ? `Encerrar ${contarLotes(marcadosLotes)}…` : 'Encerrar…'}
          </Button>
          <Button variant="outline" onClick={() => setMarcadas(tudo ? new Set() : new Set(g.folhas.map((f) => f.id_lote)))}>
            <RotuloEstavel ocupado={tudo} rotulo={`Marcar ${soFolhas(g.folhas) ? 'as' : 'os'} ${num(g.folhas.length)}`} rotuloOcupado="Desmarcar" />
          </Button>
        </div>
      )}

      <Dialog open={!!previa} onOpenChange={(v) => !v && setPrevia(null)}>
        <DialogContent className="max-w-xl">
          <DialogHeader>
            <DialogTitle>Encerrar {contarLotes(encerraLotes)}</DialogTitle>
            <DialogDescription>
              A CCAR passa a ver {fem ? (nEncerra === 1 ? 'a folha como concluída' : 'as folhas como concluídas') : nEncerra === 1 ? 'o lote como concluído' : 'os lotes como concluídos'}. O encerramento fica no histórico; abrir outra etapa pela gaveta {fem ? 'reabre a folha' : 'reabre o lote'}.
            </DialogDescription>
          </DialogHeader>
          {antecipar && puladas.length > 0 && (
            <Nota tom="alerta">
              {fem ? (nEncerra === 1 ? 'A folha não passa' : 'As folhas não passam') : nEncerra === 1 ? 'O lote não passa' : 'Os lotes não passam'} por: <b>{puladas.join(', ')}</b>. Use só quando essas etapas não fazem falta {nEncerra === 1 ? (fem ? 'nela' : 'nele') : fem ? 'nelas' : 'neles'}. O motivo e as etapas puladas ficam no histórico.
            </Nota>
          )}
          {antecipar && (
            <div className="flex flex-col gap-3">
              <Campo rotulo="Motivo (obrigatório)">
                <Input autoFocus value={motivo} onChange={(e) => setMotivo(e.target.value)} placeholder="Ex.: sem massa d'água cortada nestas folhas" className="text-corpo font-normal text-foreground" />
              </Campo>
              <label className="flex cursor-pointer items-start gap-2 text-nota">
                <input type="checkbox" className="mt-0.5" checked={ciente} onChange={(e) => setCiente(e.target.checked)} />
                <span>
                  Confirmo que {contarLotes(encerraLotes)} {nEncerra === 1 ? 'terminou' : 'terminaram'} sem {puladas.length === 1 ? 'essa etapa' : 'essas etapas'}.
                </span>
              </label>
            </div>
          )}
          {previa && previa.some((i) => i.erro) && (
            <Nota tom="alerta">
              Ficam de fora: {resumirRecusas(previa.filter((i) => i.erro).map((i) => ({ id_lote: i.id_lote, erro: i.erro ?? '' })), (id) => previa.find((i) => i.id_lote === id)?.folha_revisao ?? `#${id}`, tipoDe)}
            </Nota>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setPrevia(null)}>
              Cancelar
            </Button>
            <Button variant="destructive" disabled={ocupado || !nEncerra || (antecipar && (!motivo.trim() || !ciente))} onClick={encerrar}>
              <RotuloEstavel ocupado={ocupado} rotulo={`Encerrar ${contarLotes(encerraLotes)}`} rotuloOcupado="Encerrando…" />
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {!fim && (
        <div className="flex flex-wrap items-end gap-2.5 border-t border-linha pt-4">
          <Campo rotulo="Observação (opcional, vai para o histórico de cada lote)" className="min-w-[280px] flex-1">
            <Input value={obs} onChange={(e) => setObs(e.target.value)} placeholder="Ex.: aquisição conferida, CQ por amostragem" className="text-corpo font-normal text-foreground" />
          </Campo>
          <Button disabled={ocupado || !marcadas.size} onClick={abrir}>
            {marcadas.size ? `Abrir ${g.proxima} em ${contarLotes(marcadosLotes)}` : `Abrir ${g.proxima}`}
          </Button>
          <Button variant="destructive-tinted" disabled={ocupado || !marcadas.size} onClick={() => prever(true)} title="Encerra sem passar pelas etapas que faltam no fluxo. Pede o motivo.">
            Encerrar sem as próximas…
          </Button>
          <Button variant="outline" onClick={() => setMarcadas(tudo ? new Set() : new Set(g.folhas.map((f) => f.id_lote)))}>
            <RotuloEstavel ocupado={tudo} rotulo={`Marcar ${soFolhas(g.folhas) ? 'as' : 'os'} ${num(g.folhas.length)}`} rotuloOcupado="Desmarcar" />
          </Button>
        </div>
      )}
    </Bloco>
  )
}

// Supervisão › Esperando você: folhas que terminaram a etapa atual e só andam quando o supervisor abrir a próxima.
// Agrupadas pela decisão; marque as que vão juntas e decida de uma vez, com uma observação só.
export default function Esperando({ grupos, recarregar }: { grupos: GrupoEsperando[] | null; recarregar: () => void }) {
  const [distribuir, setDistribuir] = useState<number[]>([])
  if (!grupos)
    return (
      <Conteudo largura={1240}>
        <Carregando />
      </Conteudo>
    )
  const todos = grupos.flatMap((g) => g.folhas)
  const n = todos.length
  return (
    <Conteudo largura={1240}>
      {n === 0 ? (
        <Bloco>
          <Vazio>Nenhum lote esperando você: todos os lotes da unidade estão com uma etapa aberta ou encerrados.</Vazio>
        </Bloco>
      ) : (
        <p className="max-w-[820px] text-titulo-3">
          <b>{contarLotes(todos)}</b> {n === 1 ? 'terminou' : 'terminaram'} a etapa atual (as cargas estão concluídas) e só {n === 1 ? 'anda' : 'andam'} quando você abrir a próxima. {soFolhas(todos) ? 'Elas estão agrupadas' : 'Eles estão agrupados'} pela decisão; marque {soFolhas(todos) ? 'as que vão juntas' : 'os que vão juntos'} e decida de uma vez, com uma observação só. Abrir a próxima conclui a etapa, gera as cargas da seguinte e abre a distribuição. No CQ, a decisão é sobre o resultado: aprovar ou nova revisão.
        </p>
      )}
      {grupos.map((g) =>
        g.fase === 'cq' ? (
          <GrupoCQ key={`${g.tema}-${g.etapa}-${g.id_proxima}-${g.resultado}`} g={g} recarregar={recarregar} distribuir={setDistribuir} />
        ) : (
          <Grupo key={`${g.tema}-${g.etapa}-${g.id_proxima}`} g={g} recarregar={recarregar} distribuir={setDistribuir} />
        ),
      )}
      <Distribuir lotes={distribuir} fechar={() => setDistribuir([])} />
    </Conteudo>
  )
}
