<script setup lang="ts">
import { computed } from 'vue'
import { fmtAxis, niceMax } from './nice'

// ≤ 2 series: series-1 = "ours/now", series-compare = the comparison. One y-axis.
const props = defineProps<{
  labels: string[]
  a: (number | null)[]
  b?: (number | null)[]
  aName: string
  bName?: string
  aDisplay?: (string | null)[]
  bDisplay?: (string | null)[]
  summary: string
}>()

const W = 720
const H = 230
const L = 50
const R = 710
const T = 20
const B = 200

const max = computed(() => niceMax(Math.max(0, ...props.a.map((v) => v ?? 0), ...(props.b || []).map((v) => v ?? 0))))
const groupW = computed(() => (R - L) / Math.max(1, props.labels.length))
const barW = computed(() => Math.min(48, (groupW.value - 24) / (props.b ? 2 : 1)))
function y(v: number) {
  return B - (v / max.value) * (B - T)
}
const bars = computed(() =>
  props.labels.map((lab, i) => {
    const cx = L + groupW.value * (i + 0.5)
    const n = props.b ? 2 : 1
    const total = n * barW.value + (n - 1) * 4
    const x0 = cx - total / 2
    return {
      lab,
      cx,
      a: props.a[i],
      b: props.b ? props.b[i] : null,
      ax: x0,
      bx: x0 + barW.value + 4,
      aLabel: props.aDisplay?.[i] ?? (props.a[i] != null ? fmtAxis(props.a[i]!) : ''),
      bLabel: props.bDisplay?.[i] ?? (props.b?.[i] != null ? fmtAxis(props.b![i]!) : ''),
    }
  }),
)
const last = computed(() => bars.value.length - 1)
</script>

<template>
  <div>
    <div class="legend" aria-hidden="true">
      <span><i style="background: var(--series-1)"></i>{{ aName }}</span>
      <span v-if="b"><i style="background: var(--series-compare)"></i>{{ bName }}</span>
    </div>
    <svg :viewBox="`0 0 ${W} ${H}`" width="100%" role="img" :aria-label="summary">
      <g stroke="var(--border-row)">
        <line :x1="L" :y1="B" :x2="R" :y2="B" />
        <line :x1="L" :y1="(B + T) / 2" :x2="R" :y2="(B + T) / 2" />
        <line :x1="L" :y1="T" :x2="R" :y2="T" />
      </g>
      <g fill="var(--ink-muted)" font-size="11" text-anchor="end">
        <text :x="L - 6" :y="B + 4">0</text>
        <text :x="L - 6" :y="(B + T) / 2 + 4">{{ fmtAxis(max / 2) }}</text>
        <text :x="L - 6" :y="T + 4">{{ fmtAxis(max) }}</text>
      </g>
      <g v-for="(g, i) in bars" :key="g.lab">
        <rect v-if="g.a != null" :x="g.ax" :y="y(Math.max(0, g.a))" :width="barW" :height="Math.max(0, B - y(Math.max(0, g.a)))" rx="3" fill="var(--series-1)" />
        <rect v-if="b && g.b != null" :x="g.bx" :y="y(Math.max(0, g.b))" :width="barW" :height="Math.max(0, B - y(Math.max(0, g.b)))" rx="3" fill="var(--series-compare)" />
        <text v-if="i === last && g.a != null" :x="g.ax + barW / 2" :y="y(Math.max(0, g.a)) - 6" font-size="11" fill="var(--ink)" text-anchor="middle">{{ g.aLabel }}</text>
        <text v-if="i === last && b && g.b != null" :x="g.bx + barW / 2" :y="y(Math.max(0, g.b)) - 6" font-size="11" fill="var(--ink)" text-anchor="middle">{{ g.bLabel }}</text>
        <text :x="g.cx" :y="B + 20" font-size="11" fill="var(--ink-muted)" text-anchor="middle">{{ g.lab }}</text>
      </g>
    </svg>
  </div>
</template>

<style scoped>
.legend { display: flex; gap: 14px; justify-content: flex-end; font-size: 12px; }
.legend span { display: inline-flex; align-items: center; gap: 6px; }
.legend i { width: 10px; height: 10px; border-radius: 2px; display: inline-block; }
svg text { font-family: var(--font-sans); }
</style>
