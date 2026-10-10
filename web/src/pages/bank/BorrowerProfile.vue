<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { api, errMessage } from '@/api/client'
import type { BorrowerProfile } from '@/api/types'
import { docStatusPill, fmtDate, severityPillClass, statusLabel } from '@/api/format'
import { useEvidence } from '@/stores/evidence'
import EvidencePane from '@/components/evidence/EvidencePane.vue'
import FindingRow from '@/components/evidence/FindingRow.vue'
import NarrativeText from '@/components/evidence/NarrativeText'
import BarGroupChart from '@/components/charts/BarGroupChart.vue'
import LineChart from '@/components/charts/LineChart.vue'
import EvidenceChip from '@/components/evidence/EvidenceChip.vue'
import Modal from '@/components/ui/Modal.vue'

const route = useRoute()
const ev = useEvidence()
const loanId = computed(() => String(route.params.loanId))
const data = ref<BorrowerProfile | null>(null)
const loading = ref(true)
const err = ref('')

onMounted(async () => {
  ev.clear()
  try {
    const r = await api.borrower(loanId.value)
    data.value = r
    ev.register(r.facts)
    ev.selectDefault(r.alerts.find((a) => a.evidence?.length)?.evidence[0] || Object.keys(r.facts || {})[0])
  } catch (e) {
    err.value = errMessage(e)
  } finally {
    loading.value = false
  }
})

const b = computed(() => data.value?.business || {})
const loan = computed(() => data.value?.loan || {})

function pick(o: Record<string, any>, ...keys: string[]) {
  for (const k of keys) if (o[k] != null && o[k] !== '') return o[k]
  return null
}

const loanCells = computed(() => {
  const l = loan.value
  const cells: { label: string; main: string; sub?: string; warn?: boolean }[] = []
  const id = pick(l, 'loan_id', 'contract_no', 'id')
  const type = pick(l, 'type')
  if (id || type) cells.push({ label: 'Loan', main: [id, type].filter(Boolean).join(' · '), sub: [pick(l, 'disbursed_on') ? `Disbursed ${fmtDate(pick(l, 'disbursed_on'))}` : null, pick(l, 'purpose')].filter(Boolean).join(' · ') })
  const out = pick(l, 'outstanding_display', 'outstanding')
  const orig = pick(l, 'original_display', 'original_amount', 'original')
  if (out != null) cells.push({ label: 'Original / outstanding', main: `${out}`, sub: orig != null ? `of ${orig} mln` : undefined })
  const inst = pick(l, 'installment_display', 'installment')
  if (inst != null) cells.push({ label: 'Installment', main: `${inst} mln`, sub: [pick(l, 'due_day') ? `${pick(l, 'due_day')}th monthly` : null, pick(l, 'next_due', 'next_due_on') ? `next due ${fmtDate(pick(l, 'next_due', 'next_due_on'))}` : null].filter(Boolean).join(' · ') })
  const term = pick(l, 'term_months')
  if (term != null) {
    const paid = pick(l, 'paid_count', 'paid')
    const left = pick(l, 'left')
    cells.push({ label: 'Term', main: `${term} months${paid != null ? ` · ${paid} paid` : ''}${left != null ? `, ${left} left` : ''}`, sub: pick(l, 'maturity_on', 'maturity') ? `Matures ${fmtDate(pick(l, 'maturity_on', 'maturity'))}` : undefined })
  }
  const col = pick(l, 'collateral')
  if (col && (typeof col === 'string' || Object.keys(col).length)) cells.push({ label: 'Collateral', main: typeof col === 'string' ? col : col.description || col.type || col.name || 'Recorded', sub: typeof col === 'object' && (col.valuation_display || col.valuation) ? `Valued ${col.valuation_display || col.valuation}${col.valuation_display ? '' : ' mln'}${col.valued_at ? ` (${col.valued_at})` : ''}` : undefined })
  const cov = pick(l, 'coverage_display')
  const m04 = data.value?.status?.indicators?.M04
  if (cov) {
    const thr = m04?.threshold_display ?? (m04?.threshold != null ? `${m04.threshold}×` : pick(l, 'coverage_threshold_display'))
    cells.push({ label: 'Cash coverage of next installment', main: cov, sub: thr ? `threshold ${thr}` : undefined, warn: !!(m04?.triggered ?? pick(l, 'coverage_below_threshold')) })
  }
  return cells
})

