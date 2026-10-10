<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api, errMessage } from '@/api/client'
import type { ApplicationListItem } from '@/api/types'
import { fmtDate } from '@/api/format'
import { t, tn } from '@/i18n'

const router = useRouter()
const items = ref<ApplicationListItem[]>([])
const loading = ref(true)
const err = ref('')

onMounted(async () => {
  try {
    items.value = (await api.applications()).items
  } catch (e) {
    err.value = errMessage(e)
  } finally {
    loading.value = false
  }
})

function pill(st: string) {
  const m: Record<string, { cls: string; label: string }> = {
    processing: { cls: 'pill-neutral', label: 'Processing documents' },
    in_review: { cls: 'pill-info', label: 'In review' },
    waiting_on_applicant: { cls: 'pill-watch', label: 'Waiting on applicant' },
    decided: { cls: 'pill-stable', label: 'Decision recorded' },
    ready: { cls: 'pill-stable', label: 'Ready for review' },
  }
  const p = m[st] || { cls: 'pill-info', label: st }
  return { cls: p.cls, label: t(p.label) }
}
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h1>{{ t('Applications') }}</h1>
        <p class="meta">{{ t("Loan files assembled from the applicant's documents · oldest first") }}</p>
      </div>
      <RouterLink to="/analyse" class="btn">{{ t('Analyse a single document') }}</RouterLink>
    </div>
    <div v-if="loading" class="panel empty">{{ t('Loading applications…') }}</div>
    <div v-else-if="err" class="error-box">{{ err }}</div>
    <section v-else class="panel" :aria-label="t('Applications')">
      <div class="scrollbox">
        <table class="tbl hover" style="min-width: 760px">
          <thead><tr><th>{{ t('Applicant') }}</th><th class="r">{{ t('Requested, mln') }}</th><th class="r">{{ t('Term') }}</th><th>{{ t('Received') }}</th><th>{{ t('Documents') }}</th><th>{{ t('Status') }}</th><th>{{ t('Issues') }}</th></tr></thead>
          <tbody>
            <tr v-for="a in items" :key="a.uuid" class="clickable" @click="router.push(`/bank/applications/${a.number}`)">
              <td><RouterLink :to="`/bank/applications/${a.number}`" style="font-weight: 500" @click.stop>{{ a.name }}</RouterLink><div class="muted">{{ a.industry }} · {{ a.number }}</div></td>
              <td class="r num">{{ a.requested_display }}</td>
              <td class="r num">{{ t('{n} m', { n: a.term_months }) }}</td>
              <td class="num">{{ fmtDate(a.received_on) }}</td>
              <td class="num">{{ a.docs }}</td>
              <td><span class="pill" :class="pill(a.status).cls">{{ pill(a.status).label }}</span></td>
              <td class="muted">{{ a.issues_label || (a.issues_count ? tn(a.issues_count, '{n} issue', '{n} issues') : '—') }}</td>
            </tr>
            <tr v-if="!items.length"><td colspan="7" class="muted">{{ t("No applications yet. They appear here after the applicant's documents are attached and analysed.") }}</td></tr>
          </tbody>
        </table>
      </div>
    </section>
    <div class="footer-line">{{ t('The system prepares the file; it does not approve or reject.') }}</div>
  </div>
</template>
