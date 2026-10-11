<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, errMessage } from '@/api/client'
import type { AnalyseResult, BundleResult, Fact } from '@/api/types'
import {
  categoryLabel, confPill, docStatusPill, docTypeLabel, docTypeShort, fmtBytes, fmtPeriod, langLabel, ratioHelp, severityPillClass, stageLabel, trueMinus,
} from '@/api/format'
import { useEvidence } from '@/stores/evidence'
import Dropzone from '@/components/ui/Dropzone.vue'
import ProgressBar from '@/components/ui/ProgressBar.vue'
import EvidencePane from '@/components/evidence/EvidencePane.vue'
import EvidenceChip from '@/components/evidence/EvidenceChip.vue'
import FindingRow from '@/components/evidence/FindingRow.vue'
import InlineEvidence from '@/components/evidence/InlineEvidence'
import NarrativeText from '@/components/evidence/NarrativeText'
import { aiStatusMessage } from '@/api/aiStatus'
import { t, tn } from '@/i18n'

const route = useRoute()
const router = useRouter()
const ev = useEvidence()

const uuid = ref<string | null>(typeof route.query.doc === 'string' ? route.query.doc : null)
const file = ref<{ name: string; size: number } | null>(null)
const uploading = ref(false)
const uploadErr = ref('')
const result = ref<AnalyseResult | null>(null)
const pollErr = ref('')
const seenStages = ref<string[]>([])
const startedAt = ref<number>(0)
const elapsed = ref(0)
let timer: ReturnType<typeof setTimeout> | null = null
let tick: ReturnType<typeof setInterval> | null = null

const SAMPLES = [
  { href: '/samples/farovon_loan_file.zip', label: 'Loan file bundle', note: 'application, Форма 1 ×2 (one scanned), Форма 2 ×2, bank statement' },
  { href: '/samples/navroz_owner_docs.zip', label: 'Business owner bundle', note: 'statement, Форма 2, scanned balance sheet, blurred photo' },
  { href: '/samples/zilola_monitoring.zip', label: 'Monitoring bundle', note: 'quarterly Форма 1 and 2, three-month statement' },
]
const SINGLES = [
  { href: '/samples/form2_clean.pdf', label: 'Форма 2, text PDF' },
  { href: '/samples/form2_scan_150dpi.pdf', label: 'Форма 2, 150 dpi scan' },
  { href: '/samples/statement.xlsx', label: 'Bank statement, XLSX' },
  { href: '/samples/photo_invoice.jpg', label: 'Phone photo, JPG' },
  { href: '/samples/english_ifrs.pdf', label: 'English IFRS statement' },
]

const doc = computed(() => result.value?.document || null)
const job = computed(() => result.value?.job || null)
const running = computed(() => {
  const j = job.value
  if (!uuid.value) return false
  if (!j) return true
  return j.status === 'queued' || j.status === 'running'
})

// A sample is fetched from /samples and sent through the same upload as a visitor's own file.
const sampleBusy = ref('')
async function trySample(href: string) {
  uploadErr.value = ''
  sampleBusy.value = href
  try {
    const res = await fetch(href)
    if (!res.ok) throw new Error(t('The sample could not be loaded. Please try again.'))
    const blob = await res.blob()
    await upload([new File([blob], href.split('/').pop() || 'sample', { type: blob.type })])
  } catch (e) {
    uploadErr.value = errMessage(e)
  } finally {
    sampleBusy.value = ''
  }
}

const isZip = (f: File) => /\.zip$/i.test(f.name) || f.type === 'application/zip' || f.type === 'application/x-zip-compressed'

async function upload(files: File[]) {
  const f = files[0]
  if (!f) return
  uploadErr.value = ''
  if (files.length > 1 || isZip(f)) return uploadBundle(files)
  if (f.size > 20 * 1024 * 1024) {
    uploadErr.value = t('{file} is {size}; the public limit is 20 MB.', { file: f.name, size: fmtBytes(f.size) })
    return
  }
  stopPolling()
  ev.clear()
  result.value = null
  seenStages.value = []
  file.value = { name: f.name, size: f.size }
  uploading.value = true
  try {
    const created = await api.analyse(f)
    if (created.kind === 'bundle') {
      uploading.value = false
      return startBundle(created.uuid)
    }
    uuid.value = created.uuid
    router.replace({ query: { doc: created.uuid } })
    startedAt.value = Date.now()
    startTick()
    poll()
  } catch (e) {
    uploadErr.value = errMessage(e)
  } finally {
    uploading.value = false
  }
}

function startTick() {
  if (tick) clearInterval(tick)
  tick = setInterval(() => (elapsed.value = Math.round((Date.now() - startedAt.value) / 1000)), 500)
}

async function poll() {
  if (!uuid.value) return
  try {
    const r = await api.analyseResult(uuid.value)
    result.value = r
    pollErr.value = ''
    ev.register(r.facts)
    registerReadable(r)
    const st = r.job?.stage
    if (st && !seenStages.value.includes(st)) seenStages.value = [...seenStages.value, st]
    const kf = keyFigures.value.find((k) => k.cur.page_n != null) || keyFigures.value[0]
    const first = kf?.cur || r.facts.find((f) => f.page_n != null) || r.facts[0]
    if (first) ev.selectDefault(first.key)
    if (r.job && (r.job.status === 'done' || r.job.status === 'failed')) {
      if (tick) clearInterval(tick)
      tick = null
      return
    }
  } catch (e) {
    pollErr.value = errMessage(e)
    if ((e as any)?.status === 404) {
      if (tick) clearInterval(tick)
      return
    }
  }
  const slow = startedAt.value && Date.now() - startedAt.value > 120_000
  timer = setTimeout(poll, slow ? 3000 : 1000)
}

function stopPolling() {
  if (timer) clearTimeout(timer)
  timer = null
  if (tick) clearInterval(tick)
  tick = null
}

function reset() {
  stopPolling()
  stopBundlePolling()
  bundleId.value = null
  bundle.value = null
  fromBundle.value = null
  uuid.value = null
  result.value = null
  file.value = null
  seenStages.value = []
  ev.clear()
  router.replace({ query: {} })
}

onMounted(() => {
  if (bundleId.value) {
    startedAt.value = Date.now()
    startTick()
    pollBundle()
  } else if (uuid.value) {
    startedAt.value = Date.now()
    poll()
  }
})
onBeforeUnmount(() => { stopPolling(); stopBundlePolling() })

// Readable numbers become local evidence entries so they can be shown on their page.
function registerReadable(r: AnalyseResult) {
  const nums = r.readable?.numbers || []
  if (!nums.length || !r.document) return
  const dims = new Map<number, { w: number; h: number }>()
  for (const f of r.facts) if (f.page_n && f.page_width && f.page_height) dims.set(f.page_n, { w: f.page_width, h: f.page_height })
  const pseudo: Fact[] = nums.map((n, i) => {
    const d = dims.get(n.page_n)
    return {
      key: `r_${r.document.uuid.slice(0, 8)}_${i}`,
      uuid: '',
      field: 'readable.number',
      label: n.label || t('Number read from the page'),
      value: NaN,
      unit: 'count',
      display: n.text,
      display_unit: '',
      printed: n.text,
      period_label: '',
      line_code: null,
      kind: 'extracted',
      page_n: n.page_n,
      bbox: d ? n.bbox : null,
      page_width: d?.w ?? null,
      page_height: d?.h ?? null,
      page_image_url: `/api/v1/documents/${r.document.uuid}/pages/${n.page_n}.png`,
      passage: n.label ? `${n.label}   ${n.text}` : n.text,
      confidence: NaN,
      method: 'readable',
      formula: '',
      inputs: [],
      note: t('Read from the page but not mapped to a statutory line; shown as printed, not interpreted.'),
      status: 'auto',
      document: { uuid: r.document.uuid, filename: r.document.filename, doc_type: r.document.doc_type },
    }
  })
  ev.register(pseudo)
}

