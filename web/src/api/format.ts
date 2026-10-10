// Presentation helpers only: labels, dates, pill classes. No figure is computed here.
import type { DocStatus, Fact, MonStatus, Severity } from './types'

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

export function fmtDate(iso: string | null | undefined, opts: { short?: boolean } = {}): string {
  if (!iso) return '—'
  const m = /^(\d{4})-(\d{2})(?:-(\d{2}))?/.exec(iso)
  if (!m) return iso
  const [, y, mo, d] = m
  const mon = MONTHS[Number(mo) - 1] || mo
  if (!d) return `${mon} ${y}`
  return opts.short ? `${d} ${mon}` : `${d} ${mon} ${y}`
}

export function fmtTime(iso: string | null | undefined): string {
  if (!iso) return ''
  const dt = new Date(iso)
  if (Number.isNaN(dt.getTime())) return iso
  return dt.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })
}

export function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const dt = new Date(iso)
  if (Number.isNaN(dt.getTime())) return iso
  const d = String(dt.getDate()).padStart(2, '0')
  return `${d} ${MONTHS[dt.getMonth()]} ${dt.getFullYear()}, ${fmtTime(iso)}`
}

export function fmtPeriod(start: string | null | undefined, end: string | null | undefined): string {
  if (!start && !end) return '—'
  if (start && end) return `${fmtDate(start)} – ${fmtDate(end)}`
  return fmtDate(start || end)
}

