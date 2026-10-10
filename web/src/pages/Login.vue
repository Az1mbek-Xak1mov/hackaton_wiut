<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuth } from '@/stores/auth'
import { errMessage } from '@/api/client'
import { t } from '@/i18n'

const auth = useAuth()
const route = useRoute()
const router = useRouter()
const busy = ref<'' | 'officer' | 'owner'>('')
const err = ref(route.query.failed ? t('Could not start a demo session automatically. Try again below.') : '')

async function enter(role: 'officer' | 'owner') {
  busy.value = role
  err.value = ''
  try {
    await auth.enter(role)
    const next = typeof route.query.next === 'string' && route.query.next.startsWith('/') ? route.query.next : role === 'officer' ? '/bank' : '/owner/cfo'
    await router.push(next)
  } catch (e) {
    err.value = errMessage(e)
  } finally {
    busy.value = ''
  }
}
</script>

<template>
  <div class="page" style="max-width: 720px">
    <div class="page-head">
      <div>
        <h1>{{ t('Enter the Converza demo') }}</h1>
        <p class="meta">{{ t('Demo sessions are read-and-review accounts on synthetic data. No password is needed.') }}</p>
      </div>
    </div>
    <div class="grid-2" style="grid-template-columns: repeat(auto-fit, minmax(min(300px, 100%), 1fr))">
      <section class="panel" style="padding: 16px; display: flex; flex-direction: column; gap: 10px">
        <div class="eyebrow">{{ t('MKBANK · SME lending') }}</div>
        <h2 style="font-size: 15px; font-weight: 600">{{ t('Bank officer') }}</h2>
        <p class="muted" style="font-size: 13px">{{ t('Loan-file review with page-level evidence, reconciliation findings, ratios and monitoring statuses.') }}</p>
        <button type="button" class="btn btn-primary" :disabled="!!busy" @click="enter('officer')">{{ busy === 'officer' ? t('Starting…') : t('Enter as bank officer') }}</button>
      </section>
      <section class="panel" style="padding: 16px; display: flex; flex-direction: column; gap: 10px">
        <div class="eyebrow">{{ t('SME borrower') }}</div>
        <h2 style="font-size: 15px; font-weight: 600">{{ t('Business owner') }}</h2>
        <p class="muted" style="font-size: 13px">{{ t('Upload statements and ask the AI CFO; every answer cites the records it used.') }}</p>
        <button type="button" class="btn" :disabled="!!busy" @click="enter('owner')">{{ busy === 'owner' ? t('Starting…') : t('Enter as business owner') }}</button>
      </section>
    </div>
    <div v-if="err" class="error-box">{{ err }}</div>
    <p class="muted" style="font-size: 13px"><RouterLink to="/analyse">{{ t('Or analyse any document without signing in') }}</RouterLink></p>
  </div>
</template>
