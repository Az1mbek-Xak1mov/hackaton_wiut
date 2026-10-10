<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import Icon from '@/components/ui/Icon.vue'
import { useApp } from '@/stores/app'
import { useAuth } from '@/stores/auth'
import { fmtDateTime } from '@/api/format'

const props = defineProps<{ mode: 'officer' | 'owner' }>()
const route = useRoute()
const app = useApp()
const auth = useAuth()

interface Item { to: string; label: string; icon: string; count?: number | null; match: (p: string, q: Record<string, any>) => boolean }

const items = computed<Item[]>(() => {
  if (props.mode === 'officer') {
    return [
      { to: '/bank', label: 'Portfolio overview', icon: 'grid', match: (p) => p === '/bank' },
      { to: '/bank/applications', label: 'Applications', icon: 'file', count: app.counts.applications, match: (p) => p.startsWith('/bank/applications') },
      { to: '/bank/borrowers', label: 'Borrowers', icon: 'bank', count: app.counts.borrowers, match: (p, q) => p.startsWith('/bank/borrowers') && q.status !== 'attn' },
      { to: '/bank/borrowers?status=attn', label: 'Alerts', icon: 'alert', count: app.counts.alerts, match: (p, q) => p === '/bank/borrowers' && q.status === 'attn' },
      { to: '/analyse', label: 'Analyse a document', icon: 'search', match: (p) => p === '/analyse' },
      { to: '/metrics', label: 'Evaluation metrics', icon: 'chart', match: (p) => p === '/metrics' },
    ]
  }
  return [
    { to: '/owner/upload', label: 'Upload & analyze', icon: 'upload', match: (p) => p === '/owner/upload' },
    { to: '/owner/cfo', label: 'AI CFO', icon: 'chat', match: (p) => p === '/owner/cfo' },
    { to: '/analyse', label: 'Analyse a document', icon: 'search', match: (p) => p === '/analyse' },
    { to: '/metrics', label: 'Evaluation metrics', icon: 'chart', match: (p) => p === '/metrics' },
  ]
})
</script>

<template>
  <nav class="side nav" aria-label="Sections">
    <div class="who">
      <template v-if="mode === 'owner' && app.ownerBusiness">
        <div style="font-weight: 600; font-size: 14px">{{ app.ownerBusiness.name }}</div>
        <div class="muted" style="font-size: 12px">{{ [app.ownerBusiness.industry, app.ownerBusiness.region].filter(Boolean).join(' · ') || 'Business owner' }}</div>
      </template>
      <template v-else>
        <div style="font-weight: 600; font-size: 14px">{{ mode === 'officer' ? 'SME lending' : 'Business owner' }}</div>
        <div class="muted" style="font-size: 12px">{{ mode === 'officer' ? 'Credit analyst · demo session' : 'AI CFO · demo session' }}<template v-if="auth.name"> · {{ auth.name }}</template></div>
      </template>
    </div>
    <div class="items">
      <RouterLink v-for="it in items" :key="it.label" :to="it.to" :class="{ on: it.match(route.path, route.query) }">
        <Icon :name="it.icon" />{{ it.label }}<span v-if="it.count != null" class="cnt">{{ it.count }}</span>
      </RouterLink>
    </div>
    <div v-if="mode === 'officer' && app.monitoringRunAt" class="card">
      <div class="eyebrow" style="margin-bottom: 6px">Monitoring run</div>
      <div>{{ fmtDateTime(app.monitoringRunAt) }}</div>
      <div class="muted">Statuses computed from uploaded statements</div>
    </div>
    <div v-if="mode === 'owner' && app.ownerCoverage" class="card">
      <div class="eyebrow" style="margin-bottom: 6px">Data coverage</div>
      <div class="muted">{{ app.ownerCoverage.analysed }} of {{ app.ownerCoverage.total }} documents analyzed</div>
      <RouterLink to="/owner/upload" style="display: inline-block; margin-top: 8px">Review uploads</RouterLink>
    </div>
    <div id="side-extra"></div>
  </nav>
</template>

<style scoped>
.side { flex: 1 1 220px; max-width: 220px; padding: 16px 12px; border-right: 1px solid var(--border); background: var(--surface-2); }
.who { padding: 6px 12px 14px; }
.items { display: flex; flex-direction: column; gap: 2px; }
.card { margin-top: 28px; padding: 12px; border: 1px solid var(--border); border-radius: var(--r-panel); background: var(--surface); font-size: 12px; }
@media (max-width: 720px) {
  .side { max-width: none; border-right: 0; border-bottom: 1px solid var(--border); padding: 10px 12px; }
  .items { flex-direction: row; flex-wrap: wrap; }
  .card { margin-top: 10px; }
}
</style>
