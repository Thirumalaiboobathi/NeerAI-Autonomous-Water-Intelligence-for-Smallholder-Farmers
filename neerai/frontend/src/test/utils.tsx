import { ThemeProvider } from '@mui/material'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import type { ReactElement } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { vi } from 'vitest'
import { AppStateProvider } from '../app/AppState'
import { theme } from '../app/theme'
import type { Lang } from '../types/api'
import * as fx from './fixtures'

type Handler = (body: unknown, url: string) => unknown

/** Route-table fetch mock keyed by "METHOD /path-prefix". Unmatched routes fail the test loudly. */
export function mockApi(overrides: Record<string, Handler | unknown> = {}) {
  const calls: { method: string; url: string; body: unknown }[] = []
  const table: Record<string, Handler | unknown> = {
    'GET /api/health': { status: 'ok', agent_mode: 'demo', weather_provider: 'mock', env: 'local', repository: 'sql' },
    'GET /api/reference/options': fx.options,
    'GET /api/farms/farm_1/overview': fx.overview,
    'GET /api/farms': [fx.farm],
    'GET /api/fields': fx.fields,
    'GET /api/agent/executions': [],
    'GET /api/demo/scenarios': { note: 'n', chat_examples: ['Should I irrigate my paddy field today?'], weather_scenarios: [{ key: 'uncertain_rain', description: 'Uncertain rain' }] },
    'GET /api/scenarios/presets': [{ name: 'normal', title: 'Normal', description: '' }, { name: 'heatwave', title: 'Heatwave', description: '' }],
    'GET /api/irrigation/plans': [],
    'POST /api/irrigation/plan': fx.plan,
    'POST /api/water/allocate': fx.plan,
    'POST /api/jobs': { id: 'job_1', status: 'queued', progress: 'queued', attempts: 0, execution_id: null, error: null },
    'GET /api/jobs/job_1': { id: 'job_1', status: 'succeeded', progress: 'complete', attempts: 1, execution_id: 'exec_1', error: null },
    'GET /api/agent/executions/exec_1': fx.execution,
    'POST /api/scenarios/simulate': fx.comparison,
    ...overrides,
  }
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = init?.method ?? 'GET'
    const body = init?.body ? JSON.parse(String(init.body)) : undefined
    calls.push({ method, url, body })
    const path = url.split('?')[0]
    const key = Object.keys(table).filter((k) => k.startsWith(`${method} `) && path.startsWith(k.slice(method.length + 1)))
      .sort((a, b) => b.length - a.length)[0]
    if (!key) throw new Error(`unmocked request: ${method} ${url}`)
    const h = table[key]
    const out = typeof h === 'function' ? (h as Handler)(body, url) : h
    if (out instanceof Response) return out
    return new Response(JSON.stringify(out), { status: 200, headers: { 'Content-Type': 'application/json' } })
  }))
  return calls
}

export function renderApp(ui: ReactElement, { lang = 'en' as Lang, route = '/' } = {}) {
  try { localStorage.clear(); localStorage.setItem('neerai.lang', lang) } catch { /* ignore */ }
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  return render(
    <QueryClientProvider client={qc}>
      <AppStateProvider initialLang={lang}>
        <ThemeProvider theme={theme}>
          <MemoryRouter initialEntries={[route]}>{ui}</MemoryRouter>
        </ThemeProvider>
      </AppStateProvider>
    </QueryClientProvider>,
  )
}