export function fmtBytes(n: number | null | undefined): string {
  if (n == null) return ''
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${Math.round(n / 1024)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

/** Signed percentage with a true minus sign; value already computed by the backend. */
export function fmtSignedPct(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return '—'
  const s = Math.abs(v).toFixed(1)
  if (v > 0) return `+${s}%`
  if (v < 0) return `−${s}%`
  return `${s}%`
}

/** Replaces a leading ASCII hyphen-minus with a true minus sign in a backend display string. */
export function trueMinus(s: string | null | undefined): string {
  if (s == null) return '—'
  return s.replace(/^-/, '−').replace(/ -(\d)/g, ' −$1')
}

/** Appends a unit if the display string does not already carry one. */
export function withUnit(display: string | null | undefined, unit: string): string {
  if (display == null || display === '') return '—'
  return /[A-Za-z]/.test(display) ? display : `${display} ${unit}`
}

export const DOC_TYPE_LABEL: Record<string, string> = {
  form1: 'Balance sheet (Форма 1)',
  form2: 'Income statement (Форма 2)',
  bank_statement: 'Bank statement',
  loan_application: 'Loan application form',
  tax_declaration: 'Tax declaration (recognised only)',
  invoice: 'Invoice (recognised only)',
  sales_ledger: 'Sales ledger (recognised only)',
  unknown: 'Not a recognised statutory form',
}

export function docTypeLabel(t: string | null | undefined): string {
  if (!t) return 'Unknown'
  return DOC_TYPE_LABEL[t] || t
}

export const LANG_LABEL: Record<string, string> = {
  uz_latn: 'Uzbek (Latin)',
  uz_cyrl: 'Uzbek (Cyrillic)',
  ru: 'Russian',
  en: 'English',
  mixed: 'Mixed languages',
}

export function langLabel(l: string | null | undefined): string {
  if (!l) return '—'
  return LANG_LABEL[l] || l
}

export function fileBadge(filename: string | null | undefined, mime?: string): string {
  const ext = (filename || '').split('.').pop()?.toUpperCase() || ''
  if (ext && ext.length <= 4) return ext
  if (mime?.includes('pdf')) return 'PDF'
  if (mime?.includes('sheet')) return 'XLSX'
  if (mime?.includes('image')) return 'IMG'
  return 'FILE'
}

export function docStatusPill(s: DocStatus | string): { cls: string; label: string } {
  switch (s) {
    case 'analyzed':
    case 'processed':
      return { cls: 'pill-stable', label: s === 'processed' ? 'Processed' : 'Analyzed' }
    case 'clarification':
    case 'needs clarification':
      return { cls: 'pill-watch', label: 'Needs clarification' }
    case 'failed':
      return { cls: 'pill-attn', label: 'Could not analyze' }
    case 'missing':
      return { cls: 'pill-neutral', label: 'Missing' }
    case 'queued':
      return { cls: 'pill-info', label: 'Queued' }
    case 'processing':
      return { cls: 'pill-info', label: 'Processing' }
    default:
      return { cls: 'pill-neutral', label: s }
  }
}

export function severityPillClass(s: Severity | MonStatus | string): string {
  switch (s) {
    case 'attn':
      return 'pill-attn'
    case 'watch':
      return 'pill-watch'
    case 'stable':
      return 'pill-stable'
    case 'info':
      return 'pill-info'
    default:
      return 'pill-neutral'
  }
}

export const STATUS_LABEL: Record<string, string> = { stable: 'Stable', watch: 'Watch', attn: 'Attention', unknown: 'Not yet monitored' }

export function statusLabel(s: string | null | undefined): string {
  if (!s) return '—'
  return STATUS_LABEL[s] || s
}

/** Confidence may arrive as 0–1 or 0–100. */
export function confPct(c: number | null | undefined): number | null {
  if (c == null || Number.isNaN(c)) return null
  return Math.round(c > 1 ? c : c * 100)
}

export function confPill(c: number | null | undefined): { cls: string; label: string } | null {
  const p = confPct(c)
  if (p == null) return null
  if (p >= 95) return { cls: 'pill-stable', label: `${p}%` }
  if (p >= 80) return { cls: 'pill-neutral', label: `${p}%` }
  return { cls: 'pill-watch', label: `${p}% · needs clarification` }
}

export const METHOD_LABEL: Record<string, string> = {
  dictionary: 'Matched by statutory line code and label',
  fuzzy: 'Matched by label only (no line code printed)',
  llm_fallback: 'Mapped by the language model from candidate codes, then checked against the form arithmetic',
  'ocr+dictionary': 'Read by OCR, then matched by line code and label',
  rule: 'Produced by a reconciliation rule',
  compute: 'Computed deterministically from the cited facts',
  aggregate: 'Sum of bank-statement rows',
}

export function methodLabel(m: string | null | undefined): string {
  if (!m) return ''
  return METHOD_LABEL[m] || m
}

export function factTitle(f: Fact): string {
  const period = f.period_label && !['cur', 'prev'].includes(f.period_label) ? `, ${f.period_label}` : ''
  const unit = f.display_unit ? ` ${f.display_unit}` : ''
  return `${f.label}${period} — ${f.display}${unit}`
}

export function factWhere(f: Fact): string {
  const parts: string[] = []
  if (f.document) parts.push(f.document.filename)
  if (f.document?.doc_type) parts.push(docTypeLabel(f.document.doc_type).replace(/ \(recognised only\)/, ''))
  if (f.page_n) parts.push(`page ${f.page_n}`)
  if (f.line_code) parts.push(`line ${f.line_code}`)
  if (!parts.length && f.kind === 'computed') parts.push('Computed from other facts')
  return parts.join(' · ')
}

export const CATEGORY_LABEL: Record<string, string> = {
  sales_receipt: 'Sales receipts',
  supplier_payment: 'Supplier payments',
  salary: 'Salaries',
  payroll_tax: 'Payroll taxes',
  tax: 'Taxes',
  loan_repayment: 'Loan repayments',
  loan_disbursement: 'Loan disbursements',
  rent_utilities: 'Rent & utilities',
  own_transfer: 'Own transfers',
  cash_withdrawal: 'Cash withdrawals',
  bank_fee: 'Bank fees',
  other: 'Other / uncategorised',
}

export function categoryLabel(c: string): string {
  return CATEGORY_LABEL[c] || c
}

export const STAGES = ['classify', 'parse', 'ocr', 'extract', 'normalise', 'reconcile', 'ratios', 'narrative'] as const
export const STAGE_LABEL: Record<string, string> = {
  queued: 'Waiting in queue',
  classify: 'Recognising the document type',
  parse: 'Reading pages and tables',
  ocr: 'Running OCR on scanned pages',
  extract: 'Mapping statutory line codes',
  normalise: 'Normalising bank-statement rows',
  reconcile: 'Running reconciliation rules',
  ratios: 'Computing ratios',
  narrative: 'Writing and verifying the summary',
  readable: 'Reading numbers, dates and IDs',
  describe: 'Writing a verified description',
  done: 'Done',
}

export function stageLabel(s: string | null | undefined): string {
  if (!s) return ''
  return STAGE_LABEL[s] || s
}

export function hasUnit(display: string | null | undefined): boolean {
  return !!display && /[A-Za-z%×]/.test(display)
}

function humanise(k: string): string {
  return k
    .replace(/([a-z])([A-Z])/g, '$1 $2')
    .replace(/_/g, ' ')
    .replace(/^./, (c) => c.toUpperCase())
}

/** Renders the disclosed monitoring thresholds exactly as the backend reports them. */
export function thresholdText(t: Record<string, any> | null | undefined): string[] {
  if (!t || typeof t !== 'object') return []
  if (Array.isArray(t.rules)) {
    return t.rules.map((r: any) => [r.id, r.indicator].filter(Boolean).join(' ') + (r.rule ? `: ${r.rule}` : ''))
  }
  const out: string[] = []
  for (const [k, v] of Object.entries(t)) {
    if (v == null) continue
    if (typeof v !== 'object') out.push(`${humanise(k)}: ${v}`)
    else {
      const label = v.label || v.name || humanise(k)
      const val = v.display ?? v.threshold ?? v.value
      out.push(val != null ? `${label}: ${val}` : `${label}`)
    }
  }
  return out
}
