<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { api } from '@/api/client'
import { t } from '@/i18n'
import HeroScene from '@/components/HeroScene.vue'

// Gentle fade-in of sections as they scroll into view (skipped when reduced motion is requested).
const root = ref<HTMLElement | null>(null)
let io: IntersectionObserver | null = null
onMounted(() => {
  const els = root.value?.querySelectorAll<HTMLElement>('.reveal') ?? []
  const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
  if (reduce || typeof IntersectionObserver === 'undefined') {
    els.forEach((el) => el.classList.add('in'))
    return
  }
  io = new IntersectionObserver(
    (entries) => entries.forEach((e) => { if (e.isIntersecting) { e.target.classList.add('in'); io?.unobserve(e.target) } }),
    { threshold: 0.12 },
  )
  els.forEach((el) => io!.observe(el))
})
onBeforeUnmount(() => io?.disconnect())

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
  const d = ev.value
  const h = d?.headline
  if (!h) return []
  const rows: { label: string; value: string; note: string }[] = []
  const add = (key: string, label: string, note: string) => {
    if (h[key] != null) rows.push({ label: t(label), value: fmt(h[key]), note: t(note) })
  }
  const dt = d.document_type as any[] | undefined
  if (dt?.length) {
    const ok = dt.reduce((a, r) => a + (r.correct || 0), 0)
    const all = dt.reduce((a, r) => a + (r.documents || 0), 0)
    rows.push({ label: t('Recognises which document it is'), value: t('{a} of {b}', { a: ok, b: all }), note: t('documents recognised correctly') })
  }
  add('Form 1 field F1', 'Reads the lines of the balance sheet (Форма 1)', 'F1 score, 1 = perfect')
  add('Form 2 field F1', 'Reads the lines of the income statement (Форма 2)', 'F1 score, 1 = perfect')
  const cells = (d.field_extraction as any[] | undefined)?.filter((r) => r.variant === 'all').reduce((a, r) => a + (r.cells || 0), 0)
  if (h['Wrong values shown without a low-confidence flag'] != null)
    rows.push({ label: t('Wrong values shown without a warning'), value: fmt(h['Wrong values shown without a low-confidence flag']), note: cells ? t('out of {n} values read; the weak spot is blurred scans', { n: cells }) : t('our main known weakness') })
  add('Contradiction detection recall (micro)', 'Finds figures that do not agree between documents', 'share of planted problems found')
  add('Contradiction detection precision (micro)', 'Of the problems it raises, the share that are real', 'the rest are false alarms the officer dismisses')
  add('Hard cases passed', 'Hard cases: rotated pages, stamps, blurred photos, English IFRS, password-protected PDF', 'built by hand')
  const e2e = d.latency_production?.public_uploads_end_to_end as any[] | undefined
  for (const [path, label] of [['PDF text layer', 'From upload to result: PDF with text'], ['OCR (scanned PDF)', 'From upload to result: scanned PDF'], ['OCR (photo/image)', 'From upload to result: phone photo']]) {
    const r = e2e?.find((x) => x.path === path)
    if (r) rows.push({ label: t(label), value: `${(r.p50_ms / 1000).toFixed(1)} s`, note: t('median of {n} public uploads on our server (4 vCPU, no GPU)', { n: r.documents }) })
  }
  return rows
})
const dataset = computed(() => (ev.value ? t('{n} synthetic documents in {b} loan files that we generated and labelled; accuracy on real bank documents is measured in pilot month 1.', { n: ev.value.n_documents ?? '—', b: ev.value.n_bundles ?? '—' }) : ''))
</script>