// ----- extracted lines table -----
const lineFacts = computed(() => (result.value?.facts || []).filter((f) => f.kind === 'extracted' && f.line_code))
const otherFacts = computed(() => (result.value?.facts || []).filter((f) => !(f.kind === 'extracted' && f.line_code)))
const OTHER_SHOWN = 8
const showAllOther = ref(false)
const otherShown = computed(() => (showAllOther.value ? otherFacts.value : otherFacts.value.slice(0, OTHER_SHOWN)))
const HOW: Record<string, string> = { aggregate: 'sum of statement rows', computed: 'computed from cited values', extracted: 'read from the page' }
const isSheet = computed(() => {
  const d = doc.value
  return !!d && (/\.xlsx?$/i.test(d.filename) || (d.mime || '').includes('sheet'))
})
const periods = computed(() => {
  const order: string[] = []
  for (const f of lineFacts.value) if (!order.includes(f.period_label)) order.push(f.period_label)
  const rank = (p: string) => (p === 'cur' ? 99999 : p === 'prev' ? 99998 : Number((/(\d{4})/.exec(p) || [])[1] || 0) * 10 + (/^H1|^Q[1-2]/i.test(p) ? 1 : /^Q[34]/i.test(p) ? 2 : 0))
  return order.sort((a, b) => rank(b) - rank(a))
})
function periodHead(p: string) {
  if (p === 'cur') return t('Current period')
  if (p === 'prev') return t('Prior period')
  return p || t('Value')
}
const lineRows = computed(() => {
  const map = new Map<string, { code: string; label: string; cells: Record<string, Fact>; conf: number }>()
  for (const f of lineFacts.value) {
    const k = f.line_code!
    if (!map.has(k)) map.set(k, { code: k, label: f.label, cells: {}, conf: f.confidence })
    const row = map.get(k)!
    row.cells[f.period_label] = f
    row.conf = Math.min(row.conf, f.confidence)
  }
  return [...map.values()].sort((a, b) => a.code.localeCompare(b.code, undefined, { numeric: true }))
})

const stageRows = computed(() => {
  const t = job.value?.stage_timings || {}
  const names = Object.keys(t).filter((k) => k !== 'total')
  for (const sname of seenStages.value) if (!names.includes(sname)) names.push(sname)
  return names.map((name) => ({
    name,
    ms: typeof t[name] === 'number' ? Math.round(t[name]) : null,
    current: running.value && job.value?.stage === name,
  }))
})
const totalMs = computed(() => {
  const v = job.value?.stage_timings?.total
  return typeof v === 'number' ? Math.round(v) : null
})

const typePill = computed(() => {
  const d = doc.value
  if (!d) return { cls: 'pill-neutral', label: '' }
  if (d.status === 'failed') return { cls: 'pill-attn', label: t('Could not analyze') }
  if (['form1', 'form2', 'bank_statement', 'loan_application'].includes(d.doc_type)) return { cls: 'pill-stable', label: docTypeLabel(d.doc_type) }
  if (d.doc_type === 'unknown') return { cls: 'pill-watch', label: docTypeLabel(d.doc_type) }
  return { cls: 'pill-neutral', label: docTypeLabel(d.doc_type) }
})

const readableKeys = computed(() => {
  const r = result.value
  if (!r?.readable?.numbers?.length || !r.document) return []
  return r.readable.numbers.map((_, i) => `r_${r.document.uuid.slice(0, 8)}_${i}`)
})

const showExcerpt = ref(false)

// ----- plain-language summary (everything below comes from the API response; nothing is computed here) -----
const RECOGNISED = ['form1', 'form2', 'bank_statement', 'loan_application']
const TYPE_EXPLAIN: Record<string, string> = {
  form1: 'A balance sheet shows what the business owns and what it owes on one date.',
  form2: 'An income statement shows how much the business sold over a period and what was left after costs.',
  bank_statement: 'A bank statement lists the money that came into and went out of the account.',
  loan_application: 'A loan application states how much the business asks to borrow and on what terms.',
  tax_declaration: 'A tax declaration is what the business reported to the tax authority for a period: its revenue and the tax due.',
  invoice: 'An invoice (счёт-фактура) records one sale: who sold what to whom, for how much.',
  sales_ledger: 'A sales ledger lists the sales of the business one by one.',
  unknown: 'Converza could not match this file to a form it knows. Below is what it could still read from it.',
}
const typeExplain = computed(() => {
  const d = doc.value
  if (!d) return ''
  const e = TYPE_EXPLAIN[d.doc_type] || (RECOGNISED.includes(d.doc_type) ? '' : TYPE_EXPLAIN.unknown)
  return e ? t(e) : ''
})
// Recognised types without line extraction (e.g. tax declaration): say so instead of "could not match".
const recognisedOnly = computed(() => {
  const d = doc.value
  return !!d && d.doc_type !== 'unknown' && !!TYPE_EXPLAIN[d.doc_type] && !RECOGNISED.includes(d.doc_type) && !(result.value?.facts || []).some((f) => f.kind === 'extracted' && f.method !== 'readable')
})
const applicantName = computed(() => {
  const f = (result.value?.facts || []).find((x) => x.field === 'application.applicant_name')
  return f ? (f.note || f.printed || '').trim() : ''
})
const docStir = computed(() => (doc.value as any)?.stir || result.value?.readable?.stirs?.[0] || '')
const plainStatus = computed(() => {
  const d = doc.value
  if (!d) return ''
  if (d.status === 'analyzed') return t('Read successfully.')
  if (d.status === 'clarification') return t('Read, but some values are uncertain. They are marked below; check them on the page before relying on them.')
  if (d.status === 'failed') return t('Could not be read as a whole.')
  return ''
})
const lowConfCount = computed(() => {
  const n = doc.value?.summary?.low_confidence
  return typeof n === 'number' ? n : 0
})

