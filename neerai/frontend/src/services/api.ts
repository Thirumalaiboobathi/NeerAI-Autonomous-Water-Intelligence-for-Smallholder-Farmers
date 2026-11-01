import type {
  AgentExecution, Farm, FarmOverview, FieldCreateBody, FieldRec, Health, ImpactSummary, Lang, Options, PlanRequest, PlanResult,
  ScenarioComparison, ScenarioParams, PlanRecordLite,
} from '../types/api'

import { authEnabled, getAccessToken, login } from './auth'

const BASE = ((import.meta.env.VITE_API_URL as string | undefined) ?? '').replace(/\/$/, '')

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  const send = async () => {
    const token = await getAccessToken()
    return fetch(`${BASE}${path}`, {
      ...init,
      headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}), ...(init?.headers ?? {}) },
    })
  }
  try {
    res = await send()
  } catch {
    throw new ApiError(0, 'Cannot reach the NeerAI server. Is the backend running?')
  }
  if (res.status === 401 && authEnabled) {
    res = await send().catch(() => res) // one retry: getAccessToken() refreshes an expired token
    if (res.status === 401) {
      void login() // session is gone: back to the hosted sign-in page
      throw new ApiError(401, 'Your session has expired. Redirecting to sign in…')
    }
  }
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
    } catch { /* non-JSON error body */ }
    throw new ApiError(res.status, detail)
  }
  if (res.status === 204) return undefined as T
  const ct = res.headers.get('content-type') ?? ''
  return (ct.includes('application/json') ? res.json() : res.text()) as Promise<T>
}

const post = <T>(path: string, body: unknown) => request<T>(path, { method: 'POST', body: JSON.stringify(body) })
const qs = (p: Record<string, string | undefined | null>) => {
  const e = Object.entries(p).filter(([, v]) => v)
  return e.length ? '?' + e.map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`).join('&') : ''
}

export interface JobView {
  id: string
  status: 'queued' | 'running' | 'succeeded' | 'failed'
  progress: string
  attempts: number
  execution_id: string | null
  error: { code: string; message: string; retryable: boolean } | null
}

/** Poll interval; exported mutable so tests can shorten it. */
export const pollConfig = { ms: 1500 }
const POLL_TIMEOUT_MS = 4 * 60_000

/** Submit a long-running agent workflow as an async job and poll until it finishes (queued -> running -> succeeded|failed). */
async function runJob(body: Record<string, unknown>, onProgress?: (j: JobView) => void): Promise<AgentExecution> {
  const key = crypto.randomUUID() // idempotency: a retried POST never creates a second job
  let job = await request<JobView>('/api/jobs', { method: 'POST', body: JSON.stringify(body), headers: { 'Idempotency-Key': key } })
  const t0 = Date.now()
  for (;;) {
    onProgress?.(job)
    if (job.status === 'succeeded' && job.execution_id) return request<AgentExecution>(`/api/agent/executions/${job.execution_id}`)
    if (job.status === 'failed') throw new ApiError(500, job.error?.message ?? 'The assessment failed. Please try again.')
    if (Date.now() - t0 > POLL_TIMEOUT_MS) throw new ApiError(504, 'The assessment is taking longer than expected. Please try again in a moment.')
    await new Promise((r) => setTimeout(r, pollConfig.ms))
    job = await request<JobView>(`/api/jobs/${job.id}`)
  }
}

export const api = {
  health: () => request<Health>('/api/health'),
  options: () => request<Options>('/api/reference/options'),
  farms: () => request<Farm[]>('/api/farms'),
  createFarm: (b: Partial<Farm>) => post<Farm>('/api/farms', b),
  patchFarm: (id: string, b: Partial<Farm>) => request<Farm>(`/api/farms/${id}`, { method: 'PATCH', body: JSON.stringify(b) }),
  deleteFarm: (id: string) => request<void>(`/api/farms/${id}`, { method: 'DELETE' }),
  overview: (id: string, scenario?: string | null) => request<FarmOverview>(`/api/farms/${id}/overview${qs({ weather_scenario: scenario })}`),
  fields: () => request<FieldRec[]>('/api/fields'),
  createField: (b: FieldCreateBody) => post<FieldRec>('/api/fields', b),
  patchField: (id: string, b: Partial<FieldRec>) => request<FieldRec>(`/api/fields/${id}`, { method: 'PATCH', body: JSON.stringify(b) }),
  deleteField: (id: string) => request<void>(`/api/fields/${id}`, { method: 'DELETE' }),
  plan: (b: PlanRequest) => post<PlanResult>('/api/irrigation/plan', b),
  allocate: (b: PlanRequest) => post<PlanResult>('/api/water/allocate', b),
  plans: (farmId: string) => request<PlanRecordLite[]>(`/api/irrigation/plans${qs({ farm_id: farmId })}`),
  planReport: (id: string) => request<string>(`/api/irrigation/plans/${id}/report`),
  report: (b: PlanRequest) => post<string>('/api/irrigation/report', b),
  assess: (b: { farm_id: string; query?: string; language: Lang; weather_scenario?: string | null; available_water?: number | null; available_water_unit?: 'litres' | 'm3'; priority_overrides?: Record<string, number> },
    onProgress?: (j: JobView) => void) =>
    runJob({ kind: 'assess', ...b, query: b.query ?? 'Should I irrigate today?' }, onProgress),
  chat: (b: { farm_id: string; message: string; language: Lang; weather_scenario?: string | null }, onProgress?: (j: JobView) => void) =>
    runJob({ kind: 'chat', farm_id: b.farm_id, query: b.message, language: b.language, weather_scenario: b.weather_scenario }, onProgress),
  executions: (farmId?: string) => request<AgentExecution[]>(`/api/agent/executions${qs({ farm_id: farmId })}`),
  execution: (id: string) => request<AgentExecution>(`/api/agent/executions/${id}`),
  simulate: (b: { farm_id: string; scenarios?: string[]; custom?: ScenarioParams[]; available_water?: number | null; available_water_unit?: 'litres' | 'm3'; weather_scenario?: string | null }) =>
    post<ScenarioComparison>('/api/scenarios/simulate', b),
  presets: () => request<{ name: string; title: string; description: string }[]>('/api/scenarios/presets'),
  impact: () => request<ImpactSummary>('/api/impact/summary'),
  demo: () => request<{ note: string; chat_examples: string[]; weather_scenarios: { key: string; description: string }[] }>('/api/demo/scenarios'),
  loadDemo: (key: string, reset = false) => post<Farm>(`/api/demo/load${qs({ key, reset: reset ? 'true' : undefined })}`, {}),
}
