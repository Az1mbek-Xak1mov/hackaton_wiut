<script setup lang="ts">
import { ref } from 'vue'
import type { Finding } from '@/api/types'
import { api, errMessage } from '@/api/client'
import { fmtDate, severityPillClass } from '@/api/format'
import InlineEvidence from './InlineEvidence'

const props = defineProps<{ finding: Finding; showRule?: boolean; actions?: boolean }>()
const emit = defineEmits<{ (e: 'changed', f: Finding): void }>()

const mode = ref<'' | 'resolved' | 'dismissed'>('')
const note = ref('')
const busy = ref(false)
const err = ref('')

async function save(state: 'open' | 'resolved' | 'dismissed') {
  if (state !== 'open' && note.value.trim().length < 3) {
    err.value = 'Write your conclusion; it is stored in the audit log.'
    return
  }
  busy.value = true
  err.value = ''
  try {
    const f = await api.updateFinding(props.finding.uuid, { state, note: note.value.trim() })
    emit('changed', f)
    mode.value = ''
    note.value = ''
  } catch (e) {
    err.value = errMessage(e)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="issue" :class="{ closed: finding.state !== 'open' }">
    <span class="pill" :class="severityPillClass(finding.severity)">{{ finding.label }}</span>
    <div style="min-width: 0">
      <div style="font-weight: 500">{{ finding.title }}</div>
      <div class="muted"><InlineEvidence :text="finding.detail" :keys="finding.evidence" /></div>
      <div v-if="finding.state !== 'open'" class="muted" style="font-size: 12px; margin-top: 4px">
        <span class="pill pill-neutral">{{ finding.state === 'resolved' ? 'Resolved by officer' : 'Dismissed by officer' }}</span>
        <template v-if="finding.state_note"> “{{ finding.state_note }}”</template>
      </div>
      <form v-if="mode" class="row" style="margin-top: 8px" @submit.prevent="save(mode as 'resolved' | 'dismissed')">
        <label class="sr-only" :for="`fn-${finding.uuid}`">Conclusion</label>
        <input :id="`fn-${finding.uuid}`" v-model="note" class="input" style="flex: 1 1 220px" :placeholder="mode === 'resolved' ? 'How was it resolved?' : 'Why is it not relevant?'" />
        <button type="submit" class="btn btn-sm btn-primary" :disabled="busy">Save</button>
        <button type="button" class="btn btn-sm" @click="mode = ''">Cancel</button>
      </form>
      <div v-if="err" class="error-box" style="margin-top: 6px">{{ err }}</div>
    </div>
    <div class="row" style="justify-content: flex-end; align-items: flex-start">
      <span v-if="finding.date" class="muted num" style="font-size: 12px; white-space: nowrap">{{ fmtDate(finding.date, { short: true }) }}</span>
      <template v-if="actions && !mode">
        <template v-if="finding.state === 'open'">
          <button type="button" class="btn btn-sm" @click="mode = 'resolved'">Resolve</button>
          <button type="button" class="btn btn-sm" @click="mode = 'dismissed'">Dismiss</button>
        </template>
        <button v-else type="button" class="btn btn-sm" :disabled="busy" @click="save('open')">Reopen</button>
      </template>
      <span v-if="showRule !== false" class="rule-tag" :title="`Reconciliation rule ${finding.rule_id}`">{{ finding.rule_id }}</span>
    </div>
  </div>
</template>

<style scoped>
.issue.closed > .pill { opacity: .6; }
</style>
