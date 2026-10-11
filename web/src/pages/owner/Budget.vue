<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { api, errMessage } from '@/api/client'
import type { DocumentOut } from '@/api/types'
import { fmtBytes, fmtDateTime, ownerDocTypeLabel, ownerDocStatus } from '@/api/format'
import { useEvidence } from '@/stores/evidence'
import Dropzone from '@/components/ui/Dropzone.vue'
import EvidencePane from '@/components/evidence/EvidencePane.vue'
import EvidenceChip from '@/components/evidence/EvidenceChip.vue'
import InlineEvidence from '@/components/evidence/InlineEvidence'
import BarGroupChart from '@/components/charts/BarGroupChart.vue'
import { t } from '@/i18n'

interface Ref { fact_key: string; label: string; document_uuid: string | null; filename: string | null; page_n: number | null }
interface CatRow { category: string; label: string; planned_spending: number | null; actual_spending: number | null; difference: number | null; fact_key: string | null }
interface MonthRow {
  month: string; label: string; source: 'statement' | 'cashflow' | null
  planned_income: number | null; planned_spending: number | null
  actual_income: number | null; actual_spending: number | null
  income_difference: number | null; spending_difference: number | null; net_actual: number | null
  income_ref: Ref | null; spending_ref: Ref | null; categories: CatRow[]
}
interface AdviceItem { id: string; severity: 'attention' | 'watch' | 'info'; title: string; text: string; rule_text: string; explained: boolean; fact_keys: string[]; sources: Ref[] }

const ev = useEvidence()
const months = ref<MonthRow[]>([])
const categories = ref<{ id: string; label: string }[]>([])
const files = ref<DocumentOut[]>([])
const advice = ref<AdviceItem[]>([])
const adviceMode = ref<string | null>(null)
const adviceAt = ref<string | null>(null)
const loading = ref(true)
const err = ref('')
const upErr = ref('')
const uploading = ref(0)
const saving = ref(false)
const saveMsg = ref('')
const running = ref(false)
const adviceErr = ref('')
const view = ref<'spending' | 'income'>('spending')
const newMonth = ref('')
// plan editor, in mln UZS
const draft = ref<Record<string, { income: string; spending: string; cats: Record<string, string> }>>({})
const catMonth = ref('')
let timer: ReturnType<typeof setTimeout> | null = null

const MLN = 1_000_000
function mln(v: number | null | undefined): string {
  if (v == null) return '—'
  return (v / MLN).toLocaleString('en-US', { minimumFractionDigits: 1, maximumFractionDigits: 1 }).replace(/,/g, ' ')
}
function signed(v: number | null | undefined): string {
  if (v == null) return '—'
  return (v > 0 ? '+' : v < 0 ? '−' : '') + mln(Math.abs(v))
}
function toInput(v: number | null): string {
  return v == null ? '' : String(Math.round((v / MLN) * 10) / 10)
}
function parseInput(s: string): number | null {
  const x = parseFloat(String(s ?? '').replace(/\s/g, '').replace(',', '.'))
  return Number.isFinite(x) && x >= 0 ? Math.round(x * MLN) : null
}

function fillDraft() {
  const d: typeof draft.value = {}
  for (const m of months.value) {
    const cats: Record<string, string> = {}
    for (const c of m.categories) cats[c.category] = toInput(c.planned_spending)
    d[m.month] = { income: toInput(m.planned_income), spending: toInput(m.planned_spending), cats }
  }
  draft.value = d
  if (!catMonth.value || !d[catMonth.value]) catMonth.value = months.value[months.value.length - 1]?.month || ''
}

async function loadBudget() {
  const b = await api.ownerBudget()
  months.value = b.months || []
  categories.value = b.categories || []
  fillDraft()
}

async function loadFiles() {
  try {
    files.value = (await api.ownerFiles()).items
  } catch {
    /* the plan still works without the file list */
  }
  if (timer) clearTimeout(timer)
  if (files.value.some((f) => f.status === 'queued' || f.status === 'processing')) {
    timer = setTimeout(async () => {
      await loadFiles()
      if (!files.value.some((f) => f.status === 'queued' || f.status === 'processing')) loadBudget().catch(() => {})
    }, 2000)
  }
}

