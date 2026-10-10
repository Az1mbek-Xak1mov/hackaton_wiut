<script setup lang="ts">
import { useApp } from '@/stores/app'
import { fmtDateTime } from '@/api/format'
const app = useApp()
</script>

<template>
  <footer class="foot">
    <span v-if="app.version">
      Converza · <span class="mono">{{ (app.version.git_sha || 'dev').slice(0, 7) }}</span>
      <template v-if="app.version.deployed_at"> · deployed {{ fmtDateTime(app.version.deployed_at) }}</template>
      <template v-else-if="app.version.built_at"> · built {{ fmtDateTime(app.version.built_at) }}</template>
      · LLM {{ app.version.llm_enabled ? app.version.llm_provider : 'off' }}
    </span>
    <span v-else>Converza</span>
    <span>· Synthetic demonstration data · The system prepares evidence; it never approves or rejects.</span>
  </footer>
</template>

<style scoped>
.foot { display: flex; flex-wrap: wrap; gap: 6px; font-size: 12px; color: var(--ink-muted); padding: 20px 2px 0; margin-top: auto; }
</style>
