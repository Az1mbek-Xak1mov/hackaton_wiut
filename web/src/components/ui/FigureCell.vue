<script setup lang="ts">
defineProps<{ eyebrow: string; value?: string | number | null; unit?: string; flagged?: boolean }>()
</script>

<template>
  <div class="fig" :class="{ flagged }">
    <div class="row" style="justify-content: space-between">
      <span class="eyebrow">{{ eyebrow }}</span>
      <slot name="pill" />
    </div>
    <div class="big num" style="margin-top: 6px">
      <slot name="value">{{ value ?? '—' }}</slot>
      <span v-if="unit" class="unit"> {{ unit }}</span>
    </div>
    <div class="muted" style="margin-top: 4px; font-size: 13px"><slot /></div>
  </div>
</template>
