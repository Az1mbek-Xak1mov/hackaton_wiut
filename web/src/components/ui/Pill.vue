<script setup lang="ts">
import { computed } from 'vue'
const props = defineProps<{ kind?: 'stable' | 'watch' | 'attn' | 'neutral' | 'info' | string }>()
const cls = computed(() => {
  const k = props.kind || 'neutral'
  return ['stable', 'watch', 'attn', 'neutral', 'info'].includes(k) ? `pill-${k}` : k.startsWith('pill-') ? k : 'pill-neutral'
})
</script>

<template>
  <span class="pill" :class="cls"><slot /></span>
</template>
