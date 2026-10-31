import { describe, expect, it, vi } from 'vitest'
import { dictionaries, fmtVolume, translate } from '../i18n'
import { api, ApiError } from '../services/api'

const sources = import.meta.glob('../**/*.tsx', { query: '?raw', import: 'default', eager: true }) as Record<string, string>

describe('i18n', () => {
  it('Tamil and English dictionaries have identical keys', () => {
    expect(Object.keys(dictionaries.ta).sort()).toEqual(Object.keys(dictionaries.en).sort())
  })

  it('every translated string used in the UI exists in both languages', () => {
    const used = new Set<string>()
    for (const src of Object.values(sources)) {
      for (const m of src.matchAll(/\bt\(\s*['"`]([\w.\-/ ]+?)['"`]/g)) used.add(m[1])
    }
    expect(used.size).toBeGreaterThan(150)
    const missing = [...used].filter((k) => !(k in dictionaries.en) || !(k in dictionaries.ta))
    expect(missing).toEqual([])
  })

  it('covers dynamically built keys', () => {
    const groups: Record<string, string[]> = {
      action: ['IRRIGATE_NOW', 'DELAY_AND_MONITOR', 'PARTIAL_IRRIGATION', 'PRIORITIZE_FIELD', 'INSUFFICIENT_DATA'],
      confidence: ['high', 'medium', 'low'], heat: ['none', 'moderate', 'high'], stage: ['initial', 'development', 'mid', 'late'],
      status: ['ok', 'error', 'fallback'], tier: ['critical', 'standard', 'deferred'], 'impact.kind': ['estimated_potential', 'simulated', 'measured'],
      source: ['borewell', 'open well', 'canal', 'tank / pond', 'rain-fed'],
      nav: ['dashboard', 'farms', 'planner', 'scarcity', 'simulator', 'ask', 'impact', 'settings'],
    }
    for (const [prefix, names] of Object.entries(groups))
      for (const n of names) for (const l of ['en', 'ta'] as const) expect(dictionaries[l][`${prefix}.${n}`], `${l}:${prefix}.${n}`).toBeTruthy()
  })

  it('Tamil strings are actually Tamil and keep placeholders', () => {
    expect(translate('ta', 'dash.title')).toMatch(/[஀-௿]/)
    expect(translate('ta', 'scarcity.banner', { d: '461.5 m³' })).toContain('461.5 m³')
    expect(translate('en', 'no.such.key')).toBe('no.such.key')
  })
})

describe('volume formatting', () => {
  it('uses litres below 10,000 and cubic metres above, keeping Arabic numerals', () => {
    expect(fmtVolume(3000, 'en')).toBe('3,000 L')
    expect(fmtVolume(3000, 'ta')).toBe('3,000 லிட்டர்')
    expect(fmtVolume(700000, 'en')).toBe('700 m³')
    expect(fmtVolume(700000, 'ta')).toBe('700 கன மீட்டர்')
  })
})

describe('api client', () => {
  it('maps server errors to ApiError with the backend detail', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ detail: 'available water volume is required' }), { status: 422 })))
    await expect(api.plan({ farm_id: 'x' })).rejects.toMatchObject({ status: 422, message: 'available water volume is required' })
  })

  it('handles non-JSON error bodies', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('Bad gateway', { status: 502, statusText: 'Bad Gateway' })))
    await expect(api.farms()).rejects.toBeInstanceOf(ApiError)
  })

  it('reports an unreachable backend in plain words', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('Failed to fetch') }))
    await expect(api.health()).rejects.toThrow(/Cannot reach the NeerAI server/)
  })

  it('encodes query params', async () => {
    const f = vi.fn(async () => new Response('[]', { headers: { 'Content-Type': 'application/json' } }))
    vi.stubGlobal('fetch', f)
    await api.overview('farm 1', 'heat wave')
    expect(String((f.mock.calls[0] as unknown[])[0])).toBe('/api/farms/farm 1/overview?weather_scenario=heat%20wave')
  })
})
