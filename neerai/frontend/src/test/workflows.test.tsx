import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import Ask from '../pages/Ask'
import Dashboard from '../pages/Dashboard'
import Planner from '../pages/Planner'
import Scarcity from '../pages/Scarcity'
import Simulator from '../pages/Simulator'
import * as fx from './fixtures'
import { mockApi, renderApp } from './utils'

vi.mock('react-leaflet', () => ({ MapContainer: () => null, TileLayer: () => null, Marker: () => null, Popup: () => null, useMapEvents: () => null }))

describe('Dashboard — what should I do today?', () => {
  it('shows backend-computed water numbers and the simulated-weather label (English)', async () => {
    mockApi()
    renderApp(<Dashboard />, { lang: 'en' })
    expect(await screen.findByText('What should I do with my farm today?')).toBeInTheDocument()
    expect(await screen.findByText(/Water is short: demand 1,161,538 L/)).toBeInTheDocument()
    expect(screen.getAllByText('Simulated data').length).toBeGreaterThan(0)
    expect(screen.getByText('Water scarcity mode is ACTIVE')).toBeInTheDocument()
    expect(screen.getByText('461.5 m³')).toBeInTheDocument()
  })

  it('renders the Tamil action card and Tamil labels when Tamil is selected', async () => {
    mockApi()
    renderApp(<Dashboard />, { lang: 'ta' })
    expect(await screen.findByText('இன்று என் பண்ணையில் என்ன செய்ய வேண்டும்?')).toBeInTheDocument()
    expect(await screen.findByText(/தண்ணீர் பற்றாக்குறை: தேவை 1,161,538 லிட்டர்/)).toBeInTheDocument()
    expect(screen.getByText(/இறுதி முடிவை நீங்களே எடுக்கவும்/)).toBeInTheDocument()
  })

  it('runs the multi-agent assessment and shows the agent timeline', async () => {
    const calls = mockApi()
    renderApp(<Dashboard />)
    await userEvent.click(await screen.findByRole('button', { name: /Run multi-agent assessment/ }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText('Agent activity timeline')).toBeInTheDocument()
    expect(within(dialog).getByText('farm context →')).toBeInTheDocument()
    expect(within(dialog).getByText('allocate_water_budget')).toBeInTheDocument()
    const assess = calls.find((c) => c.method === 'POST' && c.url === '/api/jobs')!
    expect(assess.body).toMatchObject({ kind: 'assess', farm_id: 'farm_1', language: 'en' })
    expect(calls.some((c) => c.url === '/api/jobs/job_1')).toBe(true) // polled the job status
  })

  it('shows a retryable error state when the backend is down', async () => {
    mockApi({ 'GET /api/farms': () => new Response(JSON.stringify({ detail: 'down' }), { status: 500 }) })
    renderApp(<Dashboard />)
    expect(await screen.findByText('Something went wrong')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Retry/ })).toBeInTheDocument()
  })

  it('offers to load the sample farm when there are no farms', async () => {
    mockApi({ 'GET /api/farms': [] })
    renderApp(<Dashboard />)
    expect(await screen.findByText('No farm yet')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Load sample farm' })).toBeInTheDocument()
  })
})

