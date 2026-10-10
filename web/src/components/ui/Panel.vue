<script setup lang="ts">
defineProps<{ title?: string; ctx?: string; pad?: boolean; label?: string; accent?: boolean }>()
</script>

<template>
  <section class="panel" :class="{ 'accent-panel': accent }" :aria-label="label || title">
    <div v-if="title || ctx || $slots.head" class="panel-head" :style="{ padding: '12px 14px 8px' }">
      <h2 v-if="title">{{ title }}</h2>
      <slot name="head" />
      <span v-if="ctx" class="ctx">{{ ctx }}</span>
    </div>
    <div v-if="pad" style="padding: 0 14px 14px">
      <slot />
    </div>
    <slot v-else />
  </section>
</template>
