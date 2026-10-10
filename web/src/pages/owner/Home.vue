<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { api, errMessage } from '@/api/client'
import type { DocumentOut, OwnerApplication } from '@/api/types'
import { fileBadge, fmtBytes, fmtDate, fmtDateTime, fmtPeriod, ownerDocStatus, ownerDocTypeLabel } from '@/api/format'
import { useAuth } from '@/stores/auth'
import { ownerApi, useApp } from '@/stores/app'
import Dropzone from '@/components/ui/Dropzone.vue'
import DocChecklist from '@/components/owner/DocChecklist.vue'
import StepLine from '@/components/owner/StepLine.vue'
import { t } from '@/i18n'

const auth = useAuth()
const app = useApp()

const files = ref<DocumentOut[]>([])
const business = ref('')
const apps = ref<OwnerApplication[]>([])
const loadErr = ref('')
const upErr = ref('')
const uploading = ref(0)
let timer: ReturnType<typeof setTimeout> | null = null
let appTimer: ReturnType<typeof setTimeout> | null = null

async function loadFiles() {
  try {
    const r = await api.ownerFiles()
    files.value = r.items
    app.ownerCoverage = { analysed: r.items.filter((d) => d.status === 'analyzed' || d.status === 'clarification').length, total: r.items.length }
    business.value = r.business?.name || ''
    loadErr.value = ''
  } catch (e) {
    loadErr.value = errMessage(e)
  }
  app.loadChecklist()
  if (timer) clearTimeout(timer)
  if (files.value.some((f) => f.status === 'queued' || f.status === 'processing')) timer = setTimeout(loadFiles, 2000)
}

async function loadApps() {
  try {
    const r = await api.ownerApplications()
    apps.value = Array.isArray(r) ? r : r.items || []
  } catch {
    apps.value = []
  }
  if (appTimer) clearTimeout(appTimer)
  if (apps.value.some((a) => a.status === 'processing')) appTimer = setTimeout(loadApps, 3000)
}

watch(
  () => auth.loggedIn,
  (v) => {
    if (v) {
      loadFiles()
      loadApps()
    }
  },
  { immediate: true },
)
onBeforeUnmount(() => {
  if (timer) clearTimeout(timer)
  if (appTimer) clearTimeout(appTimer)
})

async function upload(list: File[]) {
  upErr.value = ''
  for (const f of list) {
    if (f.size > 20 * 1024 * 1024) {
      upErr.value = t('{file} is {size}; the limit is 20 MB.', { file: f.name, size: fmtBytes(f.size) })
      continue
    }
    uploading.value++
    try {
      await api.ownerUpload(f)
    } catch (e) {
      upErr.value = `${f.name}: ${errMessage(e)}`
    } finally {
      uploading.value--
    }
  }
  await loadFiles()
  app.loadOwner()
}

// ----- apply for a loan -----
const amount = ref<number | null>(null)
const fmtUzs = (n: number) => Math.round(n).toLocaleString('en-US').replace(/,/g, ' ')
const amountHint = computed(() => {
  const a = amount.value
  if (!a || a <= 0) return { warn: false, text: t('In millions of UZS: 850 means 850 000 000 so\'m.') }
  if (a >= 1_000_000) return { warn: true, text: t("Looks like so'm. In millions this is {mln}.", { mln: String(a / 1_000_000) }) }
  return { warn: false, text: t("= {uzs} so'm", { uzs: fmtUzs(a * 1_000_000) }) }
})
const term = ref<number | null>(12)
const purpose = ref('')
const picked = ref<string[]>([])
const applying = ref(false)
const applyErr = ref('')
const applyDone = ref('')
const analysed = computed(() => files.value.filter((f) => f.status === 'analyzed' || f.status === 'clarification'))
watch(analysed, (list) => {
  // include every analysed document by default; the owner can untick any
  const known = new Set(picked.value)
  for (const d of list) if (!known.has(d.uuid)) picked.value.push(d.uuid)
})