describe('Irrigation Planner', () => {
  it('lists field-wise decisions and recalculates when water changes', async () => {
    const calls = mockApi()
    renderApp(<Planner />)
    expect(await screen.findByText('Field-wise plan')).toBeInTheDocument()
    expect(screen.getAllByText('Irrigate first').length).toBeGreaterThan(0)
    const input = screen.getByLabelText('Available water in cubic metres')
    fireEvent.change(input, { target: { value: '300' } })
    await waitFor(() => expect(calls.some((c) => c.url === '/api/irrigation/plan' && (c.body as { available_water: number }).available_water === 300)).toBe(true))
    expect(calls.find((c) => (c.body as { available_water?: number } | undefined)?.available_water === 300)!.body).toMatchObject({ available_water_unit: 'm3' })
  })

  it('saves a plan and exports a report', async () => {
    const calls = mockApi({ 'POST /api/irrigation/report': () => new Response('# report', { headers: { 'Content-Type': 'text/plain' } }) })
    URL.createObjectURL = vi.fn(() => 'blob:x')
    URL.revokeObjectURL = vi.fn()
    renderApp(<Planner />)
    await userEvent.click(await screen.findByRole('button', { name: 'Save plan' }))
    await waitFor(() => expect(calls.some((c) => c.body && (c.body as { save?: boolean }).save === true)).toBe(true))
    await userEvent.click(screen.getByRole('button', { name: 'Export report' }))
    await waitFor(() => expect(calls.some((c) => c.url === '/api/irrigation/report')).toBe(true))
  })

  it('explains every decision ("Why this decision?")', async () => {
    mockApi()
    renderApp(<Planner />)
    await screen.findByText('Field-wise plan')
    const why = screen.getAllByText('Why this decision?')
    expect(why.length).toBe(2)
    await userEvent.click(why[0])
    expect((await screen.findAllByText('What would change this recommendation')).length).toBe(2)
    expect(screen.getAllByText(/Rain arrives/).length).toBeGreaterThan(0)
  })
})

describe('Water scarcity workflow', () => {
  it('activates scarcity mode, ranks fields and shows unmet demand', async () => {
    mockApi()
    renderApp(<Scarcity />)
    expect(await screen.findByText('Water scarcity mode is ACTIVE')).toBeInTheDocument()
    expect(screen.getByText('#1')).toBeInTheDocument()
    expect(screen.getByText(/Receives 30% of its demand because water is limited/)).toBeInTheDocument()
    expect(screen.getAllByText(/Unmet demand/).length).toBeGreaterThan(0)
  })

  it('recalculates immediately when the farmer changes a priority', async () => {
    const calls = mockApi()
    renderApp(<Scarcity />)
    await screen.findByText('Priority ranking')
    const group = screen.getByRole('group', { name: /Field priority Paddy plot/ })
    await userEvent.click(within(group).getByRole('button', { name: 'High' }))
    await waitFor(() => expect(calls.some((c) => c.url === '/api/water/allocate' && JSON.stringify((c.body as { priority_overrides: object }).priority_overrides) === '{"f1":2}')).toBe(true))
  })

  it('lets the farmer test 50% of demand', async () => {
    const calls = mockApi()
    renderApp(<Scarcity />)
    await userEvent.click(await screen.findByRole('button', { name: '50% of demand' }))
    await waitFor(() => expect(calls.some((c) => c.url === '/api/water/allocate' && (c.body as { available_water: number }).available_water === 580.8)).toBe(true))
  })
})

describe('What-if simulator', () => {
  it('marks inputs hypothetical, runs, and shows before/after with changed actions', async () => {
    const calls = mockApi()
    renderApp(<Simulator />)
    expect(await screen.findByText(/hypothetical\. They are not forecasts/)).toBeInTheDocument()
    await userEvent.click(await screen.findByRole('button', { name: 'Heatwave' }))
    await userEvent.click(screen.getByRole('button', { name: 'Run simulation' }))
    expect(await screen.findByText('Before and after')).toBeInTheDocument()
    expect(screen.getByText('Total irrigation requirement')).toBeInTheDocument()
    expect(screen.getByText('Changed')).toBeInTheDocument()
    const sim = calls.find((c) => c.url === '/api/scenarios/simulate')!
    expect(sim.body).toMatchObject({ farm_id: 'farm_1', scenarios: ['heatwave'] })
    expect((sim.body as { custom: unknown[] }).custom).toHaveLength(1)
    expect(await screen.findByText(/Scenario weather and water values are hypothetical/)).toBeInTheDocument()
  })

  it('surfaces validation errors from the API', async () => {
    mockApi({ 'POST /api/scenarios/simulate': () => new Response(JSON.stringify({ detail: 'unknown scenario' }), { status: 422 }) })
    renderApp(<Simulator />)
    await userEvent.click(await screen.findByRole('button', { name: 'Run simulation' }))
    expect(await screen.findByText('unknown scenario')).toBeInTheDocument()
  })
})

