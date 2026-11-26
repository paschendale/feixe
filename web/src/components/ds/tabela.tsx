import { cn } from '@/lib/utils'

// Tabela do design system: a superfície (com rolagem horizontal) e a <table> com o estilo de .ds-tabela (index.css).
// `solta` = sem superfície própria, dentro de um Bloco. `compacta` = linhas mais baixas. `densa` = compacta e em
// text-nota (listas longas de ocorrências). `largura` = largura mínima antes de rolar.
export function Tabela({ className, classeTabela, solta, compacta, densa, fixa, largura, children, ...props }: React.ComponentProps<'table'> & { classeTabela?: string; solta?: boolean; compacta?: boolean; densa?: boolean; fixa?: boolean; largura?: number }) {
  return (
    <div className={cn('overflow-x-auto', !solta && 'rounded-xl bg-card shadow-cartao', className)}>
      <table className={cn('ds-tabela', solta && 'solta', (compacta || densa) && 'compacta', densa && 'text-nota', fixa && 'table-fixed', classeTabela)} style={largura ? { minWidth: largura } : undefined} {...props}>
        {children}
      </table>
    </div>
  )
}

// Larguras fixas das colunas de uma tabela `fixa`: o conteúdo (um filtro, um rótulo novo, uma ação) nunca recalcula
// as colunas. Número = px; texto = qualquer largura CSS ('24%'); undefined = divide o que sobra.
export function Colunas({ larguras }: { larguras: (number | string | undefined)[] }) {
  return (
    <colgroup>
      {larguras.map((l, i) => (
        <col key={i} style={l === undefined ? undefined : { width: l }} />
      ))}
    </colgroup>
  )
}
