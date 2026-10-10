<script setup lang="ts">
defineProps<{ value: number; width?: string }>()
</script>

<template>
  <span class="progress" :style="{ width: width || '100%' }" role="progressbar" :aria-valuenow="value" aria-valuemin="0" aria-valuemax="100">
    <span :style="{ width: `${Math.max(0, Math.min(100, value))}%` }"></span>
  </span>
</template>
