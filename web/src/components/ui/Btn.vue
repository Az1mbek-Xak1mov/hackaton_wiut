<script setup lang="ts">
defineProps<{ primary?: boolean; sm?: boolean; to?: string; href?: string; disabled?: boolean; type?: 'button' | 'submit' }>()
</script>

<template>
  <RouterLink v-if="to" :to="to" class="btn" :class="{ 'btn-primary': primary, 'btn-sm': sm }"><slot /></RouterLink>
  <a v-else-if="href" :href="href" class="btn" :class="{ 'btn-primary': primary, 'btn-sm': sm }"><slot /></a>
  <button v-else :type="type || 'button'" class="btn" :class="{ 'btn-primary': primary, 'btn-sm': sm }" :disabled="disabled">
    <slot />
  </button>
</template>