async function apply() {
  applyErr.value = ''
  applyDone.value = ''
  if (!amount.value || amount.value <= 0) return (applyErr.value = t('Enter the amount you need.'))
  if (amount.value >= 1_000_000)
    return (applyErr.value = t("The amount is in millions of UZS. For {uzs} so'm enter {mln}.", { uzs: fmtUzs(amount.value), mln: String(amount.value / 1_000_000) }))
  if (!term.value || term.value < 1 || term.value > 120) return (applyErr.value = t('Enter a term between 1 and 120 months.'))
  if (purpose.value.trim().length < 3) return (applyErr.value = t('Describe the purpose of the loan.'))
  if (!picked.value.length) return (applyErr.value = t('Include at least one analysed document.'))
  applying.value = true
  try {
    const r = await api.ownerApply({
      requested_amount_mln: amount.value,
      term_months: term.value,
      purpose: purpose.value.trim(),
      document_uuids: picked.value,
    })
    applyDone.value = t('Application {n} sent to the bank. Its status appears below.', { n: r.number || '' })
    amount.value = null
    purpose.value = ''
    await loadApps()
  } catch (e) {
    applyErr.value = errMessage(e)
  } finally {
    applying.value = false
  }
}

// ----- application status in plain words -----
const STATUS: Record<string, { cls: string; label: string; explain: string }> = {
  processing: { cls: 'pill-neutral', label: 'Checking your documents', explain: 'Converza is reading the documents attached to this application before it goes to a bank officer.' },
  in_review: { cls: 'pill-info', label: 'A bank officer is reviewing', explain: 'You do not need to do anything now. The decision and any message from the bank will appear here.' },
  waiting_on_applicant: { cls: 'pill-watch', label: 'The bank needs more from you', explain: 'Read the message from the bank, upload what it asks for, then add the new documents to this application.' },
  decided: { cls: 'pill-stable', label: 'Decision made', explain: '' },
}
function appPill(a: OwnerApplication) {
  const p = STATUS[a.status] || { cls: 'pill-neutral', label: a.status, explain: '' }
  if (a.action_needed) return { cls: STATUS.waiting_on_applicant.cls, label: t(STATUS.waiting_on_applicant.label), explain: t(STATUS.waiting_on_applicant.explain) }
  return { cls: p.cls, label: t(p.label), explain: p.explain ? t(p.explain) : '' }
}
const OUTCOME: Record<string, { cls: string; label: string; explain: string }> = {
  recommend: { cls: 'pill-stable', label: 'Bank recommended approval', explain: 'A bank officer recommended your application for approval. The bank will contact you about the next steps.' },
  decline: { cls: 'pill-attn', label: 'Declined', explain: 'A bank officer declined this application. The message below explains why.' },
  request_info: { cls: 'pill-watch', label: 'The bank asked for more information', explain: '' },
}
function outcome(o: string) {
  const p = OUTCOME[o] || { cls: 'pill-neutral', label: o, explain: '' }
  return { cls: p.cls, label: t(p.label), explain: p.explain ? t(p.explain) : '' }
}
const REQUIRED_TITLE: Record<string, string> = {
  loan_application: 'Loan application form',
  form1_fy: 'Form 1 — Balance sheet, last financial year',
  form1_half: 'Form 1 — Balance sheet, latest half-year',
  form2_fy: 'Form 2 — Income statement, last financial year',
  form2_half: 'Form 2 — Income statement, latest half-year',
  bank_statement: 'Bank statement, last 8 months',
  tax_declaration: 'Tax declaration, latest quarter',
}
const reqTitle = (m: { key: string; title: string }) => (REQUIRED_TITLE[m.key] ? t(REQUIRED_TITLE[m.key]) : m.title)

// ----- add new documents to an open application -----
const adding = ref('')
const addMsg = ref<Record<string, { ok: boolean; text: string }>>({})
async function addDocs(a: OwnerApplication) {
  if (!a.uuid) return
  adding.value = a.uuid
  try {
    await ownerApi.addDocuments(a.uuid)
    addMsg.value[a.uuid] = { ok: true, text: t('New documents added. The bank will see them once they are checked.') }
    await loadApps()
  } catch (e) {
    addMsg.value[a.uuid] = { ok: false, text: errMessage(e) }
  } finally {
    adding.value = ''
  }
}

