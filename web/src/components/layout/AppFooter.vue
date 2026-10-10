<script setup lang="ts">
import { useApp } from '@/stores/app'
import { fmtDateTime } from '@/api/format'
import { t } from '@/i18n'
const app = useApp()
</script>

<template>
  <footer class="foot">
    <span v-if="app.version">
      Converza · <span class="mono">{{ (app.version.git_sha || 'dev').slice(0, 7) }}</span>
      <template v-if="app.version.deployed_at"> · {{ t('deployed {when}', { when: fmtDateTime(app.version.deployed_at) }) }}</template>
      <template v-else-if="app.version.built_at"> · {{ t('built {when}', { when: fmtDateTime(app.version.built_at) }) }}</template>
      · LLM {{ app.version.llm_enabled && app.version.llm_configured !== false ? app.version.llm_provider : t('off') }}
    </span>
    <span v-else>Converza</span>
    <span>· {{ t('Synthetic demonstration data') }}</span>
  </footer>
</template>

<style scoped>
.foot { display: flex; flex-wrap: wrap; gap: 6px; font-size: 12px; color: var(--ink-muted); padding: 20px 2px 0; margin-top: auto; }
</style>
