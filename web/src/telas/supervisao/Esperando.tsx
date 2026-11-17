import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Bloco, COR, Carregando, Conteudo } from '@/components/painel'
import type { GrupoEsperando } from '@/lib/api'
import { useAvisar } from '@/lib/avisos'
import { diaMes, num, plural } from '@/lib/formato'
import { href } from '@/lib/rotas'
import { enviar } from '@/lib/useApi'
import { cn } from '@/lib/utils'

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

function Grupo({ g, recarregar }: { g: GrupoEsperando; recarregar: () => void }) {
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
      const r = await enviar<{ abertas: { id_lote: number }[]; erros: { id_lote: number; erro: string }[] }>('/api/lotes/proxima_etapa', {
        lotes: [...marcadas],
        observacao: obs,
      })
      const nome = (id: number) => g.folhas.find((f) => f.id_lote === id)?.folha_revisao ?? `#${id}`
      if (r.abertas.length) avisar(`${g.proxima} aberta em ${plural(r.abertas.length, 'folha', 'folhas')}.`)
      if (r.erros.length) avisar(resumirRecusas(r.erros, nome), 'erro')
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
    <Bloco className={cn('gap-4', fim && 'border-[#E8C9A0]')}>
      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
        <h2 className="text-base font-semibold">
          {g.tema} · {fim ? 'fim do fluxo' : `${g.etapa} concluída`}
        </h2>
        <span className="text-[13px] text-muted-foreground">
          {plural(g.folhas.length, 'folha', 'folhas')} · {fim ? `última etapa (${g.etapa}) concluída` : 'paradas'} {periodo(g)}
        </span>
        <span className="ml-auto text-[13px] font-semibold" style={{ color: fim ? COR.alerta : 'var(--ibge)' }}>
          {fim ? 'precisa de decisão' : `próxima: ${g.proxima}`}
        </span>
      </div>

      {fim && (
        <p className="text-[13px] text-[#3D4B5C]">
          Não há etapa seguinte no fluxo {g.fluxo}, e a CCAR ainda vê estas folhas no status da última etapa. Encerrar a folha (marcar como concluída quando a última etapa do fluxo termina) ainda está para decidir; até lá, abra outra etapa pela gaveta se for o caso.
        </p>
      )}

      <div className="flex flex-wrap gap-2">
        {visiveis.map((f) =>
          fim ? (
            <a key={f.id_lote} href={href(`supervisao/folhas/${f.id_lote}`, { grupo: 'todas' })} className="tab rounded-lg border px-2.5 py-1 text-sm hover:bg-accent" title={`terminou ${diaMes(f.desde)}`}>
              {f.folha_revisao}
            </a>
          ) : (
            <label
              key={f.id_lote}
              title={`${f.situacao === 'pulada' ? 'pulada' : 'concluída'} em ${diaMes(f.desde)}`}
              className={cn('tab inline-flex cursor-pointer items-center gap-1.5 rounded-lg border px-2.5 py-1 text-sm', marcadas.has(f.id_lote) ? 'border-ibge bg-[#EEF3FA]' : 'hover:bg-accent')}
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
          <button className="px-2 text-sm text-ibge hover:underline" onClick={() => setTodas(!todas)}>
            {todas ? 'ver menos' : `mais ${num(g.folhas.length - VISIVEIS)}`}
          </button>
        )}
      </div>

      {!fim && (
        <div className="flex flex-wrap items-end gap-2.5 border-t pt-4">
          <label className="flex min-w-[280px] flex-1 flex-col gap-1.5 text-[13px] text-[#3D4B5C]">
            Observação (obrigatória, vai para o histórico de cada folha)
            <Input value={obs} onChange={(e) => setObs(e.target.value)} placeholder="Ex.: aquisição conferida, CQ por amostragem" className="text-sm text-foreground" />
          </label>
          <Button className="font-semibold" disabled={ocupado || !marcadas.size || !obs.trim()} onClick={abrir}>
            {marcadas.size ? `Abrir ${g.proxima} em ${plural(marcadas.size, 'folha', 'folhas')}` : `Abrir ${g.proxima}`}
          </Button>
          <Button variant="outline" onClick={() => setMarcadas(tudo ? new Set() : new Set(g.folhas.map((f) => f.id_lote)))}>
            {tudo ? 'Desmarcar' : `Marcar as ${num(g.folhas.length)}`}
          </Button>
        </div>
      )}
    </Bloco>
  )
}

// Supervisão › Esperando você: folhas que terminaram a etapa atual e só andam quando o supervisor abrir a próxima.
// Agrupadas pela decisão; marque as que vão juntas e decida de uma vez, com uma observação só.
export default function Esperando({ grupos, recarregar }: { grupos: GrupoEsperando[] | null; recarregar: () => void }) {
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
        <Bloco className="text-muted-foreground">Nenhuma folha esperando você: todas as folhas da unidade estão com uma etapa aberta ou encerradas.</Bloco>
      ) : (
        <p className="max-w-[820px] text-base">
          <b>{plural(n, 'folha', 'folhas')}</b> {n === 1 ? 'terminou' : 'terminaram'} a etapa atual e só {n === 1 ? 'anda' : 'andam'} quando você abrir a próxima. Elas estão agrupadas pela decisão; marque as que vão juntas e decida de uma vez, com uma observação só.
        </p>
      )}
      {grupos.map((g) => (
        <Grupo key={`${g.tema}-${g.etapa}-${g.id_proxima}`} g={g} recarregar={recarregar} />
      ))}
    </Conteudo>
  )
}