const repayments = computed<{ n: number; due_on?: string; paid_on?: string | null; days_late?: number | null; state?: string }[]>(() => {
  const r = loan.value.repayments
  return Array.isArray(r) ? r : []
})
const stripCells = computed(() => {
  const term = Number(loan.value.term_months) || repayments.value.length
  const out: { cls: string; title: string }[] = []
  for (let i = 1; i <= term; i++) {
    const r = repayments.value.find((x) => x.n === i)
    if (r && r.paid_on) {
      const late = (r.days_late ?? 0) > 0
      out.push({ cls: late ? 'late' : 'ok', title: `#${i} due ${fmtDate(r.due_on)} · paid ${fmtDate(r.paid_on)}${late ? ` · ${r.days_late} days late` : ''}` })
    } else if (r?.state === 'overdue') out.push({ cls: 'late', title: `#${i} due ${fmtDate(r.due_on)} · not paid` })
    else out.push({ cls: 'up', title: r?.due_on ? `#${i} due ${fmtDate(r.due_on)}` : `#${i} upcoming` })
  }
  return out
})
const lateCount = computed(() => repayments.value.filter((r) => (r.days_late ?? 0) > 0).length)
const paidCount = computed(() => repayments.value.filter((r) => r.paid_on).length)

// Quarterly series arrive as fact keys (one per period) so every bar is traceable.
const q = computed(() => data.value?.quarterly || null)
const qLabelsAll = computed<string[]>(() => (Array.isArray(q.value?.quarters) ? q.value!.quarters : Array.isArray(q.value?.periods) ? q.value!.periods : []))
const keepIdx = computed(() =>
  qLabelsAll.value.map((_, i) => i).filter((i) => ['revenue', 'opex'].some((n) => rawSeries(n)[i] != null)),
)
function rawSeries(name: string): unknown[] {
  const arr = q.value?.[name]
  return Array.isArray(arr) ? arr : []
}
function pickIdx<T>(arr: T[]): T[] {
  return keepIdx.value.map((i) => arr[i])
}
const qLabels = computed<string[]>(() => pickIdx(qLabelsAll.value))
function seriesKeys(name: string): (string | null)[] {
  const arr = q.value?.[name]
  return Array.isArray(arr) && arr.every((x: unknown) => x == null || typeof x === 'string') ? (arr.map((x: string | null | undefined) => x ?? null) as (string | null)[]) : []
}
function seriesValues(name: string): (number | null)[] {
  const arr = q.value?.[name]
  if (!Array.isArray(arr)) return []
  if (arr.every((x: unknown) => x == null || typeof x === 'number')) return arr.map((x: number | null | undefined) => x ?? null) as (number | null)[]
  // fact keys → values scaled from thousand to million UZS for the bar heights; labels use the fact's display
  return arr.map((k: string | null) => {
    const f = k ? data.value?.facts?.[k] : null
    if (!f) return null
    return f.unit === 'kUZS' ? f.value / 1000 : f.value
  }) as (number | null)[]
}
function seriesDisplay(name: string): (string | null)[] | undefined {
  const keys = seriesKeys(name)
  if (!keys.length) return q.value?.[`${name}_display`] as (string | null)[] | undefined
  return keys.map((k) => (k ? (data.value?.facts?.[k]?.display ?? null) : null)) as (string | null)[]
}
const qRevenue = computed(() => pickIdx(seriesValues('revenue')))
const qOpexRaw = computed(() => pickIdx(seriesValues('opex')))
const qOpex = computed(() => (qOpexRaw.value.some((v) => v != null) ? qOpexRaw.value : undefined))
const qCoverage = computed(() => pickIdx(seriesValues('coverage')))
const qThreshold = computed<number | null>(() => (typeof q.value?.coverage_threshold === 'number' ? q.value!.coverage_threshold : null))
const qChipKeys = computed(() => [...pickIdx(seriesKeys('revenue')), ...pickIdx(seriesKeys('opex'))].filter(Boolean) as string[])