// ----- what to do now -----
const reading = computed(() => files.value.some((f) => f.status === 'queued' || f.status === 'processing'))
const next = computed<{ step: number; attention: boolean; title: string; text: string; href?: string; cta?: string }>(() => {
  const cl = app.ownerChecklist
  const waiting = apps.value.find((a) => a.action_needed)
  if (waiting)
    return { step: 3, attention: true, title: t('The bank asked for more information on {n}', { n: waiting.number }), text: t('Read the message from the bank below, upload what it asks for, then press "Add new documents to this application".'), href: '#my-applications', cta: t('See the message') }
  if (!files.value.length)
    return { step: 1, attention: false, title: t('Start by uploading your documents'), text: t('The list below shows which documents the bank needs and what each one is. You can upload them all at once.'), href: '#documents', cta: t('See the list') }
  if (reading.value)
    return { step: 1, attention: false, title: t('Reading your files'), text: t('Each file is checked and recognised by itself. This page updates by itself.') }
  const latest = apps.value[0]
  if (!latest) {
    if (cl && cl.present < cl.total)
      return { step: 2, attention: false, title: t('{a} of {b} documents provided', { a: cl.present, b: cl.total }), text: t('You can send the application now, but the bank will ask for the missing documents before it decides. Adding them first saves time.'), href: '#apply', cta: t('Go to the application form') }
    return { step: 2, attention: false, title: t('Your documents are ready: send your application'), text: t('Enter the amount, term and purpose below. Your analysed documents are attached automatically.'), href: '#apply', cta: t('Go to the application form') }
  }
  if (latest.status === 'decided')
    return { step: 4, attention: false, title: t('The bank recorded a decision on {n}', { n: latest.number }), text: t('See the decision and the message from the bank below.'), href: '#my-applications', cta: t('See the decision') }
  return { step: 3, attention: false, title: t('Application {n} is with the bank', { n: latest.number }), text: t('A bank officer is reviewing it. You do not need to do anything now; the decision will appear on this page.') }
})
</script>

