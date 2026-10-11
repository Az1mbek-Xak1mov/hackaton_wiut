<script setup lang="ts">
import { t } from '@/i18n'

// A looping, illustrative "how it works" scene. Labels only — it shows no figures, so nothing here is a claim.
defineProps<{ compact?: boolean }>()

const ROWS = ['010', '020', '030', '040', '050', '060', '100', '190', '270']
const LABELS = [
  { cls: 'l1', text: 'Form 2 recognised', tone: 'hs-ok' },
  { cls: 'l2', text: 'Line 010 · Revenue', tone: '' },
  { cls: 'l3', text: 'Line 270 · Net profit', tone: '' },
  { cls: 'l4', text: 'Checked against bank statement ✓', tone: 'hs-ok' },
  { cls: 'l5', text: '1 issue found → page 1', tone: 'hs-warn' },
]
</script>

<template>
  <div class="hs-scene" :class="{ compact }" aria-hidden="true">
    <div class="hs-doc">
      <div class="hs-doc-head">
        <span class="hs-doc-form">ФОРМА №2</span>
        <span class="hs-doc-title">Moliyaviy natijalar to‘g‘risida hisobot</span>
      </div>
      <div class="hs-doc-rows">
        <div v-for="(r, i) in ROWS" :key="r" class="hs-row" :class="{ hl1: r === '010', hl2: r === '270' }">
          <span class="hs-code">{{ r }}</span>
          <span class="hs-bar" :style="{ width: 38 + ((i * 17) % 34) + '%' }" />
          <span class="hs-cell" />
        </div>
      </div>
      <div class="hs-scan" />
    </div>

    <ul class="hs-labels">
      <li v-for="l in LABELS" :key="l.cls" class="hs-label" :class="[l.cls, l.tone]">{{ t(l.text) }}</li>
    </ul>

    <div class="hs-decide">
      <div class="hs-decide-head">{{ t('Bank officer decides') }}</div>
      <div class="hs-decide-row">
        <span>{{ t('Revenue') }}</span>
        <span class="hs-num-target"><i /><i /><i /></span>
      </div>
      <div class="hs-tip">{{ t('from: page 1, line 010') }}</div>
      <svg class="hs-cursor" width="16" height="20" viewBox="0 0 16 20"><path d="M1 1 L1 16 L5 12 L8 19 L10.5 18 L7.5 11 L13 11 Z" /></svg>
    </div>
  </div>
</template>

<style scoped>
/* One 10 s loop: page slides in → scan → rows highlighted + labels → officer card, click, source tooltip. */
.hs-scene { --dur: 10s; position: relative; width: 100%; max-width: 480px; height: 330px; margin-left: auto; font-size: 12px; }
.compact { max-width: 420px; height: 280px; margin: 0; font-size: 11px; }

.hs-doc { position: absolute; left: 0; top: 10px; width: 52%; height: 290px; background: var(--surface); border: 1px solid var(--border-strong); border-radius: var(--r-chip); padding: 14px 14px 10px; overflow: hidden; animation: doc-in var(--dur) infinite; }
.compact .hs-doc { height: 250px; padding: 10px 11px 8px; }
.hs-doc-head { display: flex; flex-direction: column; gap: 2px; padding-bottom: 8px; border-bottom: 1px solid var(--border-row); margin-bottom: 6px; }
.hs-doc-form { font-family: var(--font-mono); font-size: 10px; color: var(--ink-muted); }
.hs-doc-title { font-size: 10.5px; font-weight: 600; color: var(--ink); line-height: 1.25; }
.hs-doc-rows { display: flex; flex-direction: column; }
.hs-row { display: grid; grid-template-columns: 26px 1fr 34px; gap: 6px; align-items: center; height: 23px; padding: 0 3px; border-bottom: 1px solid var(--border-row); border-radius: 2px; }
.compact .hs-row { height: 19px; }
.hs-code { font-family: var(--font-mono); font-size: 9.5px; color: var(--ink-muted); }
.hs-bar { height: 4px; border-radius: 2px; background: var(--border); }
.hs-cell { height: 6px; border-radius: 2px; background: var(--border-strong); }
.hl1 { animation: hl1 var(--dur) infinite; }
.hl2 { animation: hl2 var(--dur) infinite; }
.hs-scan { position: absolute; left: 0; right: 0; top: 0; height: 2px; background: var(--accent); opacity: 0; animation: scan var(--dur) infinite linear; }
.hs-scan::after { content: ''; position: absolute; left: 0; right: 0; bottom: 2px; height: 28px; background: var(--accent-tint); opacity: .55; }

