<script setup lang="ts">
import { ref } from 'vue'
const props = withDefaults(
  defineProps<{ accept?: string; multiple?: boolean; disabled?: boolean; title?: string; hint?: string; compact?: boolean; button?: string }>(),
  { accept: '.pdf,.xlsx,.jpg,.jpeg,.png', multiple: false, title: 'Drop a file here', hint: 'PDF · XLSX · JPG · PNG · up to 20 MB' },
)
const emit = defineEmits<{ (e: 'files', files: File[]): void }>()
const over = ref(false)
const input = ref<HTMLInputElement | null>(null)
const inputId = `dz-${Math.random().toString(36).slice(2, 8)}`

function onDrop(e: DragEvent) {
  over.value = false
  if (props.disabled) return
  const files = [...(e.dataTransfer?.files || [])]
  if (files.length) emit('files', props.multiple ? files : files.slice(0, 1))
}
function onPick(e: Event) {
  const el = e.target as HTMLInputElement
  const files = [...(el.files || [])]
  if (files.length) emit('files', props.multiple ? files : files.slice(0, 1))
  el.value = ''
}
</script>

<template>
  <div
    class="dz"
    :class="{ over, disabled, compact }"
    @dragover.prevent="over = true"
    @dragleave.prevent="over = false"
    @drop.prevent="onDrop"
  >
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true" class="muted"><path d="M12 16V4M6 10l6-6 6 6M4 20h16" /></svg>
    <div style="font-weight: 500">{{ title }}</div>
    <div class="muted" style="font-size: 12px">{{ hint }}</div>
    <label :for="inputId" class="btn btn-primary" :class="{ 'btn-sm': compact }" :aria-disabled="disabled" @click="disabled && $event.preventDefault()">{{ button || (multiple ? 'Choose files' : 'Choose file') }}</label>
    <input :id="inputId" ref="input" type="file" class="sr-only" :accept="accept" :multiple="multiple" :disabled="disabled" @change="onPick" />
  </div>
</template>

<style scoped>
.dz { border: 1.5px dashed var(--border-strong); border-radius: var(--r-panel); background: var(--surface-2); padding: 32px 20px; display: flex; flex-direction: column; align-items: center; gap: 8px; text-align: center; transition: background .15s, border-color .15s; }
.dz.compact { padding: 18px 14px; }
.dz.over { border-color: var(--accent); background: var(--accent-tint); }
.dz.disabled { opacity: .6; }
.dz label { margin-top: 6px; }
</style>
