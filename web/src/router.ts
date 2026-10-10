import { createRouter, createWebHistory, type RouteLocationNormalized } from 'vue-router'
import { getAuth, demoLogin, type Role } from '@/api/client'

declare module 'vue-router' {
  interface RouteMeta {
    public?: boolean
    role?: Role
    title?: string
  }
}

const router = createRouter({
  history: createWebHistory(),
  scrollBehavior(to, _from, saved) {
    if (saved) return saved
    if (to.hash) return { el: to.hash, top: 12, behavior: 'smooth' }
    return { top: 0 }
  },
  routes: [
    { path: '/', redirect: '/analyse' },
    { path: '/analyse', component: () => import('@/pages/Analyse.vue'), meta: { public: true, title: 'Analyse a document' } },
    { path: '/login', component: () => import('@/pages/Login.vue'), meta: { public: true, title: 'Enter the demo' } },
    { path: '/kit', component: () => import('@/pages/Kit.vue'), meta: { public: true, title: 'Component kit' } },
    { path: '/metrics', component: () => import('@/pages/Metrics.vue'), meta: { public: true, title: 'Evaluation metrics' } },
    { path: '/bank', component: () => import('@/pages/bank/Portfolio.vue'), meta: { role: 'officer', title: 'Portfolio overview' } },
    { path: '/bank/applications', component: () => import('@/pages/bank/Applications.vue'), meta: { role: 'officer', title: 'Applications' } },
    { path: '/bank/applications/:number', component: () => import('@/pages/bank/LoanReview.vue'), meta: { role: 'officer', title: 'Loan application review' } },
    { path: '/bank/borrowers', component: () => import('@/pages/bank/Borrowers.vue'), meta: { role: 'officer', title: 'Borrower portfolio' } },
    { path: '/bank/borrowers/:loanId', component: () => import('@/pages/bank/BorrowerProfile.vue'), meta: { role: 'officer', title: 'Borrower profile' } },
    { path: '/owner', redirect: '/owner/cfo' },
    { path: '/owner/cfo', component: () => import('@/pages/owner/AICFO.vue'), meta: { role: 'owner', title: 'AI CFO' } },
    { path: '/owner/upload', component: () => import('@/pages/owner/Upload.vue'), meta: { role: 'owner', title: 'Upload & analyze' } },
    { path: '/:pathMatch(.*)*', component: () => import('@/pages/NotFound.vue'), meta: { public: true, title: 'Not found' } },
  ],
})

router.beforeEach(async (to: RouteLocationNormalized) => {
  const need = to.meta.role
  if (!need) return true
  const a = getAuth()
  if (a?.access && a.role === need) return true
  try {
    await demoLogin(need) // demo build: sessions are issued on demand by POST /auth/demo
    return true
  } catch {
    return { path: '/login', query: { next: to.fullPath, role: need, failed: '1' } }
  }
})

router.afterEach((to) => {
  document.title = to.meta.title ? `${to.meta.title} · Converza` : 'Converza'
})

export default router
