<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, errMessage } from '@/api/client'
import type { AnalyseResult, Fact } from '@/api/types'
import {
  categoryLabel, confPill, docStatusPill, docTypeLabel, fmtBytes, fmtPeriod, langLabel, stageLabel, trueMinus,
} from '@/api/format'
import { useEvidence } from '@/stores/evidence'
import Dropzone from '@/components/ui/Dropzone.vue'
import ProgressBar from '@/components/ui/ProgressBar.vue'
import EvidencePane from '@/components/evidence/EvidencePane.vue'
import EvidenceChip from '@/components/evidence/EvidenceChip.vue'
import FindingRow from '@/components/evidence/FindingRow.vue'
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

async function upload(files: File[]) {
  const f = files[0]
  if (!f) return
  uploadErr.value = ''
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
    const first = r.facts.find((f) => f.page_n != null) || r.facts[0]
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
  uuid.value = null
  result.value = null
  file.value = null
  seenStages.value = []
  ev.clear()
  router.replace({ query: {} })
}

onMounted(() => {
  if (uuid.value) {
    startedAt.value = Date.now()
    poll()
  }
})
onBeforeUnmount(stopPolling)

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
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h1>{{ t('Analyse a document') }}</h1>
        <p class="meta" style="max-width: 760px">
          {{ t('Upload a statutory form (Форма 1 or Форма 2), a bank statement, a loan application or a photo of a document. Converza recognises it, reads it and shows only what it can trace back to the page. Answers arrive in under a minute.') }}
        </p>
      </div>
      <button v-if="uuid" type="button" class="btn" @click="reset">{{ t('Analyse another document') }}</button>
    </div>

    <div class="twopane">
      <div class="main-col">
        <!-- Upload -->
        <section v-if="!uuid" class="panel" :aria-label="t('Upload')" style="padding: 16px; display: flex; flex-direction: column; gap: 14px">
          <Dropzone :disabled="uploading" :title="uploading ? t('Uploading…') : t('Drop a document here')" :button="t('Choose file')" :hint="t('PDF · XLSX · JPG · PNG · up to 20 MB')" @files="upload" />
          <div v-if="uploadErr" class="error-box">{{ uploadErr }}</div>
          <div class="muted" style="font-size: 12px">
            {{ t('Recognised: balance sheet (Форма 1), income statement (Форма 2), bank statement (XLSX), loan application. Any other file still gets an honest answer: what it is not, and what could be read from it. Public uploads are deleted after 24 hours; names are not sent to the language model.') }}
          </div>
        </section>

        <section v-if="!uuid" class="panel" :aria-label="t('Sample documents')">
          <div class="panel-head" style="padding: 12px 14px 8px">
            <h2>{{ t('No document at hand? Use a sample') }}</h2>
            <span class="ctx">{{ t('Synthetic, generated for this demo') }}</span>
          </div>
          <div class="scrollbox">
            <table class="tbl">
              <tbody>
                <tr v-for="s in SAMPLES" :key="s.href">
                  <td style="width: 1%; white-space: nowrap"><a :href="s.href" download>{{ t(s.label) }}</a></td>
                  <td class="muted">{{ t(s.note) }} · {{ t('ZIP — unzip, then upload one file at a time') }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <div class="row" style="padding: 10px 14px 14px">
            <a v-for="s in SINGLES" :key="s.href" :href="s.href" download class="chip round">{{ t(s.label) }}</a>
          </div>
        </section>

        <!-- Progress -->
        <section v-if="uuid" class="panel" :aria-label="t('Processing')" style="padding: 14px 16px; display: flex; flex-direction: column; gap: 10px">
          <div class="row" style="justify-content: space-between">
            <div class="row" style="min-width: 0">
              <span class="ficon">{{ (doc?.filename || file?.name || '').split('.').pop()?.toUpperCase().slice(0, 4) }}</span>
              <div style="min-width: 0">
                <div class="mono" style="font-size: 13px; overflow-wrap: anywhere">{{ doc?.filename || file?.name || t('Document') }}</div>
                <div class="muted" style="font-size: 12px">
                  <template v-if="doc && isSheet">{{ fmtBytes(doc.size_bytes) }} · {{ t('spreadsheet') }}</template>
                  <template v-else-if="doc">{{ fmtBytes(doc.size_bytes) }} · {{ tn(doc.page_count || 0, '{n} page', '{n} pages') }} · {{ doc.text_layer ? t('text layer') : t('scanned / image — OCR') }}</template>
                  <template v-else-if="file">{{ fmtBytes(file.size) }}</template>
                </div>
              </div>
            </div>
            <span v-if="doc" class="pill" :class="docStatusPill(doc.status).cls">{{ docStatusPill(doc.status).label }}</span>
            <span v-else class="pill pill-info">{{ t('Uploaded') }}</span>
          </div>
          <template v-if="running">
            <div class="row" style="flex-wrap: nowrap">
              <ProgressBar :value="job?.progress ?? 0" />
              <span class="muted num" style="font-size: 12px; white-space: nowrap">{{ job?.progress ?? 0 }}% · {{ elapsed }} s</span>
            </div>
            <div class="muted" style="font-size: 12px">{{ stageLabel(job?.status === 'queued' ? 'queued' : job?.stage) || t('Starting…') }}</div>
          </template>
          <ol v-if="stageRows.length" class="stages" :aria-label="t('Pipeline stages run')">
            <li v-for="s in stageRows" :key="s.name" :class="{ cur: s.current }">{{ stageLabel(s.name) }}<span v-if="s.ms != null" class="num"> · {{ s.ms }} ms</span></li>
          </ol>
          <div v-if="!running && totalMs != null" class="muted num" style="font-size: 12px">{{ t('Processed in {ms} ms on the server (measured, this upload).', { ms: totalMs }) }}</div>
          <div v-if="job?.status === 'failed' && job.error" class="error-box">{{ t('Processing failed:') }} {{ job.error }}</div>
          <div v-if="pollErr" class="error-box">{{ pollErr }}</div>
          <div v-if="result?.partial || doc?.summary?.partial" class="note"><strong>{{ t('Partial result.') }}</strong> {{ t('Processing stopped at the time or page budget for public uploads; everything below is what was completed.') }}</div>
        </section>

        <!-- Recognition -->
        <section v-if="doc && doc.status !== 'queued' && doc.status !== 'processing'" class="panel" :aria-label="t('What this document is')" style="padding: 14px 16px; display: flex; flex-direction: column; gap: 10px">
          <div class="row">
            <span class="eyebrow">{{ t('Recognised as') }}</span>
            <span class="pill" :class="typePill.cls">{{ typePill.label }}</span>
            <span v-if="doc.type_confidence" class="muted num" style="font-size: 12px">{{ t('score {p}%', { p: Math.round(doc.type_confidence * (doc.type_confidence > 1 ? 1 : 100)) }) }}</span>
          </div>
          <p v-if="doc.type_reason">{{ doc.type_reason }}</p>
          <div class="kv">
            <div><div class="eyebrow">{{ t('Language') }}</div><div>{{ langLabel(doc.language) }}</div></div>
            <div><div class="eyebrow">{{ t('Period') }}</div><div class="num">{{ fmtPeriod(doc.period_start, doc.period_end) }}</div></div>
            <div v-if="!isSheet"><div class="eyebrow">{{ t('Pages') }}</div><div class="num">{{ doc.page_count || '—' }}</div></div>
            <div><div class="eyebrow">{{ t('Read with') }}</div><div>{{ isSheet ? t('Spreadsheet cells') : doc.text_layer ? t('PDF text layer') : t('OCR (Tesseract)') }}</div></div>
          </div>
          <div v-if="doc.status === 'failed'" class="stack" style="gap: 8px">
            <div class="row"><span class="pill pill-attn">{{ t('Could not analyze') }}</span></div>
            <p>{{ doc.failure_cause || t('No cause was recorded.') }}</p>
            <div class="row">
              <button type="button" class="btn btn-sm btn-primary" @click="reset">{{ t('Re-upload a clearer file') }}</button>
              <a class="btn btn-sm" href="/samples/form2_scan_150dpi.pdf" download>{{ t('Try a sample scan') }}</a>
            </div>
            <p class="muted" style="font-size: 12px">{{ t('What could still be read from it is listed below.') }}</p>
          </div>
          <div v-if="result?.description?.text && result.description.mode === 'llm'" class="stack" style="gap: 4px">
            <div class="eyebrow">{{ t('Summary · written by the language model from the values below; every number was checked against them') }}</div>
            <p>{{ result.description.text }}</p>
          </div>
        </section>

        <!-- Findings -->
        <section v-if="result?.findings?.length" class="panel" :aria-label="t('Checks that did not pass')">
          <div class="panel-head" style="padding: 12px 14px 8px">
            <h2>{{ t('Checks that did not pass') }}</h2>
            <span class="ctx">{{ t('Reconciliation rules run on this document alone') }}</span>
          </div>
          <FindingRow v-for="f in result.findings" :key="f.uuid" :finding="f" />
        </section>

        <!-- Extracted lines -->
        <section v-if="lineRows.length" class="panel" :aria-label="t('Extracted lines')">
          <div class="panel-head" style="padding: 12px 14px 8px">
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
        </section>

        <!-- Statement -->
        <section v-if="result?.transactions_preview && result.transactions_preview.count" class="panel" :aria-label="t('Where the money went')">
          <div class="panel-head" style="padding: 12px 14px 8px">
            <h2>{{ t('Where the money went') }}</h2>
            <span class="ctx num">{{ t('{n} transactions categorised', { n: result.transactions_preview.count }) }}</span>
          </div>
          <div class="scrollbox">
            <table class="tbl" style="min-width: 480px">
              <thead><tr><th>{{ t('Category') }}</th><th class="r">{{ t('Rows') }}</th><th class="r">{{ t('In, mln UZS') }}</th><th class="r">{{ t('Out, mln UZS') }}</th></tr></thead>
              <tbody>
                <tr v-for="c in result.transactions_preview.by_category" :key="c.category">
                  <td>{{ categoryLabel(c.category) }}</td>
                  <td class="r num">{{ c.count }}</td>
                  <td class="r num">{{ trueMinus(c.inflow_display) || '—' }}</td>
                  <td class="r num">{{ trueMinus(c.outflow_display) || '—' }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <template v-if="result.transactions_preview.recurring.length">
            <div class="panel-head" style="padding: 14px 14px 8px; border-top: 1px solid var(--border-row)">
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
          </template>
        </section>

        <section v-if="otherFacts.length" class="panel" :aria-label="t('Other values found')">
          <div class="panel-head" style="padding: 12px 14px 8px">
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
          <div v-if="otherFacts.length > OTHER_SHOWN" style="padding: 10px 14px; border-top: 1px solid var(--border-row)">
            <button type="button" class="linkbtn" @click="showAllOther = !showAllOther">{{ showAllOther ? t('Show the first {n}', { n: OTHER_SHOWN }) : t('Show all {n} values', { n: otherFacts.length }) }}</button>
          </div>
        </section>

        <!-- Unmapped -->
        <section v-if="result?.unmapped?.length" class="panel" :aria-label="t('Lines not mapped to a statutory code')">
          <div class="panel-head" style="padding: 12px 14px 8px">
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
        </section>

        <!-- Readable -->
        <section v-if="result?.readable && doc && (!['form1', 'form2', 'bank_statement', 'loan_application'].includes(doc.doc_type) || doc.status === 'failed')" class="panel" :aria-label="t('What I could read')" style="padding: 12px 14px 14px; display: flex; flex-direction: column; gap: 10px">
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
.stages { margin: 0; padding: 0; list-style: none; display: flex; flex-wrap: wrap; gap: 6px 14px; font-size: 12px; color: var(--ink-muted); }
.stages li::before { content: '✓ '; color: var(--stable-fg); }
.stages li.cur { color: var(--ink); }
.stages li.cur::before { content: '› '; color: var(--accent); }
</style>
