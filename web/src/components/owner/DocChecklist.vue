<script setup lang="ts">
// "What the bank needs": the required list from the backend (same counting as the bank's completeness rule),
// each item explained in plain words and ticked only when a matching document was uploaded.
import type { OwnerChecklist } from '@/api/types'
import { fmtPeriod } from '@/api/format'
import { t } from '@/i18n'

defineProps<{ checklist: OwnerChecklist | null }>()

const HELP: Record<string, { title: string; explain: string }> = {
  loan_application: {
    title: 'Loan application form',
    explain: "The bank's loan application form, filled in and signed: how much you need, for how long and what for.",
  },
  form1_fy: {
    title: 'Form 1 — Balance sheet, last financial year',
    explain: 'Бухгалтерский баланс (1-shakl): what the business owns and owes. The report for the last full year, as filed with the tax office.',
  },
  form1_half: {
    title: 'Form 1 — Balance sheet, latest half-year',
    explain: 'The same balance sheet for the most recent half-year.',
  },
  form2_fy: {
    title: 'Form 2 — Income statement, last financial year',
    explain: 'Отчёт о финансовых результатах (2-shakl): sales, costs and profit for the last full year.',
  },
  form2_half: {
    title: 'Form 2 — Income statement, latest half-year',
    explain: 'The same income statement for the most recent half-year.',
  },
  bank_statement: {
    title: 'Bank statement, last 8 months',
    explain: 'All payments in and out of your business account for the last 8 months. The Excel export from your internet bank works best.',
  },
  tax_declaration: {
    title: 'Tax declaration, latest quarter',
    explain: 'Your most recent quarterly tax declaration, as submitted.',
  },
}

function help(key: string, fallback: string) {
  const h = HELP[key]
  return h ? { title: t(h.title), explain: t(h.explain) } : { title: fallback, explain: '' }
}
</script>

<template>
  <div class="checklist">
    <div class="panel-head">
      <h2>{{ t('What the bank needs') }}</h2>
      <span v-if="checklist" class="ctx">{{ t('{a} of {b} provided', { a: checklist.present, b: checklist.total }) }}</span>
    </div>
    <p class="muted fmt">{{ t('Accepted: PDF, Excel (XLSX), or a scan or phone photo (JPG, PNG), up to 20 MB per file. Converza recognises each document by itself; file names do not matter.') }}</p>
    <ul v-if="checklist" class="items">
      <li v-for="it in checklist.items" :key="it.key" :class="{ done: it.state === 'ready' }">
        <span class="mark" :class="it.state" aria-hidden="true"></span>
        <div class="body">
          <div class="row" style="gap: 8px; justify-content: space-between; flex-wrap: wrap">
            <span class="title">{{ help(it.key, it.title).title }}</span>
            <span class="state">{{ it.state === 'ready' ? t('Provided') : it.state === 'reading' ? t('Reading…') : t('Not uploaded yet') }}</span>
          </div>
          <div class="muted explain">{{ help(it.key, it.title).explain }}</div>
          <div v-if="it.document" class="muted file">
            <span class="mono">{{ it.document.filename }}</span><template v-if="it.document.period_start || it.document.period_end"> · <span class="num">{{ fmtPeriod(it.document.period_start, it.document.period_end) }}</span></template>
          </div>
        </div>
      </li>
    </ul>
    <p v-else class="muted" style="font-size: 13px">{{ t('Loading…') }}</p>
  </div>
</template>

<style scoped>
.checklist { display: flex; flex-direction: column; gap: 8px; }
.fmt { font-size: 12px; }
.items { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; }
.items li { display: grid; grid-template-columns: 16px 1fr; gap: 10px; padding: 8px 0; border-top: 1px solid var(--border-row); }
.mark { width: 14px; height: 14px; margin-top: 2px; border: 1.5px solid var(--border-strong); border-radius: 3px; position: relative; }
.mark.ready { background: var(--stable-fg); border-color: var(--stable-fg); }
.mark.ready::after { content: ''; position: absolute; left: 3.5px; top: 0.5px; width: 4px; height: 8px; border: solid var(--surface); border-width: 0 2px 2px 0; transform: rotate(45deg); }
.mark.reading { border-color: var(--info-fg); border-style: dashed; }
.title { font-size: 13.5px; font-weight: 500; }
.state { font-size: 12px; color: var(--ink-muted); }
li.done .state { color: var(--stable-fg); font-weight: 500; }
.explain { font-size: 12.5px; margin-top: 2px; }
.file { font-size: 12px; margin-top: 3px; overflow-wrap: anywhere; }
</style>
