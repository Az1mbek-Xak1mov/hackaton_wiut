<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { api, errMessage } from '@/api/client'
import type { ApplicationReview } from '@/api/types'
import { confPill, docStatusPill, fileBadge, fmtDate, fmtDateTime, fmtTime, hasUnit, ratioHelp } from '@/api/format'
import { useEvidence } from '@/stores/evidence'
import { useApp } from '@/stores/app'
import EvidencePane from '@/components/evidence/EvidencePane.vue'
import EvidenceChip from '@/components/evidence/EvidenceChip.vue'
import FindingRow from '@/components/evidence/FindingRow.vue'
import InlineEvidence from '@/components/evidence/InlineEvidence'
import NarrativeText from '@/components/evidence/NarrativeText'
import Modal from '@/components/ui/Modal.vue'
import { t, tn } from '@/i18n'

const route = useRoute()
const ev = useEvidence()
const app = useApp()
const number = computed(() => String(route.params.number))

const data = ref<ApplicationReview | null>(null)
const loading = ref(true)
const err = ref('')
let timer: ReturnType<typeof setTimeout> | null = null

async function load(quiet = false) {
  if (timer) {
    clearTimeout(timer)
    timer = null
  }
  if (!quiet) loading.value = true
  try {
    const r = await api.applicationReview(number.value)
    data.value = r
    ev.register(r.facts)
    err.value = ''
    const firstEv = r.issues.find((i) => i.evidence?.length)?.evidence[0]
    const firstFig = r.figures.flatMap((f) => Object.values(f.cells)).find((k) => !!k) || null
    ev.selectDefault(firstEv || firstFig)
    if (r.application.status === 'processing') timer = setTimeout(() => load(true), 3000)
  } catch (e) {
    err.value = errMessage(e)
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  ev.clear()
  load()
})

// The LLM switch in the top bar: regenerate the summary so the change is visible here at once.
const regenerating = ref(false)
const regenErr = ref('')
async function regenerate() {
  regenerating.value = true
  regenErr.value = ''
  try {
    let job = await api.regenerateNarrative(number.value)
    const started = Date.now()
    while ((job.status === 'queued' || job.status === 'running') && Date.now() - started < 60_000) {
      await new Promise((r) => setTimeout(r, 1000))
      job = await api.job(job.uuid)
    }
    if (job.status === 'failed') regenErr.value = job.error || t('Regeneration failed.')
    await load(true)
  } catch (e) {
    regenErr.value = errMessage(e)
  } finally {
    regenerating.value = false
  }
}
watch(() => app.llmChanges, () => regenerate())
onBeforeUnmount(() => timer && clearTimeout(timer))

const statusPill = computed(() => {
  const a = data.value?.application
  if (!a) return null
  const day = a.sla_day != null && a.sla_days != null ? ` · ${t('working day {d} of {n}', { d: a.sla_day, n: a.sla_days })}` : ''
  switch (a.status) {
    case 'processing':
      return { cls: 'pill-neutral', label: t('Reading documents') }
    case 'in_review':
      return { cls: a.sla_day != null && a.sla_days != null && a.sla_day > a.sla_days ? 'pill-watch' : 'pill-info', label: `${t('Waiting for your review')}${day}` }
    case 'waiting_on_applicant':
      return { cls: 'pill-watch', label: `${t('Waiting for the applicant')}${day}` }
    case 'decided':
      return { cls: 'pill-stable', label: t('Decision recorded') }
    default:
      return { cls: 'pill-info', label: a.status.replace(/_/g, ' ') }
  }
})

const openIssues = computed(() => (data.value?.issues || []).filter((i) => i.state === 'open'))
const issuePill = computed(() => {
  const n = openIssues.value.length
  if (!n) return null
  const worst = openIssues.value.some((i) => i.severity === 'attn') ? 'pill-attn' : openIssues.value.some((i) => i.severity === 'watch') ? 'pill-watch' : 'pill-neutral'
  return { cls: worst, label: tn(n, '{n} issue', '{n} issues') }
})