.hs-labels { list-style: none; margin: 0; padding: 0; position: absolute; left: 56%; right: 0; top: 18px; display: flex; flex-direction: column; gap: 8px; align-items: flex-start; }
.compact .hs-labels { top: 12px; gap: 6px; }
.hs-label { background: var(--surface); color: var(--ink); border: 1px solid var(--accent-border); border-left: 3px solid var(--accent); border-radius: var(--r-chip); padding: 5px 8px; line-height: 1.3; opacity: 0; }
.hs-label.hs-ok { border-left-color: var(--stable-mark); }
.hs-label.hs-warn { border-left-color: var(--attn-mark); background: var(--attn-bg); color: var(--attn-fg); border-color: var(--attn-bg); border-left-color: var(--attn-mark); }
.l1 { animation: l1 var(--dur) infinite; }
.l2 { animation: l2 var(--dur) infinite; }
.l3 { animation: l3 var(--dur) infinite; }
.l4 { animation: l4 var(--dur) infinite; }
.l5 { animation: l5 var(--dur) infinite; }

.hs-decide { position: absolute; right: 0; bottom: 0; width: 46%; background: var(--surface); border: 1px solid var(--border-strong); border-radius: var(--r-panel); padding: 10px 12px; display: flex; flex-direction: column; gap: 8px; opacity: 0; animation: decide var(--dur) infinite; }
.hs-decide-head { font-weight: 600; color: var(--ink); }
.hs-decide-row { display: flex; justify-content: space-between; align-items: center; color: var(--ink-2); }
.hs-num-target { display: inline-flex; gap: 3px; padding: 3px 5px; border-radius: 2px; animation: target var(--dur) infinite; }
.hs-num-target i { display: block; width: 9px; height: 7px; background: var(--ink-2); border-radius: 1px; }
.hs-tip { position: absolute; right: 8px; bottom: calc(100% + 6px); background: var(--ink); color: var(--surface); font-family: var(--font-mono); font-size: 10.5px; padding: 5px 8px; border-radius: var(--r-chip); white-space: nowrap; opacity: 0; animation: tip var(--dur) infinite; }
.hs-cursor { position: absolute; right: -6px; bottom: -14px; fill: var(--surface); stroke: var(--ink); stroke-width: 1.2; animation: cursor var(--dur) infinite; }

@keyframes doc-in { 0% { opacity: 0; transform: translateX(-24px); } 7%, 94% { opacity: 1; transform: none; } 100% { opacity: 0; transform: none; } }
@keyframes scan { 0%, 8% { top: 0; opacity: 0; } 9% { opacity: 1; } 28% { top: 100%; opacity: 1; } 29%, 100% { top: 100%; opacity: 0; } }
@keyframes hl1 { 0%, 33% { background: transparent; } 36%, 94% { background: var(--highlight); } 100% { background: transparent; } }
@keyframes hl2 { 0%, 43% { background: transparent; } 46%, 94% { background: var(--highlight); } 100% { background: transparent; } }
@keyframes l1 { 0%, 25% { opacity: 0; transform: translateX(-10px); } 28%, 94% { opacity: 1; transform: none; } 98%, 100% { opacity: 0; } }
@keyframes l2 { 0%, 34% { opacity: 0; transform: translateX(-10px); } 37%, 94% { opacity: 1; transform: none; } 98%, 100% { opacity: 0; } }
@keyframes l3 { 0%, 44% { opacity: 0; transform: translateX(-10px); } 47%, 94% { opacity: 1; transform: none; } 98%, 100% { opacity: 0; } }
@keyframes l4 { 0%, 53% { opacity: 0; transform: translateX(-10px); } 56%, 94% { opacity: 1; transform: none; } 98%, 100% { opacity: 0; } }
@keyframes l5 { 0%, 61% { opacity: 0; transform: translateX(-10px); } 64%, 94% { opacity: 1; transform: none; } 98%, 100% { opacity: 0; } }
@keyframes decide { 0%, 68% { opacity: 0; transform: translateY(10px); } 72%, 94% { opacity: 1; transform: none; } 98%, 100% { opacity: 0; } }
@keyframes cursor { 0%, 72% { transform: translate(40px, 30px); opacity: 0; } 74% { opacity: 1; } 80% { transform: translate(-8px, -14px); } 81% { transform: translate(-8px, -14px) scale(.85); } 82%, 94% { transform: translate(-8px, -14px); opacity: 1; } 98%, 100% { opacity: 0; transform: translate(-8px, -14px); } }
@keyframes target { 0%, 80% { background: transparent; outline: 0 solid transparent; } 81%, 94% { background: var(--highlight); outline: 1px solid var(--highlight-underline); } 100% { background: transparent; } }
@keyframes tip { 0%, 82% { opacity: 0; transform: translateY(4px); } 84%, 94% { opacity: 1; transform: none; } 98%, 100% { opacity: 0; } }

@media (max-width: 480px) {
  .hs-scene { height: 300px; font-size: 10.5px; }
  .hs-doc { height: 260px; }
  .hs-row { height: 20px; }
  .hs-decide { width: 50%; }
}

/* Reduced motion: the final state, still. */
@media (prefers-reduced-motion: reduce) {
  .hs-scene *, .hs-scene *::after { animation: none !important; }
  .hs-label, .hs-decide, .hs-tip { opacity: 1; transform: none; }
  .hs-scan { display: none; }
  .hl1, .hl2, .hs-num-target { background: var(--highlight); }
  .hs-cursor { transform: translate(-8px, -14px); }
}
</style>