<template>
  <!-- Logged-out visitors: a plain landing -->
  <div v-if="!auth.loggedIn" class="page landing">
    <div class="stack" style="gap: 10px; max-width: 720px">
      <div class="eyebrow">{{ t('MKBANK · SME lending') }}</div>
      <h1 class="hero">{{ t('Your financial documents, read and checked — every number traceable to its page.') }}</h1>
      <p class="muted" style="font-size: 15px">
        {{ t('Upload your bank statements and Форма 1 / Форма 2. Converza extracts the figures, shows where each one came from, answers questions about your cash, and lets you apply for a loan with the analysed documents attached.') }}
      </p>
      <div class="row" style="margin-top: 6px">
        <RouterLink to="/register" class="btn btn-primary">{{ t('Register your business') }}</RouterLink>
        <RouterLink to="/login" class="btn">{{ t('Sign in') }}</RouterLink>
        <RouterLink to="/analyse">{{ t('Analyse a document without an account →') }}</RouterLink>
      </div>
    </div>
  </div>

  <!-- Logged-in owner: what to do now → documents → apply → my applications -->
  <div v-else class="page">
    <div class="page-head">
      <div>
        <h1>{{ business || app.ownerBusiness?.name || t('My business') }}</h1>
        <p class="meta">{{ t('Apply for a business loan in four steps. Converza reads your documents; a bank officer makes the decision.') }}</p>
      </div>
      <RouterLink to="/cfo" class="btn">{{ t('Ask the AI CFO →') }}</RouterLink>
    </div>
    <div v-if="loadErr" class="error-box">{{ loadErr }}</div>

    <section class="panel next" :class="{ attention: next.attention }" :aria-label="t('What to do now')">
      <div class="eyebrow">{{ t('What to do now') }}</div>
      <div class="next-row">
        <div>
          <div class="next-title">{{ next.title }}</div>
          <p class="muted next-text">{{ next.text }}</p>
        </div>
        <a v-if="next.href" :href="next.href" class="btn" :class="{ 'btn-primary': !next.attention }">{{ next.cta }}</a>
      </div>
      <StepLine :current="next.step" :attention="next.attention" details />
    </section>

    <section id="documents" class="panel docs-panel" :aria-label="t('Your documents')">
      <div class="docs-grid">
        <DocChecklist :checklist="app.ownerChecklist" />
        <div class="stack" style="gap: 10px">
          <div class="panel-head"><h2>{{ t('Upload documents') }}</h2><RouterLink to="/upload" class="ctx">{{ t('See what was read from each file →') }}</RouterLink></div>
          <Dropzone
            multiple
            :disabled="uploading > 0"
            :title="uploading ? t('Uploading {n} file(s)…', { n: uploading }) : t('Drop your documents here')"
            :hint="t('PDF · XLSX · JPG · PNG · up to 20 MB each')"
            :button="t('Choose files')"
            @files="upload"
          />
          <div v-if="upErr" class="error-box">{{ upErr }}</div>
          <p class="muted" style="font-size: 12px">{{ t('You can upload several files at once, in any order. Each one is ticked in the list when it is recognised.') }}</p>
        </div>
      </div>
    </section>

    <section class="panel" :aria-label="t('Uploaded files')">
      <div class="panel-head" style="padding: 12px 14px 8px"><h2>{{ t('Uploaded files') }}</h2><span class="ctx">{{ t('{a} of {b} ready', { a: analysed.length, b: files.length }) }}</span></div>
      <div class="scrollbox">
        <table class="tbl" style="min-width: 640px">
          <thead><tr><th>{{ t('File') }}</th><th>{{ t('What it is') }}</th><th>{{ t('Period') }}</th><th>{{ t('Status') }}</th></tr></thead>
          <tbody>
            <tr v-for="d in files" :key="d.uuid">
              <td>
                <div class="row" style="flex-wrap: nowrap">
                  <span class="ficon">{{ fileBadge(d.filename, d.mime) }}</span>
                  <div style="min-width: 0"><div class="mono" style="font-size: 12.5px; overflow-wrap: anywhere">{{ d.filename }}</div><div class="muted" style="font-size: 12px">{{ fmtBytes(d.size_bytes) }}</div></div>
                </div>
              </td>
              <td>{{ d.status === 'queued' || d.status === 'processing' ? '…' : ownerDocTypeLabel(d.doc_type) }}</td>
              <td class="num">{{ fmtPeriod(d.period_start, d.period_end) }}</td>
              <td>
                <span class="pill" :class="ownerDocStatus(d).cls">{{ ownerDocStatus(d).label }}</span>
                <div v-if="ownerDocStatus(d).explain" class="muted" style="font-size: 12px; margin-top: 3px; max-width: 360px">{{ ownerDocStatus(d).explain }}</div>
              </td>
            </tr>
            <tr v-if="!files.length"><td colspan="4" class="muted">{{ t('No files yet. Start with the documents in the list above.') }}</td></tr>
          </tbody>
        </table>
      </div>
    </section>

    <section id="apply" class="panel" :aria-label="t('Apply for a loan')" style="padding: 16px">
      <form class="stack" style="gap: 10px" @submit.prevent="apply">
        <div class="panel-head"><h2>{{ t('Apply for a loan') }}</h2><span class="ctx">{{ t('Step 2 of 4') }}</span></div>
        <div class="apply-grid">
          <label class="field"><span class="eyebrow">{{ t('Amount, mln UZS') }}</span><input v-model.number="amount" class="input num" type="number" min="1" step="0.1" :placeholder="t('e.g. 850')" required /><span class="amount-hint" :class="{ warn: amountHint.warn }">{{ amountHint.text }}</span></label>
          <label class="field"><span class="eyebrow">{{ t('Term, months') }}</span><input v-model.number="term" class="input num" type="number" min="1" max="120" required /></label>
          <label class="field wide"><span class="eyebrow">{{ t('Purpose') }}</span><input v-model="purpose" class="input" :placeholder="t('e.g. buy a second sewing line')" required /></label>
        </div>
        <fieldset class="docs">
          <legend class="eyebrow">{{ t('Documents to include') }}</legend>
          <label v-for="d in analysed" :key="d.uuid" class="row" style="gap: 8px; font-size: 13px; flex-wrap: nowrap">
            <input v-model="picked" type="checkbox" :value="d.uuid" />
            <span>{{ ownerDocTypeLabel(d.doc_type) }} <span class="muted">· {{ fmtPeriod(d.period_start, d.period_end) }} · <span class="mono">{{ d.filename }}</span></span></span>
          </label>
          <p v-if="!analysed.length" class="muted" style="font-size: 13px">{{ t('No documents are ready yet. Upload them first.') }}</p>
          <p v-else-if="app.ownerChecklist && app.ownerChecklist.present < app.ownerChecklist.total" class="muted" style="font-size: 12px">{{ t('Not uploaded yet: {list}. You can send now and add them later.', { list: app.ownerChecklist.items.filter((i) => !i.present).map((i) => reqTitle(i)).join('; ') }) }}</p>
        </fieldset>
        <div v-if="applyErr" class="error-box">{{ applyErr }}</div>
        <div v-if="applyDone" class="note">{{ applyDone }}</div>
        <div class="row">
          <button type="submit" class="btn btn-primary" :disabled="applying || !analysed.length">{{ applying ? t('Sending…') : t('Send application') }}</button>
          <span class="muted" style="font-size: 12px">{{ t('A bank officer reviews it and decides. Converza itself never approves or rejects.') }}</span>
        </div>
      </form>
    </section>

    <section id="my-applications" class="panel" :aria-label="t('My applications')">
      <div class="panel-head" style="padding: 12px 14px 8px"><h2>{{ t('My applications') }}</h2></div>
      <p v-if="!apps.length" class="muted" style="padding: 0 14px 14px; font-size: 13px">{{ t('No applications yet. After you send one, you can follow it here step by step.') }}</p>
      <article v-for="a in apps" :key="a.number" class="appcard">
        <div class="app-head">
          <div>
            <span class="mono">{{ a.number }}</span>
            <span class="muted"> · {{ a.requested_display ?? '—' }} {{ t('mln UZS') }} · {{ a.term_months ? t('{n} months', { n: a.term_months }) : '—' }} · {{ t('sent {d}', { d: fmtDate((a.received_on || a.created_at || '').slice(0, 10) || null) }) }}</span>
            <div v-if="a.purpose" class="muted" style="font-size: 12.5px">{{ a.purpose }}</div>
          </div>
          <span class="pill" :class="appPill(a).cls">{{ appPill(a).label }}</span>
        </div>
        <StepLine :current="a.step || (a.status === 'decided' ? 4 : 3)" :attention="!!a.action_needed" />
        <p v-if="appPill(a).explain" class="muted" style="font-size: 12.5px">{{ appPill(a).explain }}</p>

        <div v-if="a.decision" class="decision" :class="outcome(a.decision.outcome).cls">
          <div class="row" style="justify-content: space-between; gap: 8px">
            <strong>{{ outcome(a.decision.outcome).label }}</strong>
            <span class="muted" style="font-size: 12px">{{ fmtDateTime(a.decision.decided_at) }}</span>
          </div>
          <p v-if="outcome(a.decision.outcome).explain" style="font-size: 12.5px">{{ outcome(a.decision.outcome).explain }}</p>
          <div class="eyebrow" style="margin-top: 4px">{{ t('Message from the bank') }}</div>
          <p class="msg">{{ a.decision.message }}</p>
        </div>

        <div v-if="a.can_add_documents && a.missing_documents && a.missing_documents.length" class="missing">
          <div class="eyebrow">{{ t('The bank does not have these yet') }}</div>
          <ul><li v-for="m in a.missing_documents" :key="m.key">{{ reqTitle(m) }}</li></ul>
        </div>
        <div v-if="a.can_add_documents && (a.action_needed || (a.missing_documents && a.missing_documents.length))" class="row">
          <button type="button" class="btn" :class="{ 'btn-primary': a.action_needed }" :disabled="adding === a.uuid" @click="addDocs(a)">{{ adding === a.uuid ? t('Adding…') : t('Add new documents to this application') }}</button>
          <span class="muted" style="font-size: 12px">{{ t('Upload the files above first; every ready document not yet in this application is added.') }}</span>
        </div>
        <div v-if="a.uuid && addMsg[a.uuid]" :class="addMsg[a.uuid].ok ? 'note' : 'error-box'">{{ addMsg[a.uuid].text }}</div>
      </article>
    </section>
  </div>
