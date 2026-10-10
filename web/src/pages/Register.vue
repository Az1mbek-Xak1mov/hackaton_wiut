<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuth } from '@/stores/auth'
import { ApiError, errMessage } from '@/api/client'
import Icon from '@/components/ui/Icon.vue'
import { t } from '@/i18n'

const auth = useAuth()
const router = useRouter()
const f = reactive({ full_name: '', company_name: '', stir: '', industry: '', region: '', email: '', password: '', confirm: '' })
const busy = ref(false)
const err = ref('')
const showPw = ref(false)
const nameEl = ref<HTMLInputElement | null>(null)
onMounted(() => nameEl.value?.focus())

const BULLETS = [
  'Upload balance sheets, income statements and bank statements',
  'See your key figures, each linked to the page it was read from',
  'Apply for an SME loan at MKBANK with your documents attached',
]

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
  <div class="auth">
    <section class="intro" :aria-label="t('About Converza')">
      <div class="eyebrow">{{ t('For small and medium businesses') }}</div>
      <div class="brand">Converza</div>
      <p class="lead">{{ t('Create an account for your business. It takes a minute; you can upload documents straight after.') }}</p>
      <ul class="points">
        <li v-for="b in BULLETS" :key="b"><Icon name="check" :size="14" class="tick" />{{ t(b) }}</li>
      </ul>
      <p class="aside">
        <RouterLink to="/analyse">{{ t('Analyse a document without an account') }}</RouterLink>
      </p>
    </section>

    <form class="panel card" @submit.prevent="submit">
      <h1>{{ t('Register your business') }}</h1>
      <div class="grid">
        <label class="field"><span class="lbl">{{ t('Your full name') }}</span><input ref="nameEl" v-model="f.full_name" class="input" required autocomplete="name" /></label>
        <label class="field"><span class="lbl">{{ t('Company name') }}</span><input v-model="f.company_name" class="input" required autocomplete="organization" /></label>
        <label class="field"><span class="lbl">{{ t('STIR (optional, 9 digits)') }}</span><input v-model="f.stir" class="input mono" inputmode="numeric" maxlength="11" /></label>
        <label class="field"><span class="lbl">{{ t('Industry') }}</span><input v-model="f.industry" class="input" required /></label>
        <label class="field wide">
          <span class="lbl">{{ t('Region') }}</span>
          <select v-model="f.region" class="select" required>
            <option value="" disabled>{{ t('Choose a region') }}</option>
            <option v-for="r in REGIONS" :key="r" :value="r">{{ t(r) }}</option>
          </select>
        </label>
        <label class="field wide"><span class="lbl">{{ t('Email') }}</span><input v-model="f.email" class="input" type="email" required autocomplete="email" /></label>
        <div class="field">
          <label class="lbl" for="reg-pw">{{ t('Password') }}</label>
          <div class="pw">
            <input id="reg-pw" v-model="f.password" class="input" :type="showPw ? 'text' : 'password'" required autocomplete="new-password" />
            <button type="button" class="pw-toggle" :aria-pressed="showPw" :aria-label="showPw ? t('Hide password') : t('Show password')" @click="showPw = !showPw">{{ showPw ? t('Hide') : t('Show') }}</button>
          </div>
          <span class="hint muted">{{ t('At least 8 characters') }}</span>
        </div>
        <label class="field"><span class="lbl">{{ t('Confirm password') }}</span><input v-model="f.confirm" class="input" :type="showPw ? 'text' : 'password'" required autocomplete="new-password" /></label>
      </div>
      <div aria-live="polite"><div v-if="err" class="error-box">{{ err }}</div></div>
      <button type="submit" class="btn btn-primary submit" :disabled="busy">{{ busy ? t('Creating account…') : t('Create account') }}</button>
      <p class="foot muted">{{ t('Already registered?') }} <RouterLink to="/login">{{ t('Sign in') }}</RouterLink></p>
    </form>
  </div>
</template>

<style scoped>
.auth { width: 100%; max-width: 1040px; margin: 32px auto 8px; display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 560px); gap: 48px; align-items: start; }
.intro { display: flex; flex-direction: column; gap: 12px; padding-top: 8px; }
.brand { font-size: 28px; font-weight: 600; letter-spacing: -.01em; color: var(--ink); }
.lead { font-size: 16px; line-height: 1.5; color: var(--ink-2); max-width: 420px; }
.points { list-style: none; margin: 4px 0 0; padding: 0; display: flex; flex-direction: column; gap: 10px; font-size: 14px; color: var(--ink-2); }
.points li { display: grid; grid-template-columns: 20px 1fr; gap: 6px; align-items: start; }
.tick { color: var(--accent); margin-top: 3px; }
.aside { font-size: 13px; margin-top: 6px; }
.card { padding: 22px 22px 18px; display: flex; flex-direction: column; gap: 14px; }
.card h1 { font-size: 18px; font-weight: 600; }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(220px, 100%), 1fr)); gap: 14px 16px; }
.wide { grid-column: 1 / -1; }
.field { display: flex; flex-direction: column; gap: 5px; }
.lbl { font-size: 13px; font-weight: 500; color: var(--ink-2); }
.hint { font-size: 12px; }
.input, .select { width: 100%; height: 40px; }
.input:focus, .select:focus { outline: 2px solid var(--accent-border); outline-offset: 0; border-color: var(--accent); }
.pw { position: relative; }
.pw .input { padding-right: 64px; }
.pw-toggle { position: absolute; right: 4px; top: 4px; height: 32px; padding: 0 10px; border: 0; background: transparent; color: var(--accent); font: inherit; font-size: 12.5px; font-weight: 500; border-radius: var(--r-control); cursor: pointer; }
.pw-toggle:hover { background: var(--accent-tint); }
.submit { height: 40px; width: 100%; justify-content: center; }
.foot { font-size: 13px; }
@media (max-width: 860px) {
  .auth { grid-template-columns: 1fr; gap: 20px; margin-top: 8px; }
  .intro { padding-top: 0; }
  .brand { font-size: 24px; }
  .lead { font-size: 15px; }
}
</style>