interface KeyDef { field: (f: Fact) => boolean; label: string; explain: string; latest?: boolean }
const formField = (form: string, slug: string) => (f: Fact) => f.kind === 'extracted' && f.field.startsWith(form + '.') && f.field.endsWith('.' + slug)
const KEY_DEFS: Record<string, KeyDef[]> = {
  form2: [
    { field: formField('form2', 'net_revenue'), label: 'Revenue (sales)', explain: 'Money earned from sales in the period' },
    { field: formField('form2', 'cost_of_sales'), label: 'Cost of what was sold', explain: 'Direct cost of the goods or services sold' },
    { field: formField('form2', 'gross_profit'), label: 'Gross profit', explain: 'Revenue minus the cost of what was sold' },
    { field: formField('form2', 'operating_profit'), label: 'Operating profit', explain: 'Profit from day-to-day business' },
    { field: formField('form2', 'net_profit'), label: 'Net profit', explain: 'What is left after all costs and taxes' },
  ],
  form1: [
    { field: formField('form1', 'total_assets'), label: 'Everything the business owns', explain: 'Total assets' },
    { field: formField('form1', 'cash_total'), label: 'Cash', explain: 'Cash in hand and in bank accounts at the end of the period' },
    { field: formField('form1', 'receivables_total'), label: 'Owed to the business', explain: 'Money customers and others still have to pay' },
    { field: formField('form1', 'inventory_total'), label: 'Stock', explain: 'Goods and materials held' },
    { field: formField('form1', 'equity_total'), label: "Owner's equity", explain: 'What belongs to the owners after all debts' },
    { field: formField('form1', 'liabilities_total'), label: 'Debts and obligations', explain: 'Everything the business owes' },
  ],
  bank_statement: [
    { field: (f) => f.field === 'statement.inflow.sales_receipt.total', label: 'Received from customers', explain: 'Sum of customer payments over the statement' },
    { field: (f) => f.field === 'statement.avg_monthly_inflow', label: 'Customer receipts per month, on average', explain: 'Average over the months covered' },
    { field: (f) => f.field.startsWith('statement.balance_end.'), label: 'Account balance at the end', explain: 'Balance at the end of the last month covered', latest: true },
  ],
  loan_application: [
    { field: (f) => f.field === 'application.requested_amount', label: 'Amount requested', explain: 'How much the business asks to borrow' },
    { field: (f) => f.field === 'application.term_months', label: 'Loan term', explain: 'How long the loan would run' },
    { field: (f) => f.field === 'application.rate_pct', label: 'Interest rate', explain: 'Rate stated in the application' },
    { field: (f) => f.field === 'application.declared_revenue_fy', label: 'Declared yearly revenue', explain: 'Revenue the applicant states for the year' },
    { field: (f) => f.field === 'application.declared_debts_total', label: 'Existing debts declared', explain: 'Other loans the applicant says they have' },
  ],
}
const keyFigures = computed(() => {
  const d = doc.value
  const facts = (result.value?.facts || []).filter((f) => (f.unit as string) !== 'text')
  if (!d || !KEY_DEFS[d.doc_type]) return []
  const cur = periods.value[0]
  const prev = periods.value[1]
  const out: { label: string; explain: string; cur: Fact; prev: Fact | null; unit: string; uncertain: boolean }[] = []
  for (const def of KEY_DEFS[d.doc_type]) {
    const hits = facts.filter(def.field)
    if (!hits.length) continue
    let c: Fact | undefined
    let p: Fact | null = null
    if (def.latest) c = [...hits].sort((a, b) => b.field.localeCompare(a.field))[0]
    else if (d.doc_type === 'form1' || d.doc_type === 'form2') {
      c = hits.find((f) => f.period_label === cur) || hits[0]
      p = (prev && hits.find((f) => f.period_label === prev && f !== c)) || null
    } else c = hits[0]
    if (!c) continue
    const unit = c.display_unit || (c.field === 'application.term_months' ? t('months') : '')
    out.push({ label: t(def.label), explain: t(def.explain), cur: c, prev: p, unit, uncertain: Number.isFinite(c.confidence) && c.confidence < 0.8 })
    if (out.length >= 6) break
  }
  return out
})
function periodText(p: string) {
  if (!p || p === 'cur') return t('this period')
  if (p === 'prev') return t('prior period')
  return p
}

interface Plain { what: string; todo: string }
const RULE_PLAIN: Record<string, Plain> = {
  R01: { what: 'The balance sheet does not balance: what the business owns does not equal what it owes plus the owners’ equity.', todo: 'Compare the totals with the page. If the page itself does not balance, ask the accountant for a corrected balance sheet.' },
  R02: { what: 'A total on the balance sheet is not equal to the sum of its lines.', todo: 'Open the page and compare the total with its lines. It is either a typing error in the document or a value that was misread.' },
  R03: { what: 'A total on the income statement is not equal to the sum of its lines.', todo: 'Open the page and compare the total with its lines. It is either a typing error in the document or a value that was misread.' },
  R04: { what: 'The profit for the period does not explain the change in owners’ equity.', todo: 'Ask whether dividends were paid or earlier figures were adjusted; neither is visible in this document.' },
  R05: { what: 'Revenue in the statements is different from the money received in the bank account.', todo: 'Ask about cash sales or other bank accounts, and compare with statements for the same months.' },
  R06: { what: 'The bank statement shows regular loan payments that were not declared.', todo: 'Ask the business about this loan and add it to the declared debts.' },
  R07: { what: 'Two sources state different things.', todo: 'Check which one is correct and ask for a corrected document.' },
  R08: { what: 'Part of the period is not covered by the documents.', todo: 'Upload documents for the missing months.' },
  R09: { what: 'The documents belong to different taxpayers (different STIR).', todo: 'Make sure every document is for the same company.' },
  R10: { what: 'A required document is missing.', todo: 'Upload the missing document.' },
  R11: { what: 'Revenue follows an unusual pattern.', todo: 'Ask the business to explain it, for example seasonal or one-off sales.' },
  R12: { what: 'The same document or figure appears twice with different values.', todo: 'Keep one version and check which figure is right.' },
}
function plainFor(rule: string, title: string): Plain {
  const p = RULE_PLAIN[rule]
  return p ? { what: t(p.what), todo: t(p.todo) } : { what: title, todo: t('Click a dashed value to open its page and check the figures.') }
}
const checksRan = computed(() => {
  const tm = job.value?.stage_timings || {}
  return 'reconcile' in tm || seenStages.value.includes('reconcile')
})
const allValuesCount = computed(() => (result.value?.facts || []).length + (result.value?.unmapped?.length || 0))
const doneStages = computed(() => stageRows.value.filter((s) => !s.current))
const finished = computed(() => !!doc.value && !running.value && doc.value.status !== 'queued' && doc.value.status !== 'processing')

// ----- loan file: several files or a ZIP, checked together like a bank application -----
const MAX_BUNDLE_FILES = 12
const bundleId = ref<string | null>(typeof route.query.bundle === 'string' ? route.query.bundle : null)
const bundle = ref<BundleResult | null>(null)
const bundleErr = ref('')
const fromBundle = ref<string | null>(null) // set while one document of the loan file is opened on its own
let bundleTimer: ReturnType<typeof setTimeout> | null = null

async function uploadBundle(files: File[]) {
  const total = files.reduce((a, f) => a + f.size, 0)
  const big = files.find((f) => !isZip(f) && f.size > 20 * 1024 * 1024)
  if (big) {
    uploadErr.value = t('{file} is {size}; the public limit is 20 MB.', { file: big.name, size: fmtBytes(big.size) })
    return
  }
  if (total > 40 * 1024 * 1024) {
    uploadErr.value = t('The files are {size} together; a loan file can be up to 40 MB.', { size: fmtBytes(total) })
    return
  }
  if (files.filter((f) => !isZip(f)).length > MAX_BUNDLE_FILES) {
    uploadErr.value = t('Upload at most {n} files at once (or one ZIP).', { n: MAX_BUNDLE_FILES })
    return
  }
  stopPolling()
  ev.clear()
  result.value = null
  uuid.value = null
  file.value = files.length === 1 ? { name: files[0].name, size: files[0].size } : null
  uploading.value = true
  try {
    const created = await api.analyseBundle(files)
    startBundle(created.uuid)
  } catch (e) {
    uploadErr.value = errMessage(e)
  } finally {
    uploading.value = false
  }
}

function startBundle(id: string) {
  stopPolling()
  uuid.value = null
  result.value = null
  bundle.value = null
  bundleErr.value = ''
  bundleId.value = id
  router.replace({ query: { bundle: id } })
  startedAt.value = Date.now()
  startTick()
  pollBundle()
}

function stopBundlePolling() {
  if (bundleTimer) clearTimeout(bundleTimer)
  bundleTimer = null
}

async function pollBundle() {
  if (!bundleId.value) return
  try {
    const r = await api.analyseBundleResult(bundleId.value)
    bundle.value = r
    bundleErr.value = ''
    if (r.review) {
      ev.register(r.review.facts)
      const first = r.review.issues.find((i) => i.evidence.length)?.evidence[0]
      if (first) ev.selectDefault(first)
    }
    if (r.status === 'done' || r.status === 'failed') {
      if (tick) clearInterval(tick)
      tick = null
      return
    }
  } catch (e) {
    bundleErr.value = errMessage(e)
    if ((e as any)?.status === 404) {
      if (tick) clearInterval(tick)
      return
    }
  }
  const slow = startedAt.value && Date.now() - startedAt.value > 180_000
  bundleTimer = setTimeout(pollBundle, slow ? 4000 : 1500)
}

