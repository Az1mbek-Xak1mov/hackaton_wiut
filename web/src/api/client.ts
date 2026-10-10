import type {
  AnalyseResult, BundleCreated, BundleResult, ApplicationListItem, ApplicationReview, BorrowerList, BorrowerProfile,
  CfoHistoryItem, CfoResponse, CreatedWithJob, DocumentOut, Fact, Finding, Job, LlmSettings, OwnerApplication, OwnerBusiness,
  PortfolioSummary, TokenPair, VersionInfo, ApiErrorBody,
} from './types'

import { surface } from '@/surface'

const BASE = '/api/v1'
const LS_KEY = `converza.auth.${surface}`

export type Role = 'officer' | 'owner'

interface StoredAuth {
  access: string
  refresh: string
  role: Role
  name: string
}

function readStored(): StoredAuth | null {
  try {
    const raw = localStorage.getItem(LS_KEY)
    return raw ? (JSON.parse(raw) as StoredAuth) : null
  } catch {
    return null
  }
}

let auth: StoredAuth | null = readStored()
const listeners = new Set<(a: StoredAuth | null) => void>()

export function getAuth(): StoredAuth | null {
  return auth
}

export function onAuthChange(fn: (a: StoredAuth | null) => void) {
  listeners.add(fn)
  return () => listeners.delete(fn)
}

function setAuth(a: StoredAuth | null) {
  auth = a
  try {
    if (a) localStorage.setItem(LS_KEY, JSON.stringify(a))
    else localStorage.removeItem(LS_KEY)
  } catch {
    /* storage unavailable: keep in memory only */
  }
  listeners.forEach((fn) => fn(a))
}

export class ApiError extends Error {
  status: number
  code: string
  body: ApiErrorBody | null
  constructor(status: number, body: ApiErrorBody | null, fallback: string) {
    super(body?.message || fallback)
    this.status = status
    this.code = body?.code || `http_${status}`
    this.body = body
  }
}

async function parseError(res: Response): Promise<ApiError> {
  let body: ApiErrorBody | null = null
  try {
    const j = await res.json()
    if (j && typeof j === 'object') {
      if ('code' in j) body = j as ApiErrorBody
      else if ('detail' in j) {
        const d = (j as any).detail
        body = { code: `http_${res.status}`, message: typeof d === 'string' ? d : 'Some fields are invalid. Please check the form and try again.' }
      }
    }
  } catch {
    /* not JSON */
  }
  const fallback =
    res.status >= 500 ? 'Something went wrong on our side. Please try again in a minute.'
    : res.status === 413 ? 'The file is too large (maximum 20 MB).'
    : res.status === 429 ? 'Too many uploads in a short time. Please wait a minute and try again.'
    : res.status === 401 ? 'Your session has expired. Please sign in again.'
    : `Request failed (${res.status}).`
  return new ApiError(res.status, body, fallback)
}

let refreshing: Promise<boolean> | null = null

async function tryRefresh(): Promise<boolean> {
  if (!auth?.refresh) return false
  if (!refreshing) {
    refreshing = (async () => {
      try {
        const res = await fetch(`${BASE}/auth/refresh`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ refresh_token: auth!.refresh }),
        })
        if (!res.ok) return false
        const tp = (await res.json()) as TokenPair
        setAuth({ ...auth!, access: tp.access_token, refresh: tp.refresh_token })
        return true
      } catch {
        return false
      } finally {
        setTimeout(() => (refreshing = null), 0)
      }
    })()
  }
  return refreshing
}

interface ReqOpts {
  method?: string
  body?: unknown
  form?: FormData
  auth?: boolean // send the bearer token if we have one (default true)
  retried?: boolean
}

export async function request<T>(path: string, opts: ReqOpts = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' }
  let body: BodyInit | undefined
  if (opts.form) body = opts.form
  else if (opts.body !== undefined) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(opts.body)
  }
  const useAuth = opts.auth !== false
  if (useAuth && auth?.access) headers.Authorization = `Bearer ${auth.access}`
  const res = await fetch(`${BASE}${path}`, { method: opts.method || 'GET', headers, body })
  if (res.status === 401 && useAuth && auth && !opts.retried) {
    if (await tryRefresh()) return request<T>(path, { ...opts, retried: true })
    setAuth(null) // session is over: the router sends the user to /login
  }
  if (!res.ok) throw await parseError(res)
  if (res.status === 204) return undefined as T
  const ct = res.headers.get('content-type') || ''
  if (!ct.includes('json')) return (await res.text()) as unknown as T
  return (await res.json()) as T
}

function storeTokens(tp: TokenPair) {
  const u = tp.user || {}
  setAuth({
    access: tp.access_token,
    refresh: tp.refresh_token,
    role: surface === 'bank' ? 'officer' : 'owner',
    name: (u.full_name || u.name || u.email || '') as string,
  })
}

