import { Bloco, COR, Conteudo, Ponto, TituloBloco } from '@/components/ds'
import { useSessao } from '@/lib/sessao'

// Situação da conexão, do usuário e das versões. Abre pelas iniciais no topo.
export default function Sobre() {
  const { status, eu } = useSessao()
  return (
    <Conteudo largura={1120}>
      <h1 className="text-titulo-grande font-bold">Conta e sobre</h1>
      <section className="grid gap-4 md:grid-cols-3">
        <Bloco className="gap-1">
          <TituloBloco titulo="Banco" className="mb-2" />
          <Ponto cor={status?.online ? COR.sucesso : COR.vazio}>{status?.online ? 'online' : 'offline'}</Ponto>
          <div className="text-muted-foreground">{status?.rotulo_ambiente} · {status?.banco}</div>
          {status && !status.credencial && <div className="text-perigo">usuário e senha não configurados (botão de conectar na barra do Feixe no QGIS)</div>}
          <div className="text-muted-foreground">{status?.detalhe}</div>
        </Bloco>
        <Bloco className="gap-1">
          <TituloBloco titulo="Usuário" className="mb-2" />
          <div>{eu?.nome ?? status?.usuario ?? 'desconhecido (conecte pelo botão da barra do Feixe no QGIS)'}</div>
          {eu && (
            <div className="text-muted-foreground">
              {eu.conta} · {eu.uf ?? 'sem lotação'} · {eu.papeis.length ? eu.papeis.join(', ') : 'sem papel'}
            </div>
          )}
          {eu && !eu.elegivel && <div className="text-perigo">conta inativa, de sistema ou super no SGBC: sem papel no Feixe</div>}
        </Bloco>
        <Bloco className="gap-1">
          <TituloBloco titulo="Versões" className="mb-2" />
          <div>plugin {status?.versao_plugin}</div>
          <div className="text-muted-foreground">QGIS {status?.qgis}</div>
        </Bloco>
      </section>
    </Conteudo>
  )
}
