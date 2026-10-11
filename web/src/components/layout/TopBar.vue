<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuth } from '@/stores/auth'
import { useApp } from '@/stores/app'
import { errMessage } from '@/api/client'
import { aiStatusMessage } from '@/api/aiStatus'
import { lang, setLang, t, type Lang } from '@/i18n'

const props = defineProps<{ mode: 'officer' | 'owner' | 'public' }>()
const auth = useAuth()
const app = useApp()
const router = useRouter()
const llmBusy = ref(false)
const llmErr = ref('')

const roleLabel = computed(() =>
  props.mode === 'officer' ? t('Bank officer') : t('Business owner'),
)
const LANGS: { code: Lang; label: string }[] = [
  { code: 'uz', label: 'UZ' },
  { code: 'ru', label: 'RU' },
  { code: 'en', label: 'EN' },
]
const home = computed(() => (props.mode === 'officer' ? '/bank' : '/'))

function logout() {
  auth.logout()
  router.push(props.mode === 'officer' ? '/login' : '/')
}

async function toggleLlm(enabled: boolean) {
  if (!app.llm || app.llm.enabled === enabled) return
  llmBusy.value = true
  llmErr.value = ''
  try {
    await app.setLlm(enabled)
  } catch (e) {
    llmErr.value = errMessage(e)
  } finally {
    llmBusy.value = false
  }
}
</script>

<template>
  <header class="top">
    <RouterLink :to="home" class="brand">
      <span class="mark" :class="{ ink: mode === 'officer' }">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.4" aria-hidden="true"><path d="M4 18 10 11l4 4 6-8" /></svg>
      </span>
      <span class="word">Converza</span>
      <span v-if="mode === 'officer'" class="muted sub">{{ t('for lenders') }}</span>
    </RouterLink>
    <span class="pill" :class="mode === 'public' ? 'pill-info' : 'pill-neutral'">{{ roleLabel }}</span>
    <div style="flex: 1"></div>

    <div v-if="mode === 'officer' && app.llm" class="llm" :title="app.llm.configured === false ? t('No LLM provider key is configured: narratives fall back to template summaries') : (app.llm.status === 'no_credits' || app.llm.status === 'no_key') ? aiStatusMessage(app.llm.status, app.llm.status_text) : app.llm.provider + ' · ' + app.llm.model">
      <span class="muted llm-label">LLM<span v-if="app.llm.configured === false" class="nokey"> · {{ t('no provider key') }}</span><span v-else-if="app.llm.status === 'no_credits'" class="nokey"> · {{ t('no credits left') }}</span><span v-else-if="app.llm.status === 'no_key'" class="nokey"> · {{ t('key rejected') }}</span></span>
      <div class="seg" role="group" :aria-label="t('Language model on or off')">
        <button type="button" :class="{ on: app.llm.enabled }" :disabled="llmBusy" :aria-pressed="app.llm.enabled" @click="toggleLlm(true)">{{ t('On') }}</button>
        <button type="button" :class="{ on: !app.llm.enabled }" :disabled="llmBusy" :aria-pressed="!app.llm.enabled" @click="toggleLlm(false)">{{ t('Off') }}</button>
      </div>
    </div>

    <div class="seg" role="group" :aria-label="t('Interface language')">
      <button v-for="l in LANGS" :key="l.code" type="button" :class="{ on: lang === l.code }" :aria-pressed="lang === l.code" :lang="l.code" @click="setLang(l.code)">{{ l.label }}</button>
    </div>

    <template v-if="auth.loggedIn">
      <span class="avatar" :title="auth.name">{{ auth.initials }}</span>
      <button type="button" class="linkbtn muted switch" @click="logout">{{ t('Log out') }}</button>
    </template>
    <template v-else-if="mode !== 'officer'">
      <RouterLink to="/login" class="switch">{{ t('Sign in') }}</RouterLink>
      <RouterLink to="/register" class="btn btn-sm btn-primary">{{ t('Register') }}</RouterLink>
    </template>
    <span v-if="llmErr" class="err" role="alert">{{ llmErr }}</span>
  </header>
</template>

<style scoped>
.top { display: flex; align-items: center; gap: 16px; min-height: 52px; padding: 8px 20px; background: var(--surface); border-bottom: 1px solid var(--border); flex-wrap: wrap; }
.brand { display: flex; align-items: center; gap: 10px; text-decoration: none; color: var(--ink); }
.mark { width: 22px; height: 22px; border-radius: 4px; background: var(--accent); display: inline-flex; align-items: center; justify-content: center; }
.mark.ink { background: var(--ink); }
.word { font-weight: 600; font-size: 15px; letter-spacing: -.01em; }
.sub { font-size: 13px; }
.switch { font-size: 13px; text-decoration: none; }
.switch.muted { color: var(--ink-muted); }
.switch:hover { color: var(--ink); }
.avatar { width: 30px; height: 30px; border-radius: 50%; background: var(--border); display: inline-flex; align-items: center; justify-content: center; font-size: 12px; font-weight: 600; color: var(--ink-2); }
.llm { display: inline-flex; align-items: center; gap: 8px; }
.llm-label { font-size: 12px; font-weight: 500; }
.err { flex-basis: 100%; font-size: 12px; color: var(--attn-fg); }
@media (max-width: 720px) { .top { padding: 8px 16px; gap: 8px 10px; } .sub, .nokey { display: none; } }
</style>
