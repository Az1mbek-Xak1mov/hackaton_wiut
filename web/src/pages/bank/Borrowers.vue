<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, errMessage } from '@/api/client'
import type { BorrowerList } from '@/api/types'
import { fmtDate, fmtSignedPct, severityPillClass, statusLabel, thresholdText, trueMinus } from '@/api/format'

const route = useRoute()
const router = useRouter()
const data = ref<BorrowerList | null>(null)
const loading = ref(true)
const err = ref('')
const industry = ref('')
const region = ref('')
const q = ref('')

const status = computed(() => (typeof route.query.status === 'string' ? route.query.status : 'all'))

async function load() {
  loading.value = true
  try {
    data.value = await api.borrowers(status.value)
    err.value = ''
  } catch (e) {
    err.value = errMessage(e)
  } finally {
    loading.value = false
  }
}
watch(status, load, { immediate: true })

function setStatus(s: string) {
  router.replace({ query: s === 'all' ? {} : { status: s } })
}

const industries = computed(() => [...new Set((data.value?.items || []).map((i) => i.industry).filter(Boolean))].sort())
const regions = computed(() => [...new Set((data.value?.items || []).map((i) => i.region).filter(Boolean))].sort())
const rows = computed(() => {
  const needle = q.value.trim().toLowerCase()
  return (data.value?.items || []).filter(
    (r) =>
      (!industry.value || r.industry === industry.value) &&
      (!region.value || r.region === region.value) &&
      (!needle || r.name.toLowerCase().includes(needle) || r.loan_id.toLowerCase().includes(needle)),
  )
})

function trendClass(v: number | null) {
  if (v == null) return 'muted'
  if (v <= -15) return 'down-bad'
  if (v < 0) return 'up-bad'
  if (v > 0) return 'up-good'
  return 'muted'
}
const thresholdLines = computed(() => thresholdText(data.value?.thresholds))

const CHIPS = [
  { k: 'all', label: 'All' },
  { k: 'stable', label: 'Stable' },
  { k: 'watch', label: 'Watch' },
  { k: 'attn', label: 'Attention' },
] as const
</script>

<template>
  <div class="page">
    <Teleport to="#side-extra" defer>
      <div class="side-note">
        <div class="eyebrow" style="margin-bottom: 6px">How statuses are set</div>
        <p><strong>Stable</strong> — no indicator crossed its threshold in the last 2 periods.</p>
        <p><strong>Watch</strong> — one indicator crossed, or the latest statement is late.</p>
        <p><strong>Attention</strong> — two or more crossed, or an installment was paid late.</p>
        <p class="muted">Indicators: revenue vs prior period, receivables vs sales, payables growth, cash coverage of the next installment, payment punctuality, statement timeliness.</p>
        <template v-if="thresholdLines.length">
          <div class="eyebrow" style="margin-top: 4px">Thresholds in the latest run</div>
          <p v-for="(t, i) in thresholdLines" :key="i" class="muted">{{ t }}</p>
        </template>
        <p class="muted">{{ data?.calibration_note || 'Thresholds are illustrative; calibration against bank history is pilot month 1.' }} No numeric score is produced.</p>
      </div>
    </Teleport>

    <div class="page-head">
      <div>
        <h1>Borrower portfolio</h1>
        <p class="meta">
          <template v-if="data">{{ data.counts.all }} business borrowers · </template>monitoring computed from uploaded statements
        </p>
      </div>
    </div>

    <section class="panel" aria-label="Borrowers">
      <div style="padding: 12px 14px; border-bottom: 1px solid var(--border-row); display: flex; flex-wrap: wrap; gap: 10px; align-items: center">
        <div class="row" style="gap: 6px" role="group" aria-label="Filter by monitoring status">
          <button v-for="c in CHIPS" :key="c.k" type="button" class="chip" :class="{ on: status === c.k }" :aria-pressed="status === c.k" @click="setStatus(c.k)">
            {{ c.label }} <span v-if="data" class="n">{{ data.counts[c.k] }}</span>
          </button>
        </div>
        <div style="flex: 1"></div>
        <label class="sr-only" for="ind">Industry</label>
        <select id="ind" v-model="industry" class="select"><option value="">All industries</option><option v-for="i in industries" :key="i">{{ i }}</option></select>
        <label class="sr-only" for="reg">Region</label>
        <select id="reg" v-model="region" class="select"><option value="">All regions</option><option v-for="r in regions" :key="r">{{ r }}</option></select>
        <label class="sr-only" for="find">Search borrowers</label>
        <input id="find" v-model="q" type="search" class="input" placeholder="Name or loan id" style="width: 180px" />
      </div>
      <div v-if="loading && !data" class="empty">Loading borrowers…</div>
      <div v-else-if="err" class="error-box" style="margin: 12px">{{ err }}</div>
      <div v-else class="scrollbox">
        <table class="tbl hover" style="min-width: 1080px">
          <thead>
            <tr><th>Business</th><th>Industry · region</th><th class="r">Outstanding, mln</th><th class="r">Revenue vs prior period</th><th class="r">Cash coverage</th><th>Latest period</th><th>Status · reason</th><th>Updated</th></tr>
          </thead>
          <tbody>
            <tr v-for="r in rows" :key="r.uuid" class="clickable" @click="router.push(`/bank/borrowers/${r.loan_id}`)">
              <td><RouterLink :to="`/bank/borrowers/${r.loan_id}`" style="font-weight: 500" @click.stop>{{ r.name }}</RouterLink><div class="muted" style="font-size: 12px">{{ r.loan_id }}</div></td>
              <td>{{ r.industry }}<div class="muted" style="font-size: 12px">{{ r.region }}</div></td>
              <td class="r num">{{ trueMinus(r.outstanding_display) }}</td>
              <td class="r num" :class="trendClass(r.trend_pct)">{{ r.trend_display && r.trend_display !== 'n/a' ? trueMinus(r.trend_display) : fmtSignedPct(r.trend_pct) }}</td>
              <td class="r num">{{ r.coverage_display || '—' }}</td>
              <td class="num">{{ r.latest_period || '—' }}</td>
              <td><span class="pill" :class="severityPillClass(r.status)">{{ statusLabel(r.status) }}</span><div class="muted" style="font-size: 12px; margin-top: 3px; max-width: 320px">{{ r.reason }}</div></td>
              <td class="num muted">{{ fmtDate(r.updated, { short: true }) }}</td>
            </tr>
            <tr v-if="!rows.length"><td colspan="8" class="muted">{{ data?.counts.all ? 'No borrower matches these filters.' : 'No monitoring run yet — borrowers appear after their statements are processed.' }}</td></tr>
          </tbody>
        </table>
      </div>
      <div class="muted" style="padding: 10px 14px; border-top: 1px solid var(--border-row); font-size: 12px">
        Showing {{ rows.length }} of {{ data?.counts.all ?? 0 }} · sorted by status severity, then exposure. Cash coverage = month-end cash ÷ next installment.
      </div>
    </section>
  </div>
</template>

<style scoped>
.side-note { margin-top: 24px; padding: 0 12px; font-size: 12px; display: flex; flex-direction: column; gap: 6px; }
</style>
