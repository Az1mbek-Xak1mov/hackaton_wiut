// Presentation helpers only: labels, dates, pill classes. No figure is computed here.
import type { DocStatus, Fact, MonStatus, Severity } from './types'
import { lang, monthName, t } from '@/i18n'

export function fmtDate(iso: string | null | undefined, opts: { short?: boolean } = {}): string {
  if (!iso) return '—'
  const m = /^(\d{4})-(\d{2})(?:-(\d{2}))?/.exec(iso)
  if (!m) return iso
  const [, y, mo, d] = m
  const mon = monthName(Number(mo) - 1) || mo
  if (!d) return `${mon} ${y}`
  return opts.short ? `${d} ${mon}` : `${d} ${mon} ${y}`
}

export function fmtTime(iso: string | null | undefined): string {
  if (!iso) return ''
  const dt = new Date(iso)
  if (Number.isNaN(dt.getTime())) return iso
  return dt.toLocaleTimeString(lang.value === 'en' ? 'en-GB' : lang.value === 'ru' ? 'ru-RU' : 'uz-Latn-UZ', { hour: '2-digit', minute: '2-digit' })
}

export function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const dt = new Date(iso)
  if (Number.isNaN(dt.getTime())) return iso
  const d = String(dt.getDate()).padStart(2, '0')
  return `${d} ${monthName(dt.getMonth())} ${dt.getFullYear()}, ${fmtTime(iso)}`
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

const DOC_TYPE_SHORT: Record<string, string> = {
  form1: 'Balance sheet (Форма 1)',
  form2: 'Income statement (Форма 2)',
  bank_statement: 'Bank statement',
  loan_application: 'Loan application form',
  tax_declaration: 'Tax declaration',
  invoice: 'Invoice',
  sales_ledger: 'Sales ledger',
  unknown: 'Document',
}

export function docTypeShort(dt: string | null | undefined): string {
  if (!dt) return t('Document')
  return DOC_TYPE_SHORT[dt] ? t(DOC_TYPE_SHORT[dt]) : dt
}

