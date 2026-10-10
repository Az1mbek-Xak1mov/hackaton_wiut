<script setup lang="ts">
import { onMounted, onBeforeUnmount } from 'vue'
import { t } from '@/i18n'
const props = defineProps<{ title: string }>()
const emit = defineEmits<{ (e: 'close'): void }>()
function onKey(e: KeyboardEvent) {
  if (e.key === 'Escape') emit('close')
}
onMounted(() => document.addEventListener('keydown', onKey))
onBeforeUnmount(() => document.removeEventListener('keydown', onKey))
</script>

<template>
  <div class="modal-backdrop" @click.self="emit('close')">
    <div class="panel modal" role="dialog" aria-modal="true" :aria-label="props.title">
      <div class="panel-head" style="padding: 14px 16px 10px; border-bottom: 1px solid var(--border-row)">
        <h2>{{ props.title }}</h2>
        <button type="button" class="btn btn-sm" :aria-label="t('Close')" @click="emit('close')">{{ t('Close') }}</button>
      </div>
      <div style="padding: 14px 16px 16px">
        <slot />
      </div>
    </div>
  </div>
</template>

<style scoped>
.modal-backdrop { position: fixed; inset: 0; background: rgba(27, 26, 23, .35); display: flex; align-items: flex-start; justify-content: center; padding: 64px 16px; z-index: 50; overflow-y: auto; }
.modal { width: min(560px, 100%); }
</style>
