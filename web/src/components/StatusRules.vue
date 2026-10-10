<script setup lang="ts">
import { computed } from 'vue'
import { thresholdText } from '@/api/format'
import { t } from '@/i18n'

// Disclosure of how monitoring statuses are set (collapsed by default); thresholds come from the latest run as reported.
const props = defineProps<{ thresholds?: Record<string, any> | null; note?: string | null }>()
const lines = computed(() => thresholdText(props.thresholds))
</script>

<template>
  <details class="rules">
    <summary>{{ t('How statuses are set') }}</summary>
    <div class="body">
      <p><strong>{{ t('Stable') }}</strong> — {{ t('no warning sign in the last 2 periods.') }}</p>
      <p><strong>{{ t('Watch') }}</strong> — {{ t('one warning sign, or the latest statement is late.') }}</p>
      <p><strong>{{ t('Attention') }}</strong> — {{ t('two or more warning signs, or a payment was late.') }}</p>
      <p><strong>{{ t('No loan yet') }}</strong> — {{ t('the business has documents or an application but no loan to monitor.') }}</p>
      <template v-if="lines.length">
        <div class="eyebrow" style="margin-top: 4px">{{ t('Warning signs checked') }}</div>
        <p v-for="(l, i) in lines" :key="i" class="muted">{{ l }}</p>
      </template>
      <p class="muted">{{ note || t('Thresholds are illustrative; calibration against bank history is pilot month 1.') }} {{ t('No numeric score is produced.') }}</p>
    </div>
  </details>
</template>

<style scoped>
.rules { font-size: 12px; }
.rules summary { cursor: pointer; font-weight: 600; font-size: 12.5px; }
.body { display: flex; flex-direction: column; gap: 6px; margin-top: 8px; }
</style>
