<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import Icon from '@/components/ui/Icon.vue'
import { useApp } from '@/stores/app'
import { useAuth } from '@/stores/auth'
import { fmtDateTime } from '@/api/format'
import { t } from '@/i18n'

const props = defineProps<{ mode: 'officer' | 'owner' }>()
const route = useRoute()
const app = useApp()
const auth = useAuth()

interface Item { to: string; label: string; icon: string; count?: number | null; match: (p: string, q: Record<string, any>) => boolean }

const items = computed<Item[]>(() => {
  if (props.mode === 'officer') {
    return [
      { to: '/bank', label: t('Portfolio overview'), icon: 'grid', match: (p) => p === '/bank' },
      { to: '/bank/applications', label: t('Applications'), icon: 'file', count: app.counts.applications, match: (p) => p.startsWith('/bank/applications') },
      { to: '/bank/borrowers', label: t('Borrowers'), icon: 'bank', count: app.counts.borrowers, match: (p, q) => p.startsWith('/bank/borrowers') && q.status !== 'attn' },
      { to: '/bank/borrowers?status=attn', label: t('Alerts'), icon: 'alert', count: app.counts.alerts, match: (p, q) => p === '/bank/borrowers' && q.status === 'attn' },
      { to: '/analyse', label: t('Analyse a document'), icon: 'search', match: (p) => p === '/analyse' },
      { to: '/metrics', label: t('Evaluation metrics'), icon: 'chart', match: (p) => p === '/metrics' },
    ]
  }
  return [
    { to: '/', label: t('My business'), icon: 'grid', match: (p) => p === '/' },
    { to: '/upload', label: t('Upload & analyze'), icon: 'upload', match: (p) => p === '/upload' },
    { to: '/cfo', label: t('AI CFO'), icon: 'chat', match: (p) => p === '/cfo' },
    { to: '/analyse', label: t('Analyse a document'), icon: 'search', match: (p) => p === '/analyse' },
    { to: '/metrics', label: t('Evaluation metrics'), icon: 'chart', match: (p) => p === '/metrics' },
  ]
})
</script>

<template>
  <nav class="side nav" :aria-label="t('Sections')">
    <div class="who">
      <template v-if="mode === 'owner' && app.ownerBusiness">
        <div style="font-weight: 600; font-size: 14px">{{ app.ownerBusiness.name }}</div>
        <div class="muted" style="font-size: 12px">{{ [app.ownerBusiness.industry, app.ownerBusiness.region].filter(Boolean).join(' · ') || t('Business owner') }}</div>
      </template>
      <template v-else>
        <div style="font-weight: 600; font-size: 14px">{{ mode === 'officer' ? t('SME lending') : t('Business owner') }}</div>
        <div class="muted" style="font-size: 12px">{{ mode === 'officer' ? t('Credit analyst') : t('Business owner') }}<template v-if="auth.name"> · {{ auth.name }}</template></div>
      </template>
    </div>
    <div class="items">
      <RouterLink v-for="it in items" :key="it.label" :to="it.to" :class="{ on: it.match(route.path, route.query) }">
        <Icon :name="it.icon" />{{ it.label }}<span v-if="it.count != null" class="cnt">{{ it.count }}</span>
      </RouterLink>
    </div>
    <div v-if="mode === 'officer' && app.monitoringRunAt" class="card">
      <div class="eyebrow" style="margin-bottom: 6px">{{ t('Monitoring run') }}</div>
      <div>{{ fmtDateTime(app.monitoringRunAt) }}</div>
      <div class="muted">{{ t('Statuses computed from uploaded statements') }}</div>
    </div>
    <div v-if="mode === 'owner' && app.ownerCoverage" class="card">
      <div class="eyebrow" style="margin-bottom: 6px">{{ t('Data coverage') }}</div>
      <div class="muted">{{ t('{a} of {b} documents analyzed', { a: app.ownerCoverage.analysed, b: app.ownerCoverage.total }) }}</div>
      <RouterLink to="/upload" style="display: inline-block; margin-top: 8px">{{ t('Review uploads') }}</RouterLink>
    </div>
    <div id="side-extra"></div>
  </nav>
</template>

<style scoped>
.side { flex: 1 1 220px; max-width: 220px; padding: 16px 12px; border-right: 1px solid var(--border); background: var(--surface-2); }
.who { padding: 6px 12px 14px; }
.items { display: flex; flex-direction: column; gap: 2px; }
.card a { display: inline; height: auto; padding: 0; background: none; color: var(--accent); font-weight: 400; font-size: 12px; }
.card { margin-top: 28px; padding: 12px; border: 1px solid var(--border); border-radius: var(--r-panel); background: var(--surface); font-size: 12px; }
@media (max-width: 720px) {
  .side { max-width: none; border-right: 0; border-bottom: 1px solid var(--border); padding: 10px 12px; }
  .items { flex-direction: row; flex-wrap: wrap; }
  .card, #side-extra { display: none; }
}
</style>
