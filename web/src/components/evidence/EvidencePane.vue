<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { useEvidence } from '@/stores/evidence'
import { api, errMessage } from '@/api/client'
import { confPct, factTitle, factWhere, methodLabel } from '@/api/format'
import PageHighlight from './PageHighlight.vue'
import EvidenceChip from './EvidenceChip.vue'
import { t } from '@/i18n'

const props = withDefaults(
  defineProps<{ actions?: boolean; emptyText?: string; sticky?: boolean }>(),
  { actions: true, emptyText: '', sticky: true },
)

const ev = useEvidence()
const f = computed(() => ev.selected)
const root = ref<HTMLElement | null>(null)

// On narrow screens the pane sits below the content: bring it into view when the user clicks a chip.
watch(
  () => ev.userSelections,
  async () => {
    if (typeof window === 'undefined' || window.innerWidth >= 960 || !root.value) return
    await nextTick()
    const r = root.value.getBoundingClientRect()
    if (r.top > window.innerHeight * 0.6 || r.bottom < 0) root.value.scrollIntoView({ behavior: 'smooth', block: 'start' })
  },
)

const mode = ref<'' | 'correct' | 'flag'>('')
const value = ref('')
const note = ref('')
const busy = ref(false)
const err = ref('')
const done = ref('')

watch(() => ev.selectedKey, () => {
  mode.value = ''
  value.value = ''
  note.value = ''
  err.value = ''
  done.value = ''
})

const confPillInfo = computed(() => {
  const x = f.value
  if (!x) return null
  if (x.status === 'flagged') return { cls: 'pill-attn', label: t('Flagged as incorrect') }
  if (x.status === 'verified') return { cls: 'pill-stable', label: t('Verified by officer') }
  if (x.status === 'corrected') return { cls: 'pill-info', label: t('Corrected by officer') }
  const p = confPct(x.confidence)
  if (x.kind === 'computed') return { cls: 'pill-stable', label: t('Computed') }
  if (p == null) return null
  const cls = p >= 95 ? 'pill-stable' : p >= 80 ? 'pill-neutral' : 'pill-watch'
  return { cls, label: t('{p}% confidence', { p }) }
})

// passage with the printed value highlighted
const passageParts = computed(() => {
  const x = f.value
  if (!x || !x.passage) return null
  for (const cand of [x.printed, x.display].filter(Boolean) as string[]) {
    const i = x.passage.indexOf(cand)
    if (i >= 0) return { before: x.passage.slice(0, i), hit: cand, after: x.passage.slice(i + cand.length) }
  }
  return { before: x.passage, hit: '', after: '' }
})

// formula with input chips
const formulaParts = computed(() => {
  const x = f.value
  if (!x || !x.formula) return []
  const parts: { t: 'text' | 'key'; v: string }[] = []
  const re = /\b([A-Za-z]{1,3}_[A-Za-z0-9]+)\b/g
  let last = 0
  for (const m of x.formula.matchAll(re)) {
    if (m.index! > last) parts.push({ t: 'text', v: x.formula.slice(last, m.index) })
    parts.push({ t: 'key', v: m[1] })
    last = m.index! + m[0].length
  }
  if (last < x.formula.length) parts.push({ t: 'text', v: x.formula.slice(last) })
  return parts
})

watch(f, (x) => {
  if (x?.inputs?.length) ev.ensure(x.inputs)
})

