<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { api, errMessage } from '@/api/client'
import type { CfoAnswer, CfoHistoryItem, DocumentOut, ToolTraceItem } from '@/api/types'
import { docTypeLabel, fmtPeriod } from '@/api/format'
import { useEvidence } from '@/stores/evidence'
import { useAuth } from '@/stores/auth'
import EvidencePane from '@/components/evidence/EvidencePane.vue'
import EvidenceChip from '@/components/evidence/EvidenceChip.vue'
import InlineEvidence from '@/components/evidence/InlineEvidence'
import { citedKeys } from '@/components/evidence/inline'
import { t } from '@/i18n'

interface Turn {
  question: string
  answer?: CfoAnswer
  mode?: 'llm' | 'facts_only'
  citations?: string[]
  trace?: ToolTraceItem[]
  error?: string
  pending?: boolean
}

const ev = useEvidence()
const auth = useAuth()
const turns = ref<Turn[]>([])
const question = ref('')
const asking = ref(false)
const files = ref<DocumentOut[]>([])
const histErr = ref('')
const showTrace = ref<Record<number, boolean>>({})
const bottom = ref<HTMLElement | null>(null)

const SUGGESTIONS = [
  'Why is my cash balance falling even though I am profitable?',
  'Will I have enough cash to cover my upcoming payments?',
  'Which expenses increased the most in the latest month?',
]
const business = ref('')

const analysed = computed(() => files.value.filter((f) => f.status === 'analyzed' || f.status === 'clarification'))
const coverage = computed(() =>
  analysed.value.map((f) => `${docTypeLabel(f.doc_type).replace(/ \(.*\)$/, '').toLowerCase()} ${fmtPeriod(f.period_start, f.period_end)}`).join(', '),
)

onMounted(async () => {
  ev.clear()
  const [h, f] = await Promise.allSettled([api.cfoHistory(), api.ownerFiles()])
  if (f.status === 'fulfilled') files.value = f.value.items
  if (h.status === 'fulfilled') {
    const raw = h.value
    const items: CfoHistoryItem[] = Array.isArray(raw) ? raw : raw.messages || raw.items || []
    if (!Array.isArray(raw)) {
      if (raw.facts) ev.register(raw.facts)
      business.value = raw.business?.name || ''
    }
    const out: Turn[] = []
    for (const it of items) {
      if (it.facts) ev.register(it.facts)
      if (it.answer && (it.question || it.content)) {
        out.push({ question: it.question || it.content || '', answer: it.answer, mode: it.mode, citations: it.citations, trace: it.tool_trace })
      } else if (it.role === 'user') out.push({ question: it.content || it.question || '' })
      else if (it.role === 'assistant' && out.length && it.answer) {
        Object.assign(out[out.length - 1], { answer: it.answer, mode: it.mode, citations: it.citations, trace: it.tool_trace })
      }
    }
    turns.value = out
    const keys = out.flatMap((t) => [...(t.citations || []), ...(t.answer?.table || []).map((r) => r.fact_key).filter(Boolean) as string[]])
    if (keys.length) ev.ensure(keys)
    const lastKey = keys[keys.length - 1]
    if (lastKey) ev.selectDefault(lastKey)
  } else histErr.value = errMessage(h.reason)
})

async function ask(q?: string) {
  const text = (q ?? question.value).trim()
  if (!text || asking.value) return
  question.value = ''
  const turn: Turn = { question: text, pending: true }
  turns.value = [...turns.value, turn]
  asking.value = true
  await nextTick()
  bottom.value?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  try {
    const r = await api.cfoAsk(text)
    ev.register(r.facts)
    const idx = turns.value.length - 1
    turns.value[idx] = { question: text, answer: r.answer, mode: r.mode, citations: r.citations, trace: r.tool_trace }
    const first = r.citations?.[0] || r.answer.table.find((t) => t.fact_key)?.fact_key
    if (first) ev.select(first)
  } catch (e) {
    const idx = turns.value.length - 1
    turns.value[idx] = { question: text, error: errMessage(e) }
  } finally {
    asking.value = false
    await nextTick()
    bottom.value?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }
}

const cited = computed(() => {
  const keys: string[] = []
  for (const t of turns.value) {
    for (const k of [...(t.citations || []), ...(t.answer ? citedKeys(t.answer.direct_answer) : [])]) if (!keys.includes(k)) keys.push(k)
  }
  return keys
})

function argText(a: Record<string, any>) {
  return Object.entries(a || {})
    .map(([k, v]) => `${k}=${typeof v === 'string' ? v : JSON.stringify(v)}`)
    .join(', ')
}
</script>

