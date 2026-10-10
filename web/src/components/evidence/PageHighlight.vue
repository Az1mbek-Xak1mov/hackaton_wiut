<script setup lang="ts">
import { computed, ref, toRef } from 'vue'
import { useAuthedImage } from '@/composables/useAuthedImage'
import { t } from '@/i18n'

const props = defineProps<{
  url: string | null
  bbox: [number, number, number, number] | null
  pageWidth: number | null
  pageHeight: number | null
  alt: string
}>()

const whole = ref(false)
const { src, loading, failed } = useAuthedImage(toRef(props, 'url'))

const canOverlay = computed(() => !!(props.bbox && props.pageWidth && props.pageHeight))

const viewBox = computed(() => {
  const W = props.pageWidth || 1
  const H = props.pageHeight || 1
  if (!canOverlay.value || whole.value) return `0 0 ${W} ${H}`
  const [, y0, , y1] = props.bbox!
  const h = Math.min(H, Math.max(W * 0.32, (y1 - y0) * 6))
  const cy = (y0 + y1) / 2
  const top = Math.max(0, Math.min(H - h, cy - h / 2))
  return `0 ${top} ${W} ${h}`
})

const rect = computed(() => {
  if (!props.bbox) return null
  const [x0, y0, x1, y1] = props.bbox
  const pad = Math.max(1.5, (props.pageWidth || 600) * 0.004)
  return { x: x0 - pad, y: y0 - pad, w: x1 - x0 + pad * 2, h: y1 - y0 + pad * 2 }
})

defineExpose({ src })
</script>

<template>
  <div class="ph">
    <div v-if="loading" class="ph-msg muted">{{ t('Loading page image… (a scanned page can take a few seconds)') }}</div>
    <div v-else-if="failed || !src" class="ph-msg muted">{{ t('Page image not available.') }}</div>
    <template v-else>
      <svg
        v-if="canOverlay"
        class="ph-svg"
        :viewBox="viewBox"
        preserveAspectRatio="xMidYMin meet"
        role="img"
        :aria-label="alt"
      >
        <image :href="src" x="0" y="0" :width="pageWidth!" :height="pageHeight!" preserveAspectRatio="none" />
        <rect v-if="rect" :x="rect.x" :y="rect.y" :width="rect.w" :height="rect.h" class="ph-hit" />
      </svg>
      <img v-else :src="src" :alt="alt" class="ph-img" />
      <div class="ph-bar">
        <span class="muted">{{ canOverlay ? t('Highlighted: the cell the value was read from') : t('Location on the page was not recorded') }}</span>
        <button v-if="canOverlay" type="button" class="linkbtn" @click="whole = !whole">{{ whole ? t('Zoom to value') : t('Show whole page') }}</button>
      </div>
    </template>
  </div>
</template>

<style scoped>
.ph { border: 1px solid var(--border); border-radius: 4px; background: var(--surface-2); overflow: hidden; }
.ph-svg { display: block; width: 100%; height: auto; max-height: 560px; background: #fff; }
.ph-img { display: block; width: 100%; background: #fff; }
.ph-hit { fill: var(--highlight); fill-opacity: .45; stroke: var(--highlight-underline); stroke-width: 1.5; vector-effect: non-scaling-stroke; }
.ph-bar { display: flex; justify-content: space-between; gap: 8px; padding: 6px 10px; font-size: 12px; border-top: 1px solid var(--border-row); flex-wrap: wrap; }
.ph-msg { padding: 14px 12px; font-size: 12px; }
</style>
