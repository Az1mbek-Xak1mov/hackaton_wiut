// Types mirror docs/plan/09-API.md. The backend formats every figure (`display`); the UI never computes numbers.

export type Unit = 'kUZS' | 'UZS' | 'ratio' | 'pct' | 'days' | 'count'
export type Severity = 'attn' | 'watch' | 'neutral' | 'info'
export type MonStatus = 'stable' | 'watch' | 'attn'

export interface FactDocument {
  uuid: string
  filename: string
  doc_type: string
}

export interface Fact {
  key: string
  uuid: string
  field: string
  label: string
  value: number
  unit: Unit
  display: string
  display_unit: string
  printed: string
  period_label: string
  line_code: string | null
  kind: 'extracted' | 'computed' | 'aggregate'
  page_n: number | null
  bbox: [number, number, number, number] | null
  page_width: number | null
  page_height: number | null
  page_image_url: string | null
  passage: string
  confidence: number
  method: string
  formula: string
  inputs: string[]
  note: string
  status: 'auto' | 'verified' | 'corrected' | 'flagged'
  document: FactDocument | null
}

export interface Finding {
  uuid: string
  rule_id: string
  severity: Severity
  label: string
  title: string
  detail: string
  evidence: string[]
  state: 'open' | 'resolved' | 'dismissed'
  state_note?: string
  date?: string | null
}

export type DocStatus = 'queued' | 'processing' | 'analyzed' | 'clarification' | 'failed'

export interface DocumentOut {
  uuid: string
  filename: string
  mime: string
  size_bytes: number
  doc_type: string
  type_confidence: number
  type_reason: string
  language: string
  status: DocStatus
  failure_cause: string
  period_start: string | null
  period_end: string | null
  page_count: number
  text_layer: boolean
  summary: Record<string, any>
  created_at: string
}

export interface Job {
  uuid: string
  kind?: string
  status: 'queued' | 'running' | 'done' | 'failed'
  stage: string
  progress: number
  error: string
  stage_timings?: Record<string, number>
}

export interface VersionInfo {
  git_sha: string
  built_at: string
  deployed_at: string
  llm_provider: string
  llm_enabled: boolean
}

export interface TokenPair {
  access_token: string
  refresh_token: string
  token_type: string
  expires_in: number
  user: { uuid?: string; email?: string; role?: string; full_name?: string; name?: string } & Record<string, any>
  scopes: string[]
}

export interface UnmappedLine {
  page_n: number
  text: string
  value_printed: string
  bbox: [number, number, number, number] | null
}

export interface CategoryRow {
  category: string
  count: number
  inflow_display: string
  outflow_display: string
}

export interface RecurringRow {
  group: string
  label: string
  count: number
  amount_display: string
  day_of_month: number | null
  evidence: string[]
}

export interface ReadableNumber {
  text: string
  label: string
  page_n: number
  bbox: [number, number, number, number] | null
}

export interface AnalyseResult {
  document: DocumentOut
  job: Job | null
  facts: Fact[]
  unmapped: UnmappedLine[]
  findings: Finding[]
  transactions_preview: {
    count: number
    by_category: CategoryRow[]
    recurring: RecurringRow[]
  } | null
  readable: {
    pages: number
    language: string
    ocr_mean_conf: number | null
    numbers: ReadableNumber[]
    dates: string[]
    stirs: string[]
    text_excerpt: string
  } | null
  description: { text: string; mode: 'llm' | 'none' } | null
  partial?: boolean
}

export interface CreatedWithJob {
  uuid: string
  job: Job
}

// ---------- Officer ----------
export interface StatusDistRow {
  status: MonStatus
  label: string
  means: string
  n: number
  exposure_display: string
  pct: number
}

export interface QueueItem {
  kind: 'application' | 'borrower'
  ref: string
  name: string
  reason: string
  severity: Severity | MonStatus
  action: string
}

export interface StatusChange {
  borrower_uuid: string | null
  name: string
  outstanding_display: string
  from: MonStatus | null
  to: MonStatus
  date: string
  reason: string
  loan_id?: string
}

export interface PortfolioSummary {
  as_of: string | null
  run: { uuid: string; finished_at: string | null } | null
  monitored: number
  exposure_display: string
  applications_awaiting: number
  beyond_target: number
  warning: { n: number; exposure_display: string; pct: number }
  status_distribution: StatusDistRow[]
  thresholds: Record<string, any>
  queue: QueueItem[]
  status_changes: StatusChange[]
  exposure_unit?: string
  requested_display?: string
  calibration_note?: string
  trend?: { as_of: string | null; watch_plus_attn: number }[]
}

