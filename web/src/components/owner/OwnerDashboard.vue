<script setup lang="ts">
// The owner's own business dashboard. Every number is a stored fact from their uploaded documents
// (GET /owner/dashboard); charts only rescale those values to million UZS for drawing.
import { computed, onMounted, ref } from 'vue'
import { errMessage, request } from '@/api/client'
import type { Fact } from '@/api/types'
import { useEvidence } from '@/stores/evidence'
import BarGroupChart from '@/components/charts/BarGroupChart.vue'
import LineChart from '@/components/charts/LineChart.vue'
import FigureStrip from '@/components/ui/FigureStrip.vue'
import FigureCell from '@/components/ui/FigureCell.vue'
import EvidenceChip from '@/components/evidence/EvidenceChip.vue'
import { fmtAxis } from '@/components/charts/nice'
import { t } from '@/i18n'

interface Dash {
  months: { month: string; money_in: string | null; money_out: string | null; balance_end: string | null }[]
  periods: { period: string; label: string; revenue: string | null; net_profit: string | null }[]
  ratios: { field: string; name: string; explain: string; fact: string | null }[]
  cash_on_hand: string | null
  has: { bank_statement: boolean; form2: boolean; ratios: boolean }
  facts: Record<string, Fact>
}

const ev = useEvidence()
const d = ref<Dash | null>(null)
const err = ref('')
const loading = ref(true)

async function load() {
  try {
    d.value = await request<Dash>('/owner/dashboard')
    ev.register(d.value.facts)
    err.value = ''
  } catch (e) {
    err.value = errMessage(e)
  } finally {
    loading.value = false
  }
}
onMounted(load)
defineExpose({ reload: load })

const F = (k: string | null | undefined): Fact | null => (k && d.value ? d.value.facts[k] || null : null)
// display scaling only: the stored value converted to million UZS for drawing
function mln(k: string | null | undefined): number | null {
  const f = F(k)
  if (!f) return null
  const u = String(f.unit)
  if (u === 'kUZS') return f.value / 1000
  if (u === 'UZS') return f.value / 1_000_000
  if (u === 'mUZS' || u === 'mlnUZS') return f.value
  return null
}
const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const monLabel = (ym: string) => `${t(MON[Number(ym.slice(5, 7)) - 1] || ym)} ${ym.slice(2, 4)}`
const src = (k: string | null | undefined) => F(k)?.document?.filename || ''
const disp = (v: number | null) => (v == null ? null : fmtAxis(v))

const months = computed(() => d.value?.months || [])
const lastMonth = computed(() => [...months.value].reverse().find((m) => m.money_in || m.money_out) || null)
const periods = computed(() => d.value?.periods || [])
const lastPeriod = computed(() => [...periods.value].reverse().find((p) => p.revenue) || null)
const balances = computed(() => months.value.filter((m) => m.balance_end))
const ratiosShown = computed(() => (d.value?.ratios || []).filter((r) => r.fact))

const flowSummary = computed(() => {
  const m = lastMonth.value
  if (!m) return ''
  return t('Money in and out of your bank account by month; latest {m}: in {a}, out {b} mln UZS.', {
    m: monLabel(m.month), a: disp(mln(m.money_in)) ?? '—', b: disp(mln(m.money_out)) ?? '—',
  })
})
</script>

