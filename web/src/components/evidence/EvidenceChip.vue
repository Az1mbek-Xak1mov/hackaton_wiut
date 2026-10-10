<script setup lang="ts">
import { computed, onMounted, watch } from 'vue'
import { useEvidence } from '@/stores/evidence'
import { factTitle } from '@/api/format'

const props = defineProps<{ factKey: string; text?: string; long?: boolean; compact?: boolean }>()
const ev = useEvidence()
const fact = computed(() => ev.facts[props.factKey])
const missing = computed(() => ev.missing.has(props.factKey))

onMounted(() => ev.ensure([props.factKey]))
watch(() => props.factKey, (k) => ev.ensure([k]))

const label = computed(() => {
  if (props.text) return props.text
  if (props.compact) return 'source'
  const f = fact.value
  if (!f) return missing.value ? 'source unavailable' : '…'
  if (props.long) return `${f.label} · ${f.display}${f.display_unit ? ' ' + f.display_unit : ''}`
  return f.display
})
const title = computed(() => (fact.value ? `${factTitle(fact.value)} — click to see where it came from` : props.factKey))
</script>

<template>
  <button
    type="button"
    class="ev num"
    :class="{ on: ev.selectedKey === factKey, loading: !fact, compact }"
    :title="title"
    :aria-label="title"
    @click.stop="ev.select(factKey)"
  >{{ label }}</button>
</template>

<style scoped>
.ev.compact { font-size: 11px; padding: 0 4px; line-height: 1.4; vertical-align: 1px; }
</style>
