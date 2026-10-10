<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuth } from '@/stores/auth'
import { ApiError, errMessage } from '@/api/client'
import { OTHER_SURFACE_URL, surface } from '@/surface'
import { t } from '@/i18n'

const auth = useAuth()
const route = useRoute()
const router = useRouter()
const email = ref('')
const password = ref('')
const busy = ref(false)
const err = ref('')
const wrongSurface = ref(false)

async function submit() {
  err.value = ''
  wrongSurface.value = false
  busy.value = true
  try {
    await auth.login(email.value.trim(), password.value)
    const next = typeof route.query.next === 'string' && route.query.next.startsWith('/') ? route.query.next : surface === 'bank' ? '/bank' : '/'
    await router.push(next)
  } catch (e) {
    if (e instanceof ApiError && e.code === 'wrong_surface') wrongSurface.value = true
    else if (e instanceof ApiError && (e.status === 401 || e.code === 'invalid_credentials')) err.value = t('Wrong email or password.')
    else err.value = errMessage(e)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="page auth-page">
    <div class="page-head">
      <div>
        <h1>{{ surface === 'bank' ? t('Bank officer sign in') : t('Sign in to Converza') }}</h1>
        <p class="meta">{{ surface === 'bank' ? t('MKBANK · SME lending') : t('For business owners: your documents, analysis and loan applications.') }}</p>
      </div>
    </div>
    <form class="panel stack form" @submit.prevent="submit">
      <label class="stack field">
        <span class="eyebrow">{{ t('Email') }}</span>
        <input v-model="email" class="input" type="email" autocomplete="username" required />
      </label>
      <label class="stack field">
        <span class="eyebrow">{{ t('Password') }}</span>
        <input v-model="password" class="input" type="password" autocomplete="current-password" required />
      </label>
      <div v-if="wrongSurface" class="note">
        {{ surface === 'bank' ? t('This is a business owner account. Sign in on the business owner site:') : t('This is a bank officer account. Sign in on the bank officer site:') }}
        <a :href="OTHER_SURFACE_URL + '/login'">{{ OTHER_SURFACE_URL.replace('https://', '') }}</a>
      </div>
      <div v-if="err" class="error-box">{{ err }}</div>
      <button type="submit" class="btn btn-primary" :disabled="busy">{{ busy ? t('Signing in…') : t('Sign in') }}</button>
      <p v-if="surface === 'owner'" class="muted" style="font-size: 13px">
        {{ t('No account yet?') }} <RouterLink to="/register">{{ t('Register your business') }}</RouterLink>
      </p>
    </form>
    <p v-if="surface === 'owner'" class="muted" style="font-size: 13px"><RouterLink to="/analyse">{{ t('Or analyse any document without signing in') }}</RouterLink></p>
  </div>
</template>

<style scoped>
.auth-page { max-width: 440px; margin: 0 auto; width: 100%; }
.form { padding: 18px; gap: 12px; }
.field { gap: 4px; }
</style>
