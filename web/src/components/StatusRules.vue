<script setup lang="ts">
import { computed } from 'vue'
import { thresholdText } from '@/api/format'
import { t } from '@/i18n'

// Disclosure of how monitoring statuses are set; threshold lines come from the latest run as reported.
const props = defineProps<{ thresholds?: Record<string, any> | null; note?: string | null }>()
const lines = computed(() => thresholdText(props.thresholds))
</script>

<template>
  <div class="rules">
    <div class="eyebrow" style="margin-bottom: 6px">{{ t('How statuses are set') }}</div>
    <p><strong>{{ t('Stable') }}</strong> — {{ t('no indicator crossed its threshold in the last 2 periods.') }}</p>
    <p><strong>{{ t('Watch') }}</strong> — {{ t('one indicator crossed, or the latest statement is late.') }}</p>
    <p><strong>{{ t('Attention') }}</strong> — {{ t('two or more crossed, or an installment was paid late.') }}</p>
    <p class="muted">{{ t('Indicators: revenue vs prior period, receivables vs sales, payables growth, cash coverage of the next installment, payment punctuality, statement timeliness.') }}</p>
    <template v-if="lines.length">
      <div class="eyebrow" style="margin-top: 4px">{{ t('Thresholds in the latest run') }}</div>
      <p v-for="(l, i) in lines" :key="i" class="muted">{{ l }}</p>
    </template>
    <p class="muted">{{ note || t('Thresholds are illustrative; calibration against bank history is pilot month 1.') }} {{ t('No numeric score is produced.') }}</p>
  </div>
</template>

<style scoped>
.rules { font-size: 12px; display: flex; flex-direction: column; gap: 6px; }
</style>
