// Marca do Feixe: grade 2 por 2 com uma célula em destaque (a carga de trabalho na grade). Mesma do deck e do protótipo.
export function Logo({ tamanho = 24, escuro = false }: { tamanho?: number; escuro?: boolean }) {
  const aco = '#7492C1'
  const destaque = escuro ? '#E6EDF7' : '#004182'
  return (
    <svg width={tamanho} height={tamanho} viewBox="0 0 64 64" aria-hidden="true">
      <rect x="5" y="5" width="25" height="25" rx="5" fill={aco} />
      <rect x="34" y="5" width="25" height="25" rx="5" fill={aco} />
      <rect x="5" y="34" width="25" height="25" rx="5" fill={aco} />
      <rect x="34" y="34" width="25" height="25" rx="5" fill={destaque} />
    </svg>
  )
}