<template>
  <div ref="root" class="page landing">
    <section class="hero-band">
      <div class="hero-block">
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
      </div>
      <HeroScene class="hero-scene" />
    </section>

    <section class="block reveal">
      <h2>{{ t('How it works') }}</h2>
      <ol class="how">
        <li>
          <div class="step-top"><span class="n">1</span><svg class="pic" viewBox="0 0 40 40" aria-hidden="true"><path d="M10 5h14l7 7v23H10z" /><path d="M24 5v7h7" /><path d="M20.5 30V18M15.5 23l5-5 5 5" /></svg></div>
          <div><b>{{ t('The business uploads its documents') }}</b><p>{{ t('On converza.uz. A checklist shows which documents the bank needs and which are already there.') }}</p></div>
        </li>
        <li>
          <div class="step-top"><span class="n">2</span><svg class="pic" viewBox="0 0 40 40" aria-hidden="true"><path d="M8 5h14l6 6v12" /><path d="M8 5v30h12" /><path d="M12 14h9M12 19h11M12 24h6" /><circle cx="27" cy="29" r="5.5" /><path d="M31 33l4 4" /></svg></div>
          <div><b>{{ t('Converza reads and checks them') }}</b><p>{{ t('Every figure is taken from the page, the forms are checked against each other and against the bank statement, and anything that does not add up becomes an issue with its source.') }}</p></div>
        </li>
        <li>
          <div class="step-top"><span class="n">3</span><svg class="pic" viewBox="0 0 40 40" aria-hidden="true"><rect x="6" y="8" width="28" height="24" rx="2" /><path d="M6 15h28" /><path d="M13 23l4 4 9-9" /></svg></div>
          <div><b>{{ t('A bank officer decides') }}</b><p>{{ t('On app.converza.uz the officer sees the checked file, clicks any number to see the page it came from, and records a decision. The business sees the answer and the bank’s message.') }}</p></div>
        </li>
      </ol>
    </section>

    <section class="block two reveal">
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

    <section class="block reveal">
      <h2>{{ t('Measured, not claimed') }}</h2>
      <p v-if="!ev" class="muted">{{ t('Loading the latest evaluation…') }}</p>
      <table v-else class="tbl measured">
        <tbody>
          <tr v-for="r in measured" :key="r.label">
            <td>{{ r.label }}</td>
            <td class="r num val">{{ r.value }}</td>
            <td class="muted note">{{ r.note }}</td>
          </tr>
        </tbody>
      </table>
      <p v-if="ev" class="muted small">{{ dataset }} <RouterLink to="/metrics">{{ t('All results and known failures →') }}</RouterLink></p>
    </section>

    <section class="block reveal">
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
.landing { padding-top: 24px; display: flex; flex-direction: column; gap: 40px; max-width: 1120px; }
.hero-band { background: var(--accent-hover); color: var(--surface); border-radius: var(--r-phone-card); padding: 40px 36px; display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 470px); gap: 32px; align-items: center; overflow: hidden; }
.hero-block { display: flex; flex-direction: column; gap: 14px; }
.hero-band .eyebrow { color: var(--accent-panel-border); }
.hero { font-size: 36px; font-weight: 600; letter-spacing: -.015em; line-height: 1.2; color: var(--surface); }
.lead { font-size: 15.5px; line-height: 1.55; color: var(--accent-tint); max-width: 620px; }
.cta { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; margin-top: 6px; }
.hero-band .btn-primary { background: var(--surface); color: var(--accent-hover); border-color: var(--surface); }
.hero-band .btn-primary:hover { background: var(--accent-tint); }
.hero-band .btn:not(.btn-primary) { background: transparent; color: var(--surface); border-color: var(--accent-border); }
.hero-band .btn:not(.btn-primary):hover { background: var(--accent); }
.officer { font-size: 14px; margin-left: 6px; color: var(--surface); text-decoration: underline; text-underline-offset: 3px; }
.reveal { opacity: 0; transform: translateY(14px); transition: opacity .6s ease, transform .6s ease; }
.reveal.in { opacity: 1; transform: none; }
.step-top { display: flex; align-items: center; justify-content: space-between; }
.pic { width: 36px; height: 36px; fill: none; stroke: var(--accent); stroke-width: 1.6; stroke-linecap: round; stroke-linejoin: round; }
.block h2 { font-size: 17px; font-weight: 600; margin-bottom: 10px; }
.block ul { margin: 0; padding-left: 18px; display: flex; flex-direction: column; gap: 6px; font-size: 14px; color: var(--ink-2); line-height: 1.5; }
.how { list-style: none; margin: 0; padding: 0; display: grid; grid-template-columns: repeat(3, 1fr); gap: 20px; }
.how li { display: flex; flex-direction: column; gap: 10px; padding-top: 14px; border-top: 2px solid var(--accent); }
.how .n { width: 28px; height: 28px; border-radius: 50%; border: 1px solid var(--accent); color: var(--accent); display: inline-flex; align-items: center; justify-content: center; font-weight: 600; font-size: 13px; }
.how b { font-size: 15px; display: block; margin-bottom: 4px; }
.how p { font-size: 14px; color: var(--ink-2); line-height: 1.5; margin: 0; }
.two { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
.two > div { border: 1px solid var(--border); border-radius: 8px; padding: 16px 18px; background: var(--surface); }
.measured { max-width: 760px; }
.measured .val { font-weight: 600; white-space: nowrap; }
.measured .note { font-size: 12px; }
.small { font-size: 12.5px; margin-top: 8px; }
@media (max-width: 720px) {
  .landing { padding-top: 8px; gap: 24px; }
  .hero-band { grid-template-columns: 1fr; padding: 24px 18px; gap: 24px; }
  .hero-scene { margin: 0 auto; }
  .hero-block { min-width: 0; }
  .hero { overflow-wrap: anywhere; }
  .hero { font-size: 24px; }
  .lead { font-size: 15px; }
  .two, .how { grid-template-columns: 1fr; }
  .measured .note { display: none; }
  .officer { margin-left: 0; }
}
</style>
