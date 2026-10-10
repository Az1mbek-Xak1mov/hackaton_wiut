<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuth } from '@/stores/auth'
import { ApiError, errMessage } from '@/api/client'
import { t } from '@/i18n'

const auth = useAuth()
const router = useRouter()
const f = reactive({ full_name: '', company_name: '', stir: '', industry: '', region: '', email: '', password: '', confirm: '' })
const busy = ref(false)
const err = ref('')

const REGIONS = ['Tashkent city', 'Tashkent region', 'Andijan', 'Bukhara', 'Fergana', 'Jizzakh', 'Kashkadarya', 'Khorezm', 'Namangan', 'Navoi', 'Samarkand', 'Surkhandarya', 'Syrdarya', 'Karakalpakstan']

async function submit() {
  err.value = ''
  if (f.stir && !/^\d{9}$/.test(f.stir.replace(/\s/g, ''))) return (err.value = t('STIR must be 9 digits.'))
  if (f.password.length < 8) return (err.value = t('Password must be at least 8 characters.'))
  if (f.password !== f.confirm) return (err.value = t('Passwords do not match.'))
  busy.value = true
  try {
    await auth.register({
      full_name: f.full_name.trim(),
      company_name: f.company_name.trim(),
      stir: f.stir.replace(/\s/g, '') || undefined,
      industry: f.industry.trim(),
      region: f.region,
      email: f.email.trim(),
      password: f.password,
    })
    await router.push('/')
  } catch (e) {
    if (e instanceof ApiError && e.status === 409) err.value = t('An account with this email or STIR already exists.')
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
        <h1>{{ t('Register your business') }}</h1>
        <p class="meta">{{ t('Upload your statements, see your figures with their sources, and apply for a loan.') }}</p>
      </div>
    </div>
    <form class="panel form" @submit.prevent="submit">
      <label class="field"><span class="eyebrow">{{ t('Your full name') }}</span><input v-model="f.full_name" class="input" required autocomplete="name" /></label>
      <label class="field"><span class="eyebrow">{{ t('Company name') }}</span><input v-model="f.company_name" class="input" required autocomplete="organization" /></label>
      <label class="field"><span class="eyebrow">{{ t('STIR (optional, 9 digits)') }}</span><input v-model="f.stir" class="input mono" inputmode="numeric" maxlength="11" /></label>
      <label class="field"><span class="eyebrow">{{ t('Industry') }}</span><input v-model="f.industry" class="input" required /></label>
      <label class="field">
        <span class="eyebrow">{{ t('Region') }}</span>
        <select v-model="f.region" class="select" required>
          <option value="" disabled>{{ t('Choose a region') }}</option>
          <option v-for="r in REGIONS" :key="r" :value="r">{{ t(r) }}</option>
        </select>
      </label>
      <label class="field"><span class="eyebrow">{{ t('Email') }}</span><input v-model="f.email" class="input" type="email" required autocomplete="email" /></label>
      <label class="field"><span class="eyebrow">{{ t('Password') }}</span><input v-model="f.password" class="input" type="password" required autocomplete="new-password" /></label>
      <label class="field"><span class="eyebrow">{{ t('Confirm password') }}</span><input v-model="f.confirm" class="input" type="password" required autocomplete="new-password" /></label>
      <div v-if="err" class="error-box wide">{{ err }}</div>
      <div class="wide row">
        <button type="submit" class="btn btn-primary" :disabled="busy">{{ busy ? t('Creating account…') : t('Create account') }}</button>
        <span class="muted" style="font-size: 13px">{{ t('Already registered?') }} <RouterLink to="/login">{{ t('Sign in') }}</RouterLink></span>
      </div>
    </form>
  </div>
</template>

<style scoped>
.auth-page { max-width: 640px; margin: 0 auto; width: 100%; }
.form { padding: 18px; display: grid; grid-template-columns: repeat(auto-fit, minmax(min(260px, 100%), 1fr)); gap: 12px 16px; }
.field { display: flex; flex-direction: column; gap: 4px; }
.wide { grid-column: 1 / -1; }
</style>
