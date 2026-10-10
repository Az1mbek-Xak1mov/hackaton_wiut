<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuth } from '@/stores/auth'
import { useApp } from '@/stores/app'
import { ApiError, errMessage } from '@/api/client'
import { OTHER_SURFACE_URL, surface } from '@/surface'
import Icon from '@/components/ui/Icon.vue'
import { t } from '@/i18n'

const auth = useAuth()
const app = useApp()
const route = useRoute()
const router = useRouter()
const email = ref('')
const password = ref('')
const showPw = ref(false)
const busy = ref(false)
const err = ref('')
const wrongSurface = ref(false)
const emailEl = ref<HTMLInputElement | null>(null)
const bank = surface === 'bank'

onMounted(() => emailEl.value?.focus())

const BULLETS = bank
  ? [
      'Work through the queue of new applications and monitored borrowers',
      'See the checks that did not pass and the source page behind every figure',
      'Record your decision and reasoning; the system never approves or rejects',
    ]
  : [
      'Upload balance sheets, income statements and bank statements',
      'See your key figures, each linked to the page it was read from',
      'Apply for an SME loan at MKBANK with your documents attached',
    ]

const demoBusy = ref(false)
async function tryDemo() {
  err.value = ''
  wrongSurface.value = false
  demoBusy.value = true
  try {
    await auth.demoLogin()
    await router.push(bank ? '/bank' : '/')
  } catch (e) {
    err.value = e instanceof ApiError && e.status === 404 ? t('The demo account is switched off on this server.') : errMessage(e)
  } finally {
    demoBusy.value = false
  }
}