</template>

<style scoped>
.landing { padding-top: 32px; }
.hero { font-size: 28px; font-weight: 600; letter-spacing: -.01em; line-height: 1.25; }
.apply-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px 12px; }
.field { display: flex; flex-direction: column; gap: 4px; }
.wide { grid-column: 1 / -1; }
.docs { border: 0; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 6px; }
@media (max-width: 720px) { .hero { font-size: 22px; } }
.amount-hint { font-size: 12px; color: var(--ink-muted); margin-top: 4px; }
.amount-hint.warn { color: var(--watch-fg); font-weight: 500; }
.next { padding: 14px 16px; display: flex; flex-direction: column; gap: 10px; border-left: 3px solid var(--accent); }
.next.attention { border-left-color: var(--watch-fg); }
.next-row { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; flex-wrap: wrap; }
.next-title { font-size: 16px; font-weight: 600; }
.next-text { font-size: 13px; margin-top: 2px; max-width: 640px; }
.docs-panel { padding: 16px; }
.docs-grid { display: grid; grid-template-columns: minmax(0, 1.25fr) minmax(0, 1fr); gap: 20px; }
@media (max-width: 900px) { .docs-grid { grid-template-columns: 1fr; } }
.appcard { padding: 12px 14px; border-top: 1px solid var(--border-row); display: flex; flex-direction: column; gap: 10px; }
.app-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 8px; flex-wrap: wrap; font-size: 13px; }
.decision { padding: 10px 12px; border-radius: var(--r-control); font-size: 13px; display: flex; flex-direction: column; gap: 4px; }
.decision.pill-stable, .decision.pill-attn, .decision.pill-watch { color: var(--ink); }
.decision .msg { white-space: pre-wrap; color: var(--ink); }
.missing { font-size: 13px; }
.missing ul { margin: 4px 0 0; padding-left: 18px; }
</style>
