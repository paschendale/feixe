import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { useSessao } from '@/lib/sessao'

// Situação da conexão, do usuário e das versões (era a tela inicial antes da fase B).
export default function Sobre() {
  const { status, eu } = useSessao()
  return (
    <section className="grid gap-4 md:grid-cols-3">
      <Card>
        <CardHeader><CardTitle className="text-sm">Banco</CardTitle></CardHeader>
        <CardContent className="space-y-1 text-sm">
          <div>{status?.online ? '● online' : '○ offline'}</div>
          <div className="text-muted-foreground">{status?.banco}</div>
          {status && !status.credencial && <div className="text-destructive">usuário e senha não configurados (botão de conectar na barra do Feixe no QGIS)</div>}
          <div className="text-muted-foreground">{status?.detalhe}</div>
        </CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle className="text-sm">Usuário</CardTitle></CardHeader>
        <CardContent className="space-y-1 text-sm">
          <div>{eu?.nome ?? status?.usuario ?? 'desconhecido (conecte pelo botão da barra do Feixe no QGIS)'}</div>
          {eu && (
            <div className="text-muted-foreground">
              {eu.conta} · {eu.uf ?? 'sem lotação'} · {eu.papeis.length ? eu.papeis.join(', ') : 'sem papel'}
            </div>
          )}
          {eu && !eu.elegivel && <div className="text-destructive">conta inativa, de sistema ou super no SGBC: sem papel no Feixe</div>}
        </CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle className="text-sm">Versões</CardTitle></CardHeader>
        <CardContent className="space-y-1 text-sm">
          <div>plugin {status?.versao_plugin}</div>
          <div className="text-muted-foreground">QGIS {status?.qgis}</div>
        </CardContent>
      </Card>
    </section>
  )
}
