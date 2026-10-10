import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api, errMessage, request } from '@/api/client'
import type { CreatedWithJob, LlmSettings, OwnerBusiness, OwnerChecklist, VersionInfo } from '@/api/types'

/** Owner endpoints used by the owner app (documents checklist; adding documents to an open application). */
export const ownerApi = {
  checklist: () => request<OwnerChecklist>('/owner/checklist'),
  addDocuments: (applicationUuid: string, documentUuids?: string[]) =>
    request<CreatedWithJob & { number?: string; status?: string }>(`/owner/applications/${applicationUuid}/documents`, {
      method: 'POST',
      body: documentUuids?.length ? { document_uuids: documentUuids } : {},
    }),
}

export const useApp = defineStore('app', () => {
  const version = ref<VersionInfo | null>(null)
  const llm = ref<LlmSettings | null>(null)
  const llmError = ref('')
  const counts = ref<{ applications: number | null; borrowers: number | null; alerts: number | null }>({
    applications: null,
    borrowers: null,
    alerts: null,
  })
  const monitoringRunAt = ref<string | null>(null)
  const ownerBusiness = ref<OwnerBusiness | null>(null)
  const ownerCoverage = ref<{ analysed: number; total: number } | null>(null)
  const ownerChecklist = ref<OwnerChecklist | null>(null)

  async function loadChecklist() {
    try {
      ownerChecklist.value = await ownerApi.checklist()
    } catch {
      ownerChecklist.value = null
    }
  }

  async function loadOwner() {
    try {
      const r = await api.ownerFiles()
      ownerBusiness.value = r.business || null
      ownerCoverage.value = { analysed: r.items.filter((d) => d.status === 'analyzed' || d.status === 'clarification').length, total: r.items.length }
    } catch {
      ownerBusiness.value = null
    }
    await loadChecklist()
  }

  async function loadVersion() {
    try {
      version.value = await api.version()
    } catch {
      version.value = null
    }
  }

  async function loadLlm() {
    try {
      llm.value = await api.llmSettings()
      llmError.value = ''
    } catch (e) {
      llmError.value = errMessage(e)
    }
  }

  const llmChanges = ref(0) // pages that show generated text re-generate when this changes
  async function setLlm(enabled: boolean) {
    llm.value = await api.setLlm(enabled)
    if (version.value) version.value.llm_enabled = llm.value.enabled
    llmChanges.value++
  }

  async function loadOfficerCounts() {
    const [apps, bor] = await Promise.allSettled([api.applications(), api.borrowers()])
    if (apps.status === 'fulfilled') counts.value.applications = apps.value.items.length
    if (bor.status === 'fulfilled') {
      counts.value.borrowers = bor.value.counts.all
      counts.value.alerts = bor.value.counts.attn
    }
  }

  return { version, llm, llmError, llmChanges, counts, monitoringRunAt, ownerBusiness, ownerCoverage, ownerChecklist, loadChecklist, loadVersion, loadLlm, setLlm, loadOfficerCounts, loadOwner }
})
