<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { api, errMessage } from '@/api/client'
import type { BorrowerProfile } from '@/api/types'
import { appStatusPill, docStatusPill, docTypeShort, fmtDate, ratioHelp, severityPillClass, statusLabel } from '@/api/format'
import { useEvidence } from '@/stores/evidence'
import EvidencePane from '@/components/evidence/EvidencePane.vue'
import FindingRow from '@/components/evidence/FindingRow.vue'
import NarrativeText from '@/components/evidence/NarrativeText'
import BarGroupChart from '@/components/charts/BarGroupChart.vue'
import LineChart from '@/components/charts/LineChart.vue'
import EvidenceChip from '@/components/evidence/EvidenceChip.vue'
import Modal from '@/components/ui/Modal.vue'
import { t, tn } from '@/i18n'

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
const hasLoan = computed(() => !!data.value?.loan)

// Display-only extras from GET /borrowers/{ref}: applications, latest extracted figures and ratios (fact keys).
type ProfileExtras = {
  applications?: { number: string; status: string; received_on: string; requested_display: string | null; term_months: number | null; purpose: string }[]
  figure_keys?: string[]
  ratio_keys?: string[]
}
const extras = computed(() => (data.value || {}) as ProfileExtras)
const applications = computed(() => extras.value.applications || [])
const figureKeys = computed(() => (extras.value.figure_keys || []).filter((k) => data.value?.facts?.[k]))
const ratioKeys = computed(() => (extras.value.ratio_keys || []).filter((k) => data.value?.facts?.[k]))
function factLabel(k: string) {
  const f = data.value?.facts?.[k]
  return f ? String(f.label || '').split(',')[0] : ''
}
function factPeriod(k: string) {
  const f = data.value?.facts?.[k]
  if (!f) return ''
  const lbl = String(f.label || '')
  return lbl.includes(',') ? lbl.slice(lbl.indexOf(',') + 1).trim() : f.period_label || ''
}

function pick(o: Record<string, any>, ...keys: string[]) {
  for (const k of keys) if (o[k] != null && o[k] !== '') return o[k]
  return null
}

