<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api, errMessage } from '@/api/client'

const data = ref<Record<string, any> | null>(null)
const loading = ref(true)
const err = ref('')

onMounted(async () => {
  try {
    data.value = await api.metricsEval()
  } catch (e) {
    err.value = errMessage(e)
  } finally {
    loading.value = false
  }
})

const notMeasured = computed(() => !data.value || data.value.status === 'not_measured')
const unreadable = computed(() => data.value?.status === 'unreadable')
const META_KEYS = ['_file', 'generated_at', 'created_at', 'git_sha', 'split', 'dataset', 'n_bundles', 'n_documents', 'n', 'note', 'caveat', 'status']
const meta = computed(() => {
  const d = data.value || {}
  return META_KEYS.filter((k) => d[k] != null && typeof d[k] !== 'object').map((k) => ({ k, v: d[k] }))
})

type Section = { title: string; kind: 'table' | 'kv' | 'list' | 'json'; cols?: string[]; rows?: Record<string, any>[]; kv?: [string, any][]; list?: any[]; json?: any }

function isPrimitive(v: any) {
  return v == null || ['string', 'number', 'boolean'].includes(typeof v)
}
function title(k: string) {
  if (k === '_file') return 'Result file'
  return k.replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase())
}
function cell(v: any) {
  if (v == null) return '—'
  if (typeof v === 'number') return Number.isInteger(v) ? String(v) : String(Math.round(v * 1000) / 1000)
  if (typeof v === 'object') return JSON.stringify(v)
  return String(v)
}

// Render whatever the evaluation script wrote, faithfully: no number is added or changed here.
const sections = computed<Section[]>(() => {
  const d = data.value || {}
  const out: Section[] = []
  for (const [k, v] of Object.entries(d)) {
    if (META_KEYS.includes(k) && isPrimitive(v)) continue
    if (Array.isArray(v)) {
      if (v.length && v.every((x) => x && typeof x === 'object' && !Array.isArray(x))) {
        const cols = [...new Set(v.flatMap((x) => Object.keys(x)))]
        out.push({ title: title(k), kind: 'table', cols, rows: v })
      } else out.push({ title: title(k), kind: 'list', list: v })
    } else if (v && typeof v === 'object') {
      const vals = Object.values(v)
      if (vals.length && vals.every((x) => x && typeof x === 'object' && !Array.isArray(x) && Object.values(x).every(isPrimitive))) {
        const cols = ['', ...new Set(vals.flatMap((x: any) => Object.keys(x)))]
        out.push({ title: title(k), kind: 'table', cols, rows: Object.entries(v).map(([rk, rv]) => ({ '': rk, ...(rv as any) })) })
      } else if (vals.every(isPrimitive)) out.push({ title: title(k), kind: 'kv', kv: Object.entries(v) })
      else out.push({ title: title(k), kind: 'json', json: v })
    } else out.push({ title: title(k), kind: 'kv', kv: [[k, v]] })
  }
  return out
})
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h1>Evaluation metrics</h1>
        <p class="meta" style="max-width: 760px">Measured by <span class="mono">eval/run.py</span> on our synthetic generator's held-out test split and hand-made hard cases. Synthetic-on-synthetic results overstate real-document accuracy; evaluation on real bank files is pilot month 1.</p>
      </div>
    </div>
    <div v-if="loading" class="panel empty">Loading…</div>
    <div v-else-if="err" class="error-box">{{ err }}</div>
    <div v-else-if="unreadable" class="error-box">The latest evaluation file ({{ data?.file }}) could not be read, so no metric is shown.</div>
    <div v-else-if="notMeasured" class="panel empty">Not measured yet. This page shows the latest evaluation run as soon as one has been recorded; no number is shown before then.</div>
    <template v-else>
      <section v-if="meta.length" class="panel" style="padding: 12px 16px" aria-label="Run">
        <div class="kv">
          <div v-for="m in meta" :key="m.k"><div class="eyebrow">{{ title(m.k) }}</div><div class="num" :class="{ mono: m.k === 'git_sha' }">{{ m.v }}</div></div>
        </div>
      </section>
      <section v-for="s in sections" :key="s.title" class="panel" :aria-label="s.title">
        <div class="panel-head" style="padding: 12px 14px 8px"><h2>{{ s.title }}</h2></div>
        <div v-if="s.kind === 'table'" class="scrollbox">
          <table class="tbl">
            <thead><tr><th v-for="c in s.cols" :key="c" :class="{ r: c !== '' && typeof s.rows![0][c] === 'number' }">{{ c ? title(c) : '' }}</th></tr></thead>
            <tbody>
              <tr v-for="(r, i) in s.rows" :key="i"><td v-for="c in s.cols" :key="c" :class="{ r: typeof r[c] === 'number', num: typeof r[c] === 'number' }">{{ cell(r[c]) }}</td></tr>
            </tbody>
          </table>
        </div>
        <div v-else-if="s.kind === 'kv'" class="scrollbox">
          <table class="tbl"><tbody><tr v-for="[k, v] in s.kv" :key="k"><td>{{ title(k) }}</td><td class="r num">{{ cell(v) }}</td></tr></tbody></table>
        </div>
        <ul v-else-if="s.kind === 'list'" class="bullets" style="padding: 0 14px 14px 30px">
          <li v-for="(x, i) in s.list" :key="i">{{ typeof x === 'object' ? JSON.stringify(x) : x }}</li>
        </ul>
        <pre v-else class="passage" style="margin: 0 14px 14px; max-height: 320px; overflow: auto">{{ JSON.stringify(s.json, null, 2) }}</pre>
      </section>
    </template>
  </div>
</template>
