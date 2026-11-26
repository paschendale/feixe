import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Bloco, Campo, Carregando, Conteudo, Nota, RotuloEstavel, Selo, TituloBloco, Vazio } from '@/components/ds'
import type { DecisaoCQ, GrupoEsperando, ResultadoAvanco } from '@/lib/api'
import { useAvisar } from '@/lib/avisos'
import { diaMes, num, plural } from '@/lib/formato'
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
function resumirRecusas(erros: { id_lote: number; erro: string }[], nome: (id: number) => string) {
  const porMotivo = new Map<string, string[]>()
  for (const e of erros) {
    const motivo = e.erro.replace(/^a folha /, '')
    porMotivo.set(motivo, [...(porMotivo.get(motivo) ?? []), nome(e.id_lote)])
  }
  return [...porMotivo]
    .map(([motivo, folhas]) => `${plural(folhas.length, 'folha', 'folhas')} não ${folhas.length === 1 ? 'abriu' : 'abriram'}: ${motivo} (${folhas.slice(0, 4).join(', ')}${folhas.length > 4 ? ', …' : ''})`)
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
            {plural(g.folhas.length, 'folha', 'folhas')} com todas as amostras avaliadas {periodo(g)}
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
                  Abrir a folha (ocorrências e histórico)
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
          <RotuloEstavel ocupado={tudo} rotulo={`Marcar as ${num(g.folhas.length)}`} rotuloOcupado="Desmarcar" />
        </Button>
        <span className="text-rodape text-muted-foreground">{RESULTADO[r].rotulo === 'Reprovada' ? 'A observação e o resultado vão para o histórico de cada folha.' : 'A confirmação mostra o que acontece em cada folha.'}</span>
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

  async function abrir() {
    setOcupado(true)
    try {
      // Conclui a etapa das que terminaram as cargas e abre a seguinte; as cargas saem na hora (D-109).
      const r = await enviar<ResultadoAvanco>('/api/lotes/avancar', { lotes: [...marcadas], observacao: obs, previa: false })
      const nome = (id: number) => g.folhas.find((f) => f.id_lote === id)?.folha_revisao ?? `#${id}`
      if (r.abertas.length) avisar(`${g.proxima} aberta em ${plural(r.abertas.length, 'folha', 'folhas')}. ${resumoPreparo(r.preparo)}`.trim())
      if (r.erros.length) avisar(resumirRecusas(r.erros, nome), 'erro')
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
            {plural(g.folhas.length, 'folha', 'folhas')} · {fim ? `última etapa (${g.etapa}) concluída` : 'paradas'} {periodo(g)}
          </>
        }
        acao={<Selo tom={fim ? 'alerta' : 'info'}>{fim ? 'precisa de decisão' : `próxima: ${g.proxima}`}</Selo>}
      />

      {fim && (
        <Nota tom="alerta">
          Não há etapa seguinte no fluxo {g.fluxo}, e a CCAR ainda vê estas folhas no status da última etapa. Encerrar a folha (marcar como concluída quando a última etapa do fluxo termina) ainda está para decidir; até lá, abra outra etapa pela gaveta se for o caso.
        </Nota>
      )}

      <div className="flex flex-wrap gap-2">
        {visiveis.map((f) =>
          fim ? (
            <a key={f.id_lote} href={href(`supervisao/folhas/${f.id_lote}`, { grupo: 'todas' })} className="tab rounded-md bg-preenchimento-2 px-2.5 py-1 hover:bg-preenchimento" title={`terminou ${diaMes(f.desde)}`}>
              {f.folha_revisao}
            </a>
          ) : (
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
          ),
        )}
        {g.folhas.length > VISIVEIS && (
          <button className="px-2 font-medium text-primary hover:underline" onClick={() => setTodas(!todas)}>
            <RotuloEstavel ocupado={todas} rotulo={`mais ${num(g.folhas.length - VISIVEIS)}`} rotuloOcupado="ver menos" />
          </button>
        )}
      </div>

      {!fim && (
        <div className="flex flex-wrap items-end gap-2.5 border-t border-linha pt-4">
          <Campo rotulo="Observação (opcional, vai para o histórico de cada folha)" className="min-w-[280px] flex-1">
            <Input value={obs} onChange={(e) => setObs(e.target.value)} placeholder="Ex.: aquisição conferida, CQ por amostragem" className="text-corpo font-normal text-foreground" />
          </Campo>
          <Button disabled={ocupado || !marcadas.size} onClick={abrir}>
            {marcadas.size ? `Abrir ${g.proxima} em ${plural(marcadas.size, 'folha', 'folhas')}` : `Abrir ${g.proxima}`}
          </Button>
          <Button variant="outline" onClick={() => setMarcadas(tudo ? new Set() : new Set(g.folhas.map((f) => f.id_lote)))}>
            <RotuloEstavel ocupado={tudo} rotulo={`Marcar as ${num(g.folhas.length)}`} rotuloOcupado="Desmarcar" />
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
  const n = grupos.reduce((s, g) => s + g.folhas.length, 0)
  return (
    <Conteudo largura={1240}>
      {n === 0 ? (
        <Bloco>
          <Vazio>Nenhuma folha esperando você: todas as folhas da unidade estão com uma etapa aberta ou encerradas.</Vazio>
        </Bloco>
      ) : (
        <p className="max-w-[820px] text-titulo-3">
          <b>{plural(n, 'folha', 'folhas')}</b> {n === 1 ? 'terminou' : 'terminaram'} a etapa atual (as cargas estão concluídas) e só {n === 1 ? 'anda' : 'andam'} quando você abrir a próxima. Elas estão agrupadas pela decisão; marque as que vão juntas e decida de uma vez, com uma observação só. Abrir a próxima conclui a etapa, gera as cargas da seguinte e abre a distribuição. No CQ, a decisão é sobre o resultado: aprovar ou nova revisão.
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