async function review(action: 'verify' | 'correct' | 'flag') {
  const x = f.value
  if (!x) return
  err.value = ''
  done.value = ''
  const payload: { action: 'verify' | 'correct' | 'flag'; value?: number; note?: string } = { action }
  if (action === 'correct') {
    const v = Number(value.value.replace(/\s| /g, '').replace(',', '.'))
    if (!value.value.trim() || Number.isNaN(v)) {
      err.value = t('Enter the corrected value as printed in the document (thousand UZS).')
      return
    }
    payload.value = v
  }
  if (note.value.trim()) payload.note = note.value.trim()
  if (action === 'flag' && !payload.note) {
    err.value = t('Say what is wrong so the next reviewer can see it.')
    return
  }
  busy.value = true
  try {
    const updated = await api.reviewFact(x.uuid, payload)
    if (updated && (updated as any).key) ev.upsert(updated)
    done.value = action === 'verify' ? t('Marked as verified. Recorded in the audit log.') : action === 'correct' ? t('Correction saved; dependent checks are re-run.') : t('Flag recorded in the audit log.')
    mode.value = ''
  } catch (e) {
    err.value = errMessage(e)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <aside ref="root" class="panel pane" :class="{ sticky: props.sticky }" :aria-label="t('Evidence')">
    <div class="pane-head">
      <div style="min-width: 0">
        <div class="eyebrow">{{ t('Evidence') }}</div>
        <h2 v-if="f" class="title">{{ factTitle(f) }}</h2>
        <h2 v-else class="title muted" style="font-weight: 500">{{ t('Nothing selected') }}</h2>
        <div v-if="f" class="muted where">{{ factWhere(f) }}</div>
      </div>
      <span v-if="confPillInfo" class="pill" :class="confPillInfo.cls">{{ confPillInfo.label }}</span>
    </div>

    <div v-if="!f" class="pane-body muted" style="font-size: 13px">{{ props.emptyText || t('Click any dashed figure to see the page and line it came from.') }}</div>

    <div v-else class="pane-body">
      <PageHighlight
        v-if="f.page_image_url"
        :url="f.page_image_url"
        :bbox="f.bbox"
        :page-width="f.page_width"
        :page-height="f.page_height"
        :alt="t('Page {n} of {file}, value highlighted', { n: f.page_n, file: f.document?.filename || '' })"
      />

      <div v-if="passageParts" class="passage">{{ passageParts.before }}<span v-if="passageParts.hit" class="hit">{{ passageParts.hit }}</span>{{ passageParts.after }}</div>
      <div v-else-if="f.printed" class="passage">{{ t('As printed:') }} <span class="hit">{{ f.printed }}</span></div>

      <div class="eyebrow">{{ t('Interpretation') }}</div>
      <div class="interp">
        <p v-if="f.kind !== 'computed'">{{ methodLabel(f.method) }}<template v-if="f.printed && f.unit === 'kUZS'">; {{ t('printed in thousand UZS as') }} <span class="mono">{{ f.printed }}</span></template>.</p>
        <p v-if="formulaParts.length">
          <span class="muted">{{ t('Formula:') }} </span>
          <template v-for="(p, i) in formulaParts" :key="i">
            <EvidenceChip v-if="p.t === 'key'" :fact-key="p.v" />
            <span v-else class="mono">{{ p.v }}</span>
          </template>
        </p>
        <div v-if="f.inputs?.length && !formulaParts.length" class="row">
          <span class="muted">{{ t('Inputs:') }}</span>
          <EvidenceChip v-for="k in f.inputs" :key="k" :fact-key="k" long />
        </div>
        <p v-if="f.note">{{ f.note }}</p>
        <p class="muted" style="font-size: 12px">{{ t('Field') }} <span class="mono">{{ f.field }}</span><template v-if="f.period_label"> · {{ t('period') }} {{ f.period_label }}</template> · {{ t('fact') }} <span class="mono">{{ f.key }}</span></p>
      </div>

      <slot name="extra" :fact="f" />

      <div v-if="props.actions" class="stack" style="gap: 8px">
        <div class="row">
          <button type="button" class="btn btn-sm" :disabled="busy || f.status === 'verified'" @click="review('verify')">{{ t('Mark as verified') }}</button>
          <button type="button" class="btn btn-sm" :disabled="busy" @click="mode = mode === 'correct' ? '' : 'correct'">{{ t('Correct value') }}</button>
          <button type="button" class="btn btn-sm" :disabled="busy" @click="mode = mode === 'flag' ? '' : 'flag'">{{ t('Flag incorrect') }}</button>
        </div>
        <form v-if="mode" class="stack" style="gap: 6px" @submit.prevent="review(mode as 'correct' | 'flag')">
          <label v-if="mode === 'correct'" class="stack" style="gap: 2px">
            <span class="muted" style="font-size: 12px">{{ t('Value as printed in the document') }}</span>
            <input v-model="value" class="input mono" inputmode="decimal" :placeholder="f.printed || ''" />
          </label>
          <label class="stack" style="gap: 2px">
            <span class="muted" style="font-size: 12px">{{ mode === 'flag' ? t('What is wrong?') : t('Note (optional)') }}</span>
            <input v-model="note" class="input" />
          </label>
          <div class="row">
            <button type="submit" class="btn btn-sm btn-primary" :disabled="busy">{{ mode === 'correct' ? t('Save correction') : t('Record flag') }}</button>
            <button type="button" class="btn btn-sm" @click="mode = ''">{{ t('Cancel') }}</button>
          </div>
        </form>
        <div v-if="done" class="muted" style="font-size: 12px">{{ done }}</div>
        <div v-if="err" class="error-box">{{ err }}</div>
      </div>
      <div v-else class="muted" style="font-size: 12px">{{ t('Officers can verify, correct or flag any value; every action is written to the audit log.') }}</div>
    </div>

    <slot name="footer" />
  </aside>
</template>

<style scoped>
.pane { display: flex; flex-direction: column; min-width: 0; }
.pane.sticky { position: sticky; top: 16px; }
.pane-head { padding: 12px 14px 10px; border-bottom: 1px solid var(--border-row); display: flex; justify-content: space-between; align-items: flex-start; gap: 8px; }
.title { font-size: 14px; font-weight: 600; margin-top: 2px; overflow-wrap: anywhere; }
.where { font-size: 12px; margin-top: 2px; overflow-wrap: anywhere; }
.pane-body { padding: 12px 14px; display: flex; flex-direction: column; gap: 10px; }
.interp { display: flex; flex-direction: column; gap: 6px; font-size: 13px; }
@media (max-width: 960px) { .pane.sticky { position: static; } }
</style>
