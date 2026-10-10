<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api } from '@/api/client'
import { t } from '@/i18n'

// Every number on this page is read from the evaluation result file served by /metrics/eval; none is typed in here.
const ev = ref<Record<string, any> | null>(null)
onMounted(async () => {
  try {
    ev.value = await api.metricsEval()
  } catch {
    ev.value = null
  }
})

const fmt = (v: unknown) => (typeof v === 'number' ? (Number.isInteger(v) ? String(v) : v.toFixed(3).replace(/0+$/, '')) : String(v))

const measured = computed(() => {
  const h = ev.value?.headline
  if (!h) return []
  const rows: { label: string; value: string; note: string }[] = []
  const add = (key: string, label: string, note: string) => {
    if (h[key] != null) rows.push({ label, value: fmt(h[key]), note })
  }
  add('Document type accuracy', 'Recognises which document it is', 'accuracy, 1 = always right')
  add('Form 1 field F1', 'Reads the lines of the balance sheet (Форма 1)', 'F1 score, 1 = perfect')
  add('Form 2 field F1', 'Reads the lines of the income statement (Форма 2)', 'F1 score, 1 = perfect')
  add('Contradiction detection recall (micro)', 'Finds figures that do not agree between documents', 'share of planted problems found')
  add('Contradiction detection precision (micro)', 'Of the problems it raises, the share that are real', 'the rest are false alarms the officer dismisses')
  add('Hard cases passed', 'Hard cases: scans, blurred photos, English IFRS, wrong periods', 'built by hand')
  const lp = ev.value?.latency_production?.by_doc_type as any[] | undefined
  const textPdf = lp?.find((r) => r.doc_type === 'form1' && /text/i.test(r.path))
  if (textPdf) rows.push({ label: t('Time to read a Форма 1 PDF on our server'), value: `${(textPdf.p50_ms / 1000).toFixed(1)} s`, note: t('median of {n} documents, 4 vCPU, no GPU', { n: textPdf.documents }) })
  const scan = lp?.find((r) => r.doc_type === 'form1' && /OCR/i.test(r.path))
  if (scan) rows.push({ label: t('Time to read a scanned Форма 1'), value: `${(scan.p50_ms / 1000).toFixed(1)} s`, note: t('median of {n} documents', { n: scan.documents }) })
  return rows
})
const dataset = computed(() => (ev.value ? t('{n} synthetic documents in {b} loan files that we generated and labelled; accuracy on real bank documents is measured in pilot month 1.', { n: ev.value.n_documents ?? '—', b: ev.value.n_bundles ?? '—' }) : ''))
</script>

