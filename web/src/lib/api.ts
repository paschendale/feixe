// Cliente da API local do plugin. O token chega na URL de abertura (?token=...) e fica na sessionStorage.
const CHAVE = 'feixe.token'

export function token(): string {
  const url = new URL(window.location.href)
  const daUrl = url.searchParams.get('token')
  if (daUrl) {
    sessionStorage.setItem(CHAVE, daUrl)
    url.searchParams.delete('token')
    window.history.replaceState({}, '', url.pathname + url.search + url.hash)
  }
  return sessionStorage.getItem(CHAVE) ?? ''
}

export class ErroApi extends Error {
  status: number
  constructor(status: number, mensagem: string) {
    super(mensagem)
    this.status = status
  }
}

export async function api<T = unknown>(caminho: string, init: RequestInit = {}): Promise<T> {
  const r = await fetch(caminho, {
    ...init,
    headers: { 'Content-Type': 'application/json', 'X-Feixe-Token': token(), ...(init.headers ?? {}) },
  })
  const corpo = await r.json().catch(() => ({}))
  if (!r.ok) throw new ErroApi(r.status, (corpo as { erro?: string }).erro ?? r.statusText)
  return corpo as T
}

export type Status = {
  ambiente: string
  rotulo_ambiente: string
  cor_ambiente: string
  banco: string
  credencial: boolean
  versao_plugin: string
  qgis: string
  clientes_sse: number
  online: boolean
  usuario: string | null
  detalhe: string
}

export type Folha = {
  id: number
  cd_mi: string
  nm_carta: string | null
  nomenclatura: string
  xmin: number
  ymin: number
  xmax: number
  ymax: number
}

export type Papel = 'gerente' | 'supervisor' | 'avaliador' | 'apm' | 'consulta'

export type Eu = {
  conta: string
  cadastrada: boolean
  nome: string
  siape: number | null
  lotacao: string | null
  uf: string | null
  elegivel: boolean
  perfis: { cod_projeto: number; projeto: string; perfil: string | null; papel: Papel | null }[]
  papeis: Papel[]
  papel: Papel | null
  papel_rotulo: string
  gerente: boolean
  equipe: string | null
}

export type Carga = {
  id: number
  uuid: string
  id_lote_etapa: number
  id_lote: number
  folha_revisao: string
  tema: string
  etapa: string
  atividade: string
  geocodigo: string | null
  concluido: boolean
  concluido_em: string | null
  situacao_etapa: string
}

export type Progresso = { id_lote_etapa: number; folha_revisao: string; concluidas: number; total: number }

export type Passagem = {
  id_lote_etapa: number
  id_lote: number
  folha_revisao: string
  tema: string
  etapa: string
  situacao: 'pendente' | 'em_andamento' | 'concluida' | 'pulada'
  total: number
  concluidas: number
  ultima_conclusao: string | null
}

export type ResumoCargas = {
  concluidas: number
  desde: string | null
  pendentes: number
  folhas_pendentes: number
  passagens: Passagem[]
}

export type StatusNacional = 'PLANEJADA' | 'EM_PRODUCAO' | 'EM_CQ' | 'ENTREGUE_GCQ' | 'CONCLUIDA' | 'DEVOLVIDA'

export type Lote = {
  id: number
  tipo: 'folha' | 'livre'
  nome: string
  folha_revisao: string
  cod_projeto: number
  projeto: string
  id_tema: number
  tema: string
  uf: string
  status_nacional: StatusNacional
  etapa: string | null
  fase: string | null
  situacao: string | null
  revisao_atual: number
  cargas_total: number | null
  cargas_concluidas: number | null
  perc_concluidas: number | null
  responsavel_principal: string | null
  responsavel_nome: string | null
  ultimo_cq_resultado: string | null
  id_lote_etapa_atual: number | null
  id_fluxo: number
}

export type PassagemLote = {
  id: number
  id_fluxo_etapa: number
  expor_ocorrencias: boolean
  etapa: string
  fase: string
  ordem: number
  instancia: number
  revisao: number | null
  situacao: string
  resultado: string | null
  iniciada_em: string | null
  concluida_em: string | null
  cargas_total: number
  cargas_concluidas: number
}

export type Fluxo = {
  id: number
  nome: string
  cod_projeto: number
  projeto: string
  id_tema: number
  tema: string
  primeira_etapa: string | null
}

export type ResultadoCriacao = {
  tema: string
  criados: { cd_mi?: string; nome?: string; id_lote: number; id_lote_etapa?: number }[]
  existentes: { cd_mi: string; id_lote: number; uf: string }[]
  preparo?: Preparo
}

// O que o Feixe fez sozinho depois de abrir passagens (D-109): cargas geradas, etapas sem atividade iniciadas e avisos.
type PassagemPreparada = { id_lote_etapa: number; folha_revisao: string; etapa: string }
export type Preparo = {
  geradas: (PassagemPreparada & { gravadas: number })[]
  iniciadas: PassagemPreparada[]
  avisos: (PassagemPreparada & { aviso: string })[]
  erro?: string
}