async function loadAdvice() {
  const a = await api.ownerAdvice()
  ev.register(a.facts)
  advice.value = a.items || []
  adviceMode.value = a.mode
  adviceAt.value = a.generated_at
}

onMounted(async () => {
  ev.clear()
  try {
    await Promise.all([loadBudget(), loadAdvice(), loadFiles()])
  } catch (e) {
    err.value = errMessage(e)
  } finally {
    loading.value = false
  }
})
onBeforeUnmount(() => timer && clearTimeout(timer))

async function upload(list: File[]) {
  upErr.value = ''
  for (const f of list) {
    if (f.size > 20 * 1024 * 1024) {
      upErr.value = t('{file} is {size}; the limit is 20 MB.', { file: f.name, size: fmtBytes(f.size) })
      continue
    }
    uploading.value++
    try {
      await api.ownerUpload(f)
    } catch (e) {
      upErr.value = `${f.name}: ${errMessage(e)}`
    } finally {
      uploading.value--
    }
  }
  await loadFiles()
}

function addMonth() {
  const m = newMonth.value
  if (!/^\d{4}-\d{2}$/.test(m) || draft.value[m]) return
  draft.value[m] = { income: '', spending: '', cats: {} }
  months.value = [...months.value, {
    month: m, label: m, source: null, planned_income: null, planned_spending: null, actual_income: null, actual_spending: null,
    income_difference: null, spending_difference: null, net_actual: null, income_ref: null, spending_ref: null, categories: [],
  }].sort((a, b) => a.month.localeCompare(b.month))
  newMonth.value = ''
}

async function save() {
  saving.value = true
  saveMsg.value = ''
  const lines: { month: string; category?: string; planned_income: number | null; planned_spending: number | null }[] = []
  for (const [month, d] of Object.entries(draft.value)) {
    lines.push({ month, category: 'total', planned_income: parseInput(d.income), planned_spending: parseInput(d.spending) })
    for (const [cat, v] of Object.entries(d.cats)) {
      const p = parseInput(v)
      if (p != null) lines.push({ month, category: cat, planned_income: null, planned_spending: p })
    }
  }
  try {
    const b = await api.ownerBudgetSave(lines)
    months.value = b.months || []
    fillDraft()
    saveMsg.value = t('Plan saved.')
  } catch (e) {
    saveMsg.value = errMessage(e)
  } finally {
    saving.value = false
  }
}

async function runAdvice() {
  running.value = true
  adviceErr.value = ''
  try {
    const a = await api.ownerAdviceRun()
    ev.register(a.facts)
    advice.value = a.items || []
    adviceMode.value = a.mode
    adviceAt.value = a.generated_at
    const first = advice.value[0]?.fact_keys?.[0]
    if (first) ev.select(first)
  } catch (e) {
    adviceErr.value = errMessage(e)
  } finally {
    running.value = false
  }
}

const hasStatement = computed(() => files.value.some((f) => f.doc_type === 'bank_statement' || f.doc_type === 'cash_flow'))
const hasForm2 = computed(() => files.value.some((f) => f.doc_type === 'form2'))
const hasForm1 = computed(() => files.value.some((f) => f.doc_type === 'form1'))
const hasActuals = computed(() => months.value.some((m) => m.source))

const chart = computed(() => {
  const rows = months.value.slice(-6)
  const isSp = view.value === 'spending'
  const a = rows.map((m) => { const v = isSp ? m.actual_spending : m.actual_income; return v == null ? null : v / MLN })
  const b = rows.map((m) => { const v = isSp ? m.planned_spending : m.planned_income; return v == null ? null : v / MLN })
  return {
    labels: rows.map((m) => m.label.replace(/^(\w{3})\w*\s+(\d{4})$/, '$1 $2')),
    a, b,
    aDisplay: rows.map((m) => (isSp ? m.actual_spending : m.actual_income) != null ? mln(isSp ? m.actual_spending : m.actual_income) : null),
    bDisplay: rows.map((m) => (isSp ? m.planned_spending : m.planned_income) != null ? mln(isSp ? m.planned_spending : m.planned_income) : null),
  }
})
const catRow = computed(() => months.value.find((m) => m.month === catMonth.value))
const catList = computed(() => {
  const m = catRow.value
  const seen = new Map<string, CatRow>()
  for (const c of m?.categories || []) seen.set(c.category, c)
  return categories.value.map((c) => seen.get(c.id) || { category: c.id, label: c.label, planned_spending: null, actual_spending: null, difference: null, fact_key: null })
})