const showOutcome = ref(false)
const outcome = ref('')
const reasoning = ref('')
const outBusy = ref(false)
const outErr = ref('')
const outDone = ref('')
const OUTCOMES = [
  { v: 'no_action', label: 'No action — keep monitoring' },
  { v: 'contact', label: 'Contact the borrower' },
  { v: 'request_docs', label: 'Request documents' },
  { v: 'restructure', label: 'Discuss restructuring' },
]
async function submitOutcome() {
  outErr.value = ''
  if (!outcome.value) return (outErr.value = 'Choose an outcome.')
  if (reasoning.value.trim().length < 20) return (outErr.value = 'Write your reasoning (at least 20 characters).')
  outBusy.value = true
  try {
    await api.borrowerReviewOutcome(loanId.value, { outcome: outcome.value, reasoning: reasoning.value.trim(), evidence_reviewed: ev.opened })
    outDone.value = 'Review outcome recorded with the evidence you opened. The system status is unchanged; it stays separate from your assessment.'
    showOutcome.value = false
  } catch (e) {
    outErr.value = errMessage(e)
  } finally {
    outBusy.value = false
  }
}

const statusHistory = computed(() => {
  const h = data.value?.status.history || []
  return h
    .slice(0, -1)
    .reverse()
    .map((x) => `${statusLabel(x.status)}${x.from ? ` (${fmtDate(x.from, { short: true })})` : ''}`)
    .join(' · ')
})
</script>