describe('Ask NeerAI', () => {
  it('answers an example question with recommendation, sources, reasons and trace', async () => {
    const calls = mockApi()
    renderApp(<Ask />)
    await userEvent.click(await screen.findByText('Should I irrigate my paddy field today?'))
    expect(await screen.findByText(/Water is short: demand 1,161,538 L, available 400,000 L/)).toBeInTheDocument()
    expect(screen.getByText('Recommendation')).toBeInTheDocument()
    expect(screen.getByText('Estimated water use')).toBeInTheDocument()
    expect(screen.getByText(/Data sources/)).toBeInTheDocument()
    expect(screen.getByText(/Agent activity timeline \(3\)/)).toBeInTheDocument()
    expect(calls.find((c) => c.method === 'POST' && c.url === '/api/jobs')!.body).toMatchObject({ kind: 'chat', farm_id: 'farm_1', language: 'en' })
  })

  it('follow-up chips ask the next question', async () => {
    const calls = mockApi()
    renderApp(<Ask />)
    await userEvent.type(await screen.findByLabelText('Ask about irrigation…'), 'hello{enter}')
    await userEvent.click(await screen.findByText('What happens if I delay irrigation by one day?'))
    await waitFor(() => expect(calls.filter((c) => c.method === 'POST' && c.url === '/api/jobs')).toHaveLength(2))
  })

  it('asks for missing information instead of guessing', async () => {
    const ex = { ...fx.execution, decision: { ...fx.plan.decision, headline_action: 'INSUFFICIENT_DATA' as const, decisions: [] }, allocation: null, message: null,
      answer: 'How much water do you have available for irrigation (in litres or cubic metres)?' }
    mockApi({ 'GET /api/agent/executions/exec_1': ex })
    renderApp(<Ask />)
    await userEvent.type(await screen.findByLabelText('Ask about irrigation…'), 'Should I irrigate?{enter}')
    expect(await screen.findByText(/How much water do you have available/)).toBeInTheDocument()
  })

  it('shows a safe, retryable message when the job fails', async () => {
    mockApi({ 'GET /api/jobs/job_1': { id: 'job_1', status: 'failed', progress: 'failed', attempts: 3, execution_id: null,
      error: { code: 'agent_error', message: 'The assessment could not be completed. Please try again.', retryable: true } } })
    renderApp(<Ask />)
    await userEvent.type(await screen.findByLabelText('Ask about irrigation…'), 'Should I irrigate?{enter}')
    expect(await screen.findByText(/could not be completed/)).toBeInTheDocument()
  })

  it('shows queued progress while a job waits for a worker', async () => {
    let polls = 0
    mockApi({ 'GET /api/jobs/job_1': () => (++polls < 40 ? { id: 'job_1', status: 'queued', progress: 'queued', attempts: 0, execution_id: null, error: null }
      : { id: 'job_1', status: 'succeeded', progress: 'complete', attempts: 1, execution_id: 'exec_1', error: null }) })
    renderApp(<Ask />)
    await userEvent.type(await screen.findByLabelText('Ask about irrigation…'), 'Should I irrigate?{enter}')
    expect(await screen.findByText('Waiting for an available agent worker…')).toBeInTheDocument()
    expect(await screen.findByText('Recommendation', {}, { timeout: 6000 })).toBeInTheDocument() // then completes
  })

  it('surfaces API errors when the job cannot be submitted (quota)', async () => {
    mockApi({ 'POST /api/jobs': () => new Response(JSON.stringify({ detail: 'too many agent runs in progress; wait for one to finish' }), { status: 429 }) })
    renderApp(<Ask />)
    await userEvent.type(await screen.findByLabelText('Ask about irrigation…'), 'Should I irrigate?{enter}')
    expect(await screen.findByText(/too many agent runs in progress/)).toBeInTheDocument()
  })

  it('works in Tamil', async () => {
    mockApi()
    renderApp(<Ask />, { lang: 'ta' })
    expect(await screen.findByText('NeerAI-யிடம் கேளுங்கள்')).toBeInTheDocument()
    expect(screen.getByLabelText('பாசனம் பற்றி கேளுங்கள்…')).toBeInTheDocument()
  })
})
