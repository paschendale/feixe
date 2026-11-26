// Design system do Feixe. Tokens em src/index.css; vitrine viva em #/design (telas/Design.tsx).
//
// Regras:
// - Telas montam com estas peças e com components/ui (Button, Input, Select, Dialog...). Nada de hex, text-[Npx] ou
//   rounded-[Npx] nas telas: se faltar algo, a peça ou o token nasce aqui.
// - Uma ação primária (Button default) por área; as outras são tinted, outline (bordered) ou ghost.
// - Números em `tab` (tabular); estados com Selo/Nota no tom certo, nunca cor solta.
export * from './cores'
export * from './controles'
export * from './dados'
export * from './estrutura'
export * from './feedback'
export * from './tabela'