async function submit() {
  err.value = ''
  wrongSurface.value = false
  if (!email.value.trim() || !password.value) {
    err.value = t('Enter your email and password.')
    return
  }
  busy.value = true
  try {
    await auth.login(email.value.trim(), password.value)
    const next = typeof route.query.next === 'string' && route.query.next.startsWith('/') ? route.query.next : bank ? '/bank' : '/'
    await router.push(next)
  } catch (e) {
    if (e instanceof ApiError && e.code === 'wrong_surface') wrongSurface.value = true
    else if (e instanceof ApiError && (e.status === 401 || e.code === 'invalid_credentials')) err.value = t('Wrong email or password. Check both and try again.')
    else if (e instanceof ApiError && e.status === 429) err.value = t('Too many attempts. Wait a minute and try again.')
    else err.value = errMessage(e)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="auth">
    <section class="intro" :aria-label="t('About Converza')">
      <div class="eyebrow">{{ bank ? t('For MKBANK SME lending officers') : t('For small and medium businesses') }}</div>
      <div class="brand">Converza</div>
      <p class="lead">
        {{ bank ? t('Review loan applications with every figure traced back to the borrower’s own documents.') : t('See your company’s figures from your own statements, each one linked to the page it came from.') }}
      </p>
      <ul class="points">
        <li v-for="b in BULLETS" :key="b"><Icon name="check" :size="14" class="tick" />{{ t(b) }}</li>
      </ul>
      <p v-if="!bank" class="aside">
        <RouterLink to="/analyse">{{ t('Analyse a document without an account') }}</RouterLink>
        <span class="muted"> · {{ t('no sign-up, deleted after 24 hours') }}</span>
      </p>
    </section>

    <form class="panel card" novalidate @submit.prevent="submit">
      <h1>{{ bank ? t('Bank officer sign in') : t('Sign in') }}</h1>
      <label class="field">
        <span class="lbl">{{ t('Email') }}</span>
        <input ref="emailEl" v-model="email" class="input" type="email" autocomplete="username" required :aria-invalid="!!err" />
      </label>
      <div class="field">
        <label class="lbl" for="login-pw">{{ t('Password') }}</label>
        <div class="pw">
          <input id="login-pw" v-model="password" class="input" :type="showPw ? 'text' : 'password'" autocomplete="current-password" required :aria-invalid="!!err" />
          <button type="button" class="pw-toggle" :aria-pressed="showPw" :aria-label="showPw ? t('Hide password') : t('Show password')" @click="showPw = !showPw">
            {{ showPw ? t('Hide') : t('Show') }}
          </button>
        </div>
      </div>
      <div aria-live="polite">
        <div v-if="wrongSurface" class="note">
          {{ bank ? t('This is a business owner account. Sign in on the business owner site:') : t('This is a bank officer account. Sign in on the bank officer site:') }}
          <a :href="OTHER_SURFACE_URL + '/login'">{{ OTHER_SURFACE_URL.replace('https://', '') }}</a>
        </div>
        <div v-if="err" class="error-box">{{ err }}</div>
      </div>
      <button type="submit" class="btn btn-primary submit" :disabled="busy">{{ busy ? t('Signing in…') : t('Sign in') }}</button>
      <div v-if="app.version?.demo_login" class="demo">
        <div class="demo-head">{{ t('Jury and visitors') }}</div>
        <p class="muted demo-note">{{ bank ? t('Open the bank officer app with the shared demo account. All data is synthetic.') : t('Open the shared demo business, Farovon Savdo MChJ. All data is synthetic.') }}</p>
        <button type="button" class="btn demo-btn" :disabled="demoBusy" @click="tryDemo">{{ demoBusy ? t('Signing in…') : t('Sign in with the demo account') }}</button>
      </div>
      <p v-if="bank" class="foot muted">{{ t('Accounts are issued by the bank. Ask your branch administrator if you need access.') }}</p>
      <p v-else class="foot muted">
        {{ t('No account yet?') }} <RouterLink to="/register">{{ t('Register your business') }}</RouterLink>
      </p>
    </form>
  </div>
</template>

<style scoped>
.auth { width: 100%; max-width: 960px; margin: 32px auto 8px; display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 400px); gap: 48px; align-items: start; }
.intro { display: flex; flex-direction: column; gap: 12px; padding-top: 8px; }
.brand { font-size: 28px; font-weight: 600; letter-spacing: -.01em; color: var(--ink); }
.lead { font-size: 16px; line-height: 1.5; color: var(--ink-2); max-width: 440px; }
.points { list-style: none; margin: 4px 0 0; padding: 0; display: flex; flex-direction: column; gap: 10px; font-size: 14px; color: var(--ink-2); }
.points li { display: grid; grid-template-columns: 20px 1fr; gap: 6px; align-items: start; }
.tick { color: var(--accent); margin-top: 3px; }
.aside { font-size: 13px; margin-top: 6px; }
.card { padding: 22px 22px 18px; display: flex; flex-direction: column; gap: 14px; }
.card h1 { font-size: 18px; font-weight: 600; }
.field { display: flex; flex-direction: column; gap: 5px; }
.lbl { font-size: 13px; font-weight: 500; color: var(--ink-2); }
.input { width: 100%; height: 40px; }
.input:focus { outline: 2px solid var(--accent-border); outline-offset: 0; border-color: var(--accent); }
.pw { position: relative; }
.pw .input { padding-right: 64px; }
.pw-toggle { position: absolute; right: 4px; top: 4px; height: 32px; padding: 0 10px; border: 0; background: transparent; color: var(--accent); font: inherit; font-size: 12.5px; font-weight: 500; border-radius: var(--r-control); cursor: pointer; }
.pw-toggle:hover { background: var(--accent-tint); }
.submit { height: 40px; width: 100%; justify-content: center; }
.foot { font-size: 13px; }
.demo { border: 1px solid var(--border); border-radius: var(--r-panel); background: var(--surface-2); padding: 12px; display: flex; flex-direction: column; gap: 6px; font-size: 13px; }
.demo-head { font-weight: 600; }
.demo-note { font-size: 12.5px; }
.demo-btn { align-self: flex-start; height: 34px; }
@media (max-width: 760px) {
  .auth { grid-template-columns: 1fr; gap: 20px; margin-top: 8px; }
  .intro { padding-top: 0; }
  .brand { font-size: 24px; }
  .lead { font-size: 15px; }
}
</style>
