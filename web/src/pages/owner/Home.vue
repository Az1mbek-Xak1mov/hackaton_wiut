<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { api, errMessage } from '@/api/client'
import type { DocumentOut, OwnerApplication } from '@/api/types'
import { docStatusPill, docTypeLabel, fileBadge, fmtBytes, fmtDate, fmtPeriod } from '@/api/format'
import { useAuth } from '@/stores/auth'
import { useApp } from '@/stores/app'
import Dropzone from '@/components/ui/Dropzone.vue'
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
onBeforeUnmount(() => timer && clearTimeout(timer))

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

const STATUS: Record<string, { cls: string; label: string }> = {
  processing: { cls: 'pill-neutral', label: 'Processing documents' },
  in_review: { cls: 'pill-info', label: 'In review' },
  waiting_on_applicant: { cls: 'pill-watch', label: 'Waiting on applicant' },
  decided: { cls: 'pill-stable', label: 'Decision recorded' },
  submitted: { cls: 'pill-info', label: 'Submitted' },
}
function appPill(s: string) {
  const p = STATUS[s] || { cls: 'pill-neutral', label: s }
  return { cls: p.cls, label: t(p.label) }
}
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

  <!-- Logged-in owner -->
  <div v-else class="page">
    <div class="page-head">
      <div>
        <h1>{{ business || app.ownerBusiness?.name || t('My business') }}</h1>
        <p class="meta">{{ t('{a} of {b} documents analyzed', { a: analysed.length, b: files.length }) }}</p>
      </div>
      <RouterLink to="/cfo" class="btn">{{ t('Ask the AI CFO →') }}</RouterLink>
    </div>
    <div v-if="loadErr" class="error-box">{{ loadErr }}</div>

    <div class="grid-2">
      <section class="panel" :aria-label="t('Upload documents')" style="padding: 16px; display: flex; flex-direction: column; gap: 10px">
        <div class="panel-head"><h2>{{ t('Upload documents') }}</h2><RouterLink to="/upload" class="ctx">{{ t('Details →') }}</RouterLink></div>
        <Dropzone
          multiple
          compact
          :disabled="uploading > 0"
          :title="uploading ? t('Uploading {n} file(s)…', { n: uploading }) : t('Drop statements and reports here')"
          :hint="t('PDF · XLSX · JPG · PNG · up to 20 MB each')"
          :button="t('Choose files')"
          @files="upload"
        />
        <div v-if="upErr" class="error-box">{{ upErr }}</div>
      </section>

      <section class="panel" :aria-label="t('Apply for a loan')" style="padding: 16px">
        <form class="stack" style="gap: 10px" @submit.prevent="apply">
          <div class="panel-head"><h2>{{ t('Apply for a loan') }}</h2></div>
          <div class="apply-grid">
            <label class="field"><span class="eyebrow">{{ t('Amount, mln UZS') }}</span><input v-model.number="amount" class="input num" type="number" min="1" step="0.1" :placeholder="t('e.g. 850')" required /><span class="amount-hint" :class="{ warn: amountHint.warn }">{{ amountHint.text }}</span></label>
            <label class="field"><span class="eyebrow">{{ t('Term, months') }}</span><input v-model.number="term" class="input num" type="number" min="1" max="120" required /></label>
            <label class="field wide"><span class="eyebrow">{{ t('Purpose') }}</span><input v-model="purpose" class="input" required /></label>
          </div>
          <fieldset class="docs">
            <legend class="eyebrow">{{ t('Documents to include') }}</legend>
            <label v-for="d in analysed" :key="d.uuid" class="row" style="gap: 8px; font-size: 13px; flex-wrap: nowrap">
              <input v-model="picked" type="checkbox" :value="d.uuid" />
              <span><span class="mono">{{ d.filename }}</span> <span class="muted">· {{ docTypeLabel(d.doc_type) }} · {{ fmtPeriod(d.period_start, d.period_end) }}</span></span>
            </label>
            <p v-if="!analysed.length" class="muted" style="font-size: 13px">{{ t('No analysed documents yet — upload them first.') }}</p>
          </fieldset>
          <div v-if="applyErr" class="error-box">{{ applyErr }}</div>
          <div v-if="applyDone" class="note">{{ applyDone }}</div>
          <div class="row">
            <button type="submit" class="btn btn-primary" :disabled="applying || !analysed.length">{{ applying ? t('Sending…') : t('Send application') }}</button>
            <span class="muted" style="font-size: 12px">{{ t('The bank reviews it; Converza does not approve or reject.') }}</span>
          </div>
        </form>
      </section>
    </div>

    <section class="panel" :aria-label="t('Uploaded files')">
      <div class="panel-head" style="padding: 12px 14px 8px"><h2>{{ t('Uploaded files') }}</h2></div>
      <div class="scrollbox">
        <table class="tbl" style="min-width: 640px">
          <thead><tr><th>{{ t('File') }}</th><th>{{ t('Recognised as') }}</th><th>{{ t('Period') }}</th><th>{{ t('Status') }}</th></tr></thead>
          <tbody>
            <tr v-for="d in files" :key="d.uuid">
              <td>
                <div class="row" style="flex-wrap: nowrap">
                  <span class="ficon">{{ fileBadge(d.filename, d.mime) }}</span>
                  <div style="min-width: 0"><div class="mono" style="font-size: 12.5px; overflow-wrap: anywhere">{{ d.filename }}</div><div class="muted" style="font-size: 12px">{{ fmtBytes(d.size_bytes) }}</div></div>
                </div>
              </td>
              <td>{{ d.status === 'queued' || d.status === 'processing' ? '…' : docTypeLabel(d.doc_type) }}</td>
              <td class="num">{{ fmtPeriod(d.period_start, d.period_end) }}</td>
              <td>
                <span class="pill" :class="docStatusPill(d.status).cls">{{ docStatusPill(d.status).label }}</span>
                <div v-if="d.status === 'failed' && d.failure_cause" class="muted" style="font-size: 12px; margin-top: 3px; max-width: 320px">{{ d.failure_cause }}</div>
              </td>
            </tr>
            <tr v-if="!files.length"><td colspan="4" class="muted">{{ t('No files yet. Upload a bank statement to start.') }}</td></tr>
          </tbody>
        </table>
      </div>
    </section>

    <section class="panel" :aria-label="t('My applications')">
      <div class="panel-head" style="padding: 12px 14px 8px"><h2>{{ t('My applications') }}</h2></div>
      <div class="scrollbox">
        <table class="tbl" style="min-width: 560px">
          <thead><tr><th>{{ t('Application') }}</th><th class="r">{{ t('Requested, mln') }}</th><th class="r">{{ t('Term') }}</th><th>{{ t('Sent') }}</th><th>{{ t('Status') }}</th></tr></thead>
          <tbody>
            <tr v-for="a in apps" :key="a.number">
              <td><span class="mono">{{ a.number }}</span><div v-if="a.purpose" class="muted" style="font-size: 12px">{{ a.purpose }}</div></td>
              <td class="r num">{{ a.requested_display ?? '—' }}</td>
              <td class="r num">{{ a.term_months ? t('{n} m', { n: a.term_months }) : '—' }}</td>
              <td class="num">{{ fmtDate((a.received_on || a.created_at || '').slice(0, 10) || null) }}</td>
              <td><span class="pill" :class="appPill(a.status).cls">{{ appPill(a.status).label }}</span><div v-if="a.issues_label" class="muted" style="font-size: 12px">{{ a.issues_label }}</div></td>
            </tr>
            <tr v-if="!apps.length"><td colspan="5" class="muted">{{ t('No applications yet.') }}</td></tr>
          </tbody>
        </table>
      </div>
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
</style>
