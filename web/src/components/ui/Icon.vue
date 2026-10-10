<script setup lang="ts">
// Stroke icons copied from the design reference artboards (16px, stroke 2).
defineProps<{ name: string; size?: number }>()
</script>

<template>
  <svg :width="size || 16" :height="size || 16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
    <template v-if="name === 'grid'"><rect x="3" y="3" width="7" height="9" /><rect x="14" y="3" width="7" height="5" /><rect x="14" y="12" width="7" height="9" /><rect x="3" y="16" width="7" height="5" /></template>
    <template v-else-if="name === 'file'"><path d="M14 3H6a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8z" /><path d="M14 3v5h5M9 13h6M9 17h6" /></template>
    <template v-else-if="name === 'bank'"><path d="M3 21h18M5 21V8l7-5 7 5v13M9 21v-6h6v6" /></template>
    <template v-else-if="name === 'alert'"><path d="M12 3 2 21h20z M12 10v5M12 18h.01" /></template>
    <template v-else-if="name === 'upload'"><path d="M12 16V4M6 10l6-6 6 6M4 20h16" /></template>
    <template v-else-if="name === 'pulse'"><path d="M3 12h4l3-8 4 16 3-8h4" /></template>
    <template v-else-if="name === 'chat'"><path d="M4 5h16v11H9l-5 4z" /></template>
    <template v-else-if="name === 'info'"><circle cx="12" cy="12" r="9" /><path d="M12 8v5M12 16h.01" /></template>
    <template v-else-if="name === 'search'"><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></template>
    <template v-else-if="name === 'chart'"><path d="M4 20V10M10 20V4M16 20v-7M22 20H2" /></template>
    <template v-else-if="name === 'check'"><path d="m5 12 5 5L20 7" /></template>
    <template v-else-if="name === 'logo'"><path d="M4 18 10 11l4 4 6-8" /></template>
    <template v-else><circle cx="12" cy="12" r="2" /></template>
  </svg>
</template>
