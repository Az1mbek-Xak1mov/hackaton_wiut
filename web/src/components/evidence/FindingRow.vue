<script setup lang="ts">
import { ref } from 'vue'
import type { Finding } from '@/api/types'
import { api, errMessage } from '@/api/client'
import { fmtDate, plainRule, severityPillClass } from '@/api/format'
import InlineEvidence from './InlineEvidence'
import { t } from '@/i18n'

const props = defineProps<{ finding: Finding; showRule?: boolean; actions?: boolean }>()
const emit = defineEmits<{ (e: 'changed', f: Finding): void }>()

const mode = ref<'' | 'resolved' | 'dismissed'>('')
const note = ref('')
const busy = ref(false)
const err = ref('')

async function save(state: 'open' | 'resolved' | 'dismissed') {
  if (state !== 'open' && note.value.trim().length < 3) {
    err.value = t('Write your conclusion; it is stored in the audit log.')
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
      <div v-if="plainRule(finding.rule_id)" class="muted" style="font-size: 12px; font-style: italic">{{ plainRule(finding.rule_id) }}</div>
      <div class="muted"><InlineEvidence :text="finding.detail" :keys="finding.evidence" :max-trailing="2" /></div>
      <div v-if="finding.state !== 'open'" class="muted" style="font-size: 12px; margin-top: 4px">
        <span class="pill pill-neutral">{{ finding.state === 'resolved' ? t('Resolved by officer') : t('Dismissed by officer') }}</span>
        <template v-if="finding.state_note"> “{{ finding.state_note }}”</template>
      </div>
      <form v-if="mode" class="row" style="margin-top: 8px" @submit.prevent="save(mode as 'resolved' | 'dismissed')">
        <div class="seg" role="group" :aria-label="t('Conclusion')">
          <button type="button" :class="{ on: mode === 'resolved' }" @click="mode = 'resolved'">{{ t('Resolved') }}</button>
          <button type="button" :class="{ on: mode === 'dismissed' }" @click="mode = 'dismissed'">{{ t('Not relevant') }}</button>
        </div>
        <label class="sr-only" :for="`fn-${finding.uuid}`">{{ t('Conclusion') }}</label>
        <input :id="`fn-${finding.uuid}`" v-model="note" class="input" style="flex: 1 1 220px" :placeholder="mode === 'resolved' ? t('How was it resolved?') : t('Why is it not relevant?')" />
        <button type="submit" class="btn btn-sm btn-primary" :disabled="busy">{{ t('Save') }}</button>
        <button type="button" class="btn btn-sm" @click="mode = ''">{{ t('Cancel') }}</button>
      </form>
      <div v-if="err" class="error-box" style="margin-top: 6px">{{ err }}</div>
    </div>
    <div class="row" style="justify-content: flex-end; align-items: flex-start">
      <span v-if="finding.date" class="muted num" style="font-size: 12px; white-space: nowrap">{{ fmtDate(finding.date, { short: true }) }}</span>
      <template v-if="actions && !mode">
        <button v-if="finding.state === 'open'" type="button" class="btn btn-sm" @click="mode = 'resolved'">{{ t('Record conclusion') }}</button>
        <button v-else type="button" class="btn btn-sm" :disabled="busy" @click="save('open')">{{ t('Reopen') }}</button>
      </template>
      <span v-if="showRule !== false" class="rule-tag" :title="t('Reconciliation rule {id}', { id: finding.rule_id })">{{ finding.rule_id }}</span>
    </div>
  </div>
</template>

<style scoped>
.issue.closed > .pill { opacity: .6; }
</style>
