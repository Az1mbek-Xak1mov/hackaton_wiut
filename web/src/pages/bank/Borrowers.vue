<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, errMessage } from '@/api/client'
import type { BorrowerList } from '@/api/types'
import { fmtDate, fmtSignedPct, severityPillClass, statusLabel, trueMinus } from '@/api/format'
import StatusRules from '@/components/StatusRules.vue'
import { t, tn } from '@/i18n'

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
      (!needle || r.name.toLowerCase().includes(needle) || (r.loan_id || '').toLowerCase().includes(needle)),
  )
})

function trendClass(v: number | null) {
  if (v == null) return 'muted'
  if (v <= -15) return 'down-bad'
  if (v < 0) return 'up-bad'
  if (v > 0) return 'up-good'
  return 'muted'
}
const CHIPS = [
  { k: 'all', label: 'All' },
  { k: 'stable', label: 'Stable' },
  { k: 'watch', label: 'Watch' },
  { k: 'attn', label: 'Attention' },
  { k: 'not_monitored', label: 'No loan yet' },
] as const
function hasValue(v: string | null | undefined) {
  return !!v && v !== 'n/a'
}
function open(r: { loan_id: string | null; uuid: string }) {
  router.push(`/bank/borrowers/${r.loan_id || r.uuid}`)
}
</script>

<template>
  <div class="page">
    <Teleport to="#side-extra" defer>
      <div class="side-note"><StatusRules :thresholds="data?.thresholds" :note="data?.calibration_note" /></div>
    </Teleport>

    <div class="page-head">
      <div>
        <h1>{{ t('Borrower portfolio') }}</h1>
        <p class="meta">
          <template v-if="data">{{ tn(data.counts.all, '{n} business', '{n} businesses') }} · </template>{{ t('Every business with a loan or uploaded documents. Statuses come from fixed rules over their statements; open a row to see why and what to check.') }}
        </p>
      </div>
    </div>

    <div class="panel mobile-only rules-m">
      <StatusRules :thresholds="data?.thresholds" :note="data?.calibration_note" />
    </div>

    <section class="panel" :aria-label="t('Borrowers')">
      <div style="padding: 12px 14px; border-bottom: 1px solid var(--border-row); display: flex; flex-wrap: wrap; gap: 10px; align-items: center">
        <div class="row" style="gap: 6px" role="group" :aria-label="t('Filter by monitoring status')">
          <button v-for="c in CHIPS" :key="c.k" type="button" class="chip" :class="{ on: status === c.k }" :aria-pressed="status === c.k" @click="setStatus(c.k)">
            {{ t(c.label) }} <span v-if="data" class="n">{{ (data.counts as Record<string, number>)[c.k] ?? 0 }}</span>
          </button>
        </div>
        <div style="flex: 1"></div>
        <label class="sr-only" for="ind">{{ t('Industry') }}</label>
        <select id="ind" v-model="industry" class="select"><option value="">{{ t('All industries') }}</option><option v-for="i in industries" :key="i">{{ i }}</option></select>
        <label class="sr-only" for="reg">{{ t('Region') }}</label>
        <select id="reg" v-model="region" class="select"><option value="">{{ t('All regions') }}</option><option v-for="r in regions" :key="r">{{ r }}</option></select>
        <label class="sr-only" for="find">{{ t('Search borrowers') }}</label>
        <input id="find" v-model="q" type="search" class="input" :placeholder="t('Business name or loan number')" style="width: 180px" />
      </div>
      <div v-if="loading && !data" class="empty">{{ t('Loading borrowers…') }}</div>
      <div v-else-if="err" class="error-box" style="margin: 12px">{{ err }}</div>
      <div v-else class="scrollbox">
        <table class="tbl hover" style="min-width: 1080px">
          <thead>
            <tr>
              <th>{{ t('Business') }}</th>
              <th>{{ t('Industry · region') }}</th>
              <th class="r" :title="t('Amount still owed on the loan, million UZS')">{{ t('Loan balance, mln UZS') }}</th>
              <th class="r" :title="t('Revenue in the latest period compared with the period before, from the uploaded statements')">{{ t('Revenue change') }}</th>
              <th class="r" :title="t('Cash at month end divided by the next loan payment. 2.0× means the cash would cover the payment twice.')">{{ t('Cash vs next payment') }}</th>
              <th :title="t('Most recent period covered by an uploaded statement')">{{ t('Latest statement') }}</th>
              <th>{{ t('Status and why') }}</th>
              <th :title="t('Date of the last monitoring check')">{{ t('Last checked') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in rows" :key="r.uuid" class="clickable" @click="open(r)">
              <td>
                <RouterLink :to="`/bank/borrowers/${r.loan_id || r.uuid}`" style="font-weight: 500" @click.stop>{{ r.name }}</RouterLink>
                <div class="muted" style="font-size: 12px">{{ r.loan_id ? t('Loan {id}', { id: r.loan_id }) : t('No loan yet') }}</div>
              </td>
              <td>{{ r.industry || '—' }}<div class="muted" style="font-size: 12px">{{ r.region }}</div></td>
              <td class="r num">{{ r.loan_id ? trueMinus(r.outstanding_display) : '—' }}</td>
              <td class="r num" :class="trendClass(r.trend_pct)">
                <template v-if="hasValue(r.trend_display)">{{ trueMinus(r.trend_display) }}</template>
                <template v-else-if="r.trend_pct != null">{{ fmtSignedPct(r.trend_pct) }}</template>
                <span v-else class="muted" :title="t('Needs statements for two periods')">—</span>
              </td>
              <td class="r num">
                <template v-if="hasValue(r.coverage_display)">{{ r.coverage_display }}</template>
                <span v-else class="muted" :title="r.loan_id ? t('Needs a bank statement') : t('No loan payment to compare with')">—</span>
              </td>
              <td class="num">
                <template v-if="hasValue(r.latest_period)">{{ r.latest_period }}</template>
                <span v-else class="muted">{{ t('None uploaded') }}</span>
              </td>
              <td><span class="pill" :class="severityPillClass(r.status)">{{ statusLabel(r.status) }}</span><div class="muted" style="font-size: 12px; margin-top: 3px; max-width: 320px">{{ r.loan_id ? r.reason : t('Monitoring starts once a loan is disbursed. Open to see documents and applications.') }}</div></td>
              <td class="num muted">{{ r.loan_id ? fmtDate(r.updated, { short: true }) : '—' }}</td>
            </tr>
            <tr v-if="!rows.length"><td colspan="8" class="muted">{{ data?.counts.all ? t('No business matches these filters.') : t('No businesses yet. They appear here when a business registers on converza.uz and uploads documents, or when a loan is added.') }}</td></tr>
          </tbody>
        </table>
      </div>
      <div class="muted" style="padding: 10px 14px; border-top: 1px solid var(--border-row); font-size: 12px">
        {{ t('Showing {a} of {b} · most urgent first, then by loan size. “—” means the figure needs a document that has not been uploaded yet; hover it to see which.', { a: rows.length, b: data?.counts.all ?? 0 }) }}
      </div>
    </section>
  </div>
</template>

<style scoped>
.side-note { margin-top: 24px; padding: 0 12px; }
.rules-m { padding: 10px 14px; }
.rules-m summary { cursor: pointer; font-weight: 600; font-size: 13px; }
.rules-m[open] summary { margin-bottom: 8px; }
</style>