const SEV: Record<string, [string, string]> = {
  attention: ['pill-attn', 'Attention'],
  watch: ['pill-watch', 'Watch'],
  info: ['pill-info', 'For information'],
}
</script>

<template>
  <div class="page">
    <div class="twopane" style="gap: 20px">
      <section class="main-col" style="gap: 18px" :aria-label="t('Budget & advice')">
        <div class="page-head">
          <div>
            <h1>{{ t('Budget & advice') }}</h1>
            <p class="meta" style="font-size: 13px">
              {{ t('Set a monthly plan for money in and money out. Actual figures come from your bank statements or your cash-flow table; differences are calculated, not guessed.') }}
            </p>
          </div>
        </div>
        <div v-if="err" class="error-box">{{ err }}</div>

        <!-- upload -->
        <div class="panel" style="padding: 14px 16px; display: flex; flex-direction: column; gap: 10px">
          <div class="eyebrow">{{ t('Your files') }}</div>
          <Dropzone multiple :disabled="uploading > 0" @files="upload"
            :title="uploading ? t('Uploading {n} file(s)…', { n: uploading }) : t('Drop a cash-flow table, balance sheet, P&L or bank statement')"
            :hint="t('Excel (XLSX, XLS, CSV) or PDF · a cash-flow table needs columns for month, money in and money out')" :button="t('Choose files')" />
          <div v-if="upErr" class="error-box">{{ upErr }}</div>
          <div class="row" style="gap: 8px; flex-wrap: wrap; font-size: 13px">
            <span :class="['pill', hasStatement ? 'pill-stable' : 'pill-neutral']">{{ hasStatement ? t('Bank statement or cash flow on file') : t('n/a — upload a bank statement or cash-flow table') }}</span>
            <span :class="['pill', hasForm2 ? 'pill-stable' : 'pill-neutral']">{{ hasForm2 ? t('P&L (Form 2) on file') : t('n/a — upload Form 2 (P&L)') }}</span>
            <span :class="['pill', hasForm1 ? 'pill-stable' : 'pill-neutral']">{{ hasForm1 ? t('Balance sheet (Form 1) on file') : t('n/a — upload Form 1 (balance sheet)') }}</span>
          </div>
          <ul v-if="files.length" class="flist">
            <li v-for="f in files.slice(0, 6)" :key="f.uuid">
              <span>{{ f.filename }}</span>
              <span class="muted">{{ ownerDocTypeLabel(f.doc_type) }} · {{ ownerDocStatus(f).label }}</span>
            </li>
          </ul>
        </div>

        <!-- chart -->
        <div class="panel" style="padding: 14px 16px">
          <div class="row" style="justify-content: space-between; flex-wrap: wrap; gap: 8px; margin-bottom: 8px">
            <h2 style="font-size: 16px; margin: 0">{{ view === 'spending' ? t('Money out: actual vs plan') : t('Money in: actual vs plan') }} <span class="muted" style="font-weight: 400; font-size: 13px">{{ t('mln UZS') }}</span></h2>
            <div class="row" style="gap: 6px">
              <button type="button" :class="['chip', view === 'spending' && 'on']" @click="view = 'spending'">{{ t('Money out') }}</button>
              <button type="button" :class="['chip', view === 'income' && 'on']" @click="view = 'income'">{{ t('Money in') }}</button>
            </div>
          </div>
          <div v-if="loading" class="muted">{{ t('Loading…') }}</div>
          <div v-else-if="!months.length" class="empty muted">{{ t('n/a — upload a bank statement or cash-flow table, or add a month to the plan below.') }}</div>
          <BarGroupChart v-else :labels="chart.labels" :a="chart.a" :b="chart.b" :a-display="chart.aDisplay" :b-display="chart.bDisplay"
            :a-name="t('Actual')" :b-name="t('Plan')"
            :summary="t('Actual versus planned money, last six months, in mln UZS')" />
        </div>

        <!-- plan table -->
        <div class="panel" style="padding: 14px 16px; display: flex; flex-direction: column; gap: 10px">
          <h2 style="font-size: 16px; margin: 0">{{ t('Monthly plan') }} <span class="muted" style="font-weight: 400; font-size: 13px">{{ t('mln UZS') }}</span></h2>
          <div class="scrollbox">
            <table class="tbl">
              <thead>
                <tr>
                  <th>{{ t('Month') }}</th>
                  <th class="r">{{ t('Plan in') }}</th><th class="r">{{ t('Actual in') }}</th><th class="r">{{ t('Difference') }}</th>
                  <th class="r">{{ t('Plan out') }}</th><th class="r">{{ t('Actual out') }}</th><th class="r">{{ t('Difference') }}</th>
                  <th>{{ t('From') }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="m in months" :key="m.month">
                  <td style="white-space: nowrap">{{ m.label }}</td>
                  <td class="r"><input v-if="draft[m.month]" v-model="draft[m.month].income" class="input num cell" inputmode="decimal" :aria-label="t('Planned income, {m}', { m: m.label })" /></td>
                  <td class="r num">
                    <EvidenceChip v-if="m.income_ref" :fact-key="m.income_ref.fact_key" :text="mln(m.actual_income)" />
                    <span v-else class="muted">n/a</span>
                  </td>
                  <td class="r num" :class="m.income_difference != null && m.income_difference < 0 ? 'neg' : ''">{{ signed(m.income_difference) }}</td>
                  <td class="r"><input v-if="draft[m.month]" v-model="draft[m.month].spending" class="input num cell" inputmode="decimal" :aria-label="t('Planned spending, {m}', { m: m.label })" /></td>
                  <td class="r num">
                    <EvidenceChip v-if="m.spending_ref" :fact-key="m.spending_ref.fact_key" :text="mln(m.actual_spending)" />
                    <span v-else class="muted">n/a</span>
                  </td>
                  <td class="r num" :class="m.spending_difference != null && m.spending_difference > 0 ? 'neg' : ''">{{ signed(m.spending_difference) }}</td>
                  <td class="muted" style="font-size: 12px">{{ m.source === 'statement' ? t('bank statement') : m.source === 'cashflow' ? t('cash-flow table') : t('n/a — upload X', { X: t('a statement') }) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <div class="row" style="gap: 8px; flex-wrap: wrap">
            <label class="sr-only" for="nm">{{ t('Add a month') }}</label>
            <input id="nm" v-model="newMonth" type="month" class="input" style="height: 36px" />
            <button type="button" class="btn" :disabled="!newMonth" @click="addMonth">{{ t('Add month') }}</button>
            <span style="flex: 1"></span>
            <span v-if="saveMsg" class="muted" style="font-size: 13px">{{ saveMsg }}</span>
            <button type="button" class="btn btn-primary" :disabled="saving || !months.length" @click="save">{{ saving ? t('Saving…') : t('Save plan') }}</button>
          </div>

          <details v-if="months.length">
            <summary style="cursor: pointer; font-size: 13px">{{ t('Spending limits by category (optional)') }}</summary>
            <div class="row" style="gap: 8px; margin: 10px 0">
              <label for="cm" class="muted" style="font-size: 13px">{{ t('Month') }}</label>
              <select id="cm" v-model="catMonth" class="input" style="height: 34px">
                <option v-for="m in months" :key="m.month" :value="m.month">{{ m.label }}</option>
              </select>
            </div>
            <table v-if="draft[catMonth]" class="tbl">
              <thead><tr><th>{{ t('Category') }}</th><th class="r">{{ t('Limit') }}</th><th class="r">{{ t('Actual') }}</th><th class="r">{{ t('Difference') }}</th></tr></thead>
              <tbody>
                <tr v-for="c in catList" :key="c.category">
                  <td>{{ t(c.label) }}</td>
                  <td class="r"><input v-model="draft[catMonth].cats[c.category]" class="input num cell" inputmode="decimal" :aria-label="t('Limit for {c}', { c: t(c.label) })" /></td>
                  <td class="r num"><EvidenceChip v-if="c.fact_key" :fact-key="c.fact_key" :text="mln(c.actual_spending)" /><span v-else class="muted">n/a</span></td>
                  <td class="r num" :class="c.difference != null && c.difference > 0 ? 'neg' : ''">{{ signed(c.difference) }}</td>
                </tr>
              </tbody>
            </table>
          </details>
        </div>

        <!-- advice -->
        <div class="panel" style="padding: 14px 16px; display: flex; flex-direction: column; gap: 12px">
          <div class="row" style="justify-content: space-between; gap: 8px; flex-wrap: wrap">
            <div>
              <h2 style="font-size: 16px; margin: 0">{{ t('Advice') }}</h2>
              <p class="muted" style="font-size: 12px; margin: 2px 0 0">
                {{ t('Disclosed rules find the issues from your records; the AI only explains them in plain words, and every number is checked against the records.') }}
                <template v-if="adviceAt"> · {{ fmtDateTime(adviceAt) }}</template>
              </p>
            </div>
            <button type="button" class="btn btn-primary" :disabled="running" @click="runAdvice">{{ running ? t('Checking…') : advice.length || adviceAt ? t('Check again') : t('Get advice') }}</button>
          </div>
          <div v-if="adviceErr" class="error-box">{{ adviceErr }}</div>
          <div v-if="adviceMode === 'rules' && advice.length" class="row"><span class="pill pill-neutral">{{ t('LLM is off — rule texts shown') }}</span></div>
          <div v-if="!advice.length" class="empty muted">
            <template v-if="adviceAt">{{ t('No issues found by the rules in the records on file.') }}</template>
            <template v-else-if="!hasActuals">{{ t('n/a — upload a bank statement or cash-flow table, then press “Get advice”.') }}</template>
            <template v-else>{{ t('Press “Get advice” to check your records against your plan.') }}</template>
          </div>
          <article v-for="it in advice" :key="it.id" class="adv">
            <div class="row" style="gap: 8px; align-items: center">
              <span :class="['pill', SEV[it.severity]?.[0] || 'pill-neutral']">{{ t(SEV[it.severity]?.[1] || it.severity) }}</span>
              <strong>{{ t(it.title) }}</strong>
            </div>
            <p style="margin: 6px 0 0"><InlineEvidence :text="it.text" /></p>
            <details v-if="it.explained" style="font-size: 12px; margin-top: 4px">
              <summary class="muted" style="cursor: pointer">{{ t('Rule that found this') }}</summary>
              <p class="muted" style="margin: 4px 0 0"><InlineEvidence :text="it.rule_text" /></p>
            </details>
            <div v-if="it.sources.length" class="muted" style="font-size: 12px; margin-top: 6px">
              {{ t('from:') }}
              <template v-for="(s, k) in it.sources" :key="s.document_uuid || k">
                <EvidenceChip :fact-key="s.fact_key" :text="s.filename || s.label" /><template v-if="k < it.sources.length - 1">, </template>
              </template>
            </div>
          </article>
        </div>
      </section>

      <div class="ev-col" style="flex-basis: 380px">
        <EvidencePane :actions="false" :empty-text="t('Click any dashed figure to see the record it came from.')" />
      </div>
    </div>
  </div>
</template>

<style scoped>
.cell { width: 96px; height: 32px; text-align: right; }
.neg { color: var(--attn-fg); }
.flist { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 4px; font-size: 13px; }
.flist li { display: flex; justify-content: space-between; gap: 12px; border-top: 1px solid var(--border-row); padding-top: 4px; }
.adv { border-top: 1px solid var(--border-row); padding-top: 10px; }
.chip.on { border-color: var(--series-1); color: var(--series-1); }
.empty { padding: 12px 0; font-size: 13px; }
</style>
