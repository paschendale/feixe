import { Bloco, Conteudo } from '@/components/painel'
import { hojePorExtenso, primeiroNome, saudacao } from '@/lib/formato'
import { useSessao } from '@/lib/sessao'
import { ResumoExecucao } from './ResumoExecucao'
import { ResumoSupervisao, fraseSupervisao, usePainel } from './ResumoSupervisao'

export const unidadeDe = (uf: string | null | undefined) => (!uf ? 'Na unidade' : uf === 'RJ' ? 'Na CCAR' : `Na GGC-${uf}`)

function SupervisorInicio() {
  const dados = usePainel()
  const { eu } = useSessao()
  const p = dados.painel.dados
  return (
    <>
      <p className="mt-1 max-w-[880px] text-[19px] leading-normal">{p ? fraseSupervisao(p, dados.esperando.dados?.grupos ?? null, unidadeDe(eu?.uf)) : 'Carregando…'}</p>
      {dados.painel.erro && <p className="text-sm text-destructive">{dados.painel.erro}</p>}
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
