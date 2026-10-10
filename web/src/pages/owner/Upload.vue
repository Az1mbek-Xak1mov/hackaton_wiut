<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { api, errMessage } from '@/api/client'
import type { DocumentOut, Fact } from '@/api/types'
import { confPill, docStatusPill, docTypeLabel, fileBadge, fmtBytes, fmtDateTime, fmtPeriod } from '@/api/format'
import { useEvidence } from '@/stores/evidence'
import Dropzone from '@/components/ui/Dropzone.vue'
import EvidencePane from '@/components/evidence/EvidencePane.vue'
import EvidenceChip from '@/components/evidence/EvidenceChip.vue'
import { t } from '@/i18n'

const ev = useEvidence()
const files = ref<DocumentOut[]>([])
const loading = ref(true)
const err = ref('')
const upErr = ref('')
const uploading = ref(0)
const openUuid = ref<string | null>(null)
const openFacts = ref<Fact[]>([])
const factsErr = ref('')
let timer: ReturnType<typeof setTimeout> | null = null

async function load() {
  try {
    files.value = (await api.ownerFiles()).items
    err.value = ''
  } catch (e) {
    err.value = errMessage(e)
  } finally {
    loading.value = false
  }
  if (timer) clearTimeout(timer)
  if (files.value.some((f) => f.status === 'queued' || f.status === 'processing')) timer = setTimeout(load, 2000)
}

onMounted(() => {
  ev.clear()
  load()
})
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
  await load()
}

async function toggle(d: DocumentOut) {
  if (openUuid.value === d.uuid) {
    openUuid.value = null
    return
  }
  openUuid.value = d.uuid
  openFacts.value = []
  factsErr.value = ''
  try {
    const r = await api.documentFacts(d.uuid)
    const list = Array.isArray(r) ? r : 'facts' in r ? r.facts : r.items
    openFacts.value = list
    ev.register(list)
    if (list[0]) ev.select(list[0].key)
  } catch (e) {
    factsErr.value = errMessage(e)
  }
}

function summaryText(d: DocumentOut): string {
  const s = d.summary || {}
  if (typeof s.text === 'string') return s.text
  if (typeof s.extracted === 'string') return s.extracted
  const parts: string[] = []
  for (const [k, v] of Object.entries(s)) {
    if (['partial', 'text'].includes(k) || v == null || typeof v === 'object') continue
    parts.push(`${k.replace(/_/g, ' ')}: ${v}`)
    if (parts.length >= 3) break
  }
  return parts.join(' · ')
}