const figureCols = computed(() => {
  if (data.value?.columns?.length) return data.value.columns.map((c) => c.key)
  const cols: string[] = []
  for (const f of data.value?.figures || []) for (const k of Object.keys(f.cells)) if (!cols.includes(k)) cols.push(k)
  return cols
})
function colHead(k: string) {
  const c = data.value?.columns?.find((x) => x.key === k)
  if (c) return c.label
  const m = /^fy(\d{4})$/i.exec(k)
  if (m) return `FY ${m[1]}`
  const h = /^h([12])_(\d{4})$/i.exec(k)
  if (h) return `H${h[1]} ${h[2]}`
  const q = /^q([1-4])_(\d{4})$/i.exec(k)
  if (q) return `Q${q[1]} ${q[2]}`
  return k.replace(/_/g, ' ').toUpperCase()
}

const docsReceived = computed(() => (data.value?.documents || []).filter((d) => d.status !== 'missing').length)
const docsMissing = computed(() => (data.value?.documents || []).filter((d) => d.status === 'missing').length)
const docsProblem = computed(() => (data.value?.documents || []).filter((d) => d.status === 'failed' || d.status === 'needs clarification').length)
const missingTitles = computed(() => (data.value?.documents || []).filter((d) => d.status === 'missing').map((d) => d.title))
const decided = computed(() => data.value?.application.status === 'decided')
type DecisionOut = { outcome: string; reasoning: string; officer: string; created_at: string | null }
const lastDecision = computed<DecisionOut | null>(() => ((data.value as any)?.decisions as DecisionOut[] | undefined)?.[0] || null)
const OUTCOME_TEXT: Record<string, string> = {
  recommend: 'You recommended approval',
  decline: 'You recommended decline',
  request_info: 'You asked the applicant for more information',
}

const showRejected = ref(false)
const narrativeLabel = computed(() => {
  const n = data.value?.narrative
  if (!n || !n.mode) return ''
  if (n.mode === 'llm') {
    const when = n.accepted_at ? ` · ${t('generated {when}', { when: `${fmtDate(n.accepted_at.slice(0, 10), { short: true })}, ${fmtTime(n.accepted_at)}` })}` : ''
    const att = n.attempts > 1 ? ` · ${t('accepted on attempt {n} (earlier drafts rejected by the verifier)', { n: n.attempts })}` : ''
    return `${t('AI analysis')}${when}${att} · ${t('every figure links to its source')}`
  }
  return n.attempts > 0
    ? `${t('Template summary')} · ${tn(n.attempts, '{n} AI draft was rejected by the citation verifier', '{n} AI drafts were rejected by the citation verifier')}`
    : `${t('Template summary')} · ${t('the language model is switched off; issues, figures and ratios are unchanged')}`
})

// ----- decision modal -----
const showDecision = ref(false)
const outcome = ref('')
const reasoning = ref('')
const decBusy = ref(false)
const decErr = ref('')
const decDone = ref('')
const OUTCOMES = [
  { v: 'recommend', label: 'Recommend for approval' },
  { v: 'decline', label: 'Recommend decline' },
  { v: 'request_info', label: 'Request more information' },
]
async function submitDecision() {
  decErr.value = ''
  if (!outcome.value) {
    decErr.value = t('Choose an outcome.')
    return
  }
  if (reasoning.value.trim().length < 20) {
    decErr.value = t('Write your reasoning (at least 20 characters). It is stored with the evidence you reviewed.')
    return
  }
  decBusy.value = true
  try {
    await api.recordDecision(number.value, { outcome: outcome.value, reasoning: reasoning.value.trim(), evidence_reviewed: ev.opened })
    decDone.value = t('Decision recorded with the evidence you opened.')
    showDecision.value = false
    await load(true)
  } catch (e) {
    decErr.value = errMessage(e)
  } finally {
    decBusy.value = false
  }
}
</script>