<template>
  <div class="stack" style="gap: 14px">
    <div v-if="err" class="error-box">{{ err }}</div>
    <p v-else-if="loading" class="muted">{{ t('Loading your figures…') }}</p>

    <template v-else-if="d">
      <!-- headline figures, each pointing at its source -->
      <FigureStrip :label="t('Your business at a glance')">
        <FigureCell :eyebrow="t('Cash on the account')" :unit="F(d.cash_on_hand)?.display_unit">
          <template #value><EvidenceChip v-if="d.cash_on_hand" :fact-key="d.cash_on_hand" /><span v-else class="muted na">{{ t('n/a — upload a bank statement') }}</span></template>
          <template v-if="d.cash_on_hand">{{ t('End of {m}', { m: monLabel(F(d.cash_on_hand)?.period_label || '') }) }} · {{ t('from: {doc}', { doc: src(d.cash_on_hand) }) }}</template>
        </FigureCell>
        <FigureCell :eyebrow="lastMonth ? t('Money in, {m}', { m: monLabel(lastMonth.month) }) : t('Money in, last month')" :unit="F(lastMonth?.money_in)?.display_unit">
          <template #value><EvidenceChip v-if="lastMonth?.money_in" :fact-key="lastMonth.money_in" /><span v-else class="muted na">{{ t('n/a — upload a bank statement') }}</span></template>
          <template v-if="lastMonth?.money_in">{{ t('from: {doc}', { doc: src(lastMonth.money_in) }) }}</template>
        </FigureCell>
        <FigureCell :eyebrow="lastMonth ? t('Money out, {m}', { m: monLabel(lastMonth.month) }) : t('Money out, last month')" :unit="F(lastMonth?.money_out)?.display_unit">
          <template #value><EvidenceChip v-if="lastMonth?.money_out" :fact-key="lastMonth.money_out" /><span v-else class="muted na">{{ t('n/a — upload a bank statement') }}</span></template>
          <template v-if="lastMonth?.money_out">{{ t('from: {doc}', { doc: src(lastMonth.money_out) }) }}</template>
        </FigureCell>
        <FigureCell :eyebrow="lastPeriod ? t('Sales, {p}', { p: lastPeriod.label }) : t('Sales')" :unit="F(lastPeriod?.revenue)?.display_unit">
          <template #value><EvidenceChip v-if="lastPeriod?.revenue" :fact-key="lastPeriod.revenue" /><span v-else class="muted na">{{ t('n/a — upload Form 2') }}</span></template>
          <template v-if="lastPeriod?.revenue">{{ t('from: {doc}', { doc: src(lastPeriod.revenue) }) }}</template>
        </FigureCell>
      </FigureStrip>

      <section class="panel chart-panel" :aria-label="t('Money in and out')">
        <div class="panel-head"><h2>{{ t('Money in and out, by month') }}</h2><span class="ctx">{{ t('mln UZS · from your bank statement') }}</span></div>
        <BarGroupChart
          v-if="months.length"
          :labels="months.map((m) => monLabel(m.month))"
          :a="months.map((m) => mln(m.money_in))"
          :b="months.map((m) => mln(m.money_out))"
          :a-name="t('Money in')"
          :b-name="t('Money out')"
          :summary="flowSummary"
        />
        <p v-else class="muted na">{{ t('n/a — upload a bank statement to see money in and out each month.') }}</p>
      </section>

      <div class="two">
        <section class="panel chart-panel" :aria-label="t('Sales and profit')">
          <div class="panel-head"><h2>{{ t('Sales and profit') }}</h2><span class="ctx">{{ t('mln UZS · from Form 2') }}</span></div>
          <BarGroupChart
            v-if="periods.length"
            :labels="periods.map((p) => p.label)"
            :a="periods.map((p) => mln(p.revenue))"
            :b="periods.map((p) => mln(p.net_profit))"
            :a-name="t('Sales (revenue)')"
            :b-name="t('Net profit')"
            :summary="t('Sales and net profit per reported period, from Form 2.')"
          />
          <p v-else class="muted na">{{ t('n/a — upload Form 2 (income statement) to see sales and profit.') }}</p>
          <p v-if="periods.length > 1" class="muted foot">{{ t('Periods differ in length (full year vs half-year); compare like with like.') }}</p>
        </section>

        <section class="panel chart-panel" :aria-label="t('Cash on the account')">
          <div class="panel-head"><h2>{{ t('Cash on the account') }}</h2><span class="ctx">{{ t('mln UZS · month end') }}</span></div>
          <div v-if="balances.length" class="legend" aria-hidden="true"><span><i></i>{{ t('Balance at month end') }}</span></div>
          <LineChart
            v-if="balances.length"
            :labels="balances.map((m) => monLabel(m.month))"
            :values="balances.map((m) => mln(m.balance_end))"
            :height="200"
            :summary="t('Account balance at the end of each month, from your bank statement.')"
          />
          <p v-else class="muted na">{{ t('n/a — upload a bank statement to see your month-end balance.') }}</p>
        </section>
      </div>

      <section class="panel" :aria-label="t('Health checks in plain words')">
        <div class="panel-head" style="padding: 12px 14px 8px"><h2>{{ t('Health checks in plain words') }}</h2><span class="ctx">{{ t('computed from Form 1 and Form 2') }}</span></div>
        <table v-if="ratiosShown.length" class="tbl">
          <tbody>
            <tr v-for="r in ratiosShown" :key="r.field">
              <td>
                <div>{{ t(r.name) }}</div>
                <div class="muted" style="font-size: 12px">{{ t(r.explain) }}</div>
              </td>
              <td class="num" style="white-space: nowrap; text-align: right">
                <EvidenceChip :fact-key="r.fact!" /> <span class="muted">{{ F(r.fact)?.display_unit }}</span>
                <div class="muted" style="font-size: 12px">{{ F(r.fact)?.period_label }}</div>
              </td>
            </tr>
          </tbody>
        </table>
        <p v-else class="muted na" style="padding: 0 14px 14px">{{ t('n/a — upload Form 1 and Form 2 and send an application; these are computed from them.') }}</p>
      </section>
    </template>
  </div>
</template>

<style scoped>
.chart-panel { padding: 12px 14px; display: flex; flex-direction: column; gap: 8px; }
.two { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
@media (max-width: 900px) { .two { grid-template-columns: 1fr; } }
.na { font-size: 13px; }
.figstrip .na { font-size: 14px; font-weight: 400; }
.foot { font-size: 12px; }
.legend { display: flex; justify-content: flex-end; font-size: 12px; }
.legend span { display: inline-flex; align-items: center; gap: 6px; }
.legend i { width: 10px; height: 10px; border-radius: 2px; display: inline-block; background: var(--series-1); }
</style>
