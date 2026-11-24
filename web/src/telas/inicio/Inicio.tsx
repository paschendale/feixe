import { Bloco, Conteudo, LinkSeta } from '@/components/painel'
import type { FluxoCompleto } from '@/lib/api'
import { hojePorExtenso, primeiroNome, saudacao } from '@/lib/formato'
import { href } from '@/lib/rotas'
import { useSessao } from '@/lib/sessao'
import { useApi } from '@/lib/useApi'
import { cn } from '@/lib/utils'
import { ResumoExecucao } from './ResumoExecucao'
import { ResumoSupervisao, fraseSupervisao, usePainel } from './ResumoSupervisao'

export const unidadeDe = (uf: string | null | undefined) => (!uf ? 'Na unidade' : uf === 'RJ' ? 'Na CCAR' : `Na GGC-${uf}`)

// Unidade sem folhas no Feixe (dia 0, D-109): os três passos que dependem do supervisor, na ordem, com o estado de cada
// um. O que não depende de ninguém (gerar as cargas, iniciar a etapa) acontece sozinho entre eles.
function ComecePorAqui() {
  const { dados } = useApi<{ itens: FluxoCompleto[] }>('/api/fluxos/completos', ['fluxo'])
  const fluxos = (dados?.itens ?? []).filter((f) => f.ativo)
  const passos = [
    {
      titulo: 'Montar o fluxo',
      texto: fluxos.length
        ? `${fluxos.length === 1 ? `Fluxo ${fluxos[0].nome} pronto` : `${fluxos.length} fluxos prontos`}. Confira se cada etapa tem a atividade certa: é ela que define as cargas.`
        : 'Projeto, tema e a sequência de etapas, a partir do modelo da CCAR ou de uma cópia do fluxo de outra unidade.',
      feito: fluxos.length > 0,
      link: { href: '#/supervisao/fluxos', rotulo: fluxos.length ? 'Ver os fluxos' : 'Criar o fluxo' },
    },
    {
      titulo: 'Pôr as folhas',
      texto: 'Escolha as folhas no mapa do QGIS ou pela busca. Cada folha entra na primeira etapa já com as cargas geradas.',
      feito: false,
      link: fluxos.length ? { href: href('supervisao/folhas', { novas: fluxos.length === 1 ? fluxos[0].id : 1 }), rotulo: 'Escolher as folhas' } : null,
    },
    {
      titulo: 'Distribuir',
      texto: 'Uma folha por pessoa: quem recebe começa na hora (a etapa inicia), e as folhas que sobram vão para a fila de cada um.',
      feito: false,
      link: null,
    },
  ]
  return (
    <Bloco className="mt-6 gap-5">
      <div className="flex flex-col gap-1">
        <h2 className="text-lg font-semibold">Comece por aqui</h2>
        <span className="text-[13px] text-muted-foreground">A sua unidade ainda não tem folhas no Feixe. São três passos; o resto o Feixe faz sozinho.</span>
      </div>
      <ol className="flex flex-col gap-4">
        {passos.map((p, i) => (
          <li key={p.titulo} className="grid grid-cols-[32px_1fr] gap-3">
            <span className={cn('grid size-7 place-items-center rounded-full text-sm font-semibold', p.feito ? 'bg-[#2E7D4F] text-white' : 'bg-aco-claro text-ibge')}>{p.feito ? '✓' : i + 1}</span>
            <div className="flex flex-col gap-1">
              <b>{p.titulo}</b>
              <span className="text-[13px] text-[#3D4B5C]">{p.texto}</span>
              {p.link && (
                <LinkSeta href={p.link.href} className="mt-1 text-[13px]">
                  {p.link.rotulo}
                </LinkSeta>
              )}
            </div>
          </li>
        ))}
      </ol>
      <p className="border-t pt-4 text-[13px] text-[#3D4B5C]">
        <b>Depois, no dia a dia:</b> quando uma folha termina as cargas, ela aparece aqui em "Precisa de você". Você abre a próxima etapa (as cargas saem na hora) e distribui de novo. Com as filas montadas, quem termina já recebe a próxima folha sem esperar você.
      </p>
    </Bloco>
  )
}

function SupervisorInicio() {
  const dados = usePainel()
  const { eu, tem } = useSessao()
  const p = dados.painel.dados
  return (
    <>
      <p className="mt-1 max-w-[880px] text-[19px] leading-normal">{p ? fraseSupervisao(p, dados.esperando.dados?.grupos ?? null, unidadeDe(eu?.uf)) : 'Carregando…'}</p>
      {dados.painel.erro && <p className="text-sm text-destructive">{dados.painel.erro}</p>}
      {tem('supervisor') && dados.lotes.dados && dados.lotes.dados.itens.length === 0 && <ComecePorAqui />}
      <div className="mt-6 flex flex-col gap-11">
        <ResumoSupervisao dados={dados} />
      </div>
    </>
  )
}

// Início (D-103): um painel por papel, na ordem do que a pessoa decide primeiro (supervisão antes de execução). Cada
// painel termina num link para o módulo; as ferramentas ficam nos módulos.
export default function Inicio() {
  const { eu, tem, pronta } = useSessao()
  const supervisiona = tem('supervisor', 'gerente')
  const executa = tem('apm', 'avaliador', 'supervisor')
  const projetos = [...new Set((eu?.perfis ?? []).filter((p) => p.papel && p.papel !== 'consulta').map((p) => p.projeto))].slice(0, 3)
  return (
    <Conteudo largura={1200} className="gap-2 pt-8">
      <p className="text-[13px] text-muted-foreground">{[hojePorExtenso(), eu?.uf, ...projetos].filter(Boolean).join(' · ')}</p>
      <h1 className="text-[28px] font-semibold tracking-[-.01em]">
        {saudacao()}
        {eu ? `, ${primeiroNome(eu.nome)}` : ''}
      </h1>
      {pronta && !eu?.papeis.length && (
        <Bloco className="mt-4">
          Sem papel no Feixe para esta conta. Conecte com o botão da barra do Feixe no QGIS; os perfis vêm do SGBC. Veja a situação em <a href="#/sobre" className="text-ibge underline">Sobre</a>.
        </Bloco>
      )}
      {supervisiona && <SupervisorInicio />}
      {executa && (supervisiona ? <div className="mt-11"><ResumoExecucao comTitulo /></div> : <ResumoExecucao comTitulo={false} />)}
    </Conteudo>
  )
}