// Opens one document of the loan file in the single-document view; "Back" returns to the loan file.
function openBundleDoc(docUuid: string) {
  stopBundlePolling()
  fromBundle.value = bundleId.value
  bundleId.value = null
  ev.clear()
  result.value = null
  seenStages.value = []
  uuid.value = docUuid
  router.replace({ query: { doc: docUuid } })
  startedAt.value = Date.now()
  poll()
}
function backToBundle() {
  const id = fromBundle.value
  if (!id) return
  stopPolling()
  fromBundle.value = null
  uuid.value = null
  result.value = null
  ev.clear()
  startBundle(id)
}

const bundleRunning = computed(() => !!bundleId.value && (!bundle.value || bundle.value.status === 'reading' || bundle.value.status === 'analysing'))
const bundleDone = computed(() => bundle.value?.status === 'done' && !!bundle.value.review)
const bundleReadCount = computed(() => (bundle.value?.documents || []).filter((d) => ['analyzed', 'clarification', 'failed'].includes(d.status)).length)
const bundleIssues = computed(() => bundle.value?.review?.issues || [])
const bundleRatios = computed(() => bundle.value?.review?.ratios || [])
const bundleFigures = computed(() => bundle.value?.review?.figures || [])
const bundleColumns = computed(() => bundle.value?.review?.columns || [])
const bundleNarrative = computed(() => {
  const n = bundle.value?.review?.narrative
  return n && n.markdown && n.verified !== false ? n : null
})
// plain reason there is no AI summary / description (switched off, no key, no credits left, provider error)
const bundleAiOff = computed(() => {
  const n = bundle.value?.review?.narrative
  return n && n.mode !== 'llm' ? aiStatusMessage(n.llm_status, n.llm_status_text) : ''
})
const docAiOff = computed(() => {
  const d = result.value?.description
  return d && d.mode !== 'llm' ? aiStatusMessage(d.llm_status, d.llm_status_text) : ''
})
const bundleRequest = computed(() => {
  const r = bundle.value?.review?.request
  return r && r.amount_display && r.amount_display !== 'n/a' ? r : null
})
function bundleDocState(d: { status: string; job?: { status: string; stage: string; progress: number } | null }) {
  if (d.status === 'queued') return { cls: 'pill-neutral', label: t('Waiting') }
  if (d.status === 'processing') return { cls: 'pill-info', label: (stageLabel(d.job?.stage) || t('Reading')) }
  return docStatusPill(d.status)
}
function bundleDocKind(d: { doc_type: string; status: string }) {
  if (d.status === 'queued' || d.status === 'processing') return '…'
  if (d.status === 'failed' && d.doc_type === 'unknown') return t('Could not analyze')
  return d.doc_type === 'unknown' ? t('Not a recognised form') : docTypeShort(d.doc_type)
}
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h1>{{ t('Analyse a document') }}</h1>
        <p class="meta" style="max-width: 760px">
          {{ t('Upload one document: a balance sheet, an income statement, a bank statement or a loan application. Converza tells you what it is, shows its main figures in plain words, and links every number to the page it came from.') }}
          {{ t('Or upload a whole loan file — several files at once, or one ZIP — to check the documents against each other.') }}
        </p>
      </div>
      <div class="row">
        <button v-if="uuid && fromBundle" type="button" class="btn" @click="backToBundle">{{ t('Back to the loan file') }}</button>
        <button v-if="uuid || bundleId" type="button" class="btn" @click="reset">{{ t('Analyse another document') }}</button>
      </div>
    </div>

    <div class="twopane">
      <div class="main-col">
        <!-- Upload -->
        <section v-if="!uuid && !bundleId" class="panel" :aria-label="t('Upload')" style="padding: 16px; display: flex; flex-direction: column; gap: 14px">
          <Dropzone multiple accept=".pdf,.xlsx,.xls,.csv,.jpg,.jpeg,.png,.tif,.tiff,.heic,.zip" :disabled="uploading" :title="uploading ? t('Uploading…') : t('Drop a document or a whole loan file here')" :button="t('Choose files')" :hint="t('One file, several files or one ZIP · up to 20 MB per file')" @files="upload" />
          <div v-if="uploadErr" class="error-box">{{ uploadErr }}</div>
          <ul class="works muted">
            <li>{{ t('PDF, scan or phone photo of: Форма 1 (balance sheet), Форма 2 (income statement), tax declaration, loan application.') }}</li>
            <li>{{ t('Bank statement: as an Excel file (XLSX) exported from the bank.') }}</li>
            <li>{{ t('A whole loan file: several of these files at once, or one ZIP with them (up to 12 files, 40 MB). The documents are then checked against each other.') }}</li>
            <li>{{ t('Any other file still gets an honest answer: what it is not, and what could be read from it. Public uploads are deleted after 24 hours; names are not sent to the language model.') }}</li>
          </ul>
        </section>

        <section v-if="!uuid && !bundleId" class="panel" :aria-label="t('Sample documents')">
          <div class="panel-head" style="padding: 12px 14px 8px">
            <h2>{{ t('No document at hand? Use a sample') }}</h2>
            <span class="ctx">{{ t('Synthetic, generated for this demo') }}</span>
          </div>
          <div class="scrollbox">
            <table class="tbl">
              <tbody>
                <tr v-for="s in SAMPLES" :key="s.href">
                  <td style="width: 1%; white-space: nowrap">
                    <button type="button" class="btn btn-sm" :disabled="!!sampleBusy || uploading" @click="trySample(s.href)">{{ sampleBusy === s.href ? t('Loading…') : t('Analyse this loan file') }}</button>
                  </td>
                  <td>{{ t(s.label) }} <span class="muted">· {{ t(s.note) }} · <a :href="s.href" download>{{ t('download ZIP') }}</a></span></td>
                </tr>
              </tbody>
            </table>
          </div>
          <div style="padding: 10px 14px 4px; font-size: 13px">{{ t('Click a sample to analyse it now. It goes through exactly the same steps as your own file.') }}</div>
          <div class="row" style="padding: 6px 14px 14px">
            <button v-for="s in SINGLES" :key="s.href" type="button" class="chip round" :disabled="!!sampleBusy || uploading" @click="trySample(s.href)">{{ sampleBusy === s.href ? t('Loading…') : t(s.label) }}</button>
          </div>
        </section>

        <!-- Loan file: progress per document -->
        <section v-if="bundleId" class="panel" :aria-label="t('Loan file')" style="padding: 14px 16px; display: flex; flex-direction: column; gap: 10px">
          <div class="row" style="justify-content: space-between">
            <div>
              <div class="eyebrow">{{ t('Loan file check') }}</div>
              <div class="doc-title">{{ bundle ? tn(bundle.documents.length, '{n} document', '{n} documents') : t('Uploading…') }}</div>
            </div>
            <span v-if="bundleRunning && bundle" class="muted num" style="font-size: 12px">{{ t('{a} of {b} read', { a: bundleReadCount, b: bundle.documents.length }) }} · {{ elapsed }} s</span>
          </div>
          <div v-if="bundleRunning" class="now" aria-live="polite">
            <span class="pill pill-info">{{ t('Working') }}</span>
            <span>{{ bundle?.status === 'analysing' ? t('Checking the documents against each other…') : t('Reading each document…') }}</span>
          </div>
          <div v-if="bundle" class="scrollbox">
            <table class="tbl" style="min-width: 520px">
              <thead><tr><th>{{ t('File') }}</th><th>{{ t('Recognised as') }}</th><th>{{ t('Period') }}</th><th>{{ t('Status') }}</th><th></th></tr></thead>
              <tbody>
                <tr v-for="d in bundle.documents" :key="d.uuid">
                  <td class="mono" style="font-size: 12.5px; overflow-wrap: anywhere">{{ d.filename }}</td>
                  <td>{{ bundleDocKind(d) }}</td>
                  <td class="num muted" style="white-space: nowrap">{{ d.period_start || d.period_end ? fmtPeriod(d.period_start, d.period_end) : '—' }}</td>
                  <td>
                    <div v-if="d.status === 'processing' && d.job" class="row" style="flex-wrap: nowrap; gap: 6px; min-width: 140px"><ProgressBar :value="d.job.progress" /><span class="muted num" style="font-size: 12px">{{ d.job.progress }}%</span></div>
                    <span v-else class="pill" :class="bundleDocState(d).cls">{{ bundleDocState(d).label }}</span>
                    <div v-if="d.status === 'failed' && d.failure_cause" class="muted" style="font-size: 12px; margin-top: 4px">{{ d.failure_cause }}</div>
                  </td>
                  <td class="r"><button v-if="!['queued', 'processing'].includes(d.status)" type="button" class="linkbtn" @click="openBundleDoc(d.uuid)">{{ t('Open') }}</button></td>
                </tr>
              </tbody>
            </table>
          </div>
          <div v-if="bundle?.skipped?.length" class="note">
            <strong>{{ tn(bundle.skipped.length, '{n} file not analysed:', '{n} files not analysed:') }}</strong>
            <span v-for="(k, i) in bundle.skipped" :key="k.filename + i"> <span class="mono">{{ k.filename }}</span> ({{ k.reason }}){{ i < bundle.skipped.length - 1 ? ';' : '' }}</span>
          </div>
          <div v-if="bundle?.status === 'failed'" class="error-box">{{ t('Processing failed:') }} {{ bundle.job?.error || '' }}</div>
          <div v-if="bundleErr" class="error-box">{{ bundleErr }}</div>
        </section>

        <!-- Loan file: what is missing -->
        <section v-if="bundleDone && bundle" class="panel" :aria-label="t('Required documents')" style="padding: 12px 16px; display: flex; flex-direction: column; gap: 8px">
          <div class="panel-head">
            <h2>{{ t('Against the bank’s required set') }}</h2>
            <span class="ctx num">{{ t('{a} of {b} present', { a: bundle.required.filter((r) => r.present).length, b: bundle.required.length }) }}</span>
          </div>
          <p v-if="!bundle.missing.length" class="plain">{{ t('Every required document is in the file.') }}</p>
          <template v-else>
            <p class="plain">{{ t('Missing from this loan file:') }}</p>
            <ul class="missing">
              <li v-for="m in bundle.missing" :key="m.key">{{ t(m.title) }}</li>
            </ul>
          </template>
          <div v-if="bundleRequest" class="muted" style="font-size: 13px">
            {{ t('Requested in the application:') }}
            <span class="num">{{ bundleRequest.amount_display }} {{ bundleRequest.amount_unit || '' }}</span><template v-if="bundleRequest.term_months"> · {{ t('{n} months', { n: bundleRequest.term_months }) }}</template>
          </div>
        </section>

        <!-- Loan file: cross-document issues -->
        <section v-if="bundleDone && bundleIssues.length" class="panel" :aria-label="t('Problems found')">
          <div class="panel-head" style="padding: 12px 16px 8px">
            <h2>{{ tn(bundleIssues.length, '{n} problem found', '{n} problems found') }}</h2>
            <span class="ctx">{{ t('Checks across all documents of the loan file') }}</span>
          </div>
          <ol class="problems">
            <li v-for="f in bundleIssues" :key="f.uuid">
              <div class="row" style="gap: 8px; align-items: baseline">
                <span class="pill" :class="severityPillClass(f.severity)">{{ f.label }}</span>
                <span class="p-what">{{ plainFor(f.rule_id, f.title).what }}</span>
              </div>
              <div class="p-todo"><strong>{{ t('What to do:') }}</strong> {{ plainFor(f.rule_id, f.title).todo }}</div>
              <div class="muted p-detail"><InlineEvidence :text="f.detail" :keys="f.evidence" :max-trailing="4" /></div>
            </li>
          </ol>
        </section>
        <section v-else-if="bundleDone" class="panel" :aria-label="t('Problems found')" style="padding: 12px 16px">
          <div class="row"><span class="pill pill-stable">{{ t('No problems found') }}</span><span>{{ t('The checks across the documents found nothing to flag.') }}</span></div>
        </section>

        <!-- Loan file: key figures -->
        <section v-if="bundleDone && bundleFigures.length" class="panel" :aria-label="t('Main figures')">
          <div class="panel-head" style="padding: 12px 16px 8px">
            <h2>{{ t('Main figures') }}</h2>
            <span class="ctx">{{ t('Click a dashed number to see it on the page') }}</span>
          </div>
          <div class="scrollbox">
            <table class="tbl" style="min-width: 460px">
              <thead><tr><th></th><th v-for="c in bundleColumns" :key="c.key" class="r">{{ c.label }}</th><th>{{ t('Source') }}</th></tr></thead>
              <tbody>
                <tr v-for="r in bundleFigures" :key="r.label">
                  <td :style="r.indent ? 'padding-left: 24px' : ''">{{ r.label }}<span v-if="r.flag" class="pill pill-attn" style="margin-left: 6px">{{ r.flag }}</span></td>
                  <td v-for="c in bundleColumns" :key="c.key" class="r">
                    <EvidenceChip v-if="r.cells[c.key]" :fact-key="r.cells[c.key]!" />
                    <span v-else class="muted">—</span>
                  </td>
                  <td class="muted" style="font-size: 12px">{{ r.source }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>

        <!-- Loan file: ratios -->
        <section v-if="bundleDone" class="panel" :aria-label="t('Ratios')" style="padding: 12px 14px 14px; display: flex; flex-direction: column; gap: 10px">
          <div class="panel-head">
            <h2>{{ t('Ratios') }}</h2>
            <span class="ctx">{{ t('Computed deterministically from the extracted figures · click a value for its formula') }}</span>
          </div>
          <div v-if="bundleRatios.length" class="ratios">
            <div v-for="r in bundleRatios" :key="r.label" class="ratio" :class="{ flag: !!r.flag }">
              <span class="eyebrow">{{ r.label }}</span>
              <span class="v num">
                <template v-if="r.fact_keys && r.fact_keys.length === 2"><EvidenceChip :fact-key="r.fact_keys[0]" /> <span class="muted" style="font-size: 13px; font-weight: 400">→</span> <EvidenceChip :fact-key="r.fact_keys[1]" /></template>
                <EvidenceChip v-else-if="r.fact_key" :fact-key="r.fact_key" :text="r.value_display" />
                <template v-else>{{ r.value_display }}</template>
              </span>
              <span class="muted" style="font-size: 12px"><InlineEvidence :text="r.note" /><template v-if="r.period"> · {{ r.period }}</template></span>
              <span v-if="ratioHelp(r.label)" class="muted" style="font-size: 12px; line-height: 1.4">{{ ratioHelp(r.label) }}</span>
            </div>
          </div>
          <div v-else class="muted">{{ t('n/a — upload Форма 1 (balance sheet) and Форма 2 (income statement) for the ratios.') }}</div>
        </section>

        <!-- Loan file: written summary -->
        <section v-if="bundleDone" class="panel" :aria-label="t('Summary')" style="padding: 12px 16px 14px; display: flex; flex-direction: column; gap: 8px">
          <div class="panel-head">
            <h2>{{ t('Summary') }}</h2>
            <span class="ctx">{{ bundleNarrative?.mode === 'llm' ? t('AI draft · every number checked against the documents by the citation verifier') : t('Template summary · built from the same figures and issues') }}</span>
          </div>
          <div v-if="bundleAiOff" class="note" role="status">{{ bundleAiOff }}</div>
          <NarrativeText v-if="bundleNarrative" class="plain" :markdown="bundleNarrative.markdown" />
          <div v-else-if="!bundleAiOff" class="muted">{{ t('No summary passed the citation verifier; the issues, figures and ratios above do not depend on it.') }}</div>
        </section>

        <details v-if="bundleDone && bundle?.review?.findings?.length" class="panel more">
          <summary>
            <span>{{ t('Show every check that did not pass') }}</span>
            <span class="muted num" style="font-size: 12px">{{ t('{n} findings with rule ids and evidence', { n: bundle.review.findings.length }) }}</span>
          </summary>
          <div class="more-body">
            <FindingRow v-for="f in bundle.review.findings" :key="f.uuid" :finding="f" />
          </div>
        </details>

        <div v-if="bundleDone" class="footer-line">
          {{ t('Every value above links to its page. Nothing is shown that was not read from the files; the system does not score, approve or reject. Public uploads are deleted after 24 hours.') }}
        </div>

        <!-- File + progress -->
        <section v-if="uuid" class="panel" :aria-label="t('Processing')" style="padding: 14px 16px; display: flex; flex-direction: column; gap: 10px">
          <div class="row" style="justify-content: space-between">
            <div class="row" style="min-width: 0">
              <span class="ficon">{{ (doc?.filename || file?.name || '').split('.').pop()?.toUpperCase().slice(0, 4) }}</span>
              <div style="min-width: 0">
                <div class="mono" style="font-size: 13px; overflow-wrap: anywhere">{{ doc?.filename || file?.name || t('Document') }}</div>
                <div class="muted" style="font-size: 12px">
                  <template v-if="doc && isSheet">{{ fmtBytes(doc.size_bytes) }} · {{ t('spreadsheet') }}</template>
                  <template v-else-if="doc">{{ fmtBytes(doc.size_bytes) }}<template v-if="doc.page_count"> · {{ tn(doc.page_count, '{n} page', '{n} pages') }}</template></template>
                  <template v-else-if="file">{{ fmtBytes(file.size) }}</template>
                </div>
              </div>
            </div>
            <span v-if="!running && totalMs != null" class="muted num" style="font-size: 12px">{{ t('Done in {s} s', { s: (totalMs / 1000).toFixed(1) }) }}</span>
          </div>
          <template v-if="running">
            <div class="now" aria-live="polite">
              <span class="pill pill-info">{{ t('Working') }}</span>
              <span>{{ (stageLabel(job?.status === 'queued' ? 'queued' : job?.stage) || t('Starting')) + '…' }}</span>
            </div>
            <div class="row" style="flex-wrap: nowrap">
              <ProgressBar :value="job?.progress ?? 0" />
              <span class="muted num" style="font-size: 12px; white-space: nowrap">{{ job?.progress ?? 0 }}% · {{ elapsed }} s</span>
            </div>
            <div v-if="doneStages.length" class="muted" style="font-size: 12px">
              {{ t('Done so far:') }} {{ doneStages.map((s) => stageLabel(s.name)).join(' · ') }}
            </div>
            <div class="muted" style="font-size: 12px">{{ t('Most documents take under a minute. You can keep this page open; the result appears here.') }}</div>
          </template>
          <div v-if="job?.status === 'failed' && job.error" class="error-box">{{ t('Processing failed:') }} {{ job.error }}</div>
          <div v-if="pollErr" class="error-box">{{ pollErr }}</div>
          <div v-if="result?.partial || doc?.summary?.partial" class="note"><strong>{{ t('Partial result.') }}</strong> {{ t('Processing stopped at the time or page budget for public uploads; everything below is what was completed.') }}</div>
        </section>

        <!-- 1. What this is -->
        <section v-if="finished && doc" class="panel" :aria-label="t('What this document is')" style="padding: 16px 18px; display: flex; flex-direction: column; gap: 10px">
          <div class="eyebrow">{{ t('What this document is') }}</div>
          <div class="doc-title">{{ doc.status === 'failed' && doc.doc_type === 'unknown' ? t('Could not analyze') : docTypeLabel(doc.doc_type) }}</div>
          <p v-if="typeExplain" class="plain">{{ typeExplain }}</p>
          <p v-if="recognisedOnly && doc.status !== 'failed'" class="plain muted">{{ t('Converza recognises this document and counts it toward the bank’s required set; its figures are not read into the checks yet. What could be read from it is shown below.') }}</p>
          <ul class="facts-line">
            <li v-if="applicantName"><span class="muted">{{ t('Company') }}</span> {{ applicantName }}</li>
            <li v-if="docStir"><span class="muted">{{ t('Taxpayer ID (STIR)') }}</span> <span class="num">{{ docStir }}</span></li>
            <li v-if="doc.period_start || doc.period_end"><span class="muted">{{ t('Period') }}</span> <span class="num">{{ fmtPeriod(doc.period_start, doc.period_end) }}</span></li>
            <li v-if="doc.language"><span class="muted">{{ t('Written in') }}</span> {{ langLabel(doc.language) }}</li>
          </ul>
          <p v-if="plainStatus" class="status-line">
            <span class="pill" :class="docStatusPill(doc.status).cls">{{ docStatusPill(doc.status).label }}</span>
            <span>{{ plainStatus }}<template v-if="lowConfCount && doc.status !== 'failed'"> {{ tn(lowConfCount, '{n} value was read with low certainty.', '{n} values were read with low certainty.') }}</template></span>
          </p>
          <div v-if="doc.status === 'failed'" class="stack" style="gap: 8px">
            <p>{{ doc.failure_cause || t('No cause was recorded.') }}</p>
            <div class="row">
              <button type="button" class="btn btn-sm btn-primary" @click="reset">{{ t('Re-upload a clearer file') }}</button>
              <button type="button" class="btn btn-sm" @click="reset(); trySample('/samples/form2_scan_150dpi.pdf')">{{ t('Try a sample scan') }}</button>
            </div>
            <p class="muted" style="font-size: 12px">{{ t('What could still be read from it is listed below.') }}</p>
          </div>
          <div v-if="result?.description?.text && result.description.mode === 'llm'" class="stack" style="gap: 4px; border-top: 1px solid var(--border-row); padding-top: 10px">
            <div class="eyebrow">{{ t('In short') }}</div>
            <NarrativeText class="plain" :markdown="result.description.text" />
            <div class="muted" style="font-size: 12px">{{ t('Written by the language model from the values below; every number in it was checked against them.') }}</div>
          </div>
          <div v-else-if="docAiOff" class="note" role="status" style="margin-top: 4px">{{ docAiOff }}</div>
        </section>

        <!-- 2. Main figures -->
        <section v-if="finished && keyFigures.length" class="panel" :aria-label="t('Main figures')">
          <div class="panel-head" style="padding: 12px 16px 4px">
            <h2>{{ t('Main figures') }}</h2>
            <span class="ctx">{{ t('Click a dashed number to see it on the page') }}</span>
          </div>
          <div class="figstrip keyfigs">
            <div v-for="k in keyFigures" :key="k.cur.key" class="fig" :class="{ flagged: k.uncertain }">
              <div class="kf-label">{{ k.label }}</div>
              <div class="big num"><EvidenceChip :fact-key="k.cur.key" /><span v-if="k.unit" class="unit">{{ k.unit }}</span></div>
              <div class="kf-sub muted">
                {{ k.explain }}<template v-if="k.cur.period_label && (doc?.doc_type === 'form1' || doc?.doc_type === 'form2' || doc?.doc_type === 'bank_statement')"> · {{ periodText(k.cur.period_label) }}</template>
              </div>
              <div v-if="k.prev" class="kf-sub muted">{{ t('Previous period ({p}):', { p: periodText(k.prev.period_label) }) }} <EvidenceChip :fact-key="k.prev.key" /></div>
              <div v-if="k.uncertain" class="kf-sub" style="color: var(--watch-fg)">{{ t('Uncertain reading; check it on the page.') }}</div>
            </div>
          </div>
        </section>

        <!-- 3. Problems -->
        <section v-if="finished && result?.findings?.length" class="panel" :aria-label="t('Problems found')">
          <div class="panel-head" style="padding: 12px 16px 8px">
            <h2>{{ tn(result.findings.length, '{n} problem found', '{n} problems found') }}</h2>
            <span class="ctx">{{ t('Arithmetic checks on this document alone') }}</span>
          </div>
          <ol class="problems">
            <li v-for="f in result.findings" :key="f.uuid">
              <div class="row" style="gap: 8px; align-items: baseline">
                <span class="pill" :class="severityPillClass(f.severity)">{{ f.label }}</span>
                <span class="p-what">{{ plainFor(f.rule_id, f.title).what }}</span>
              </div>
              <div class="p-todo"><strong>{{ t('What to do:') }}</strong> {{ plainFor(f.rule_id, f.title).todo }}</div>
              <div class="muted p-detail"><InlineEvidence :text="f.detail" :keys="f.evidence" :max-trailing="3" /></div>
            </li>
          </ol>
        </section>
        <section v-else-if="finished && checksRan && doc && RECOGNISED.includes(doc.doc_type)" class="panel" :aria-label="t('Problems found')" style="padding: 12px 16px">
          <div class="row"><span class="pill pill-stable">{{ t('No problems found') }}</span><span>{{ t('The arithmetic checks on this document found nothing to flag.') }}</span></div>
        </section>

        <!-- Statement: where the money went -->
        <section v-if="finished && result?.transactions_preview && result.transactions_preview.count" class="panel" :aria-label="t('Where the money went')">
          <div class="panel-head" style="padding: 12px 14px 8px">
            <h2>{{ t('Where the money went') }}</h2>
            <span class="ctx num">{{ t('{n} transactions sorted into categories', { n: result.transactions_preview.count }) }}</span>
          </div>
          <div class="scrollbox">
            <table class="tbl" style="min-width: 420px">
              <thead><tr><th>{{ t('Category') }}</th><th class="r">{{ t('Money in, mln UZS') }}</th><th class="r">{{ t('Money out, mln UZS') }}</th></tr></thead>
              <tbody>
                <tr v-for="c in result.transactions_preview.by_category" :key="c.category">
                  <td>{{ categoryLabel(c.category) }}</td>
                  <td class="r num">{{ trueMinus(c.inflow_display) || '—' }}</td>
                  <td class="r num">{{ trueMinus(c.outflow_display) || '—' }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>

        <!-- Readable (unrecognised or failed documents) -->
        <section v-if="result?.readable && doc && (!RECOGNISED.includes(doc.doc_type) || doc.status === 'failed')" class="panel" :aria-label="t('What I could read')" style="padding: 12px 14px 14px; display: flex; flex-direction: column; gap: 10px">
          <div class="panel-head">
            <h2>{{ t('What I could read') }}</h2>
            <span class="ctx">{{ t('Not interpreted — shown as it appears in the file') }}</span>
          </div>
          <div class="kv">
            <div><div class="eyebrow">{{ t('Pages read') }}</div><div class="num">{{ result.readable.pages }}</div></div>
            <div><div class="eyebrow">{{ t('Language') }}</div><div>{{ langLabel(result.readable.language) }}</div></div>
            <div v-if="result.readable.ocr_mean_conf != null"><div class="eyebrow">{{ t('OCR mean confidence') }}</div><div class="num">{{ Math.round(result.readable.ocr_mean_conf > 1 ? result.readable.ocr_mean_conf : result.readable.ocr_mean_conf * 100) }}%</div></div>
            <div v-if="result.readable.stirs.length"><div class="eyebrow">{{ t('STIR found') }}</div><div class="mono">{{ result.readable.stirs.join(', ') }}</div></div>
            <div v-if="result.readable.dates.length"><div class="eyebrow">{{ t('Dates found') }}</div><div class="mono" style="font-size: 12px">{{ result.readable.dates.slice(0, 6).join(', ') }}</div></div>
          </div>
          <div v-if="readableKeys.length" class="stack" style="gap: 6px">
            <div class="eyebrow">{{ t('Numbers on the page ({n})', { n: readableKeys.length }) }}</div>
            <div class="row" style="gap: 6px">
              <EvidenceChip v-for="k in readableKeys" :key="k" :fact-key="k" class="mono" />
            </div>
          </div>
          <div v-if="result.readable.text_excerpt" class="stack" style="gap: 6px">
            <button type="button" class="linkbtn" style="align-self: flex-start" @click="showExcerpt = !showExcerpt">{{ showExcerpt ? t('Hide text excerpt') : t('Show text excerpt') }}</button>
            <div v-if="showExcerpt" class="passage" style="max-height: 280px; overflow: auto">{{ result.readable.text_excerpt }}</div>
          </div>
        </section>

        <!-- 4. Full detail, collapsed -->
        <details v-if="finished && (allValuesCount || stageRows.length)" class="panel more">
          <summary>
            <span>{{ t('Show all extracted lines') }}</span>
            <span class="muted num" style="font-size: 12px">{{ t('{n} values, line codes, certainty and processing steps', { n: allValuesCount }) }}</span>
          </summary>

          <div class="more-body">
            <!-- Technical recognition -->
            <div class="kv" style="padding: 12px 14px">
              <div><div class="eyebrow">{{ t('Recognised as') }}</div><div><span class="pill" :class="typePill.cls">{{ typePill.label }}</span></div></div>
              <div v-if="doc?.type_confidence"><div class="eyebrow">{{ t('Recognition score') }}</div><div class="num">{{ Math.round(doc.type_confidence * (doc.type_confidence > 1 ? 1 : 100)) }}%</div></div>
              <div><div class="eyebrow">{{ t('Read with') }}</div><div>{{ isSheet ? t('Spreadsheet cells') : doc?.text_layer ? t('PDF text layer') : t('OCR (Tesseract)') }}</div></div>
              <div v-if="!isSheet"><div class="eyebrow">{{ t('Pages') }}</div><div class="num">{{ doc?.page_count || '—' }}</div></div>
            </div>
            <p v-if="doc?.type_reason" class="muted" style="padding: 0 14px 12px; font-size: 12.5px">{{ doc.type_reason }}</p>

            <!-- Extracted lines -->
            <template v-if="lineRows.length">
              <div class="panel-head sub">
                <h2>{{ t('Extracted from {file}', { file: doc?.filename || '' }) }}</h2>
                <span class="ctx">{{ t('Values as printed · click a value to see it on the page') }}</span>
              </div>
              <div class="scrollbox">
                <table class="tbl" style="min-width: 520px">
                  <thead>
                    <tr>
                      <th>{{ t('Line') }}</th>
                      <th>{{ t('Interpreted as') }}</th>
                      <th v-for="p in periods" :key="p" class="r">{{ periodHead(p) }}</th>
                      <th>{{ t('Confidence') }}</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="r in lineRows" :key="r.code">
                      <td class="mono">{{ r.code }}</td>
                      <td>{{ r.label }}</td>
                      <td v-for="p in periods" :key="p" class="r">
                        <EvidenceChip v-if="r.cells[p]" :fact-key="r.cells[p].key" :text="r.cells[p].printed || r.cells[p].display" class="mono" />
                        <span v-else class="muted" :title="t('Cell blank in the document')">—</span>
                      </td>
                      <td>
                        <span v-if="confPill(r.conf)" class="pill" :class="confPill(r.conf)!.cls">{{ confPill(r.conf)!.label }}</span>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </template>

            <!-- Recurring payments -->
            <template v-if="result?.transactions_preview?.recurring?.length">
              <div class="panel-head sub">
                <h2>{{ t('Recurring payments detected') }}</h2>
                <span class="ctx">{{ t('Same counterparty, similar amount, same day of month') }}</span>
              </div>
              <div class="scrollbox">
                <table class="tbl" style="min-width: 480px">
                  <thead><tr><th>{{ t('Payment') }}</th><th class="r">{{ t('Times') }}</th><th class="r">{{ t('Amount, mln') }}</th><th class="r">{{ t('Day') }}</th><th>{{ t('Other sources') }}</th></tr></thead>
                  <tbody>
                    <tr v-for="g in result.transactions_preview.recurring" :key="g.group">
                      <td>{{ g.label }}</td>
                      <td class="r num">{{ g.count }}</td>
                      <td class="r num">
                        <template v-if="g.amount_display">{{ g.amount_display }}</template>
                        <EvidenceChip v-else-if="g.evidence[0]" :fact-key="g.evidence[0]" />
                      </td>
                      <td class="r num">{{ g.day_of_month ?? '—' }}</td>
                      <td><span class="row" style="gap: 4px"><EvidenceChip v-for="k in g.evidence.slice(g.amount_display ? 0 : 1)" :key="k" :fact-key="k" /></span></td>
                    </tr>
                  </tbody>
                </table>
              </div>
              <div class="muted" style="font-size: 12px; padding: 8px 14px 0">{{ t('Rows per category') }}: <span v-for="(c, i) in result.transactions_preview.by_category" :key="c.category" class="num">{{ i ? ' · ' : '' }}{{ categoryLabel(c.category) }} {{ c.count }}</span></div>
            </template>

            <!-- Other values -->
            <template v-if="otherFacts.length">
              <div class="panel-head sub">
                <h2>{{ t('Other values found') }}</h2>
                <span class="ctx">{{ t('Each links to the rows or page it came from') }}</span>
              </div>
              <div class="scrollbox">
                <table class="tbl">
                  <thead><tr><th>{{ t('Value') }}</th><th>{{ t('Period') }}</th><th class="r">{{ t('Amount') }}</th><th>{{ t('How') }}</th></tr></thead>
                  <tbody>
                    <tr v-for="f in otherShown" :key="f.key">
                      <td>{{ f.label }}</td>
                      <td class="muted">{{ f.period_label || '—' }}</td>
                      <td class="r"><EvidenceChip :fact-key="f.key" /> <span class="muted">{{ f.display_unit }}</span></td>
                      <td class="muted" style="font-size: 12px">{{ HOW[f.kind] ? t(HOW[f.kind]) : f.kind }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
              <div v-if="otherFacts.length > OTHER_SHOWN" style="padding: 10px 14px">
                <button type="button" class="linkbtn" @click="showAllOther = !showAllOther">{{ showAllOther ? t('Show the first {n}', { n: OTHER_SHOWN }) : t('Show all {n} values', { n: otherFacts.length }) }}</button>
              </div>
            </template>

            <!-- Unmapped -->
            <template v-if="result?.unmapped?.length">
              <div class="panel-head sub">
                <h2>{{ t('Lines not mapped to a statutory code') }}</h2>
                <span class="ctx">{{ t('Shown as printed; not used in any check') }}</span>
              </div>
              <div class="scrollbox">
                <table class="tbl">
                  <thead><tr><th>{{ t('Page') }}</th><th>{{ t('Text') }}</th><th class="r">{{ t('Value as printed') }}</th></tr></thead>
                  <tbody>
                    <tr v-for="(u, i) in result.unmapped" :key="i">
                      <td class="num">{{ u.page_n }}</td>
                      <td>{{ u.text }}</td>
                      <td class="r mono">{{ u.value_printed || '—' }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </template>

            <!-- Rules -->
            <template v-if="result?.findings?.length">
              <div class="panel-head sub">
                <h2>{{ t('Checks that did not pass') }}</h2>
                <span class="ctx">{{ t('Reconciliation rules run on this document alone') }}</span>
              </div>
              <FindingRow v-for="f in result.findings" :key="f.uuid" :finding="f" />
            </template>

            <!-- Pipeline -->
            <template v-if="stageRows.length">
              <div class="panel-head sub">
                <h2>{{ t('Processing steps') }}</h2>
                <span v-if="totalMs != null" class="ctx num">{{ t('Processed in {ms} ms on the server (measured, this upload).', { ms: totalMs }) }}</span>
              </div>
              <ol class="stages" :aria-label="t('Pipeline stages run')" style="padding: 0 14px 14px">
                <li v-for="s in stageRows" :key="s.name" :class="{ cur: s.current }">{{ stageLabel(s.name) }}<span v-if="s.ms != null" class="num"> · {{ s.ms }} ms</span></li>
              </ol>
            </template>
          </div>
        </details>

        <div v-if="doc && !running" class="footer-line">
          {{ t('Every value above links to its page. Nothing is shown that was not read from the file; the system does not score, approve or reject.') }}
        </div>
      </div>

      <div class="ev-col">
        <EvidencePane :actions="false" :empty-text="t('Upload a document, then click any dashed value to see the page and the cell it was read from.')" />
      </div>
    </div>
  </div>
</template>

<style scoped>
.now { display: flex; align-items: center; gap: 8px; font-size: 14px; color: var(--ink); }
.doc-title { font-size: 18px; font-weight: 600; letter-spacing: -.01em; }
.plain { font-size: 14px; line-height: 1.5; color: var(--ink-2); max-width: 680px; }
.facts-line { list-style: none; margin: 0; padding: 0; display: flex; flex-wrap: wrap; gap: 6px 20px; font-size: 13px; }
.facts-line .muted { margin-right: 4px; }
.status-line { display: flex; gap: 8px; align-items: baseline; flex-wrap: wrap; font-size: 13.5px; }
.keyfigs .fig { display: flex; flex-direction: column; gap: 4px; padding: 12px 16px 14px; border-top: 1px solid var(--border-row); }
.kf-label { font-size: 13px; font-weight: 500; color: var(--ink-2); }
.kf-sub { font-size: 12px; line-height: 1.4; }
.problems { list-style: none; margin: 0; padding: 0; }
.problems li { padding: 12px 16px; border-top: 1px solid var(--border-row); display: flex; flex-direction: column; gap: 6px; }
.p-what { font-weight: 500; font-size: 14px; flex: 1 1 260px; }
.p-todo { font-size: 13.5px; }
.p-detail { font-size: 12.5px; }
.more > summary { cursor: pointer; padding: 12px 16px; display: flex; flex-wrap: wrap; gap: 4px 12px; align-items: baseline; font-weight: 600; font-size: 14px; list-style: none; }
.more > summary::-webkit-details-marker { display: none; }
.more > summary::before { content: '▸'; color: var(--ink-muted); width: 12px; display: inline-block; }
.more[open] > summary::before { content: '▾'; }
.more > summary:hover { background: var(--surface-2); }
.more-body { border-top: 1px solid var(--border-row); }
.panel-head.sub { padding: 14px 14px 8px; border-top: 1px solid var(--border-row); }
.stages { margin: 0; padding: 0; list-style: none; display: flex; flex-wrap: wrap; gap: 6px 14px; font-size: 12px; color: var(--ink-muted); }
.stages li::before { content: '✓ '; color: var(--stable-fg); }
.stages li.cur { color: var(--ink); }
.stages li.cur::before { content: '› '; color: var(--accent); }
.works { margin: 0; padding-left: 18px; font-size: 12.5px; line-height: 1.5; display: flex; flex-direction: column; gap: 2px; }
.missing { margin: 0; padding-left: 18px; font-size: 14px; line-height: 1.6; }
.ratios { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(180px, 100%), 1fr)); gap: 10px; }
</style>