/** Email + password sign-in for this surface (OAuth2 password form). */
export async function login(email: string, password: string): Promise<TokenPair> {
  const body = new URLSearchParams({ username: email, password })
  const res = await fetch(`${BASE}/auth/login?surface=${surface}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded', Accept: 'application/json' },
    body,
  })
  if (!res.ok) throw await parseError(res)
  const tp = (await res.json()) as TokenPair
  storeTokens(tp)
  return tp
}

/** Shared jury/visitor demo account for this surface (passwordless; the server answers 404 when it is switched off). */
export async function demoLogin(): Promise<TokenPair> {
  const res = await fetch(`${BASE}/auth/demo`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify({ role: surface === 'bank' ? 'officer' : 'owner' }),
  })
  if (!res.ok) throw await parseError(res)
  const tp = (await res.json()) as TokenPair
  storeTokens(tp)
  return tp
}

export interface RegisterPayload {
  full_name: string
  company_name: string
  stir?: string
  industry: string
  region: string
  email: string
  password: string
}

/** Business-owner self-registration; the response is a token pair (signed in at once). */
export async function register(payload: RegisterPayload): Promise<TokenPair> {
  const res = await fetch(`${BASE}/auth/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!res.ok) throw await parseError(res)
  const tp = (await res.json()) as TokenPair
  if (tp.access_token) storeTokens(tp)
  else await login(payload.email, payload.password)
  return tp
}

export function logout() {
  setAuth(null)
}

// ---------- endpoints ----------
export const api = {
  version: () => request<VersionInfo>('/version', { auth: false }),

  // public analyse
  analyse: (file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    return request<CreatedWithJob>('/analyse', { method: 'POST', form: fd, auth: false })
  },
  analyseBundle: (files: File[]) => {
    const fd = new FormData()
    for (const f of files) fd.append('files', f)
    return request<BundleCreated>('/analyse/bundle', { method: 'POST', form: fd, auth: false })
  },
  analyseBundleResult: (uuid: string) => request<BundleResult>(`/analyse/bundle/${encodeURIComponent(uuid)}`, { auth: false }),
  analyseResult: (uuid: string) => request<AnalyseResult>(`/analyse/${encodeURIComponent(uuid)}`, { auth: false }),
  metricsEval: () => request<Record<string, any>>('/metrics/eval', { auth: false }),

  // facts
  facts: (keys: string[]) =>
    request<{ facts: Fact[] }>(`/facts?keys=${keys.map(encodeURIComponent).join(',')}`),
  reviewFact: (uuid: string, payload: { action: 'verify' | 'correct' | 'flag'; value?: number; note?: string }) =>
    request<Fact>(`/facts/${encodeURIComponent(uuid)}/review`, { method: 'POST', body: payload }),
  documentFacts: (uuid: string) => request<Fact[] | { facts: Fact[] } | { items: Fact[] }>(`/documents/${encodeURIComponent(uuid)}/facts`),

  // officer
  portfolio: () => request<PortfolioSummary>('/portfolio/summary'),
  applications: () => request<{ items: ApplicationListItem[] }>('/applications'),
  applicationReview: (number: string) => request<ApplicationReview>(`/applications/${encodeURIComponent(number)}/review`),
  regenerateNarrative: (number: string) =>
    request<Job>(`/applications/${encodeURIComponent(number)}/narrative/regenerate`, { method: 'POST' }),
  job: (uuid: string) => request<Job>(`/jobs/${encodeURIComponent(uuid)}`, { auth: false }),
  recordDecision: (number: string, payload: { outcome: string; reasoning: string; evidence_reviewed: string[] }) =>
    request<unknown>(`/applications/${encodeURIComponent(number)}/decision`, { method: 'POST', body: payload }),
  borrowers: (status?: string) =>
    request<BorrowerList>(`/borrowers${status && status !== 'all' ? `?status=${encodeURIComponent(status)}` : ''}`),
  borrower: (loanId: string) => request<BorrowerProfile>(`/borrowers/${encodeURIComponent(loanId)}`),
  updateFinding: (uuid: string, payload: { state: 'open' | 'resolved' | 'dismissed'; note?: string }) =>
    request<Finding>(`/findings/${encodeURIComponent(uuid)}`, { method: 'PATCH', body: payload }),
  borrowerReviewOutcome: (loanId: string, payload: { outcome: string; reasoning: string; evidence_reviewed: string[] }) =>
    request<unknown>(`/borrowers/${encodeURIComponent(loanId)}/review-outcome`, { method: 'POST', body: payload }),
  llmSettings: () => request<LlmSettings>('/settings/llm'),
  setLlm: (enabled: boolean) => request<LlmSettings>('/settings/llm', { method: 'PUT', body: { enabled } }),

  // owner
  ownerFiles: () => request<{ business?: OwnerBusiness | null; items: DocumentOut[] }>('/owner/files'),
  ownerUpload: (file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    return request<CreatedWithJob>('/owner/files', { method: 'POST', form: fd })
  },
  ownerApplications: () => request<{ items: OwnerApplication[] } | OwnerApplication[]>('/owner/applications'),
  ownerApply: (payload: { requested_amount_mln: number; term_months: number; purpose: string; document_uuids: string[] }) =>
    request<OwnerApplication>('/owner/applications', { method: 'POST', body: payload }),
  cfoAsk: (question: string) => request<CfoResponse>('/cfo/messages', { method: 'POST', body: { question } }),
  cfoHistory: () =>
    request<CfoHistoryItem[] | { business?: OwnerBusiness; messages?: CfoHistoryItem[]; items?: CfoHistoryItem[]; facts?: Record<string, Fact> }>('/cfo/messages'),
}

export function errMessage(e: unknown): string {
  if (e instanceof ApiError) return e.message
  if (e instanceof Error) return e.message
  return String(e)
}