<template>
  <div class="page">
    <div class="crumbs"><RouterLink to="/bank/borrowers">Borrowers</RouterLink> / {{ data?.business?.name || loanId }}</div>
    <div v-if="loading" class="panel empty">Loading borrower…</div>
    <div v-else-if="err" class="error-box">{{ err }} <RouterLink to="/bank/borrowers">Back to borrowers</RouterLink></div>

    <template v-if="data">
      <div class="page-head" style="align-items: flex-start">
        <div>
          <div class="row" style="gap: 10px">
            <h1>{{ b.name }}</h1>
            <span class="pill" :class="severityPillClass(data.status.current)">{{ statusLabel(data.status.current) }}<template v-if="data.status.since"> · since {{ fmtDate(data.status.since) }}</template></span>
            <span v-if="statusHistory" class="muted">previously {{ statusHistory }}</span>
          </div>
          <p v-if="data.status.reason" class="reason"><span class="eyebrow">Why</span> {{ data.status.reason }}</p>
          <p class="meta">
            <template v-if="b.industry">{{ b.industry }}</template><template v-if="b.region"> · {{ b.region }}</template><template v-if="b.stir"> · STIR <span class="num">{{ b.stir }}</span></template><template v-if="b.since"> · operating since {{ b.since }}</template><template v-if="b.employees"> · {{ b.employees }} employees</template>
          </p>
        </div>
        <div class="actions"><button type="button" class="btn btn-primary" @click="showOutcome = true">Record review outcome</button></div>
      </div>
      <div v-if="outDone" class="note">{{ outDone }}</div>

      <section v-if="loanCells.length || stripCells.length" class="panel" style="padding: 12px 16px; display: flex; flex-direction: column; gap: 12px" aria-label="Loan details">
        <div class="kv">
          <div v-for="c in loanCells" :key="c.label">
            <div class="eyebrow">{{ c.label }}</div>
            <div class="num" style="font-size: 16px; font-weight: 500" :style="c.warn ? { color: 'var(--attn-fg)' } : undefined">{{ c.main }}</div>
            <div v-if="c.sub" class="muted">{{ c.sub }}</div>
          </div>
        </div>
        <div v-if="stripCells.length">
          <div class="muted" style="font-size: 12px; margin-bottom: 6px">Repayment history · {{ paidCount }} installments paid · {{ paidCount - lateCount }} on time, {{ lateCount }} late</div>
          <div class="strip" :style="{ gridTemplateColumns: `repeat(${stripCells.length}, minmax(0, 1fr))` }" role="img" :aria-label="`${stripCells.length} installments: ${paidCount - lateCount} on time, ${lateCount} late, ${stripCells.length - paidCount} upcoming`">
            <span v-for="(c, i) in stripCells" :key="i" :class="c.cls" :title="c.title"></span>
          </div>
          <div class="row muted" style="justify-content: flex-end; font-size: 12px; margin-top: 4px; gap: 12px">
            <span><i class="lg ok"></i>on time</span><span><i class="lg late"></i>late</span><span><i class="lg up"></i>upcoming</span>
          </div>
        </div>
      </section>

      <div class="twopane">
        <div class="main-col">
          <section class="panel" aria-label="Monitoring alerts">
            <div class="panel-head" style="padding: 12px 14px 8px">
              <h2>Why this borrower is under {{ statusLabel(data.status.current) }}</h2>
              <span class="ctx">{{ data.alerts.length }} indicator{{ data.alerts.length === 1 ? '' : 's' }} moved · thresholds disclosed</span>
            </div>
            <FindingRow v-for="a in data.alerts" :key="a.uuid" :finding="a" />
            <div v-if="!data.alerts.length" class="empty" style="border-top: 1px solid var(--border-row)">No indicator crossed its threshold in the latest periods.</div>
          </section>

          <section v-if="qLabels.length && qRevenue.some((v) => v != null)" class="panel" aria-label="Financial performance over time">
            <div class="panel-head" style="padding: 12px 14px 0">
              <div>
                <h2>Quarterly revenue and operating expenses</h2>
                <p class="muted" style="font-size: 12px">mln UZS · from statements uploaded by the borrower</p>
              </div>
            </div>
            <div style="padding: 6px 10px 0">
              <BarGroupChart
                :labels="qLabels"
                :a="qRevenue"
                :b="qOpex"
                a-name="Revenue"
                b-name="Operating expenses"
                :a-display="pickIdx(seriesDisplay('revenue') || [])"
                :b-display="pickIdx(seriesDisplay('opex') || [])"
                :summary="`Quarterly revenue: ${qLabels.map((l, i) => `${l} ${pickIdx(seriesDisplay('revenue') || [])[i] ?? 'n/a'}`).join(', ')} million UZS.`"
              />
            </div>
            <div v-if="qChipKeys.length" class="row" style="padding: 0 14px 10px; gap: 6px">
              <span class="muted" style="font-size: 12px">Sources:</span>
              <EvidenceChip v-for="k in qChipKeys" :key="k" :fact-key="k" long />
            </div>
            <template v-if="qCoverage.some((v) => v != null)">
              <div class="panel-head" style="margin: 0 14px; padding-top: 10px; border-top: 1px solid var(--border-row)">
                <span style="font-weight: 600">Cash coverage of next installment, quarter end</span>
                <span v-if="qThreshold != null" class="ctx">threshold shown as dashed line</span>
              </div>
              <div style="padding: 2px 10px 10px">
                <LineChart
                  :labels="qLabels"
                  :values="qCoverage"
                  :display="q?.coverage_display ? pickIdx(q.coverage_display) : undefined"
                  :threshold="qThreshold"
                  suffix="×"
                  :summary="`Cash coverage at quarter end: ${qLabels.map((l, i) => `${l} ${q?.coverage_display?.[i] ?? qCoverage[i] ?? 'n/a'}`).join(', ')}.`"
                />
              </div>
            </template>
          </section>

          <section class="panel" aria-label="AI explanation" style="padding: 12px 14px 14px; display: flex; flex-direction: column; gap: 10px">
            <div class="panel-head">
              <h2>What changed, and why it matters for repayment</h2>
              <span v-if="data.narrative?.markdown" class="ctx">{{ data.narrative.mode === 'llm' ? 'AI explanation · every figure links to its source' : 'Template summary · AI draft not used' }}</span>
            </div>
            <NarrativeText v-if="data.narrative?.markdown && data.narrative.verified !== false" :markdown="data.narrative.markdown" />
            <p v-else class="muted">No written explanation yet; the alerts above are complete on their own.</p>
          </section>

          <div class="footer-line">{{ data.calibration_note }} Statuses are rule-based monitoring indicators, not a credit score. The officer records the review outcome; the system status stays separate from the officer's assessment.</div>
        </div>

        <div class="ev-col stack" style="gap: 16px">
          <EvidencePane :sticky="false" />
          <section v-if="data.timeline.length" class="panel" aria-label="How it developed" style="padding: 12px 14px">
            <div class="eyebrow" style="margin-bottom: 8px">How it developed</div>
            <div v-for="(t, i) in data.timeline" :key="i" class="tl">
              <span class="num muted" style="font-size: 12px">{{ fmtDate(t.date, { short: t.date.length > 7 }) }}</span>
              <span class="dotcol"><span class="dot" :class="t.status"></span><span v-if="i < data.timeline.length - 1" class="conn"></span></span>
              <span style="font-size: 12.5px; padding-bottom: 10px">{{ t.title }}</span>
            </div>
          </section>
          <section v-if="data.documents.length" class="panel" aria-label="Documents" style="padding: 12px 14px 8px">
            <div class="eyebrow" style="margin-bottom: 4px">Documents &amp; previous assessments</div>
            <div v-for="(d, i) in data.documents" :key="i" class="doc" style="grid-template-columns: 1fr auto">
              <div style="min-width: 0">
                <div style="font-weight: 500">{{ d.title || d.filename }}</div>
                <div class="muted">{{ [d.uploaded_at || d.uploaded || d.date ? fmtDate(String(d.uploaded_at || d.uploaded || d.date).slice(0, 10)) : null, d.note].filter(Boolean).join(' · ') }}</div>
              </div>
              <span v-if="d.status" class="pill" :class="docStatusPill(d.status).cls">{{ docStatusPill(d.status).label }}</span>
            </div>
          </section>
        </div>
      </div>
    </template>

    <Modal v-if="showOutcome && data" title="Record review outcome" @close="showOutcome = false">
      <form class="stack" @submit.prevent="submitOutcome">
        <p class="muted" style="font-size: 13px">Your assessment is stored with the {{ ev.opened.length }} piece{{ ev.opened.length === 1 ? '' : 's' }} of evidence you opened. The monitoring status itself is not changed by this.</p>
        <fieldset class="stack" style="border: 0; padding: 0; margin: 0; gap: 6px">
          <legend class="eyebrow" style="margin-bottom: 6px">Outcome</legend>
          <label v-for="o in OUTCOMES" :key="o.v" class="row" style="gap: 8px; font-size: 13px"><input v-model="outcome" type="radio" name="outcome" :value="o.v" /> {{ o.label }}</label>
        </fieldset>
        <label class="stack" style="gap: 4px">
          <span class="eyebrow">Reasoning</span>
          <textarea v-model="reasoning" class="input" rows="5" placeholder="What did you conclude from the alerts and evidence?"></textarea>
          <span class="muted" style="font-size: 12px">{{ reasoning.trim().length }} / 20 characters minimum</span>
        </label>
        <div v-if="outErr" class="error-box">{{ outErr }}</div>
        <div class="row">
          <button type="submit" class="btn btn-primary" :disabled="outBusy">{{ outBusy ? 'Recording…' : 'Record outcome' }}</button>
          <button type="button" class="btn" @click="showOutcome = false">Cancel</button>
        </div>
      </form>
    </Modal>
  </div>
</template>

<style scoped>
.reason { margin-top: 4px; font-size: 13px; color: var(--ink-2); }
.strip { display: grid; gap: 3px; }
.strip span { height: 10px; border-radius: 2px; }
.ok { background: var(--stable-mark); }
.late { background: var(--attn-mark); }
.up { background: var(--border); }
.lg { display: inline-block; width: 8px; height: 8px; border-radius: 2px; margin-right: 4px; }
.tl { display: grid; grid-template-columns: 84px 14px 1fr; gap: 8px; }
.dotcol { display: flex; flex-direction: column; align-items: center; }
.dot { width: 10px; height: 10px; border-radius: 50%; margin-top: 4px; background: var(--border-strong); flex: none; }
.dot.stable { background: var(--stable-mark); }
.dot.watch { background: var(--watch-mark); }
.dot.attn { background: var(--attn-mark); }
.dot.today { background: var(--ink); }
.conn { width: 2px; flex: 1; background: var(--border-row); }
</style>