<template>
  <div class="page">
    <div class="twopane" style="gap: 20px">
      <section class="main-col" style="gap: 18px" :aria-label="t('Conversation')">
        <div class="page-head">
          <div>
            <h1>{{ t('AI CFO') }}<template v-if="business"> · {{ business }}</template></h1>
            <p class="meta" style="font-size: 13px">
              <template v-if="coverage">{{ t('Answers only from your records: {list}.', { list: coverage }) }}</template>
              <template v-else>{{ t('Answers only from your records — none analysed yet.') }} <RouterLink to="/upload">{{ t('Upload statements first.') }}</RouterLink></template>
              {{ t('Every number links to the record it came from.') }}
            </p>
          </div>
        </div>
        <div v-if="histErr" class="error-box">{{ histErr }}</div>

        <template v-for="(turn, i) in turns" :key="i">
          <div class="msg">
            <span class="av user">{{ auth.initials }}</span>
            <p style="padding-top: 4px; font-weight: 500">{{ turn.question }}</p>
          </div>
          <div class="msg">
            <span class="av ai">AI</span>
            <div v-if="turn.pending" class="ans muted">{{ t('Looking through your records…') }}</div>
            <div v-else-if="turn.error" class="ans"><div class="error-box">{{ turn.error }}</div></div>
            <div v-else-if="turn.answer" class="ans">
              <template v-if="turn.mode === 'facts_only'">
                <div class="row"><span class="pill pill-neutral">{{ t('LLM is off — matching facts') }}</span></div>
                <p class="muted" style="font-size: 13px">{{ t('These are the records matching your question, without a written answer.') }}</p>
              </template>
              <p v-else><strong><InlineEvidence :text="turn.answer.direct_answer" /></strong></p>
              <div v-if="turn.answer.table?.length" class="scrollbox">
                <table class="tbl">
                  <thead><tr><th>{{ t('Item') }}</th><th class="r">{{ t('Value') }}</th><th>{{ t('Record') }}</th></tr></thead>
                  <tbody>
                    <tr v-for="(r, k) in turn.answer.table" :key="k">
                      <td><InlineEvidence :text="r.label" /></td>
                      <td class="r num" style="white-space: nowrap">
                        <template v-if="r.fact_key && ev.facts[r.fact_key]">{{ ev.facts[r.fact_key].display }} <span class="muted">{{ ev.facts[r.fact_key].display_unit }}</span></template>
                        <span v-else class="muted">—</span>
                      </td>
                      <td>
                        <EvidenceChip v-if="r.fact_key" :fact-key="r.fact_key" :text="ev.facts[r.fact_key]?.document?.filename ? `${ev.facts[r.fact_key]!.document!.filename}${ev.facts[r.fact_key]!.page_n ? ' · p.' + ev.facts[r.fact_key]!.page_n : ''}` : undefined" />
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
              <div v-if="turn.answer.cant_see" class="note"><strong>{{ t("What I can't see.") }}</strong> <InlineEvidence :text="turn.answer.cant_see" /></div>
              <div v-if="turn.answer.next_steps?.length">
                <div class="eyebrow" style="margin-bottom: 6px">{{ t('What I would do first') }}</div>
                <ol class="steps">
                  <li v-for="(s, k) in turn.answer.next_steps" :key="k"><InlineEvidence :text="s" /></li>
                </ol>
              </div>
              <div v-if="turn.trace?.length">
                <button type="button" class="linkbtn" style="font-size: 12px" @click="showTrace[i] = !showTrace[i]">{{ showTrace[i] ? t('Hide how this was computed') : t('How this was computed') }} · {{ t('{n} steps', { n: turn.trace.length }) }}</button>
                <ol v-if="showTrace[i]" class="trace">
                  <li v-for="(s, k) in turn.trace" :key="k">
                    <span class="mono">{{ s.tool }}({{ argText(s.args) }})</span>
                    <template v-if="s.result_key"> → <EvidenceChip :fact-key="s.result_key" long /></template>
                  </li>
                </ol>
              </div>
            </div>
          </div>
        </template>

        <div v-if="!turns.length" class="panel empty">
          {{ t('Ask about any figure, period or counterparty in your uploaded records. The answer starts with one sentence, then shows the records behind it, says what it cannot see, and lists next steps — cheapest first.') }}
        </div>

        <div ref="bottom" class="panel" style="padding: 12px 14px; display: flex; flex-direction: column; gap: 10px">
          <form class="row" style="gap: 10px; flex-wrap: wrap" @submit.prevent="ask()">
            <label for="q" class="sr-only">{{ t('Ask a question') }}</label>
            <input id="q" v-model="question" type="text" class="input" :placeholder="t('Ask about any figure, period or counterparty…')" style="flex: 1 1 280px; height: 40px" :disabled="asking" />
            <button type="submit" class="btn btn-primary" style="height: 40px" :disabled="asking || !question.trim()">{{ asking ? t('Asking…') : t('Ask') }}</button>
          </form>
          <div class="row" style="gap: 8px">
            <button v-for="s in SUGGESTIONS" :key="s" type="button" class="chip round" :disabled="asking" @click="ask(t(s))">{{ t(s) }}</button>
          </div>
        </div>
      </section>

      <div class="ev-col" style="flex-basis: 400px">
        <EvidencePane :actions="false" :empty-text="t('Click any dashed figure in an answer to see the record it came from.')">
          <template #footer>
            <div v-if="cited.length" style="padding: 10px 14px 14px; border-top: 1px solid var(--border-row)">
              <div class="eyebrow" style="margin-bottom: 8px">{{ t('Cited in this conversation') }}</div>
              <div class="stack" style="gap: 6px; align-items: flex-start">
                <EvidenceChip v-for="k in cited" :key="k" :fact-key="k" long />
              </div>
            </div>
          </template>
        </EvidencePane>
      </div>
    </div>
  </div>
</template>

<style scoped>
.trace { margin: 8px 0 0; padding-left: 18px; font-size: 12px; display: flex; flex-direction: column; gap: 4px; color: var(--ink-2); }
</style>