export function docTypeLabel(dt: string | null | undefined): string {
  if (!dt) return t('Unknown')
  return DOC_TYPE_LABEL[dt] ? t(DOC_TYPE_LABEL[dt]) : dt
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
  return LANG_LABEL[l] ? t(LANG_LABEL[l]) : l
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
      return { cls: 'pill-stable', label: s === 'processed' ? t('Processed') : t('Analyzed') }
    case 'clarification':
    case 'needs clarification':
      return { cls: 'pill-watch', label: t('Needs clarification') }
    case 'failed':
      return { cls: 'pill-attn', label: t('Could not analyze') }
    case 'missing':
      return { cls: 'pill-neutral', label: t('Missing') }
    case 'queued':
      return { cls: 'pill-info', label: t('Queued') }
    case 'processing':
      return { cls: 'pill-info', label: t('Processing') }
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

export const STATUS_LABEL: Record<string, string> = {
  stable: 'Stable',
  watch: 'Watch',
  attn: 'Attention',
  unknown: 'Not yet monitored',
  not_monitored: 'No loan yet',
}

/** Loan-application workflow status → pill class and plain label. */
export const APP_STATUS: Record<string, { cls: string; label: string }> = {
  processing: { cls: 'pill-neutral', label: 'Reading documents' },
  in_review: { cls: 'pill-info', label: 'Waiting for your review' },
  waiting_on_applicant: { cls: 'pill-watch', label: 'Waiting for the applicant' },
  decided: { cls: 'pill-stable', label: 'Decision recorded' },
  ready: { cls: 'pill-stable', label: 'Ready for review' },
}

export function appStatusPill(st: string | null | undefined): { cls: string; label: string } {
  const p = (st && APP_STATUS[st]) || { cls: 'pill-neutral', label: st ? st.replace(/_/g, ' ') : '—' }
  return { cls: p.cls, label: t(p.label) }
}

/** Plain-language meaning of each ratio label the backend computes (definitions only, no thresholds). */
const RATIO_HELP: [string, string][] = [
  ['Est. debt service coverage', 'Money the business earns per month divided by its monthly loan payments (DSCR). Below 1 means earnings do not cover the payments.'],
  ['Current ratio', 'Current assets divided by current liabilities: can short-term assets pay short-term debts.'],
  ['Quick ratio', 'Same as the current ratio but without inventory, which may be slow to sell.'],
  ['Debt to equity', "Liabilities divided by the owners' equity: how much of the business is funded by debt."],
  ['Net margin', 'Net profit as a share of revenue.'],
  ['Receivable days', 'Average number of days customers take to pay.'],
  ['Installment vs average monthly revenue', 'The new monthly payment as a share of average monthly revenue.'],
]

export function ratioHelp(label: string | null | undefined): string {
  if (!label) return ''
  const hit = RATIO_HELP.find(([k]) => label.startsWith(k))
  return hit ? t(hit[1]) : ''
}

export function statusLabel(s: string | null | undefined): string {
  if (!s) return '—'
  return STATUS_LABEL[s] ? t(STATUS_LABEL[s]) : s
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
  return { cls: 'pill-watch', label: t('{p}% · needs clarification', { p }) }
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
  return METHOD_LABEL[m] ? t(METHOD_LABEL[m]) : m
}

export function factTitle(f: Fact): string {
  const period = f.period_label && !['cur', 'prev'].includes(f.period_label) ? `, ${f.period_label}` : ''
  const unit = f.display_unit ? ` ${f.display_unit}` : ''
  return `${f.label}${period} — ${f.display}${unit}`
}

export function factWhere(f: Fact): string {
  const parts: string[] = []
  if (f.document) parts.push(f.document.filename)
  if (f.document?.doc_type) parts.push(docTypeShort(f.document.doc_type))
  if (f.page_n) parts.push(t('page {n}', { n: f.page_n }))
  if (f.line_code) parts.push(t('line {code}', { code: f.line_code }))
  if (!parts.length && f.kind === 'computed') parts.push(t('Computed from other facts'))
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
  return CATEGORY_LABEL[c] ? t(CATEGORY_LABEL[c]) : c
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
  return STAGE_LABEL[s] ? t(STAGE_LABEL[s]) : s
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
    return t.rules.map((r: any) => (r.indicator || r.id || '') + (r.rule ? `: ${r.rule}` : ''))
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

// ---------- owner-clarity: plain-language variants for the business-owner app ----------
const OWNER_DOC_TYPE: Record<string, string> = {
  form1: 'Balance sheet (Form 1)',
  form2: 'Income statement (Form 2)',
  bank_statement: 'Bank statement',
  loan_application: 'Loan application form',
  tax_declaration: 'Tax declaration',
  invoice: 'Invoice (kept on file, not required)',
  sales_ledger: 'Sales ledger (kept on file, not required)',
  unknown: 'Not recognised as a required document',
}

export function ownerDocTypeLabel(dt: string | null | undefined): string {
  if (!dt) return t('Not recognised as a required document')
  return OWNER_DOC_TYPE[dt] ? t(OWNER_DOC_TYPE[dt]) : dt
}

/** Owner-facing status: a plain label plus one line saying what it means and what to do. */
export function ownerDocStatus(d: { status: string; failure_cause?: string; doc_type?: string; summary?: Record<string, any> }): {
  cls: string
  label: string
  explain: string
} {
  switch (d.status) {
    case 'analyzed':
      return d.doc_type === 'unknown'
        ? { cls: 'pill-neutral', label: t('Read'), explain: t('This file is not one of the documents the bank needs. Check the list above.') }
        : { cls: 'pill-stable', label: t('Ready'), explain: '' }
    case 'clarification': {
      const n = Number(d.summary?.low_confidence || 0)
      const what = n ? t('{n} figure(s) were hard to read, for example on a blurry scan or photo.', { n }) : t('Some figures were hard to read, for example on a blurry scan or photo.')
      return {
        cls: 'pill-watch',
        label: t('Ready, some figures unclear'),
        explain: `${what} ${t('You can still send it: a bank officer will check those figures against the page. For a faster review, upload the original PDF or Excel file, or a sharper photo.')}`,
      }
    }
    case 'failed':
      return {
        cls: 'pill-attn',
        label: t('Could not read'),
        explain: `${d.failure_cause ? d.failure_cause + ' ' : ''}${t('Please upload it again as a PDF, an Excel file, or a sharp, well-lit photo of each page.')}`,
      }
    case 'queued':
    case 'processing':
      return { cls: 'pill-info', label: t('Reading…'), explain: t('This page updates by itself.') }
    default:
      return { cls: 'pill-neutral', label: d.status, explain: '' }
  }
}
