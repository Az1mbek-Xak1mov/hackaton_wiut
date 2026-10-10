import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { getAuth } from '@/api/client'
import { surface } from '@/surface'

declare module 'vue-router' {
  interface RouteMeta {
    public?: boolean
    auth?: boolean
    title?: string
    bare?: boolean // no side navigation (login, register, landing)
  }
}

const shared: RouteRecordRaw[] = [
  { path: '/analyse', component: () => import('@/pages/Analyse.vue'), meta: { public: true, title: 'Analyse a document' } },
  { path: '/metrics', component: () => import('@/pages/Metrics.vue'), meta: { public: true, title: 'Evaluation metrics' } },
  { path: '/kit', component: () => import('@/pages/Kit.vue'), meta: { public: true, title: 'Component kit' } },
  { path: '/login', component: () => import('@/pages/Login.vue'), meta: { public: true, bare: true, title: 'Sign in' } },
]

// Business owner app (converza.uz)
const ownerRoutes: RouteRecordRaw[] = [
  { path: '/', component: () => import('@/pages/owner/Home.vue'), meta: { public: true, title: 'Home' } },
  { path: '/register', component: () => import('@/pages/Register.vue'), meta: { public: true, bare: true, title: 'Register' } },
  { path: '/upload', component: () => import('@/pages/owner/Upload.vue'), meta: { auth: true, title: 'Upload & analyze' } },
  { path: '/cfo', component: () => import('@/pages/owner/AICFO.vue'), meta: { auth: true, title: 'AI CFO' } },
  { path: '/owner/upload', redirect: '/upload' },
  { path: '/owner/cfo', redirect: '/cfo' },
  { path: '/owner', redirect: '/' },
  { path: '/bank/:rest(.*)*', redirect: '/' }, // officer screens live on app.converza.uz
]

// Bank officer app (app.converza.uz)
const bankRoutes: RouteRecordRaw[] = [
  { path: '/', redirect: '/bank' },
  { path: '/bank', component: () => import('@/pages/bank/Portfolio.vue'), meta: { auth: true, title: 'Portfolio overview' } },
  { path: '/bank/applications', component: () => import('@/pages/bank/Applications.vue'), meta: { auth: true, title: 'Applications' } },
  { path: '/bank/applications/:number', component: () => import('@/pages/bank/LoanReview.vue'), meta: { auth: true, title: 'Loan application review' } },
  { path: '/bank/borrowers', component: () => import('@/pages/bank/Borrowers.vue'), meta: { auth: true, title: 'Borrower portfolio' } },
  { path: '/bank/borrowers/:loanId', component: () => import('@/pages/bank/BorrowerProfile.vue'), meta: { auth: true, title: 'Borrower profile' } },
  { path: '/register', redirect: '/login' },
  { path: '/upload', redirect: '/bank' },
  { path: '/cfo', redirect: '/bank' },
  { path: '/owner/:rest(.*)*', redirect: '/bank' }, // owner screens live on converza.uz
]

const router = createRouter({
  history: createWebHistory(),
  scrollBehavior(to, _from, saved) {
    if (saved) return saved
    if (to.hash) return { el: to.hash, top: 12, behavior: 'smooth' }
    return { top: 0 }
  },
  routes: [
    ...(surface === 'bank' ? bankRoutes : ownerRoutes),
    ...shared,
    { path: '/:pathMatch(.*)*', component: () => import('@/pages/NotFound.vue'), meta: { public: true, title: 'Not found' } },
  ],
})

router.beforeEach((to) => {
  if (to.meta.auth && !getAuth()?.access) return { path: '/login', query: { next: to.fullPath } }
  if ((to.path === '/login' || to.path === '/register') && getAuth()?.access) return surface === 'bank' ? '/bank' : '/'
  return true
})

router.afterEach((to) => {
  document.title = to.meta.title ? `${to.meta.title} · Converza` : 'Converza'
})

export default router
