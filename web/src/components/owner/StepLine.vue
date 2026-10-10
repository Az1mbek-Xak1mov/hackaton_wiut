<script setup lang="ts">
// The four steps of a loan application, with the current one marked. `current` is 1–4; `attention` marks it amber.
import { t } from '@/i18n'

withDefaults(defineProps<{ current: number; attention?: boolean; details?: boolean }>(), { attention: false, details: false })

const STEPS = [
  { title: 'Upload documents', sub: 'Reports and statements from the list' },
  { title: 'Send application', sub: 'Amount, term and purpose' },
  { title: 'Bank officer reviews', sub: 'Checks the figures against your documents' },
  { title: 'Decision', sub: 'Shown here with a message from the bank' },
]
</script>

<template>
  <ol class="stepline" :aria-label="t('Application steps')">
    <li
      v-for="(s, i) in STEPS"
      :key="s.title"
      :class="{ done: i + 1 < current, now: i + 1 === current, attn: attention && i + 1 === current }"
      :aria-current="i + 1 === current ? 'step' : undefined"
    >
      <span class="n">{{ i + 1 }}</span>
      <span class="txt">
        <span class="title">{{ t(s.title) }}</span>
        <span v-if="details" class="sub">{{ t(s.sub) }}</span>
      </span>
    </li>
  </ol>
</template>

<style scoped>
.stepline { list-style: none; margin: 0; padding: 0; display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 6px; }
.stepline li { display: flex; gap: 8px; align-items: flex-start; padding: 8px 10px 8px 0; border-top: 3px solid var(--border); font-size: 13px; color: var(--ink-muted); }
.stepline li.done { border-top-color: var(--stable-fg); color: var(--ink-2); }
.stepline li.now { border-top-color: var(--accent); color: var(--ink); }
.stepline li.attn { border-top-color: var(--watch-fg); }
.n { flex: none; width: 20px; height: 20px; border-radius: 4px; background: var(--neutral-bg); color: var(--ink-2); font-size: 11px; font-weight: 600; display: inline-flex; align-items: center; justify-content: center; font-variant-numeric: tabular-nums; }
li.done .n { background: var(--stable-bg); color: var(--stable-fg); }
li.now .n { background: var(--accent); color: var(--surface); }
li.attn .n { background: var(--watch-bg); color: var(--watch-fg); }
.txt { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.title { font-weight: 500; }
li.now .title { font-weight: 600; }
.sub { font-size: 12px; color: var(--ink-muted); }
@media (max-width: 720px) {
  .stepline { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
</style>
