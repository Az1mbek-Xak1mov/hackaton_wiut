<script setup lang="ts">
// The officer's recorded decision on an application, in plain words. Converza never decides; an officer does.
import { computed } from 'vue'
import type { OwnerApplication } from '@/api/types'
import { fmtDateTime } from '@/api/format'
import BalanceAfter from '@/components/owner/BalanceAfter.vue'
import { t } from '@/i18n'

const props = defineProps<{ application: OwnerApplication; reqTitle?: (m: { key: string; title: string }) => string }>()
defineEmits<{ (e: 'add-documents'): void }>()

// outcome code → wording (codes from app/modules/applications/schemas.py)
const TONE: Record<string, { cls: string; title: string; explain: string }> = {
  recommend: {
    cls: 'ok',
    title: 'The bank officer recommended approval',
    explain: 'A bank officer reviewed your documents and recommended your application for approval. The bank will contact you about signing and when the money arrives.',
  },
  decline: {
    cls: 'no',
    title: 'The bank declined your application',
    explain: 'A bank officer reviewed your application and declined it. The reason is in the message below.',
  },
  request_info: {
    cls: 'info',
    title: 'The bank needs more information',
    explain: 'A bank officer needs more before deciding. Upload what the message asks for, then add the new documents to this application.',
  },
}
const a = computed(() => props.application)
const tone = computed(() => {
  const o = a.value.decision?.outcome || ''
  const p = TONE[o] || { cls: 'info', title: o, explain: '' }
  return { cls: p.cls, title: t(p.title), explain: p.explain ? t(p.explain) : '' }
})
const title = (m: { key: string; title: string }) => (props.reqTitle ? props.reqTitle(m) : m.title)
</script>

<template>
  <section v-if="a.decision" class="dp" :class="tone.cls" :aria-label="t('Decision from the bank')">
    <div class="head">
      <div>
        <div class="eyebrow">{{ t('Application {n}', { n: a.number }) }}</div>
        <h2 class="title">{{ tone.title }}</h2>
      </div>
      <span class="muted when">{{ fmtDateTime(a.decision.decided_at) }}</span>
    </div>
    <p class="facts">
      {{ t('Amount') }} <strong class="num">{{ a.requested_display ?? '—' }} {{ t('mln UZS') }}</strong>
      · {{ t('Term') }} <strong class="num">{{ a.term_months ? t('{n} months', { n: a.term_months }) : '—' }}</strong>
      <template v-if="a.purpose"> · {{ a.purpose }}</template>
    </p>
    <p v-if="tone.explain" class="explain">{{ tone.explain }}</p>
    <div v-if="a.decision.message" class="msgbox">
      <div class="eyebrow">{{ t('Message from the bank officer') }}</div>
      <p class="msg">{{ a.decision.message }}</p>
    </div>

    <BalanceAfter v-if="a.decision.outcome === 'recommend' && a.balance_after" :data="a.balance_after" />

    <div v-if="a.decision.outcome === 'decline'" class="next">
      <div class="eyebrow">{{ t('What you can do next') }}</div>
      <ul>
        <li>{{ t('Read the reason above. If a document was missing or out of date, upload the newer one.') }}</li>
        <li>{{ t('When your documents are complete, send a new application with the form below.') }}</li>
        <li>{{ t('If something in the reason is not clear, ask the bank officer directly.') }}</li>
      </ul>
    </div>

    <div v-if="a.decision.outcome === 'request_info'" class="next">
      <template v-if="a.missing_documents && a.missing_documents.length">
        <div class="eyebrow">{{ t('The bank does not have these yet') }}</div>
        <ul><li v-for="m in a.missing_documents" :key="m.key">{{ title(m) }}</li></ul>
      </template>
      <div class="row" style="gap: 8px; margin-top: 6px">
        <a href="#documents" class="btn">{{ t('Upload documents') }}</a>
        <button v-if="a.can_add_documents" type="button" class="btn btn-primary" @click="$emit('add-documents')">{{ t('Add new documents to this application') }}</button>
      </div>
    </div>
    <p class="muted small">{{ t('Converza only reads the documents. This decision was written by a bank officer.') }}</p>
  </section>
</template>

<style scoped>
.dp { padding: 16px 18px; border: 1px solid var(--border); border-left: 4px solid var(--info-fg); border-radius: var(--r-control); background: var(--info-bg); display: flex; flex-direction: column; gap: 8px; color: var(--ink); }
.dp.ok { border-left-color: var(--stable-fg); background: var(--stable-bg); }
.dp.no { border-left-color: var(--attn-fg); background: var(--attn-bg); }
.dp.info { border-left-color: var(--watch-fg); background: var(--watch-bg); }
.head { display: flex; justify-content: space-between; align-items: flex-start; gap: 8px; flex-wrap: wrap; }
.title { font-size: 20px; font-weight: 600; margin: 2px 0 0; }
.dp.ok .title { color: var(--stable-fg); }
.dp.no .title { color: var(--attn-fg); }
.dp.info .title { color: var(--watch-fg); }
.when { font-size: 12px; }
.facts, .explain { font-size: 13.5px; }
.num { font-variant-numeric: tabular-nums; }
.msgbox { background: var(--surface); border: 1px solid var(--border); border-radius: var(--r-control); padding: 8px 12px; }
.msg { white-space: pre-wrap; font-size: 13.5px; }
.next { font-size: 13px; }
.next ul { margin: 4px 0 0; padding-left: 18px; }
.small { font-size: 12px; }
</style>