const counts = computed(() => ({
  analysed: files.value.filter((f) => f.status === 'analyzed').length,
  total: files.value.length,
}))
const openDoc = computed(() => files.value.find((f) => f.uuid === openUuid.value) || null)
const lineFacts = computed(() => openFacts.value.filter((f) => f.line_code))
const otherFacts = computed(() => openFacts.value.filter((f) => !f.line_code))
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h1>{{ t('Upload & analyze') }}</h1>
        <p class="meta">{{ t("Bank statements, Форма 1 and Форма 2 feed the AI CFO and your bank's monitoring.") }} {{ t('{a} of {b} documents analyzed', { a: counts.analysed, b: counts.total }) }}</p>
      </div>
      <RouterLink to="/owner/cfo" class="btn btn-primary">{{ t('Ask the AI CFO →') }}</RouterLink>
    </div>

    <section class="panel" :aria-label="t('Upload')" style="padding: 16px; display: flex; flex-direction: column; gap: 10px">
      <Dropzone multiple :disabled="uploading > 0" @files="upload" :title="uploading ? t('Uploading {n} file(s)…', { n: uploading }) : t('Drop statements and reports here')" :hint="t('PDF · XLSX · JPG · PNG · up to 20 MB each')" :button="t('Choose files')" />
      <div v-if="upErr" class="error-box">{{ upErr }}</div>
      <div class="muted" style="font-size: 12px">{{ t('Recognised: bank statement (XLSX), balance sheet (Форма 1), income statement (Форма 2). Values you correct are recorded with your name.') }}</div>
    </section>

    <section class="panel" aria-label="Uploaded files">
      <div class="panel-head" style="padding: 12px 14px 8px">
        <h2>{{ t('Uploaded files') }}</h2>
        <span class="ctx">{{ t('Click a file to see what was extracted') }}</span>
      </div>
      <div v-if="loading" class="empty">{{ t('Loading…') }}</div>
      <div v-else-if="err" class="error-box" style="margin: 12px">{{ err }}</div>
      <div v-else class="scrollbox">
        <table class="tbl hover" style="min-width: 820px">
          <thead><tr><th>{{ t('File') }}</th><th>{{ t('Recognised as') }}</th><th>{{ t('Period') }}</th><th>{{ t('Status') }}</th><th>{{ t('Extracted') }}</th></tr></thead>
          <tbody>
            <tr v-for="d in files" :key="d.uuid" class="clickable" :class="{ sel: openUuid === d.uuid }" @click="toggle(d)">
              <td>
                <div class="row" style="flex-wrap: nowrap">
                  <span class="ficon">{{ fileBadge(d.filename, d.mime) }}</span>
                  <div style="min-width: 0"><div class="mono" style="font-size: 12.5px; overflow-wrap: anywhere">{{ d.filename }}</div><div class="muted" style="font-size: 12px">{{ fmtBytes(d.size_bytes) }} · {{ fmtDateTime(d.created_at) }}</div></div>
                </div>
              </td>
              <td>{{ d.status === 'queued' || d.status === 'processing' ? '…' : docTypeLabel(d.doc_type) }}</td>
              <td class="num">{{ fmtPeriod(d.period_start, d.period_end) }}</td>
              <td>
                <span class="pill" :class="docStatusPill(d.status).cls">{{ docStatusPill(d.status).label }}</span>
                <div v-if="d.status === 'failed' && d.failure_cause" class="muted" style="font-size: 12px; margin-top: 3px; max-width: 280px">{{ d.failure_cause }}</div>
              </td>
              <td class="muted" style="font-size: 12px">{{ summaryText(d) }}</td>
            </tr>
            <tr v-if="!files.length"><td colspan="5" class="muted">{{ t('No files yet. Upload a bank statement to start.') }}</td></tr>
          </tbody>
        </table>
      </div>
    </section>

    <div v-if="openDoc" class="twopane">
      <section class="main-col panel" :aria-label="t('Extracted from {file}', { file: openDoc.filename })" style="gap: 0">
        <div class="panel-head" style="padding: 12px 14px 8px">
          <h2>{{ t('Extracted from {file}', { file: '' }) }}<span class="mono" style="font-size: 13px">{{ openDoc.filename }}</span></h2>
          <span class="ctx">{{ t('Values as printed · click a value to see it on the page') }}</span>
        </div>
        <div v-if="factsErr" class="error-box" style="margin: 12px">{{ factsErr }}</div>
        <div v-else-if="!openFacts.length" class="empty">{{ openDoc.status === 'processing' ? t('Nothing extracted from this file yet.') : t('Nothing extracted from this file.') }}</div>
        <div v-else class="scrollbox">
          <table class="tbl" style="min-width: 520px">
            <thead><tr><th>{{ t('Line') }}</th><th>{{ t('Interpreted as') }}</th><th>{{ t('Period') }}</th><th class="r">{{ t('Value') }}</th><th>{{ t('Confidence') }}</th></tr></thead>
            <tbody>
              <tr v-for="f in [...lineFacts, ...otherFacts]" :key="f.key">
                <td class="mono">{{ f.line_code || '—' }}</td>
                <td>{{ f.label }}</td>
                <td class="muted">{{ f.period_label || '—' }}</td>
                <td class="r"><EvidenceChip :fact-key="f.key" :text="f.printed || f.display" class="mono" /></td>
                <td><span v-if="confPill(f.confidence)" class="pill" :class="confPill(f.confidence)!.cls">{{ confPill(f.confidence)!.label }}</span></td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
      <div class="ev-col"><EvidencePane /></div>
    </div>
  </div>
</template>

<style scoped>
tr.sel td { background: var(--accent-tint); }
</style>
