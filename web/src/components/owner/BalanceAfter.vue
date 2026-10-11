<script setup lang="ts">
// Cash on the account now + the loan = the balance once the money arrives. All three numbers come from the
// backend (month-end balance fact + application amount, added in Python); this only draws them.
import { computed } from 'vue'
import type { OwnerBalanceAfter } from '@/api/types'
import { fmtDate } from '@/api/format'
import { t } from '@/i18n'

const props = defineProps<{ data: OwnerBalanceAfter; preview?: boolean }>()

const W = 320
const LABEL = 92
const VAL = 70
const bars = computed(() => {
  const d = props.data
  const now = Math.max(0, d.cash_now_kuzs ?? 0)
  const after = Math.max(0, d.cash_after_kuzs ?? 0)
  const max = Math.max(now, after, 1)
  const span = W - LABEL - VAL
  return [
    { y: 4, label: t('Now'), w: Math.max(2, (now / max) * span), v: d.cash_now_display, fill: 'var(--border-strong)' },
    { y: 30, label: t('After the loan'), w: Math.max(2, (after / max) * span), v: d.cash_after_display, fill: 'var(--stable-mark)' },
  ]
})
const source = computed(() => {
  const f = props.data.cash_fact
  const file = f?.document?.filename || t('bank statement')
  return f?.page_n ? t('{file}, page {p}', { file, p: f.page_n }) : file
})
</script>

<template>
  <div class="ba">
    <div class="eyebrow">{{ preview ? t('Your balance if the loan is approved') : t('Your balance after the loan') }}</div>
    <template v-if="data.available">
      <p class="eq">
        {{ t('Cash on your account now') }} <strong class="num">{{ data.cash_now_display }}</strong>
        + {{ t('loan') }} <strong class="num">{{ data.loan_display }}</strong>
        = <strong class="num">{{ data.cash_after_display }}</strong> {{ t('mln UZS after the money arrives') }}
      </p>
      <svg :viewBox="`0 0 ${W} 52`" class="bars" role="img" :aria-label="t('Account balance now and after the loan, mln UZS')">
        <g v-for="b in bars" :key="b.y">
          <text :x="0" :y="b.y + 13" class="lbl">{{ b.label }}</text>
          <rect :x="LABEL" :y="b.y" :width="b.w" height="18" :fill="b.fill" rx="2" />
          <text :x="LABEL + b.w + 6" :y="b.y + 13" class="val">{{ b.v }}</text>
        </g>
      </svg>
      <p class="muted small">
        {{ t('Cash now: month-end balance for {m}, from {src}.', { m: fmtDate(data.as_of_month), src: source }) }}
        {{ t('The loan amount is the one on your application. Monthly repayments depend on the bank\'s rate and are not shown.') }}
      </p>
    </template>
    <p v-else class="muted small">{{ t('n/a — upload a bank statement to see your balance after the loan.') }}</p>
  </div>
</template>

<style scoped>
.ba { display: flex; flex-direction: column; gap: 6px; padding: 10px 12px; background: var(--surface); border: 1px solid var(--border); border-radius: var(--r-control); }
.eq { font-size: 13px; color: var(--ink); }
.num { font-variant-numeric: tabular-nums; }
.bars { width: 100%; max-width: 420px; height: auto; }
.lbl { font-size: 11px; fill: var(--ink-2); }
.val { font-size: 11px; font-weight: 600; fill: var(--ink); font-variant-numeric: tabular-nums; }
.small { font-size: 12px; }
</style>