<template>
  <div class="page">
    <div class="crumbs"><RouterLink to="/bank/applications">{{ t('Applications') }}</RouterLink> / {{ number }}</div>

    <div v-if="loading && !data" class="panel empty">{{ t('Loading the application file…') }}</div>
    <div v-else-if="err && !data" class="error-box">
      {{ err }} <RouterLink to="/bank/applications">{{ t('Back to applications') }}</RouterLink>
    </div>

    <template v-if="data">
      <div class="page-head" style="align-items: flex-start">
        <div>
          <div class="row" style="gap: 10px">
            <h1>{{ data.applicant.name }}</h1>
            <span v-if="statusPill" class="pill" :class="statusPill.cls">{{ statusPill.label }}</span>
            <span v-if="issuePill" class="pill" :class="issuePill.cls">{{ issuePill.label }}</span>
          </div>
          <p class="meta">
            <template v-if="data.applicant.industry">{{ data.applicant.industry }}</template>
            <template v-if="data.applicant.region"> · {{ data.applicant.region }}</template>
            <template v-if="data.applicant.stir"> · {{ t('STIR') }} <span class="num">{{ data.applicant.stir }}</span></template>
            <template v-if="data.applicant.since"> · {{ t('operating since {y}', { y: data.applicant.since }) }}</template>
            <template v-if="data.applicant.employees"> · {{ tn(data.applicant.employees, '{n} employee', '{n} employees') }}</template>
          </p>
        </div>
        <div class="actions">
          <button type="button" class="btn" :disabled="regenerating" @click="regenerate">{{ regenerating ? t('Regenerating…') : t('Regenerate summary') }}</button>
          <a v-if="!decided" href="#decision" class="btn btn-primary">{{ t('Your decision') }}</a>
        </div>
      </div>
      <div v-if="decDone" class="note">{{ decDone }}</div>
      <div v-if="data.application.status === 'processing'" class="note">
        {{ t('Documents are still being processed. Figures, issues and ratios appear here as each pipeline stage finishes; this page refreshes itself.') }}
      </div>

      <section class="panel" style="padding: 12px 16px; display: flex; flex-direction: column; gap: 12px" :aria-label="t('Request summary')">
        <p class="summary-line">
          {{ t('{name} asks for {amount} mln UZS', { name: data.applicant.name, amount: data.request.amount_display && data.request.amount_display !== 'n/a' ? data.request.amount_display : '—' }) }}<template v-if="data.request.term_months"> {{ t('over {term}', { term: tn(data.request.term_months, '{n} month', '{n} months') }) }}</template>.
          {{ tn(docsReceived, '{n} document received', '{n} documents received') }}<template v-if="docsMissing">, {{ tn(docsMissing, '{n} required document missing', '{n} required documents missing') }}</template>.
          <template v-if="data.application.status === 'processing'">{{ t('Documents are still being read.') }}</template>
          <template v-else-if="openIssues.length">{{ tn(openIssues.length, '{n} issue to check before you decide.', '{n} issues to check before you decide.') }}</template>
          <template v-else>{{ t('The automatic checks found no open issue.') }}</template>
        </p>
        <div class="kv">
          <div><div class="eyebrow">{{ t('Requested') }}</div><div class="num" style="font-size: 18px; font-weight: 500">{{ data.request.amount_display || '—' }} <span v-if="data.request.amount_display && !hasUnit(data.request.amount_display)" class="muted" style="font-size: 12px; font-weight: 400">{{ t('mln UZS') }}</span></div></div>
          <div><div class="eyebrow">{{ t('Term & repayment') }}</div><div style="font-size: 14px">{{ data.request.term_months ? tn(data.request.term_months, '{n} month', '{n} months') : '—' }}</div><div v-if="data.request.installment_display" class="muted num">{{ t('{amount} mln / month', { amount: data.request.installment_display }) }}</div></div>
          <div><div class="eyebrow">{{ t('Purpose') }}</div><div style="font-size: 14px">{{ data.request.purpose || '—' }}</div></div>
          <div><div class="eyebrow">{{ t('Proposed collateral') }}</div><div style="font-size: 14px">{{ data.request.collateral || '—' }}</div></div>
          <div><div class="eyebrow">{{ t('Received') }}</div><div style="font-size: 14px" class="num">{{ fmtDate(data.application.received_on) }}</div><div class="muted">{{ data.application.analysed_at ? t('analysed {when}', { when: fmtDateTime(data.application.analysed_at) }) : t('analysis pending') }}</div></div>
          <div>
            <div class="eyebrow">{{ t('Documents') }}</div>
            <div style="font-size: 14px"><a href="#documents">{{ t('{n} received', { n: docsReceived }) }}</a><template v-if="docsMissing">, <span style="color: var(--watch-fg)">{{ t('{n} missing', { n: docsMissing }) }}</span></template></div>
            <div v-if="missingTitles.length" class="muted" style="font-size: 12px">{{ t('Missing: {list}', { list: missingTitles.join('; ') }) }}</div>
            <div v-else-if="docsProblem" class="muted" style="font-size: 12px">{{ tn(docsProblem, '{n} could not be read fully', '{n} could not be read fully') }}</div>
          </div>
          <div>
            <div class="eyebrow">{{ t('Issues to check') }}</div>
            <div style="font-size: 14px"><a href="#issues">{{ openIssues.length ? tn(openIssues.length, '{n} open', '{n} open') : t('None open') }}</a></div>
            <div v-if="data.issues.length > openIssues.length" class="muted" style="font-size: 12px">{{ t('{n} already concluded', { n: data.issues.length - openIssues.length }) }}</div>
          </div>
        </div>
      </section>

      <nav class="tabs" :aria-label="t('Application sections')">
        <a href="#issues">{{ t('Issues') }} · {{ data.issues.length }}</a>
        <a href="#figures">{{ t('Figures') }}</a>
        <a href="#ratios">{{ t('Ratios') }}</a>
        <a href="#analysis">{{ t('AI analysis') }}</a>
        <a href="#documents">{{ t('Documents') }} · {{ data.documents.length }}</a>
        <a href="#decision">{{ t('Your decision') }}</a>
      </nav>

      <div class="twopane">
        <div class="main-col">
          <section id="issues" class="panel" :aria-label="t('Issues to resolve before a decision')">
            <div class="panel-head" style="padding: 12px 14px 8px">
              <h2>{{ t('Issues to resolve before a decision') }}</h2>
              <span class="ctx">{{ t('Found by automatic cross-checks between the documents. For each one, mark it resolved or not relevant and write why.') }}</span>
            </div>
            <FindingRow v-for="i in data.issues" :key="i.uuid" :finding="i" actions @changed="load(true)" />
            <div v-if="!data.issues.length" class="empty" style="border-top: 1px solid var(--border-row)">
              {{ data.application.status === 'processing' ? t('No rule fired on the documents received so far.') : t('No rule fired on the documents received.') }}
            </div>
          </section>

          <section id="figures" class="panel" :aria-label="t('Extracted figures')">
            <div class="panel-head" style="padding: 12px 14px 8px">
              <h2>{{ t('Extracted figures') }}</h2>
              <span class="ctx">{{ t('mln UZS · click a figure to see where it came from') }}</span>
            </div>
            <div class="scrollbox">
              <table class="tbl" style="min-width: 560px">
                <thead>
                  <tr>
                    <th>{{ t('Figure') }}</th>
                    <th v-for="c in figureCols" :key="c" class="r">{{ colHead(c) }}</th>
                    <th>{{ t('Source') }}</th>
                    <th :title="t('How sure the system is that it read the number correctly. Below 80% needs checking against the page.')">{{ t('Reading confidence') }}</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="(f, i) in data.figures" :key="i">
                    <td :style="f.indent ? { paddingLeft: '22px' } : undefined">{{ f.label }}</td>
                    <td v-for="c in figureCols" :key="c" class="r">
                      <EvidenceChip v-if="f.cells[c]" :fact-key="f.cells[c]!" />
                      <span v-else class="muted">—</span>
                    </td>
                    <td class="muted">{{ f.source }}</td>
                    <td>
                      <span v-if="f.flag" class="pill pill-attn">{{ f.flag }}</span>
                      <span v-else-if="confPill(f.confidence)" class="pill" :class="confPill(f.confidence)!.cls">{{ confPill(f.confidence)!.label }}</span>
                    </td>
                  </tr>
                  <tr v-if="!data.figures.length">
                    <td :colspan="figureCols.length + 3" class="muted">{{ t('Not available yet — the applicant has not uploaded Form 1 (balance sheet) and Form 2 (income statement).') }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </section>

          <section id="ratios" class="panel" :aria-label="t('Ratios')" style="padding: 12px 14px 14px; display: flex; flex-direction: column; gap: 10px">
            <div class="panel-head">
              <h2>{{ t('Ratios') }}</h2>
              <span class="ctx">{{ t('Computed deterministically from the extracted figures · click a value for its formula') }}</span>
            </div>
            <div v-if="data.ratios.length" style="display: grid; grid-template-columns: repeat(auto-fit, minmax(min(160px, 100%), 1fr)); gap: 10px">
              <div v-for="r in data.ratios" :key="r.label" class="ratio" :class="{ flag: !!r.flag }">
                <span class="eyebrow" :title="ratioHelp(r.label)">{{ r.label }}</span>
                <span class="v num">
                  <template v-if="r.fact_keys && r.fact_keys.length === 2"><EvidenceChip :fact-key="r.fact_keys[0]" /> <span class="muted" style="font-size: 13px; font-weight: 400">→</span> <EvidenceChip :fact-key="r.fact_keys[1]" /></template>
                  <EvidenceChip v-else-if="r.fact_key" :fact-key="r.fact_key" :text="r.value_display" />
                  <template v-else>{{ r.value_display }}</template>
                </span>
                <span class="muted" style="font-size: 12px"><InlineEvidence :text="r.note" /><template v-if="r.period"> · {{ r.period }}</template></span>
                <span v-if="ratioHelp(r.label)" class="muted help">{{ ratioHelp(r.label) }}</span>
              </div>
            </div>
            <div v-else class="muted">{{ t('Not available yet — ratios need both Form 1 (balance sheet) and Form 2 (income statement).') }}</div>
          </section>

          <section id="analysis" class="panel" :aria-label="t('Preliminary assessment and AI analysis')">
            <div v-if="data.indicator" style="padding: 12px 14px; border-bottom: 1px solid var(--border-row); display: flex; flex-wrap: wrap; gap: 12px; align-items: center; justify-content: space-between">
              <div>
                <div class="eyebrow">{{ t('Preliminary repayment-capacity indicator') }}</div>
                <div style="font-size: 16px; font-weight: 600; margin-top: 4px">{{ data.indicator.label }}</div>
              </div>
              <div class="muted" style="font-size: 12px; max-width: 360px">
                <div>{{ data.indicator.disclaimer }}</div>
                <div v-if="data.indicator.rule" style="margin-top: 4px">{{ data.indicator.rule }}</div>
              </div>
            </div>
            <div v-if="data.indicator && (data.indicator.supports.length || data.indicator.weighs_against.length)" style="padding: 12px 14px; display: grid; grid-template-columns: repeat(auto-fit, minmax(min(240px, 100%), 1fr)); gap: 12px; border-bottom: 1px solid var(--border-row)">
              <div>
                <div class="eyebrow" style="color: var(--stable-fg); margin-bottom: 6px">{{ t('Supports repayment') }}</div>
                <ul class="bullets">
                  <li v-for="(s, i) in data.indicator.supports" :key="i"><InlineEvidence :text="s" /></li>
                  <li v-if="!data.indicator.supports.length" class="muted">{{ t('Nothing recorded') }}</li>
                </ul>
              </div>
              <div>
                <div class="eyebrow" style="color: var(--attn-fg); margin-bottom: 6px">{{ t('Weighs against') }}</div>
                <ul class="bullets">
                  <li v-for="(s, i) in data.indicator.weighs_against" :key="i"><InlineEvidence :text="s" /></li>
                  <li v-if="!data.indicator.weighs_against.length" class="muted">{{ t('Nothing recorded') }}</li>
                </ul>
              </div>
            </div>
            <div style="padding: 12px 14px 14px; display: flex; flex-direction: column; gap: 10px">
              <div v-if="regenerating" class="note">{{ app.llm?.enabled ? t('Regenerating the summary with the language model on… Issues, figures and ratios above do not change.') : t('Regenerating the summary with the language model off… Issues, figures and ratios above do not change.') }}</div>
              <div v-if="regenErr" class="error-box">{{ regenErr }}</div>
              <template v-if="data.narrative && data.narrative.markdown && data.narrative.verified !== false">
                <div class="eyebrow">{{ narrativeLabel }}</div>
                <NarrativeText :markdown="data.narrative.markdown" />
              </template>
              <div v-else class="muted">{{ t('The written summary appears once all documents are analysed. Issues, figures and ratios above do not depend on it.') }}</div>
              <div v-if="data.narrative?.rejected?.length" class="stack" style="gap: 6px">
                <button type="button" class="linkbtn" style="align-self: flex-start; font-size: 12px" @click="showRejected = !showRejected">
                  {{ showRejected ? t('Hide') : t('Show') }} · {{ tn(data.narrative.rejected.length, '{n} draft rejected by the citation verifier', '{n} drafts rejected by the citation verifier') }}
                </button>
                <div v-if="showRejected" class="scrollbox">
                  <table class="tbl">
                    <thead><tr><th>{{ t('Attempt') }}</th><th>{{ t('Numbers not found in the facts') }}</th><th>{{ t('Sentences without a citation') }}</th><th>{{ t('Unknown fact ids') }}</th></tr></thead>
                    <tbody>
                      <tr v-for="r in data.narrative.rejected" :key="r.attempt + (r.at || '')">
                        <td class="num">{{ r.attempt }}</td>
                        <td class="mono" style="font-size: 12px">{{ r.unmatched.map((u: any) => (typeof u === 'object' ? u.text ?? JSON.stringify(u) : u)).join(', ') || '—' }}</td>
                        <td style="font-size: 12px">{{ r.uncited_sentences.length ? r.uncited_sentences.map((u: any) => (typeof u === 'object' ? u.text ?? JSON.stringify(u) : u)).join(' · ') : '—' }}</td>
                        <td class="mono" style="font-size: 12px">{{ r.unknown_ids.join(', ') || '—' }}</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          </section>

          <section id="documents" class="panel" :aria-label="t('Documents')" style="padding: 12px 14px 10px">
            <div class="panel-head" style="margin-bottom: 4px">
              <h2>{{ t('Documents') }} · {{ t('{n} received', { n: docsReceived }) }}<template v-if="docsMissing">, {{ t('{n} missing', { n: docsMissing }) }}</template></h2>
            </div>
            <div v-for="(d, i) in data.documents" :key="i" class="doc" :style="d.status === 'missing' ? { opacity: .85 } : undefined">
              <span class="ficon" :style="d.status === 'missing' ? { borderStyle: 'dashed' } : undefined">{{ d.status === 'missing' ? '—' : fileBadge(d.filename) }}</span>
              <div style="min-width: 0">
                <div style="font-weight: 500">{{ d.title }}</div>
                <div class="muted"><span v-if="d.filename" class="mono">{{ d.filename }}</span><template v-if="d.filename && d.note"> · </template>{{ d.note }}</div>
              </div>
              <span class="pill" :class="docStatusPill(d.status).cls">{{ docStatusPill(d.status).label }}</span>
            </div>
          </section>

          <section id="decision" class="panel" :aria-label="t('Your decision')" style="padding: 12px 14px 14px; display: flex; flex-direction: column; gap: 8px">
            <h2>{{ t('Your decision') }}</h2>
            <div v-if="lastDecision" class="note">
              <div style="font-weight: 600">{{ t(OUTCOME_TEXT[lastDecision.outcome] || lastDecision.outcome) }}</div>
              <div class="muted" style="font-size: 12px">{{ lastDecision.officer }}<template v-if="lastDecision.created_at"> · {{ fmtDateTime(lastDecision.created_at) }}</template></div>
              <p style="margin-top: 6px; white-space: pre-wrap">{{ lastDecision.reasoning }}</p>
              <p v-if="data.application.status === 'waiting_on_applicant'" class="muted" style="font-size: 12.5px; margin-top: 6px">{{ t('The applicant sees this message on converza.uz. When they add documents, the file is analysed again and comes back to your queue.') }}</p>
            </div>
            <template v-if="decided">
              <p>{{ t('A decision has been recorded for this application. See the review trail for who recorded it and when.') }}</p>
            </template>
            <template v-else>
              <p class="muted" style="font-size: 13px">{{ t('Converza does not approve or reject. When you have checked the issues and figures above, record one of: recommend for approval, recommend decline, or request more information. Your reasoning is stored with the evidence you opened ({n}).', { n: ev.opened.length }) }}</p>
              <p v-if="openIssues.length" class="muted" style="font-size: 12.5px; color: var(--watch-fg)">{{ tn(openIssues.length, '{n} issue is still open.', '{n} issues are still open.') }}</p>
              <div><button type="button" class="btn btn-primary" @click="showDecision = true">{{ t('Record your decision') }}</button></div>
            </template>
          </section>

          <div class="footer-line">{{ t("The system prepares the file; it does not approve or reject. The officer's decision and reasoning are recorded with the evidence reviewed.") }}</div>
        </div>

        <div class="ev-col">
          <EvidencePane>
            <template #footer>
              <div style="padding: 10px 14px 12px; border-top: 1px solid var(--border-row)">
                <div class="eyebrow" style="margin-bottom: 6px">{{ t('Review trail') }}</div>
                <div class="muted" style="font-size: 12px; display: flex; flex-direction: column; gap: 4px">
                  <span v-for="(tr, i) in data.review_trail" :key="i"><span class="num">{{ fmtTime(tr.at) || tr.at }}</span> · {{ tr.text }}</span>
                  <span v-if="!data.review_trail.length">{{ t('No actions recorded yet.') }}</span>
                </div>
              </div>
            </template>
          </EvidencePane>
        </div>
      </div>
    </template>

    <Modal v-if="showDecision && data" :title="t('Record your decision')" @close="showDecision = false">
      <form class="stack" @submit.prevent="submitDecision">
        <p class="muted" style="font-size: 13px">{{ t('Converza does not approve or reject. Your outcome and reasoning are stored with the evidence you opened on this page ({n}).', { n: ev.opened.length }) }}</p>
        <p class="muted" style="font-size: 13px">{{ t('The applicant will see your reasoning as a message from the bank, so write it in plain words.') }}</p>
        <fieldset class="stack" style="border: 0; padding: 0; margin: 0; gap: 6px">
          <legend class="eyebrow" style="margin-bottom: 6px">{{ t('Outcome') }}</legend>
          <label v-for="o in OUTCOMES" :key="o.v" class="row" style="gap: 8px; font-size: 13px">
            <input v-model="outcome" type="radio" name="outcome" :value="o.v" /> {{ t(o.label) }}
          </label>
        </fieldset>
        <label class="stack" style="gap: 4px">
          <span class="eyebrow">{{ t('Reasoning') }}</span>
          <textarea v-model="reasoning" class="input" rows="5" :placeholder="t('What did you conclude about each open issue, and why?')"></textarea>
          <span class="muted" style="font-size: 12px">{{ t('{n} / 20 characters minimum', { n: reasoning.trim().length }) }}</span>
        </label>
        <div v-if="ev.opened.length" class="row" style="gap: 6px">
          <span class="muted" style="font-size: 12px">{{ t('Evidence reviewed:') }}</span>
          <EvidenceChip v-for="k in ev.opened" :key="k" :fact-key="k" />
        </div>
        <div v-if="decErr" class="error-box">{{ decErr }}</div>
        <div class="row">
          <button type="submit" class="btn btn-primary" :disabled="decBusy">{{ decBusy ? t('Recording…') : t('Record decision') }}</button>
          <button type="button" class="btn" @click="showDecision = false">{{ t('Cancel') }}</button>
        </div>
      </form>
    </Modal>
  </div>
</template>

<style scoped>
.summary-line { font-size: 14px; line-height: 1.5; max-width: 860px; }
.help { font-size: 11.5px; }
</style>