const loanCells = computed(() => {
  const l = loan.value
  const cells: { label: string; main: string; sub?: string; help?: string; warn?: boolean }[] = []
  const id = pick(l, 'loan_id', 'contract_no', 'id')
  const type = pick(l, 'type')
  if (id || type) cells.push({ label: t('Loan'), main: [id, type].filter(Boolean).join(' · '), sub: [pick(l, 'disbursed_on') ? t('Disbursed {d}', { d: fmtDate(pick(l, 'disbursed_on')) }) : null, pick(l, 'purpose')].filter(Boolean).join(' · ') })
  const out = pick(l, 'outstanding_display', 'outstanding')
  const orig = pick(l, 'original_display', 'original_amount', 'original')
  if (out != null) cells.push({ label: t('Original / outstanding'), main: `${out}`, sub: orig != null ? t('of {amount} mln', { amount: orig }) : undefined })
  const inst = pick(l, 'installment_display', 'installment')
  if (inst != null) cells.push({ label: t('Installment'), main: t('{amount} mln', { amount: inst }), sub: [pick(l, 'due_day') ? t('monthly, day {d}', { d: pick(l, 'due_day') }) : null, pick(l, 'next_due', 'next_due_on') ? t('next due {d}', { d: fmtDate(pick(l, 'next_due', 'next_due_on')) }) : null].filter(Boolean).join(' · ') })
  const term = pick(l, 'term_months')
  if (term != null) {
    const paid = pick(l, 'paid_count', 'paid')
    const left = pick(l, 'left')
    cells.push({ label: t('Term'), main: `${tn(term, '{n} month', '{n} months')}${paid != null ? ` · ${t('{n} paid', { n: paid })}` : ''}${left != null ? `, ${t('{n} left', { n: left })}` : ''}`, sub: pick(l, 'maturity_on', 'maturity') ? t('Matures {d}', { d: fmtDate(pick(l, 'maturity_on', 'maturity')) }) : undefined })
  }
  const col = pick(l, 'collateral')
  if (col && (typeof col === 'string' || Object.keys(col).length)) cells.push({ label: t('Collateral'), main: typeof col === 'string' ? col : col.description || col.type || col.name || t('Recorded'), sub: typeof col === 'object' && (col.valuation_display || col.valuation) ? `${t('Valued')} ${col.valuation_display || col.valuation}${col.valuation_display ? '' : ' ' + t('mln')}${col.valued_at ? ` (${col.valued_at})` : ''}` : undefined })
  const cov = pick(l, 'coverage_display')
  const m04 = data.value?.status?.indicators?.M04
  if (cov) {
    const thr = m04?.threshold_display ?? (m04?.threshold != null ? `${m04.threshold}×` : pick(l, 'coverage_threshold_display'))
    const covMain = cov === 'n/a' ? t('Not available yet: needs a bank statement') : cov
    cells.push({ label: t('Cash vs next payment'), main: covMain, sub: thr ? t('month-end cash ÷ next payment · warning below {v}', { v: thr }) : t('month-end cash ÷ next payment'), help: t('How many monthly payments the money on the account could cover. Below 1.5 is a warning.'), warn: !!(m04?.triggered ?? pick(l, 'coverage_below_threshold')) })
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
      out.push({ cls: late ? 'late' : 'ok', title: `#${i} ${t('due {d}', { d: fmtDate(r.due_on) })} · ${t('paid {d}', { d: fmtDate(r.paid_on) })}${late ? ` · ${t('{n} days late', { n: r.days_late ?? 0 })}` : ''}` })
    } else if (r?.state === 'overdue') out.push({ cls: 'late', title: `#${i} ${t('due {d}', { d: fmtDate(r.due_on) })} · ${t('not paid')}` })
    else out.push({ cls: 'up', title: r?.due_on ? `#${i} ${t('due {d}', { d: fmtDate(r.due_on) })}` : `#${i} ${t('upcoming')}` })
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
  if (!outcome.value) return (outErr.value = t('Choose an outcome.'))
  if (reasoning.value.trim().length < 20) return (outErr.value = t('Write your reasoning (at least 20 characters).'))
  outBusy.value = true
  try {
    await api.borrowerReviewOutcome(loanId.value, { outcome: outcome.value, reasoning: reasoning.value.trim(), evidence_reviewed: ev.opened })
    outDone.value = t('Review outcome recorded with the evidence you opened. The system status is unchanged; it stays separate from your assessment.')
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
    <div class="crumbs"><RouterLink to="/bank/borrowers">{{ t('Borrowers') }}</RouterLink> / {{ data?.business?.name || loanId }}</div>
    <div v-if="loading" class="panel empty">{{ t('Loading borrower…') }}</div>
    <div v-else-if="err" class="error-box">{{ err }} <RouterLink to="/bank/borrowers">{{ t('Back to borrowers') }}</RouterLink></div>

    <template v-if="data">
      <div class="page-head" style="align-items: flex-start">
        <div>
          <div class="row" style="gap: 10px">
            <h1>{{ b.name }}</h1>
            <span class="pill" :class="severityPillClass(data.status.current)">{{ statusLabel(data.status.current) }}<template v-if="data.status.since"> · {{ t('since {d}', { d: fmtDate(data.status.since) }) }}</template></span>
            <span v-if="statusHistory" class="muted">{{ t('previously {list}', { list: statusHistory }) }}</span>
          </div>
          <p v-if="data.status.reason" class="reason"><span class="eyebrow">{{ t('Why') }}</span> {{ data.status.reason }}</p>
          <p v-else-if="data.status.current === 'unknown'" class="reason"><span class="eyebrow">{{ t('Why') }}</span> {{ t('No monitoring check has run for this loan yet.') }}</p>
          <p class="meta">
            <template v-if="b.industry">{{ b.industry }}</template><template v-if="b.region"> · {{ b.region }}</template><template v-if="b.stir"> · {{ t('STIR') }} <span class="num">{{ b.stir }}</span></template><template v-if="b.since"> · {{ t('operating since {y}', { y: b.since }) }}</template><template v-if="b.employees"> · {{ tn(b.employees, '{n} employee', '{n} employees') }}</template>
          </p>
        </div>
        <div v-if="hasLoan" class="actions"><button type="button" class="btn btn-primary" @click="showOutcome = true">{{ t('Record review outcome') }}</button></div>
      </div>
      <p class="muted page-help">
        {{ hasLoan
          ? t('Loan follow-up for this business: what changed in its latest statements, the evidence behind each warning, and its repayment record. Review the warnings, then record your conclusion.')
          : t('This business has no loan with the bank yet, so there is nothing to monitor. Monitoring starts once a loan is disbursed. Below are its uploaded documents, the figures read from them and its loan applications.') }}
      </p>
      <div v-if="outDone" class="note">{{ outDone }}</div>

      <section v-if="loanCells.length || stripCells.length" class="panel" style="padding: 12px 16px; display: flex; flex-direction: column; gap: 12px" :aria-label="t('Loan details')">
        <div class="kv">
          <div v-for="c in loanCells" :key="c.label">
            <div class="eyebrow">{{ c.label }}</div>
            <div class="num" style="font-size: 16px; font-weight: 500" :style="c.warn ? { color: 'var(--attn-fg)' } : undefined">{{ c.main }}</div>
            <div v-if="c.sub" class="muted">{{ c.sub }}</div>
            <div v-if="c.help" class="muted" style="font-size: 12px; font-style: italic; max-width: 240px">{{ c.help }}</div>
          </div>
        </div>
        <div v-if="stripCells.length">
          <div class="muted" style="font-size: 12px; margin-bottom: 6px">{{ t('Repayment history · {paid} installments paid · {ok} on time, {late} late', { paid: paidCount, ok: paidCount - lateCount, late: lateCount }) }}</div>
          <div class="strip" :style="{ gridTemplateColumns: `repeat(${stripCells.length}, minmax(0, 1fr))` }" role="img" :aria-label="t('{n} installments: {ok} on time, {late} late, {up} upcoming', { n: stripCells.length, ok: paidCount - lateCount, late: lateCount, up: stripCells.length - paidCount })">
            <span v-for="(c, i) in stripCells" :key="i" :class="c.cls" :title="c.title"></span>
          </div>
          <div class="row muted" style="justify-content: flex-end; font-size: 12px; margin-top: 4px; gap: 12px">
            <span><i class="lg ok"></i>{{ t('on time') }}</span><span><i class="lg late"></i>{{ t('late') }}</span><span><i class="lg up"></i>{{ t('upcoming') }}</span>
          </div>
        </div>
      </section>

      <details class="howto">
        <summary>{{ t('How we watch this loan') }}</summary>
        <ul>
          <li>{{ t('After the loan is paid out, the business uploads its new statements every quarter (or the bank receives them).') }}</li>
          <li>{{ t('Converza reads them automatically and compares them with the previous quarter.') }}</li>
          <li>{{ t('It checks simple published warning rules. By default: sales fall by 15% or more; money customers owe grows by 25% or more while sales do not grow; money owed to suppliers grows by 40% or more; cash on the account covers less than 1.5 times the next payment; one of the last 3 loan payments was late; statements arrive more than 10 days late.') }}</li>
          <li>{{ t('Each warning shows the numbers behind it, and every number links to the page it came from.') }}</li>
          <li>{{ t('The status Stable / Watch / Attention comes only from these rules. There is no credit score.') }}</li>
          <li>{{ t('The thresholds are illustrative; calibration against bank history is pilot month 1.') }}</li>
          <li>{{ t('The bank officer reviews each warning and records a conclusion. Converza never decides.') }}</li>
        </ul>
      </details>

      <div class="twopane">
        <div class="main-col">
          <section v-if="hasLoan" class="panel" :aria-label="t('Warning signs')">
            <div class="panel-head" style="padding: 12px 14px 8px">
              <h2>{{ t('Warning signs found') }}</h2>
              <span class="ctx">{{ tn(data.alerts.length, '{n} warning sign', '{n} warning signs') }} · {{ t('click a figure to see its source') }}</span>
            </div>
            <FindingRow v-for="a in data.alerts" :key="a.uuid" :finding="a" />
            <div v-if="!data.alerts.length" class="empty" style="border-top: 1px solid var(--border-row)">
              {{ data.status.current === 'unknown' ? t('Not available yet: no monitoring check has run for this loan.') : t('No warning sign in the latest periods.') }}
            </div>
          </section>

          <section v-if="applications.length || !hasLoan" class="panel" :aria-label="t('Loan applications')">
            <div class="panel-head" style="padding: 12px 14px 8px">
              <h2>{{ t('Loan applications') }}</h2>
              <span class="ctx">{{ t('Open one to review it and record your decision') }}</span>
            </div>
            <div class="scrollbox">
              <table class="tbl hover" style="min-width: 520px">
                <thead><tr><th>{{ t('Application') }}</th><th class="r">{{ t('Amount, mln UZS') }}</th><th class="r">{{ t('Term') }}</th><th>{{ t('Received') }}</th><th>{{ t('Status') }}</th></tr></thead>
                <tbody>
                  <tr v-for="a in applications" :key="a.number">
                    <td><RouterLink :to="`/bank/applications/${a.number}`" style="font-weight: 500">{{ a.number }}</RouterLink><div v-if="a.purpose" class="muted" style="font-size: 12px">{{ a.purpose }}</div></td>
                    <td class="r num">{{ a.requested_display || '—' }}</td>
                    <td class="r num">{{ a.term_months ? tn(a.term_months, '{n} month', '{n} months') : '—' }}</td>
                    <td class="num">{{ fmtDate(a.received_on) }}</td>
                    <td><span class="pill" :class="appStatusPill(a.status).cls">{{ appStatusPill(a.status).label }}</span></td>
                  </tr>
                  <tr v-if="!applications.length"><td colspan="5" class="muted">{{ t('No applications yet. They appear here when the business applies for a loan on converza.uz.') }}</td></tr>
                </tbody>
              </table>
            </div>
          </section>

          <section v-if="figureKeys.length || ratioKeys.length || !hasLoan" class="panel" :aria-label="t('Latest figures from the documents')">
            <div class="panel-head" style="padding: 12px 14px 8px">
              <h2>{{ t('Latest figures from the documents') }}</h2>
              <span class="ctx">{{ t('click a value to see the page it came from') }}</span>
            </div>
            <div v-if="figureKeys.length || ratioKeys.length" class="scrollbox">
              <table class="tbl" style="min-width: 480px">
                <tbody>
                  <tr v-for="k in figureKeys" :key="k">
                    <td>{{ factLabel(k) }}<div class="muted" style="font-size: 12px">{{ factPeriod(k) }}</div></td>
                    <td class="r"><EvidenceChip :fact-key="k" /> <span v-if="data.facts[k].display_unit" class="muted" style="font-size: 12px">{{ data.facts[k].display_unit }}</span></td>
                  </tr>
                  <tr v-for="k in ratioKeys" :key="k">
                    <td :title="ratioHelp(factLabel(k))">{{ factLabel(k) }}<div class="muted" style="font-size: 12px">{{ ratioHelp(factLabel(k)) || factPeriod(k) }}</div></td>
                    <td class="r"><EvidenceChip :fact-key="k" /></td>
                  </tr>
                </tbody>
              </table>
            </div>
            <div v-else class="empty" style="border-top: 1px solid var(--border-row)">{{ t('Not available yet — upload Form 1 (balance sheet) and Form 2 (income statement) to see figures.') }}</div>
          </section>

          <section v-if="qLabels.length && qRevenue.some((v) => v != null)" class="panel" aria-label="Financial performance over time">
            <div class="panel-head" style="padding: 12px 14px 0">
              <div>
                <h2>{{ t('Quarterly revenue and operating expenses') }}</h2>
                <p class="muted" style="font-size: 12px">{{ t('mln UZS · from statements uploaded by the borrower') }}</p>
              </div>
            </div>
            <div style="padding: 6px 10px 0">
              <BarGroupChart
                :labels="qLabels"
                :a="qRevenue"
                :b="qOpex"
                :a-name="t('Revenue')"
                :b-name="t('Operating expenses')"
                :a-display="pickIdx(seriesDisplay('revenue') || [])"
                :b-display="pickIdx(seriesDisplay('opex') || [])"
                :summary="`Quarterly revenue: ${qLabels.map((l, i) => `${l} ${pickIdx(seriesDisplay('revenue') || [])[i] ?? 'n/a'}`).join(', ')} million UZS.`"
              />
            </div>
            <div v-if="qChipKeys.length" class="row" style="padding: 0 14px 10px; gap: 6px">
              <span class="muted" style="font-size: 12px">{{ t('Sources:') }}</span>
              <EvidenceChip v-for="k in qChipKeys" :key="k" :fact-key="k" long />
            </div>
            <template v-if="qCoverage.some((v) => v != null)">
              <div class="panel-head" style="margin: 0 14px; padding-top: 10px; border-top: 1px solid var(--border-row)">
                <span style="font-weight: 600">{{ t('Cash coverage of next installment, quarter end') }}</span>
                <span v-if="qThreshold != null" class="ctx">{{ t('threshold shown as dashed line') }}</span>
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

          <section v-if="hasLoan" class="panel" :aria-label="t('Explanation')" style="padding: 12px 14px 14px; display: flex; flex-direction: column; gap: 10px">
            <div class="panel-head">
              <h2>{{ t('What changed, and why it matters for repayment') }}</h2>
              <span v-if="data.narrative?.markdown" class="ctx">{{ data.narrative.mode === 'llm' ? t('AI explanation · every figure links to its source') : t('Template summary · AI draft not used') }}</span>
            </div>
            <NarrativeText v-if="data.narrative?.markdown && data.narrative.verified !== false" :markdown="data.narrative.markdown" />
            <p v-else class="muted">{{ t('No written explanation yet. It is written only for loans under Watch or Attention; the warning signs above are complete on their own.') }}</p>
          </section>

          <div class="footer-line">{{ data.calibration_note }} {{ t("Statuses are rule-based monitoring indicators, not a credit score. The officer records the review outcome; the system status stays separate from the officer's assessment.") }}</div>
        </div>

        <div class="ev-col stack" style="gap: 16px">
          <EvidencePane v-if="hasLoan || figureKeys.length || ratioKeys.length || data.alerts.length" :sticky="false" />
          <section v-if="data.timeline.length" class="panel" aria-label="How it developed" style="padding: 12px 14px">
            <div class="eyebrow" style="margin-bottom: 8px">{{ t('How it developed') }}</div>
            <div v-for="(t, i) in data.timeline" :key="i" class="tl">
              <span class="num muted" style="font-size: 12px">{{ fmtDate(t.date, { short: t.date.length > 7 }) }}</span>
              <span class="dotcol"><span class="dot" :class="t.status"></span><span v-if="i < data.timeline.length - 1" class="conn"></span></span>
              <span style="font-size: 12.5px; padding-bottom: 10px">{{ t.title }}</span>
            </div>
          </section>
          <section class="panel" :aria-label="t('Uploaded documents')" style="padding: 12px 14px 8px">
            <div class="eyebrow" style="margin-bottom: 4px">{{ t('Uploaded documents') }} · {{ data.documents.length }}</div>
            <div v-if="!data.documents.length" class="muted" style="font-size: 12.5px; padding: 4px 0 6px">{{ t('No documents yet. The business uploads them on converza.uz.') }}</div>
            <div v-for="(d, i) in data.documents" :key="i" class="doc" style="grid-template-columns: 1fr auto">
              <div style="min-width: 0">
                <div style="font-weight: 500">{{ d.title || docTypeShort(d.doc_type) }}</div>
                <div class="muted mono" style="font-size: 11.5px; overflow-wrap: anywhere">{{ d.filename }}</div>
                <div class="muted">{{ [d.uploaded_at || d.uploaded || d.date ? fmtDate(String(d.uploaded_at || d.uploaded || d.date).slice(0, 10)) : null, d.note].filter(Boolean).join(' · ') }}</div>
              </div>
              <span v-if="d.status" class="pill" :class="docStatusPill(d.status).cls">{{ docStatusPill(d.status).label }}</span>
            </div>
          </section>
        </div>
      </div>
    </template>

    <Modal v-if="showOutcome && data" :title="t('Record review outcome')" @close="showOutcome = false">
      <form class="stack" @submit.prevent="submitOutcome">
        <p class="muted" style="font-size: 13px">{{ t('Your assessment is stored with the evidence you opened ({n}). The monitoring status itself is not changed by this.', { n: ev.opened.length }) }}</p>
        <fieldset class="stack" style="border: 0; padding: 0; margin: 0; gap: 6px">
          <legend class="eyebrow" style="margin-bottom: 6px">{{ t('Outcome') }}</legend>
          <label v-for="o in OUTCOMES" :key="o.v" class="row" style="gap: 8px; font-size: 13px"><input v-model="outcome" type="radio" name="outcome" :value="o.v" /> {{ t(o.label) }}</label>
        </fieldset>
        <label class="stack" style="gap: 4px">
          <span class="eyebrow">{{ t('Reasoning') }}</span>
          <textarea v-model="reasoning" class="input" rows="5" :placeholder="t('What did you conclude from the alerts and evidence?')"></textarea>
          <span class="muted" style="font-size: 12px">{{ t('{n} / 20 characters minimum', { n: reasoning.trim().length }) }}</span>
        </label>
        <div v-if="outErr" class="error-box">{{ outErr }}</div>
        <div class="row">
          <button type="submit" class="btn btn-primary" :disabled="outBusy">{{ outBusy ? t('Recording…') : t('Record outcome') }}</button>
          <button type="button" class="btn" @click="showOutcome = false">{{ t('Cancel') }}</button>
        </div>
      </form>
    </Modal>
  </div>
</template>

<style scoped>
.reason { margin-top: 4px; font-size: 13px; color: var(--ink-2); }
.page-help { font-size: 13px; margin: -4px 0 12px; max-width: 760px; }
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
.howto { border: 1px solid var(--border); border-radius: var(--r-panel); background: var(--note-bg); padding: 8px 14px; font-size: 13px; }
.howto summary { cursor: pointer; font-weight: 600; color: var(--accent); }
.howto ul { margin: 8px 0 2px; padding-left: 18px; display: flex; flex-direction: column; gap: 4px; line-height: 1.5; }
</style>
