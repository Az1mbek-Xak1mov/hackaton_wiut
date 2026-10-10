<script setup lang="ts">
import Icon from '@/components/ui/Icon.vue'
import { t } from '@/i18n'
</script>

<template>
  <div class="proto" role="note">
    <span class="main"><Icon name="info" :size="14" class="ic" />{{ t('Prototype for the MKBANK pilot. Sample documents are synthetic; all figures are computed live from uploaded files.') }}</span>
    <span class="proto-extra">{{ t('No numeric credit score is produced; statuses are rule-based and their thresholds are disclosed.') }}</span>
  </div>
</template>

<style scoped>
.proto { display: flex; align-items: center; gap: 10px; min-height: 28px; padding: 4px 20px; background: var(--watch-bg); color: var(--watch-fg); font-size: 12px; font-weight: 500; flex-wrap: wrap; }
.main { display: inline-flex; align-items: flex-start; gap: 8px; }
.ic { flex: none; margin-top: 2px; }
.proto-extra { color: var(--watch-fg); opacity: .85; font-weight: 400; }
@media (max-width: 720px) { .proto { padding: 4px 16px; } .proto-extra { display: none; } }
</style>
