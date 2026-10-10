<script setup lang="ts">
import { computed, onMounted, watch } from 'vue'
import { useEvidence } from '@/stores/evidence'
import { factTitle } from '@/api/format'
import { t } from '@/i18n'

const props = defineProps<{ factKey: string; text?: string; long?: boolean; compact?: boolean }>()
const ev = useEvidence()
const fact = computed(() => ev.facts[props.factKey])
const missing = computed(() => ev.missing.has(props.factKey))

onMounted(() => ev.ensure([props.factKey]))
watch(() => props.factKey, (k) => ev.ensure([k]))

const label = computed(() => {
  if (props.text) return props.text
  const f = fact.value
  if (props.compact) {
    // the number is already in the sentence: the chip only points at its source
    if (!f) return '↗'
    if (f.page_n && f.line_code) return `p.${f.page_n} · ${f.line_code}`
    if (f.page_n) return `p.${f.page_n}`
    if (f.line_code) return f.line_code
    return '↗'
  }
  if (!f) return missing.value ? t('source unavailable') : '…'
  if (props.long) return `${f.label} · ${f.display}${f.display_unit ? ' ' + f.display_unit : ''}`
  return f.display
})
const title = computed(() => (fact.value ? `${factTitle(fact.value)} — ${t('click to see where it came from')}` : props.factKey))
</script>

<template>
  <button
    type="button"
    class="ev num"
    :class="{ on: ev.selectedKey === factKey, loading: !fact, compact, long }"
    :title="title"
    :aria-label="title"
    @click.stop="ev.select(factKey)"
  >{{ label }}</button>
</template>

<style scoped>
.ev.compact { font-size: 11px; padding: 0 4px; line-height: 1.4; vertical-align: 1px; }
/* long labels wrap like text instead of becoming a centred block */
.ev.long { display: inline; text-align: left; -webkit-box-decoration-break: clone; box-decoration-break: clone; line-height: 1.6; }
</style>
