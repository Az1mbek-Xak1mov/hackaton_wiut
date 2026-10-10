import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { api } from '@/api/client'
import type { Fact } from '@/api/types'

/**
 * One evidence store for the whole app: any EvidenceChip anywhere selects a fact key,
 * the EvidencePane shows it. Facts arrive embedded in page payloads (`facts` maps) or are
 * fetched in batches through GET /facts?keys=…
 */
export const useEvidence = defineStore('evidence', () => {
  const facts = ref<Record<string, Fact>>({})
  const selectedKey = ref<string | null>(null)
  const opened = ref<string[]>([]) // keys the user opened — sent with an officer decision
  const missing = ref<Set<string>>(new Set())
  const userSelections = ref(0) // increments only on a user's click, so pages can scroll the pane into view
  let pending = new Set<string>()
  let timer: ReturnType<typeof setTimeout> | null = null

  const selected = computed<Fact | null>(() => (selectedKey.value ? facts.value[selectedKey.value] || null : null))

  function register(input: Record<string, Fact> | Fact[] | null | undefined) {
    if (!input) return
    const list = Array.isArray(input) ? input : Object.values(input)
    if (!list.length) return
    const next = { ...facts.value }
    for (const f of list) if (f && f.key) next[f.key] = f
    facts.value = next
  }

  function upsert(f: Fact) {
    facts.value = { ...facts.value, [f.key]: f }
  }

  function select(key: string) {
    selectedKey.value = key
    userSelections.value++
    if (!opened.value.includes(key)) opened.value = [...opened.value, key]
    if (!facts.value[key]) ensure([key])
  }

  function selectDefault(key: string | null | undefined) {
    if (!key) return
    if (!selectedKey.value || !facts.value[selectedKey.value]) selectedKey.value = key
  }

  function clear() {
    selectedKey.value = null
    opened.value = []
  }

  function ensure(keys: string[]) {
    for (const k of keys) {
      if (k && !facts.value[k] && !missing.value.has(k)) pending.add(k)
    }
    if (!pending.size || timer) return
    timer = setTimeout(flush, 30)
  }

  async function flush() {
    timer = null
    const keys = [...pending]
    pending = new Set()
    if (!keys.length) return
    for (let i = 0; i < keys.length; i += 50) {
      const batch = keys.slice(i, i + 50)
      try {
        const res = await api.facts(batch)
        register(res.facts)
        const got = new Set(res.facts.map((f) => f.key))
        const miss = new Set(missing.value)
        batch.filter((k) => !got.has(k)).forEach((k) => miss.add(k))
        missing.value = miss
      } catch {
        const miss = new Set(missing.value)
        batch.forEach((k) => miss.add(k))
        missing.value = miss
      }
    }
  }

  return { facts, selectedKey, selected, opened, missing, userSelections, register, upsert, select, selectDefault, clear, ensure }
})
