<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuth } from '@/stores/auth'
import { useApp } from '@/stores/app'
import { errMessage } from '@/api/client'

const props = defineProps<{ mode: 'officer' | 'owner' | 'public' }>()
const auth = useAuth()
const app = useApp()
const router = useRouter()
const switching = ref(false)
const llmBusy = ref(false)
const llmErr = ref('')

const roleLabel = computed(() =>
  props.mode === 'officer' ? 'Bank officer' : props.mode === 'owner' ? 'Business owner' : 'Public analysis',
)
const home = computed(() => (props.mode === 'officer' ? '/bank' : props.mode === 'owner' ? '/owner/cfo' : '/analyse'))

async function switchTo(role: 'officer' | 'owner') {
  switching.value = true
  try {
    await auth.enter(role)
    await router.push(role === 'officer' ? '/bank' : '/owner/cfo')
  } catch (e) {
    llmErr.value = errMessage(e)
  } finally {
    switching.value = false
  }
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
      <span v-if="mode === 'officer'" class="muted sub">for lenders</span>
    </RouterLink>
    <span class="pill" :class="mode === 'public' ? 'pill-info' : 'pill-neutral'">{{ roleLabel }}</span>
    <div style="flex: 1"></div>

    <div v-if="mode === 'officer' && app.llm" class="llm" :title="app.llm.configured === false ? 'No LLM provider key is configured: narratives fall back to template summaries' : app.llm.provider + ' · ' + app.llm.model">
      <span class="muted llm-label">LLM</span>
      <div class="seg" role="group" aria-label="Language model on or off">
        <button type="button" :class="{ on: app.llm.enabled }" :disabled="llmBusy" :aria-pressed="app.llm.enabled" @click="toggleLlm(true)">On</button>
        <button type="button" :class="{ on: !app.llm.enabled }" :disabled="llmBusy" :aria-pressed="!app.llm.enabled" @click="toggleLlm(false)">Off</button>
      </div>
    </div>

    <div class="seg" aria-label="Interface language">
      <button type="button" disabled title="Uzbek interface is not part of this build">UZ</button>
      <button type="button" disabled title="Russian interface is not part of this build">RU</button>
      <button type="button" class="on" aria-pressed="true">EN</button>
    </div>

    <template v-if="mode === 'officer'">
      <button type="button" class="linkbtn muted switch" :disabled="switching" @click="switchTo('owner')">Open business owner view →</button>
    </template>
    <template v-else-if="mode === 'owner'">
      <button type="button" class="linkbtn muted switch" :disabled="switching" @click="switchTo('officer')">Open bank officer view →</button>
    </template>
    <template v-else>
      <button type="button" class="linkbtn switch" :disabled="switching" @click="switchTo('officer')">Enter as bank officer</button>
      <button type="button" class="linkbtn switch" :disabled="switching" @click="switchTo('owner')">Enter as business owner</button>
    </template>

    <span v-if="mode !== 'public'" class="avatar" :title="auth.name">{{ auth.initials }}</span>
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
@media (max-width: 720px) { .top { padding: 8px 16px; gap: 10px; } .sub { display: none; } }
</style>
