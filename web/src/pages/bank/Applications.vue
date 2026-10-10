<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api, errMessage } from '@/api/client'
import type { ApplicationListItem } from '@/api/types'
import { appStatusPill as pill, fmtDate } from '@/api/format'
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

function docsLabel(d: string | null | undefined) {
  if (!d) return '—'
  const [a, b] = d.split('/')
  return b ? t('{a} of {b}', { a, b }) : d
}
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h1>{{ t('Applications') }}</h1>
        <p class="meta">{{ t('Loan requests sent by businesses from converza.uz, oldest first. Open one to see the figures, the issues to check and to record your decision.') }}</p>
      </div>
      <RouterLink to="/analyse" class="btn">{{ t('Analyse a single document') }}</RouterLink>
    </div>
    <div v-if="loading" class="panel empty">{{ t('Loading applications…') }}</div>
    <div v-else-if="err" class="error-box">{{ err }}</div>
    <section v-else class="panel" :aria-label="t('Applications')">
      <div class="scrollbox">
        <table class="tbl hover" style="min-width: 760px">
          <thead>
            <tr>
              <th>{{ t('Business') }}</th>
              <th class="r">{{ t('Amount, mln UZS') }}</th>
              <th class="r">{{ t('Term') }}</th>
              <th>{{ t('Received') }}</th>
              <th :title="t('Required documents received, out of the full set (application form, Form 1 and Form 2 for two periods, bank statement, tax declaration)')">{{ t('Documents received') }}</th>
              <th>{{ t('Status') }}</th>
              <th :title="t('Problems the automatic checks found in the documents; each needs your conclusion')">{{ t('Issues to check') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="a in items" :key="a.uuid" class="clickable" @click="router.push(`/bank/applications/${a.number}`)">
              <td><RouterLink :to="`/bank/applications/${a.number}`" style="font-weight: 500" @click.stop>{{ a.name }}</RouterLink><div class="muted">{{ [a.industry, a.number].filter(Boolean).join(' · ') }}</div></td>
              <td class="r num">{{ a.requested_display && a.requested_display !== 'n/a' ? a.requested_display : '—' }}</td>
              <td class="r num">{{ a.term_months ? tn(a.term_months, '{n} month', '{n} months') : '—' }}</td>
              <td class="num">{{ fmtDate(a.received_on) }}</td>
              <td class="num">{{ docsLabel(a.docs) }}</td>
              <td><span class="pill" :class="pill(a.status).cls">{{ pill(a.status).label }}</span></td>
              <td :class="a.issues_count ? '' : 'muted'">{{ a.issues_count ? tn(a.issues_count, '{n} issue', '{n} issues') : a.status === 'processing' ? t('Checking…') : t('None found') }}</td>
            </tr>
            <tr v-if="!items.length"><td colspan="7" class="muted">{{ t('No applications yet. They appear here when a business submits one on converza.uz.') }}</td></tr>
          </tbody>
        </table>
      </div>
    </section>
    <div class="footer-line">{{ t('The system prepares the file; it does not approve or reject. Only an officer records a decision.') }}</div>
  </div>
</template>