export type FolhaDistribuir = {
  id_lote: number
  id_lote_etapa: number
  folha_revisao: string
  tema: string
  etapa: string
  fase: string
  a_atribuir: number
  cargas: number
  na_fila_de: string | null
  anteriores: string[]
  com_cargas: string[]
  sugerida: string | null
}
export type PessoaDistribuir = { conta: string; nome: string; perfis: string | null; pendentes: number; na_fila: number }
export type SugestaoDistribuicao = { folhas: FolhaDistribuir[]; pessoas: PessoaDistribuir[] }

export type ItemAvanco = {
  id_lote: number
  folha_revisao: string
  tema: string
  etapa: string | null
  concluir: boolean
  cargas: number
  pendentes: number
  proxima: string | null
  erro: string | null
}
export type ResultadoAvanco = {
  abertas: { id_lote: number; id_lote_etapa: number; etapa: string }[]
  erros: { id_lote: number; erro: string }[]
  preparo?: Preparo
}

export type Atividade = {
  id: number
  nome: string
  cod_projeto: number
  projeto: string
  id_tema: number
  tema: string
  fase: string
  fase_nome: string
  geracao: string | null
  grade_nivel: number | null
  id_medidadequalidade: number | null
  medida: string | null
  ativo: boolean
  em_uso: boolean
  tem_cargas: boolean
}

export type Tema = { id: number; nome: string; ativo: boolean; atividades: number }

export type Catalogo = {
  temas: Tema[]
  atividades: Atividade[]
  elementos_cq: { id: number; nome: string; nucleo: boolean; fracao_critica: number; ativo: boolean }[]
  fases: { codigo: string; nome: string; ordem: number; status_nacional: string }[]
  projetos: { cod_projeto: number; nome: string }[]
  geracoes: string[]
  niveis_grade: number[]
}

export type ResultadoGeracao = {
  resultados: { id_lote_etapa: number; folha_revisao: string; etapa: string; atividade: string; grade_nivel: number; celulas: number; gravadas: number }[]
  erros: { id_lote_etapa: number; erro: string }[]
}

export type EtapaFluxo = {
  id?: number
  ordem?: number
  fase: string
  fase_nome?: string
  nome: string
  obrigatoria: boolean
  repetivel: boolean
  conta_revisao: boolean
  fracao_critica: number | null
  passagens?: number
  atividades: { id: number; nome: string; geracao?: string }[]
}

export type FluxoCompleto = {
  id: number
  nome: string
  uf: string
  ativo: boolean
  cod_projeto: number
  projeto: string
  id_tema: number
  tema: string
  lotes: number
  etapas: EtapaFluxo[]
}

export type EstadoLote = {
  id: number
  status_nacional: StatusNacional
  situacao: string | null
  etapa: string | null
  sugestao: { id: number; nome: string; ordem: number } | null
  preparo?: Preparo
}

export type Historico = { em: string; acao: string; observacao: string | null; por: string; por_nome: string; etapa: string; instancia: number }

export type Pessoa = { conta: string; nome: string; perfis: string; pendentes: number; folhas: number; ultima: string | null }
export type ResultadoAtribuicao = { atribuidas: number; ja_estavam: number; fora: number }

// --- Painel (D-103): Início por papel e abas da Supervisão ---

// Atividade em produção: o mesmo corte dos subgrupos do QGIS (as de CQ de um tema num grupo só).
export type GrupoAtividade = {
  chave: string
  rotulo: string
  id_tema: number
  tema: string
  fase: string
  atividades: number[]
  lotes: number[]
  pessoas: number
  total: number
  concluidas: number
  com_alguem: number
  a_atribuir: number
  na_fila: number
  concluidas_7d: number
}

export type LotePainel = { id_lote: number; responsaveis: string[]; a_atribuir: number; na_fila: number; fila_de: string | null; ultima: string | null; iniciada_em: string | null }

export type PessoaPainel = {
  conta: string
  nome: string
  pendentes: number
  concluidas_7d: number
  ultima: string | null
  grupos: string[]
  lotes: number[]
}

export type PainelSupervisao = {
  grupos: GrupoAtividade[]
  lotes: LotePainel[]
  pessoas: PessoaPainel[]
  status: Partial<Record<StatusNacional, number>>
}

export type GrupoEsperando = {
  tema: string
  etapa: string
  fluxo: string
  id_proxima: number | null
  proxima: string | null
  desde: string | null
  ate: string | null
  folhas: { id_lote: number; folha_revisao: string; situacao: string; desde: string | null }[]
}

export type PessoaLote = { conta: string | null; nome: string | null; total: number; concluidas: number; ultima: string | null }

export type LoteCompleto = Lote & { passagens: PassagemLote[]; pessoas: PessoaLote[] }

// --- Fila de folhas por pessoa (B8, D-106) ---

export type ItemFila = {
  id: number
  responsavel: string
  nome: string
  ordem: number
  id_lote_etapa: number
  id_lote: number
  folha_revisao: string
  tema: string
  etapa: string
  situacao: string
  cargas: number
  a_atribuir: number
}

export type AtribuidaFila = { id: number; responsavel: string; nome: string; atribuida_em: string; atribuidas: number; folha_revisao: string; id_lote: number }

export type Filas = { itens: ItemFila[]; recentes: AtribuidaFila[] }
