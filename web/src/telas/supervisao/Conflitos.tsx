import { useEffect, useState } from 'react'
import { MapPin } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { Bloco, Campo, Carregando, Conteudo, Nota, Selo, Tabela, type Tom } from '@/components/ds'
import type { ContagemSyncLog, ItemSyncLog, ListaSyncLog, Pessoa } from '@/lib/api'
import { useAvisar } from '@/lib/avisos'
import { dataHora, FUSO, num, plural } from '@/lib/formato'
import { href, navegar, useRota } from '@/lib/rotas'
import { useSessao } from '@/lib/sessao'
import { enviar, useApi } from '@/lib/useApi'
import { cn } from '@/lib/utils'


// Contador da aba e do Início: conflitos e recusas dos últimos 7 dias.
export function useContagemConflitos(ativo: boolean) {
  return useApi<ContagemSyncLog>(ativo ? '/api/sync_log/contagem?dias=7' : null, ['sincronizacao'])
}

const TIPOS: { id: string; rotulo: string; resultado: string }[] = [
  { id: 'todos', rotulo: 'Conflitos e recusas', resultado: '' },
  { id: 'conflitos', rotulo: 'Só conflitos', resultado: 'conflito_*' },
  { id: 'recusas', rotulo: 'Só recusas', resultado: 'recusado' },
]
const PERIODOS = [
  { id: '7', rotulo: 'Últimos 7 dias' },
  { id: '30', rotulo: 'Últimos 30 dias' },
  { id: '90', rotulo: 'Últimos 90 dias' },
]

const diaIso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`

function rotuloResultado(i: ItemSyncLog): { texto: string; tom: Tom } {
  if (i.resultado === 'recusado') return { texto: 'Recusada pela CCAR', tom: 'perigo' }
  if (i.resultado === 'conflito_perdido') return { texto: 'Conflito · ficou o que estava na CCAR', tom: 'alerta' }
  return { texto: 'Conflito · ficou o que foi enviado', tom: 'alerta' }
}

function Lado({ titulo, quem, em, ficou }: { titulo: string; quem: string | null; em: string | null; ficou: boolean }) {
  return (
    <th className={cn('w-[39%] px-3 py-2 text-foreground', ficou ? 'bg-sucesso-suave' : 'bg-preenchimento-2')}>
      <span className="block text-nota">{titulo}</span>
      <span className="block font-normal text-muted-foreground">
        {quem ?? '—'}
        {em ? ` · ${dataHora(em)}` : ''}
      </span>
      <Selo tom={ficou ? 'sucesso' : 'neutro'} className="mt-1">
        {ficou ? 'ficou' : 'descartado'}
      </Selo>
    </th>
  )
}

function Item({ i }: { i: ItemSyncLog }) {
  const avisar = useAvisar()
  const { conectado } = useSessao()
  const r = rotuloResultado(i)
  const a = i.alvo
  const ficouLocal = i.vencedor === 'local'
  const zoom = () =>
    a.id_lote &&
    enviar(`/api/lotes/${a.id_lote}/zoom`)
      .then(() => avisar(`${a.folha ?? 'Lote'} no mapa do QGIS.`))
      .catch((e) => avisar((e as Error).message, 'erro'))
  return (
    <Bloco className="gap-3">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
        <Selo tom={r.tom}>{r.texto}</Selo>
        <span className="text-nota text-muted-foreground">{dataHora(i.em)}</span>
        <span className="flex flex-wrap items-baseline gap-x-2">
          {a.id_lote && a.existe !== false ? (
            <a href={href(`supervisao/folhas/${a.id_lote}`, { grupo: 'todas' })} className="tab font-semibold text-primary hover:underline">
              {a.folha ?? `Lote #${a.id_lote}`}
            </a>
          ) : (
            <b className="tab">{a.folha ?? 'Lote não identificado'}</b>
          )}
          <span className="text-nota text-muted-foreground">
            {[i.tipo === 'carga' ? (a.geocodigo ? `carga ${a.geocodigo}` : a.id_carga ? `carga nº ${a.id_carga}` : 'carga') : i.tipo === 'fila' ? 'fila' : i.tipo, a.etapa, a.atividade]
              .filter(Boolean)
              .join(' · ')}
          </span>
          {!a.existe && <span className="text-nota font-semibold text-alerta">apagada na CCAR depois</span>}
        </span>
        {a.id_lote && (
          <Button variant="outline" size="sm" className="ml-auto" disabled={!conectado} onClick={zoom} title={conectado ? 'Aproximar o mapa do QGIS no lote' : 'Abra o QGIS para ver no mapa'}>
            <MapPin className="size-3.5" /> Ver no mapa
          </Button>
        )}
      </div>
      <p>{i.frase}</p>
      {i.valores.length > 0 && (
        <Tabela solta compacta fixa largura={560}>
            <thead>
              <tr>
                <th className="w-[22%]">Campo</th>
                <Lado titulo="O que foi enviado" quem={i.local.por?.nome ?? null} em={i.local.em} ficou={ficouLocal} />
                <Lado titulo="O que estava na CCAR" quem={i.servidor?.por?.nome ?? null} em={i.servidor?.em ?? null} ficou={!ficouLocal} />
              </tr>
            </thead>
            <tbody>
              {i.valores.map((v) => (
                <tr key={v.campo}>
                  <td className="text-nota text-muted-foreground">{v.rotulo}</td>
                  <td className={cn('tab px-3', !ficouLocal && !v.igual && 'text-muted-foreground line-through')}>{v.local}</td>
                  <td className={cn('tab px-3', ficouLocal && !v.igual && 'text-muted-foreground line-through')}>{v.servidor}</td>
                </tr>
              ))}
            </tbody>
        </Tabela>
      )}
      {i.juntados > 1 && <span className="text-rodape text-muted-foreground">{num(i.juntados)} ações seguidas na mesma carga foram enviadas juntas.</span>}
    </Bloco>
  )
}

