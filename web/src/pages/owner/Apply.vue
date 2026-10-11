<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { api, errMessage } from '@/api/client'
import type { DocumentOut, OwnerApplication } from '@/api/types'
import { fmtBytes, fmtDate, fmtDateTime, fmtPeriod, ownerDocStatus, ownerDocTypeLabel } from '@/api/format'
import { useAuth } from '@/stores/auth'
import { ownerApi, useApp } from '@/stores/app'
import Dropzone from '@/components/ui/Dropzone.vue'
import DocChecklist from '@/components/owner/DocChecklist.vue'
import StepLine from '@/components/owner/StepLine.vue'
import DecisionPanel from '@/components/owner/DecisionPanel.vue'
import BalanceAfter from '@/components/owner/BalanceAfter.vue'
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

// the most recent application, if a bank officer has recorded a decision on it: shown first, in full
const decided = computed(() => (apps.value[0]?.decision ? apps.value[0] : null))
const stepNow = computed(() => {
  const latest = apps.value[0]
  if (latest) return latest.step || (latest.status === 'decided' ? 4 : 3)
  return files.value.length ? 2 : 1
})

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

</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h1>{{ t('Apply for credit') }}</h1>
        <p class="meta">{{ t('Tell the bank what you need, attach your documents and send. Converza reads the documents; a bank officer makes the decision.') }}</p>
      </div>
      <RouterLink to="/" class="btn">{{ t('← My business') }}</RouterLink>
    </div>
    <div v-if="loadErr" class="error-box">{{ loadErr }}</div>

    <DecisionPanel v-if="decided" :application="decided" :req-title="reqTitle" @add-documents="addDocs(decided)" />
    <div v-if="decided && decided.uuid && addMsg[decided.uuid]" :class="addMsg[decided.uuid].ok ? 'note' : 'error-box'">{{ addMsg[decided.uuid].text }}</div>

    <section class="panel" style="padding: 14px 16px" :aria-label="t('Application steps')">
      <StepLine :current="stepNow" :attention="!!apps.find((a) => a.action_needed)" :outcome="apps[0]?.decision?.outcome" />
    </section>

    <form class="stack" style="gap: 16px" @submit.prevent="apply">
      <section class="panel" style="padding: 16px" :aria-label="t('Loan details')">
        <div class="panel-head" style="margin-bottom: 10px"><h2>{{ t('1. What you need') }}</h2></div>
        <div class="apply-grid">
          <label class="field"><span class="eyebrow">{{ t('Amount, mln UZS') }}</span><input v-model.number="amount" class="input num" type="number" min="1" step="0.1" :placeholder="t('e.g. 850')" required /><span class="amount-hint" :class="{ warn: amountHint.warn }">{{ amountHint.text }}</span></label>
          <label class="field"><span class="eyebrow">{{ t('Term, months') }}</span><input v-model.number="term" class="input num" type="number" min="1" max="120" required /></label>
          <label class="field wide"><span class="eyebrow">{{ t('Purpose') }}</span><input v-model="purpose" class="input" :placeholder="t('e.g. buy a second sewing line')" required /></label>
        </div>
      </section>

      <section id="documents" class="panel docs-panel" :aria-label="t('Your documents')">
        <div class="panel-head" style="margin-bottom: 10px"><h2>{{ t('2. Documents the bank needs') }}</h2><RouterLink to="/upload" class="ctx">{{ t('See what was read from each file →') }}</RouterLink></div>
        <div class="docs-grid">
          <DocChecklist :checklist="app.ownerChecklist" />
          <div class="stack" style="gap: 10px">
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
        <fieldset class="docs" style="margin-top: 14px">
          <legend class="eyebrow">{{ t('Documents to include') }} · {{ t('{a} of {b} ready', { a: analysed.length, b: files.length }) }}</legend>
          <label v-for="d in files" :key="d.uuid" class="row" style="gap: 8px; font-size: 13px; flex-wrap: nowrap">
            <input v-model="picked" type="checkbox" :value="d.uuid" :disabled="!analysed.includes(d)" />
            <span>{{ d.status === 'queued' || d.status === 'processing' ? '…' : ownerDocTypeLabel(d.doc_type) }} <span class="muted">· {{ fmtPeriod(d.period_start, d.period_end) }} · <span class="mono">{{ d.filename }}</span></span></span>
            <span class="pill" :class="ownerDocStatus(d).cls" style="margin-left: auto">{{ ownerDocStatus(d).label }}</span>
          </label>
          <p v-if="!files.length" class="muted" style="font-size: 13px">{{ t('No documents are ready yet. Upload them first.') }}</p>
          <p v-else-if="app.ownerChecklist && app.ownerChecklist.present < app.ownerChecklist.total" class="muted" style="font-size: 12px">{{ t('Not uploaded yet: {list}. You can send now and add them later.', { list: app.ownerChecklist.items.filter((i) => !i.present).map((i) => reqTitle(i)).join('; ') }) }}</p>
        </fieldset>
      </section>

      <section id="apply" class="panel" style="padding: 16px" :aria-label="t('Send application')">
        <div class="panel-head" style="margin-bottom: 10px"><h2>{{ t('3. Send to the bank') }}</h2></div>
        <div v-if="applyErr" class="error-box" style="margin-bottom: 10px">{{ applyErr }}</div>
        <div v-if="applyDone" class="note" style="margin-bottom: 10px">{{ applyDone }}</div>
        <div class="row">
          <button type="submit" class="btn btn-primary" :disabled="applying || !analysed.length">{{ applying ? t('Sending…') : t('Send application') }}</button>
          <span class="muted" style="font-size: 12px">{{ t('A bank officer reviews it and decides. Converza itself never approves or rejects.') }}</span>
        </div>
      </section>
    </form>

    <section id="my-applications" class="panel" :aria-label="t('My applications')">
      <div class="panel-head" style="padding: 12px 14px 8px"><h2>{{ t('My applications and the bank\'s answer') }}</h2></div>
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
        <StepLine :current="a.step || (a.status === 'decided' ? 4 : 3)" :attention="!!a.action_needed" :outcome="a.decision?.outcome" />
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

        <BalanceAfter v-if="a.balance_after && (!a.decision || a.decision.outcome === 'request_info')" :data="a.balance_after" preview />
        <BalanceAfter v-else-if="a.balance_after && a.decision?.outcome === 'recommend' && a !== decided" :data="a.balance_after" />

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
.apply-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px 12px; }
.field { display: flex; flex-direction: column; gap: 4px; }
.wide { grid-column: 1 / -1; }
.docs { border: 0; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 6px; }
.amount-hint { font-size: 12px; color: var(--ink-muted); margin-top: 4px; }
.amount-hint.warn { color: var(--watch-fg); font-weight: 500; }
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
