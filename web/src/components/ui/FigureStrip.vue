<script setup lang="ts">
defineProps<{ label?: string }>()
</script>

<template>
  <section class="panel figstrip" :aria-label="label || 'Key figures'">
    <slot />
  </section>
</template>