export interface ApplicationListItem {
  uuid: string
  number: string
  name: string
  industry: string
  requested_display: string
  term_months: number
  received_on: string
  docs: string
  status: string
  issues_count: number
  issues_label: string
}

export interface FigureRow {
  label: string
  indent: boolean
  cells: Record<string, string | null>
  source: string
  confidence: number | null
  flag: string | null
}

export interface RatioBox {
  label: string
  value_display: string
  note: string
  flag: boolean | string | null
  fact_key: string | null
  fact_keys?: string[]
  period?: string | null
}

export interface RejectedDraft {
  attempt: number
  mode: string
  at: string | null
  unmatched: any[]
  uncited_sentences: any[]
  unknown_ids: any[]
}

export interface Narrative {
  mode: 'llm' | 'template' | null
  markdown: string
  accepted_at: string | null
  attempts: number
  verified?: boolean
  rejected?: RejectedDraft[]
}

export interface ReviewDocument {
  title: string
  filename: string | null
  uuid: string | null
  status: string
  note: string
}

export interface ApplicationReview {
  application: {
    uuid: string
    number: string
    status: string
    sla_day: number | null
    sla_days: number | null
    received_on: string | null
    analysed_at: string | null
  }
  applicant: {
    name: string
    industry: string
    region: string
    stir: string
    since: number | string | null
    employees: number | null
  }
  request: {
    amount_display: string
    amount_unit?: string
    term_months: number | null
    rate_pct?: number | null
    installment_display: string
    installment_key?: string | null
    purpose: string
    collateral: string
  }
  columns?: { key: string; label: string }[]
  issues: Finding[]
  figures: FigureRow[]
  ratios: RatioBox[]
  indicator: {
    label: string
    supports: string[]
    weighs_against: string[]
    disclaimer: string
    rule?: string
  } | null
  narrative: Narrative | null
  documents: ReviewDocument[]
  review_trail: { at: string; text: string }[]
  facts: Record<string, Fact>
}

export interface BorrowerListItem {
  uuid: string
  loan_id: string
  name: string
  industry: string
  region: string
  outstanding_display: string
  trend_pct: number | null
  trend_display?: string
  coverage_display: string
  latest_period: string
  status: MonStatus | 'unknown'
  reason: string
  updated: string | null
}

export interface BorrowerList {
  counts: { all: number; stable: number; watch: number; attn: number }
  items: BorrowerListItem[]
  run?: { uuid: string; finished_at: string | null } | null
  thresholds?: Record<string, any>
  calibration_note?: string
}

export interface BorrowerProfile {
  business: Record<string, any>
  loan: Record<string, any>
  status: {
    current: MonStatus | 'unknown'
    since: string | null
    history: { status: MonStatus; from?: string | null; until?: string | null; date?: string | null }[]
    reason?: string
    indicators?: Record<string, any>
  }
  calibration_note?: string
  alerts: Finding[]
  quarterly: Record<string, any> | null
  narrative: Narrative | null
  timeline: { date: string; title: string; status: string }[]
  documents: Record<string, any>[]
  facts: Record<string, Fact>
}

export interface LlmSettings {
  enabled: boolean
  provider: string
  model: string
  configured?: boolean
}

export interface OwnerBusiness {
  uuid?: string
  name: string
  industry?: string
  region?: string
}

// ---------- Owner ----------
export interface CfoAnswer {
  direct_answer: string
  table: { label: string; fact_key: string | null }[]
  cant_see: string | null
  next_steps: string[]
}

export interface ToolTraceItem {
  tool: string
  args: Record<string, any>
  result_key: string | null
}

export interface CfoResponse {
  answer: CfoAnswer
  citations: string[]
  tool_trace: ToolTraceItem[]
  mode: 'llm' | 'facts_only'
  facts: Record<string, Fact>
}

export interface CfoHistoryItem {
  uuid?: string
  role?: 'user' | 'assistant'
  question?: string
  content?: string
  answer?: CfoAnswer
  citations?: string[]
  tool_trace?: ToolTraceItem[]
  mode?: 'llm' | 'facts_only'
  created_at?: string
  facts?: Record<string, Fact>
}

export interface ApiErrorBody {
  code: string
  i18n_key?: string
  params?: Record<string, any>
  message: string
}
