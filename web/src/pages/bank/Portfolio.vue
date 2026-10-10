<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api, errMessage } from '@/api/client'
import type { ApplicationListItem, PortfolioSummary } from '@/api/types'
import { fmtDate, fmtDateTime, hasUnit, severityPillClass, statusLabel, trueMinus } from '@/api/format'
import { useApp } from '@/stores/app'
import FigureStrip from '@/components/ui/FigureStrip.vue'
import FigureCell from '@/components/ui/FigureCell.vue'
import BarGroupChart from '@/components/charts/BarGroupChart.vue'
import { t, tn } from '@/i18n'

const app = useApp()
const s = ref<PortfolioSummary | null>(null)
const apps = ref<ApplicationListItem[]>([])
const loading = ref(true)
const err = ref('')

onMounted(async () => {
  const [a, b] = await Promise.allSettled([api.portfolio(), api.applications()])
  if (a.status === 'fulfilled') {
    s.value = a.value
    app.monitoringRunAt = a.value.run?.finished_at || null
  } else err.value = errMessage(a.reason)
  if (b.status === 'fulfilled') apps.value = b.value.items
  loading.value = false
})

const distBar = computed(() => (s.value?.status_distribution || []).filter((d) => d.n > 0))
const MARK: Record<string, string> = { stable: 'var(--stable-mark)', watch: 'var(--watch-mark)', attn: 'var(--attn-mark)' }
function tagColor(q: PortfolioSummary['queue'][number]) {
  if (q.kind === 'application') return 'var(--info-fg)'
  return q.severity === 'attn' ? 'var(--attn-fg)' : q.severity === 'watch' ? 'var(--watch-fg)' : 'var(--ink-2)'
}
const QUEUE_SHOWN = 7
const showAllQueue = ref(false)
const queueRows = computed(() => (showAllQueue.value ? s.value?.queue || [] : (s.value?.queue || []).slice(0, QUEUE_SHOWN)))

