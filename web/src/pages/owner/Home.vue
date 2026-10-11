<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { api, errMessage } from '@/api/client'
import type { DocumentOut, OwnerApplication } from '@/api/types'
import { useAuth } from '@/stores/auth'
import { useApp } from '@/stores/app'
import StepLine from '@/components/owner/StepLine.vue'
import Landing from '@/components/owner/Landing.vue'
import OwnerDashboard from '@/components/owner/OwnerDashboard.vue'
import EvidencePane from '@/components/evidence/EvidencePane.vue'
import { t } from '@/i18n'

const auth = useAuth()
const app = useApp()

const files = ref<DocumentOut[]>([])
const business = ref('')
const apps = ref<OwnerApplication[]>([])
const loadErr = ref('')
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

const analysed = computed(() => files.value.filter((f) => f.status === 'analyzed' || f.status === 'clarification'))
// ----- what to do now -----
const reading = computed(() => files.value.some((f) => f.status === 'queued' || f.status === 'processing'))
const next = computed<{ step: number; attention: boolean; title: string; text: string; href?: string; cta?: string }>(() => {
  const cl = app.ownerChecklist
  const waiting = apps.value.find((a) => a.action_needed)
  if (waiting)
    return { step: 3, attention: true, title: t('The bank asked for more information on {n}', { n: waiting.number }), text: t('Open your application, read the message from the bank, upload what it asks for, then press "Add new documents to this application".'), href: '/apply#my-applications', cta: t('See the message') }
  if (!files.value.length)
    return { step: 1, attention: false, title: t('Start by uploading your documents'), text: t('The application page lists which documents the bank needs and what each one is. You can upload them all at once.'), href: '/apply#documents', cta: t('See the list') }
  if (reading.value)
    return { step: 1, attention: false, title: t('Reading your files'), text: t('Each file is checked and recognised by itself. This page updates by itself.') }
  const latest = apps.value[0]
  if (!latest) {
    if (cl && cl.present < cl.total)
      return { step: 2, attention: false, title: t('{a} of {b} documents provided', { a: cl.present, b: cl.total }), text: t('You can send the application now, but the bank will ask for the missing documents before it decides. Adding them first saves time.'), href: '/apply#documents', cta: t('Go to the application form') }
    return { step: 2, attention: false, title: t('Your documents are ready: send your application'), text: t('Enter the amount, term and purpose on the application page. Your analysed documents are attached automatically.'), href: '/apply#documents', cta: t('Go to the application form') }
  }
  if (latest.status === 'decided')
    return { step: 4, attention: false, title: t('The bank recorded a decision on {n}', { n: latest.number }), text: t('See the decision and the message from the bank on the application page.'), href: '/apply#my-applications', cta: t('See the decision') }
  return { step: 3, attention: false, title: t('Application {n} is with the bank', { n: latest.number }), text: t('A bank officer is reviewing it. You do not need to do anything now; the decision will appear on the application page.') }
})
</script>

<template>
  <!-- Logged-out visitors: the landing -->
  <Landing v-if="!auth.loggedIn" />

  <!-- Logged-in owner: what to do now → business dashboard (figures from their own documents) -->
  <div v-else class="page">
    <div class="page-head">
      <div>
        <h1>{{ business || app.ownerBusiness?.name || t('My business') }}</h1>
        <p class="meta">{{ t('How your business is doing, read from the documents you uploaded. Click any figure to see where it came from.') }}</p>
      </div>
      <div class="row">
        <RouterLink to="/cfo" class="btn">{{ t('Ask the AI CFO →') }}</RouterLink>
        <RouterLink to="/apply" class="btn btn-primary">{{ t('Apply for credit') }}</RouterLink>
      </div>
    </div>
    <div v-if="loadErr" class="error-box">{{ loadErr }}</div>

    <section class="panel next" :class="{ attention: next.attention }" :aria-label="t('What to do now')">
      <div class="next-row">
        <div>
          <div class="eyebrow">{{ t('What to do now') }}</div>
          <div class="next-title">{{ next.title }}</div>
          <p class="muted next-text">{{ next.text }}</p>
        </div>
        <RouterLink v-if="next.href" :to="next.href" class="btn" :class="{ 'btn-primary': !next.attention }">{{ next.cta }}</RouterLink>
      </div>
      <StepLine :current="next.step" :attention="next.attention" />
    </section>

    <div class="twopane" style="gap: 20px">
      <div class="main-col">
        <OwnerDashboard :key="analysed.length" />
      </div>
      <div class="ev-col" style="flex-basis: 360px">
        <EvidencePane :actions="false" :empty-text="t('Click any figure on the dashboard to see the document and line it came from.')" />
      </div>
    </div>
  </div>
</template>

<style scoped>
.next { padding: 14px 16px; display: flex; flex-direction: column; gap: 10px; border-left: 3px solid var(--accent); }
.next.attention { border-left-color: var(--watch-fg); }
.next-row { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; flex-wrap: wrap; }
.next-title { font-size: 16px; font-weight: 600; }
.next-text { font-size: 13px; margin-top: 2px; max-width: 640px; }
</style>