<template>
  <div class="page landing">
    <section class="hero-block">
      <div class="eyebrow">{{ t('For MKBANK SME lending · pilot prototype') }}</div>
      <h1 class="hero">{{ t('Loan documents in. Checked figures out.') }}</h1>
      <p class="lead">
        {{ t('A small business uploads its balance sheet (Форма 1), income statement (Форма 2) and bank statements: PDF, scan, phone photo or Excel, in Uzbek or Russian. Converza reads every line, checks the documents against each other and shows the bank officer what does not add up, with a link to the exact page.') }}
      </p>
      <div class="cta">
        <RouterLink to="/analyse" class="btn btn-primary">{{ t('Try it on a document — no account needed') }}</RouterLink>
        <RouterLink to="/register" class="btn">{{ t('I run a business: register') }}</RouterLink>
        <a href="https://app.converza.uz" class="officer">{{ t('I am a bank officer → app.converza.uz') }}</a>
      </div>
    </section>

    <section class="block">
      <h2>{{ t('How it works') }}</h2>
      <ol class="steps">
        <li>
          <span class="n">1</span>
          <div><b>{{ t('The business uploads its documents') }}</b><p>{{ t('On converza.uz. A checklist shows which documents the bank needs and which are already there.') }}</p></div>
        </li>
        <li>
          <span class="n">2</span>
          <div><b>{{ t('Converza reads and checks them') }}</b><p>{{ t('Every figure is taken from the page, the forms are checked against each other and against the bank statement, and anything that does not add up becomes an issue with its source.') }}</p></div>
        </li>
        <li>
          <span class="n">3</span>
          <div><b>{{ t('A bank officer decides') }}</b><p>{{ t('On app.converza.uz the officer sees the checked file, clicks any number to see the page it came from, and records a decision. The business sees the answer and the bank’s message.') }}</p></div>
        </li>
      </ol>
    </section>

    <section class="block two">
      <div>
        <h2>{{ t('For the business') }}</h2>
        <ul>
          <li>{{ t('Know exactly which documents to bring') }}</li>
          <li>{{ t('See your own figures and ask questions about your cash') }}</li>
          <li>{{ t('Follow your application and read the bank’s answer') }}</li>
        </ul>
      </div>
      <div>
        <h2>{{ t('For the bank') }}</h2>
        <ul>
          <li>{{ t('No retyping of figures from paper forms') }}</li>
          <li>{{ t('Problems are found before the officer starts reading') }}</li>
          <li>{{ t('Existing borrowers are watched every quarter for warning signs') }}</li>
        </ul>
      </div>
    </section>

    <section class="block">
      <h2>{{ t('Measured, not claimed') }}</h2>
      <p v-if="!ev" class="muted">{{ t('Loading the latest evaluation…') }}</p>
      <table v-else class="tbl measured">
        <tbody>
          <tr v-for="r in measured" :key="r.label">
            <td>{{ t(r.label) }}</td>
            <td class="r num val">{{ r.value }}</td>
            <td class="muted note">{{ t(r.note) }}</td>
          </tr>
        </tbody>
      </table>
      <p v-if="ev" class="muted small">{{ dataset }} <RouterLink to="/metrics">{{ t('All results and known failures →') }}</RouterLink></p>
    </section>

    <section class="block">
      <h2>{{ t('What Converza does not do') }}</h2>
      <ul>
        <li>{{ t('It never approves or rejects a loan. Only a bank officer records a decision, with the reasoning and the evidence they opened.') }}</li>
        <li>{{ t('It gives no credit score. Warning statuses come from published rules, each with its reason.') }}</li>
        <li>{{ t('The AI may not state a number that is not in the documents; every sentence is checked before it is shown. With the AI switched off, reading and checking work the same.') }}</li>
        <li>{{ t('Customer documents can stay inside the bank: the production design runs on the bank’s own server, with a local AI model or with the AI switched off. This public prototype uses an external AI service on synthetic documents only.') }}</li>
      </ul>
    </section>
  </div>
</template>

<style scoped>
.landing { padding-top: 24px; display: flex; flex-direction: column; gap: 32px; max-width: 880px; }
.hero-block { display: flex; flex-direction: column; gap: 12px; }
.hero { font-size: 32px; font-weight: 600; letter-spacing: -.015em; line-height: 1.2; }
.lead { font-size: 16px; line-height: 1.55; color: var(--ink-2); max-width: 720px; }
.cta { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; margin-top: 6px; }
.officer { font-size: 14px; margin-left: 6px; }
.block h2 { font-size: 17px; font-weight: 600; margin-bottom: 10px; }
.block ul { margin: 0; padding-left: 18px; display: flex; flex-direction: column; gap: 6px; font-size: 14px; color: var(--ink-2); line-height: 1.5; }
.steps { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 14px; }
.steps li { display: grid; grid-template-columns: 28px 1fr; gap: 12px; align-items: start; }
.steps .n { width: 28px; height: 28px; border-radius: 50%; border: 1px solid var(--accent); color: var(--accent); display: inline-flex; align-items: center; justify-content: center; font-weight: 600; font-size: 13px; }
.steps b { font-size: 14.5px; }
.steps p { font-size: 14px; color: var(--ink-2); line-height: 1.5; margin-top: 2px; }
.two { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; }
.measured { max-width: 760px; }
.measured .val { font-weight: 600; white-space: nowrap; }
.measured .note { font-size: 12px; }
.small { font-size: 12.5px; margin-top: 8px; }
@media (max-width: 720px) {
  .landing { padding-top: 8px; gap: 24px; }
  .hero { font-size: 24px; }
  .lead { font-size: 15px; }
  .two { grid-template-columns: 1fr; }
  .measured .note { display: none; }
  .officer { margin-left: 0; }
}
</style>
