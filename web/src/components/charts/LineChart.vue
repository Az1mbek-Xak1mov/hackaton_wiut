<script setup lang="ts">
import { computed } from 'vue'
import { fmtAxis, niceMax } from './nice'

const props = defineProps<{
  labels: string[]
  values: (number | null)[]
  display?: (string | null)[]
  threshold?: number | null
  thresholdLabel?: string
  suffix?: string
  summary: string
  height?: number
}>()

const W = 720
const H = computed(() => props.height || 120)
const L = 50
const R = 710
const T = 20
const B = computed(() => H.value - 22)
const max = computed(() => niceMax(Math.max(props.threshold ?? 0, ...props.values.map((v) => v ?? 0)) * 1.1))
const step = computed(() => (R - L) / Math.max(1, props.labels.length))
function x(i: number) {
  return L + step.value * (i + 0.5)
}
function y(v: number) {
  return B.value - (Math.max(0, v) / max.value) * (B.value - T)
}
const pts = computed(() => props.values.map((v, i) => (v == null ? null : { x: x(i), y: y(v), v, i })).filter(Boolean) as { x: number; y: number; v: number; i: number }[])
const poly = computed(() => pts.value.map((p) => `${p.x},${p.y}`).join(' '))
const lastI = computed(() => pts.value.length - 1)
function lab(p: { v: number; i: number }) {
  return props.display?.[p.i] ?? `${fmtAxis(p.v)}${props.suffix || ''}`
}
function below(v: number) {
  return props.threshold != null && v < props.threshold
}
</script>

<template>
  <svg :viewBox="`0 0 ${W} ${H}`" width="100%" role="img" :aria-label="summary">
    <line :x1="L" :y1="B" :x2="R" :y2="B" stroke="var(--border-row)" />
    <template v-if="threshold != null">
      <line :x1="L" :y1="y(threshold)" :x2="R" :y2="y(threshold)" stroke="var(--attn-mark)" stroke-dasharray="4 4" stroke-width="1" />
      <text :x="R - 4" :y="y(threshold) - 4" fill="var(--attn-fg)" font-size="11" text-anchor="end">{{ thresholdLabel || `${fmtAxis(threshold)}${suffix || ''}` }}</text>
    </template>
    <polyline v-if="pts.length > 1" fill="none" stroke="var(--series-1)" stroke-width="2" stroke-linejoin="round" :points="poly" />
    <template v-for="(p, k) in pts" :key="p.i">
      <circle v-if="k !== lastI" :cx="p.x" :cy="p.y" r="4" fill="#fff" stroke="var(--series-1)" stroke-width="2" />
      <circle v-else :cx="p.x" :cy="p.y" r="5" :fill="below(p.v) ? 'var(--attn-mark)' : 'var(--series-1)'" />
      <text v-if="k === 0 || k === lastI" :x="p.x" :y="p.y - 10" font-size="11" fill="var(--ink)" text-anchor="middle">{{ lab(p) }}</text>
    </template>
    <text v-for="(l, i) in labels" :key="l + i" :x="x(i)" :y="H - 4" font-size="11" fill="var(--ink-muted)" text-anchor="middle">{{ l }}</text>
  </svg>
</template>

<style scoped>
svg text { font-family: var(--font-sans); }
</style>