function queueLink(q: PortfolioSummary['queue'][number]) {
  return q.kind === 'application' ? `/bank/applications/${q.ref}` : `/bank/borrowers/${q.ref}`
}
function queuePillLabel(sev: string) {
  return ['stable', 'watch', 'attn'].includes(sev) ? statusLabel(sev) : sev === 'info' ? t('In review') : sev === 'neutral' ? t('Pending') : sev
}
function appPill(st: string) {
  const m: Record<string, { cls: string; label: string }> = {
    processing: { cls: 'pill-neutral', label: 'Processing documents' },
    in_review: { cls: 'pill-info', label: 'In review' },
    waiting_on_applicant: { cls: 'pill-watch', label: 'Waiting on applicant' },
    decided: { cls: 'pill-stable', label: 'Decision recorded' },
    ready: { cls: 'pill-stable', label: 'Ready for review' },
  }
  const p = m[st] || { cls: 'pill-info', label: st }
  return { cls: p.cls, label: t(p.label) }
}
const nextApp = computed(() => apps.value.find((a) => a.status === 'in_review' || a.status === 'ready') || apps.value[0])
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h1>{{ t('Portfolio overview') }}</h1>
        <p class="meta">
          <template v-if="s?.as_of">{{ t('Exposure as of {d}', { d: fmtDate(s.as_of) }) }} · </template>
          <template v-if="s?.run?.finished_at">{{ t('Monitoring run {d}', { d: fmtDateTime(s.run.finished_at) }) }} · </template>
          {{ t('Statuses computed from documents uploaded by borrowers') }}
        </p>
      </div>
      <div class="actions">
        <RouterLink v-if="nextApp" :to="`/bank/applications/${nextApp.number}`" class="btn">{{ t('Next application in queue') }}</RouterLink>
        <RouterLink to="/bank/borrowers?status=attn" class="btn btn-primary">{{ t('Review alerts') }}</RouterLink>
      </div>
    </div>

    <div v-if="loading" class="panel empty">{{ t('Loading portfolio…') }}</div>
    <div v-else-if="err && !s" class="error-box">{{ err }}</div>

    <template v-if="s">
      <div v-if="!s.run" class="note">{{ t('No monitoring run yet — statuses appear after the first run over uploaded statements.') }}</div>

      <FigureStrip :label="t('Portfolio figures')">
        <FigureCell :eyebrow="t('Businesses monitored')" :value="s.monitored">
          {{ s.run ? t('with a current monitoring status') : t('awaiting the first monitoring run') }}
        </FigureCell>
        <FigureCell :eyebrow="t('Outstanding exposure')" :value="s.exposure_display" :unit="hasUnit(s.exposure_display) ? '' : t(s.exposure_unit || 'bn UZS')">
          {{ t('Synthetic loan book (declared input)') }}
        </FigureCell>
        <FigureCell :eyebrow="t('Applications awaiting review')" :value="s.applications_awaiting">
          <span v-if="s.beyond_target" style="color: var(--watch-fg)">{{ t('{n} beyond the 5-day target', { n: s.beyond_target }) }}</span>
          <span v-else>{{ t('none beyond the 5-day target') }}</span>
          <template v-if="s.requested_display"> · {{ t('{amount} bn requested', { amount: s.requested_display }) }}</template>
        </FigureCell>
        <FigureCell :eyebrow="t('Emerging warning signs')" :value="s.warning.n" :unit="t('borrowers')" :flagged="s.warning.n > 0">
          {{ t('{amount} bn exposure · {pct}% of portfolio', { amount: s.warning.exposure_display, pct: s.warning.pct }) }}
        </FigureCell>
      </FigureStrip>

      <div class="grid-2">
        <section class="panel" :aria-label="t('Needs attention today')">
          <div class="panel-head" style="padding: 14px 16px 10px">
            <h2>{{ t('Needs attention today') }}</h2>
            <span class="ctx">{{ t('Ranked by severity, then exposure · {a} of {b} items', { a: queueRows.length, b: s.queue.length }) }}</span>
          </div>
          <div v-for="(q, i) in queueRows" :key="i" class="q">
            <span class="tag" :style="{ color: tagColor(q) }">{{ q.kind === 'application' ? t('Application') : t('Borrower') }}</span>
            <div style="min-width: 0">
              <RouterLink :to="queueLink(q)" style="font-weight: 600; text-decoration: none; color: var(--ink)">{{ q.name }}</RouterLink>
              <span class="pill" :class="severityPillClass(q.severity)" style="margin-left: 6px">{{ queuePillLabel(q.severity) }}</span>
              <div class="muted" style="margin-top: 2px">{{ q.reason }}</div>
            </div>
            <RouterLink :to="queueLink(q)" class="btn btn-sm">{{ t(q.action || 'Open') }}</RouterLink>
          </div>
          <div v-if="!s.queue.length" class="empty" style="border-top: 1px solid var(--border-row)">{{ t('Nothing needs attention today.') }}</div>
          <div v-else-if="s.queue.length > QUEUE_SHOWN" style="padding: 10px 16px; border-top: 1px solid var(--border-row)">
            <button type="button" class="linkbtn" @click="showAllQueue = !showAllQueue">{{ showAllQueue ? t('Show the first {n}', { n: QUEUE_SHOWN }) : t('Show all {n} items →', { n: s.queue.length }) }}</button>
          </div>
        </section>

        <div class="stack" style="gap: 16px">
          <section class="panel" :aria-label="t('Monitoring status')" style="padding: 14px 16px 16px; display: flex; flex-direction: column; gap: 10px">
            <div class="panel-head">
              <h2>{{ t('Monitoring status') }} · {{ tn(s.monitored, '{n} borrower', '{n} borrowers') }}</h2>
              <span class="ctx">{{ t('Rule-based indicator — every status carries its reason') }}</span>
            </div>
            <div v-if="distBar.length" style="display: flex; height: 16px; gap: 2px; border-radius: 3px; overflow: hidden" role="img" :aria-label="distBar.map((d) => `${d.label} ${d.n}`).join(', ')">
              <span v-for="d in distBar" :key="d.status" :style="{ flex: `${d.n} 1 0`, background: MARK[d.status] }"></span>
            </div>
            <div class="scrollbox"><table class="tbl">
              <thead><tr><th>{{ t('Status') }}</th><th>{{ t('Means') }}</th><th class="r">{{ t('Borrowers') }}</th><th class="r">{{ t('Exposure') }}</th></tr></thead>
              <tbody>
                <tr v-for="d in s.status_distribution" :key="d.status">
                  <td><span class="pill" :class="severityPillClass(d.status)">{{ statusLabel(d.status) }}</span></td>
                  <td class="muted">{{ d.means }}</td>
                  <td class="r num"><RouterLink :to="`/bank/borrowers?status=${d.status}`">{{ d.n }}</RouterLink></td>
                  <td class="r num">{{ d.exposure_display }}<template v-if="!hasUnit(d.exposure_display)"> {{ t('bn') }}</template></td>
                </tr>
              </tbody>
            </table></div>
            <p class="muted" style="font-size: 12px">{{ s.calibration_note || t('Thresholds are illustrative; calibration against bank history is pilot month 1.') }} {{ t('No numeric score is produced.') }}</p>
          </section>

          <section v-if="(s.trend || []).length >= 2" class="panel" :aria-label="t('Borrowers under Watch or Attention, by monitoring run')" style="padding: 14px 16px 12px; display: flex; flex-direction: column; gap: 6px">
            <div class="panel-head">
              <h2>{{ t('Borrowers under Watch or Attention, by monitoring run') }}</h2>
              <span class="ctx">{{ t('{n} runs', { n: s.trend!.length }) }}</span>
            </div>
            <BarGroupChart
              :labels="s.trend!.map((t) => fmtDate(t.as_of, { short: true }))"
              :a="s.trend!.map((t) => t.watch_plus_attn)"
              :a-name="t('Watch + Attention')"
              a-color="var(--watch-mark)"
              :summary="`Borrowers under Watch or Attention by run: ${s.trend!.map((t) => `${fmtDate(t.as_of)} ${t.watch_plus_attn}`).join(', ')}.`"
            />
          </section>
        </div>
      </div>

      <div class="grid-2">
        <section class="panel" :aria-label="t('New applications')">
          <div class="panel-head" style="padding: 14px 16px 8px">
            <h2>{{ t('New applications') }}</h2>
            <span class="ctx">{{ t('{n} in the queue', { n: apps.length }) }}</span>
          </div>
          <div class="scrollbox">
            <table class="tbl hover" style="min-width: 540px">
              <thead><tr><th>{{ t('Applicant') }}</th><th class="r">{{ t('Requested, mln') }}</th><th class="r">{{ t('Term') }}</th><th>{{ t('Received') }}</th><th>{{ t('Documents') }}</th><th>{{ t('Status') }}</th></tr></thead>
              <tbody>
                <tr v-for="a in apps.slice(0, 8)" :key="a.uuid">
                  <td><RouterLink :to="`/bank/applications/${a.number}`" style="font-weight: 500">{{ a.name }}</RouterLink><div class="muted">{{ a.industry }} · {{ a.number }}</div></td>
                  <td class="r num">{{ a.requested_display }}</td>
                  <td class="r num">{{ t('{n} m', { n: a.term_months }) }}</td>
                  <td class="num">{{ fmtDate(a.received_on, { short: true }) }}</td>
                  <td class="num">{{ a.docs }}</td>
                  <td><span class="pill" :class="appPill(a.status).cls">{{ appPill(a.status).label }}</span><div v-if="a.issues_label" class="muted" style="font-size: 12px; margin-top: 2px">{{ a.issues_label }}</div></td>
                </tr>
                <tr v-if="!apps.length"><td colspan="6" class="muted">{{ t('No applications yet.') }}</td></tr>
              </tbody>
            </table>
          </div>
          <div style="padding: 10px 16px; border-top: 1px solid var(--border-row)"><RouterLink to="/bank/applications" style="font-size: 13px">{{ t('All applications →') }}</RouterLink></div>
        </section>

        <section class="panel" :aria-label="t('Existing borrowers — status changes')">
          <div class="panel-head" style="padding: 14px 16px 8px">
            <h2>{{ t('Existing borrowers — status changes') }}</h2>
            <span class="ctx">{{ t('{n} changes since the previous run', { n: s.status_changes.length }) }}</span>
          </div>
          <div class="scrollbox">
            <table class="tbl" style="min-width: 600px">
              <thead><tr><th>{{ t('Borrower') }}</th><th>{{ t('Change') }}</th><th>{{ t('Date') }}</th><th>{{ t('Reason') }}</th></tr></thead>
              <tbody>
                <tr v-for="c in s.status_changes" :key="c.borrower_uuid + c.date">
                  <td>
                    <RouterLink v-if="c.loan_id" :to="`/bank/borrowers/${c.loan_id}`" style="font-weight: 500">{{ c.name }}</RouterLink>
                    <span v-else style="font-weight: 500">{{ c.name }}</span>
                    <div class="muted">{{ t('{amount} mln outstanding', { amount: trueMinus(c.outstanding_display) }) }}</div>
                  </td>
                  <td style="white-space: nowrap">
                    <template v-if="c.from"><span class="pill" :class="severityPillClass(c.from)">{{ statusLabel(c.from) }}</span> → </template>
                    <span class="pill" :class="severityPillClass(c.to)">{{ statusLabel(c.to) }}</span>
                  </td>
                  <td class="num">{{ fmtDate(c.date, { short: true }) }}</td>
                  <td class="muted">{{ c.reason }}</td>
                </tr>
                <tr v-if="!s.status_changes.length"><td colspan="4" class="muted">{{ t('No status changes since the previous monitoring run.') }}</td></tr>
              </tbody>
            </table>
          </div>
          <div style="padding: 10px 16px; border-top: 1px solid var(--border-row)"><RouterLink to="/bank/borrowers" style="font-size: 13px">{{ t('Open borrower portfolio →') }}</RouterLink></div>
        </section>
      </div>
    </template>
  </div>
</template>