// Supervisão › Conflitos (C5): o que duas pessoas mudaram ao mesmo tempo sem se ver (uma delas sem conexão) e o que a
// CCAR recusou ao receber. O Feixe já decidiu (ficou a ação mais recente, D-120); aqui o supervisor vê os dois lados e,
// se o que ficou não é o certo, age pelas telas de sempre. Nada é desfeito sozinho.
export default function Conflitos() {
  const rota = useRota()
  const q = rota.query
  const tipo = TIPOS.find((t) => t.id === q.get('tipo')) ?? TIPOS[0]
  const periodo = q.get('periodo') ?? (q.get('desde') ? 'datas' : '7')
  const pessoa = q.get('pessoa') ?? ''
  const folha = q.get('folha') ?? ''
  const pagina = Math.max(1, Number(q.get('pagina') ?? 1) || 1)
  const [texto, setTexto] = useState(folha)
  useEffect(() => setTexto(folha), [folha])

  const desde = periodo === 'datas' ? q.get('desde') ?? '' : diaIso(new Date(Date.now() - (Number(periodo) - 1) * 864e5))
  const ate = periodo === 'datas' ? q.get('ate') ?? '' : ''
  const params = new URLSearchParams({ fuso: FUSO, pagina: String(pagina), por_pagina: '30' })
  if (tipo.resultado) params.set('resultado', tipo.resultado)
  if (desde) params.set('desde', desde)
  if (ate) params.set('ate', ate)
  if (pessoa) params.set('pessoa', pessoa)
  if (folha) params.set('folha', folha)
  const { dados, erro, carregando } = useApi<ListaSyncLog>(`/api/sync_log?${params}`, ['sincronizacao'], { manterAnterior: true })
  const { dados: equipe } = useApi<{ itens: Pessoa[] }>('/api/equipe', ['carga'])

  const mudar = (novo: Record<string, string | number | null>) => {
    const atual: Record<string, string> = {}
    q.forEach((v, k) => (atual[k] = v))
    navegar(href('supervisao/conflitos', { ...atual, pagina: null, ...novo }))
  }
  const paginas = dados ? Math.max(1, Math.ceil(dados.total / dados.por_pagina)) : 1

  return (
    <Conteudo>
      <p className="max-w-[900px] text-lede text-texto-2">
        Quando duas pessoas mudam a mesma carga sem uma ver a outra (alguém estava sem conexão com a CCAR), o Feixe fica com a ação mais recente e guarda a outra aqui. As recusas são mudanças que a CCAR não aceitou ao receber, como concluir numa etapa já encerrada. Nada é desfeito sozinho: se o que ficou não é o certo, corrija pelo lote.
      </p>

      <div className="flex flex-wrap items-end gap-3">
        <Campo rotulo="O quê">
          <Select className="w-[200px] text-foreground" value={tipo.id} onChange={(e) => mudar({ tipo: e.target.value === 'todos' ? null : e.target.value })}>
            {TIPOS.map((t) => (
              <option key={t.id} value={t.id}>
                {t.rotulo}
              </option>
            ))}
          </Select>
        </Campo>
        <Campo rotulo="Quando">
          <Select
            className="w-[180px] text-foreground"
            value={periodo}
            onChange={(e) => mudar(e.target.value === 'datas' ? { periodo: 'datas', desde: desde || diaIso(new Date()), ate: null } : { periodo: e.target.value === '7' ? null : e.target.value, desde: null, ate: null })}
          >
            {PERIODOS.map((p) => (
              <option key={p.id} value={p.id}>
                {p.rotulo}
              </option>
            ))}
            <option value="datas">Entre datas…</option>
          </Select>
        </Campo>
        {periodo === 'datas' && (
          <>
            <Campo rotulo="De">
              <Input type="date" className="w-[160px] text-foreground" value={desde} onChange={(e) => mudar({ periodo: 'datas', desde: e.target.value || null })} />
            </Campo>
            <Campo rotulo="Até">
              <Input type="date" className="w-[160px] text-foreground" value={ate} onChange={(e) => mudar({ periodo: 'datas', ate: e.target.value || null })} />
            </Campo>
          </>
        )}
        <Campo rotulo="Pessoa">
          <Select className="w-[220px] text-foreground" value={pessoa} onChange={(e) => mudar({ pessoa: e.target.value || null })}>
            <option value="">Todas</option>
            {(equipe?.itens ?? [])
              .slice()
              .sort((a, b) => a.nome.localeCompare(b.nome))
              .map((p) => (
                <option key={p.conta} value={p.conta}>
                  {p.nome}
                </option>
              ))}
            {pessoa && !(equipe?.itens ?? []).some((p) => p.conta === pessoa) && <option value={pessoa}>{pessoa}</option>}
          </Select>
        </Campo>
        <form
          onSubmit={(e) => {
            e.preventDefault()
            mudar({ folha: texto.trim() || null })
          }}
        >
          <Campo rotulo="Lote ou geocódigo">
            <Input className="w-[180px] text-foreground" placeholder="ex.: 2534" value={texto} onChange={(e) => setTexto(e.target.value)} onBlur={() => texto.trim() !== folha && mudar({ folha: texto.trim() || null })} />
          </Campo>
        </form>
        {(tipo.id !== 'todos' || periodo !== '7' || pessoa || folha) && (
          <Button variant="ghost" onClick={() => navegar(href('supervisao/conflitos'))}>
            Limpar filtros
          </Button>
        )}
      </div>

      {!dados ? (
        <Carregando erro={erro} />
      ) : (
        <>
          {erro && <Nota tom="perigo">{erro}</Nota>}
          <p className={cn('text-muted-foreground', carregando && 'opacity-60')}>
            {dados.total ? plural(dados.total, 'registro', 'registros') : 'Nenhum conflito nem recusa com estes filtros.'}
            {dados.total > dados.por_pagina ? ` · página ${num(dados.pagina)} de ${num(paginas)}` : ''}
          </p>
          <div className={cn('flex flex-col gap-3 transition-opacity', carregando && 'opacity-60')}>
            {dados.itens.map((i) => (
              <Item key={i.id} i={i} />
            ))}
          </div>
          {paginas > 1 && (
            <div className="flex items-center gap-2">
              <Button variant="outline" disabled={pagina <= 1} onClick={() => mudar({ pagina: pagina - 1 })}>
                Anterior
              </Button>
              <Button variant="outline" disabled={pagina >= paginas} onClick={() => mudar({ pagina: pagina + 1 })}>
                Próxima
              </Button>
            </div>
          )}
        </>
      )}
      <p className="text-nota text-muted-foreground">
        Conflito: a carga mudou na CCAR depois da última sincronização de quem enviou; ficou a ação mais recente pela hora em que foi feita (o relógio de cada computador é acertado pelo da CCAR). Recusa: a CCAR conferiu de novo as regras ao receber (carga que passou para outra pessoa, etapa encerrada, desfazer depois de 24 horas, lote da fila que outra pessoa pegou) e não aplicou; quem enviou recebeu o aviso e o computador dele voltou ao que está na CCAR.
      </p>
    </Conteudo>
  )
}
