import {
  Alert,
  Button,
  Chip,
  Slider,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
} from '@mui/material'
import { Box, Stack, Typography } from '../components/mui'
import ScienceIcon from '@mui/icons-material/Science'
import { useMutation } from '@tanstack/react-query'
import { useState } from 'react'
import { useAppState } from '../app/AppState'
import { ScenarioBars } from '../components/charts'
import { ErrorBlock, Grid, PageHeader, Panel } from '../components/common'
import { ActionChip, PriorityControls } from '../components/domain'
import FarmGate from '../components/FarmGate'
import { useInvalidateData, useOverview, usePresets } from '../hooks/useApi'
import { fmtVolume, useT } from '../i18n'
import { api } from '../services/api'
import type { Farm, ScenarioParams } from '../types/api'

interface Knobs {
  waterPct: number
  rain: number
  prob: number
  temp: number
  eff: number // 0 = unchanged
  area: number
  delay: number
}
const DEFAULT: Knobs = { waterPct: 100, rain: 0, prob: 0, temp: 0, eff: 0, area: 100, delay: 0 }

function Knob({ label, value, min, max, step, unit, onChange, hint }: { label: string; value: number; min: number; max: number; step: number; unit: string; onChange: (v: number) => void; hint?: string }) {
  return (
    <Box>
      <Stack direction="row" justifyContent="space-between"><Typography variant="body2" fontWeight={600} id={`k-${label}`}>{label}</Typography><Typography variant="body2" color="primary.dark" fontWeight={700}>{value}{unit}</Typography></Stack>
      <Slider aria-labelledby={`k-${label}`} value={value} min={min} max={max} step={step} onChange={(_, v) => onChange(v as number)} />
      {hint && <Typography variant="caption" color="text.secondary">{hint}</Typography>}
    </Box>
  )
}

function SimulatorBody({ farm }: { farm: Farm }) {
  const { t, lang } = useT()
  const { weatherScenario } = useAppState()
  const ov = useOverview(farm.id)
  const presets = usePresets()
  const invalidate = useInvalidateData()
  const [k, setK] = useState<Knobs>(DEFAULT)
  const [chosen, setChosen] = useState<string[]>([])
  const [prio, setPrio] = useState<Record<string, number>>({})

  const custom = (): ScenarioParams => ({
    name: 'custom', title: t('sim.custom'), description: t('sim.custom_desc'),
    water_factor: k.waterPct / 100, rainfall_mm: k.prob > 0 || k.rain > 0 ? k.rain : null, rain_probability_pct: k.prob > 0 || k.rain > 0 ? k.prob : null,
    temperature_delta_c: k.temp, efficiency_override: k.eff > 0 ? k.eff / 100 : null, area_factor: k.area / 100, delay_days: k.delay, priority_overrides: prio,
  })
  const run = useMutation({
    mutationFn: () => api.simulate({ farm_id: farm.id, scenarios: chosen, custom: [custom()], weather_scenario: weatherScenario }),
    onSuccess: invalidate,
  })
  const toggle = (n: string) => setChosen((c) => (c.includes(n) ? c.filter((x) => x !== n) : [...c, n]))
  const res = run.data
  const mine = res?.scenarios.find((s) => s.name === 'custom')
  const fieldList = ov.data?.fields ?? []

  return (
    <>
      <PageHeader title={t('sim.title')} subtitle={t('sim.subtitle')}
        actions={<Button variant="contained" size="large" startIcon={<ScienceIcon />} onClick={() => run.mutate()} disabled={run.isPending}>{run.isPending ? t('sim.running') : t('sim.run')}</Button>} />
      <Alert severity="warning" sx={{ mb: 2 }}>{t('sim.hypothetical')}</Alert>
      <Stack spacing={2.5}>
        <Grid cols={{ xs: 1, lg: 2 }}>
          <Panel title={t('sim.knobs')} action={<Button size="small" onClick={() => { setK(DEFAULT); setPrio({}) }}>{t('sim.reset')}</Button>}>
            <Stack spacing={1.5}>
              <Knob label={t('sim.water')} value={k.waterPct} min={10} max={200} step={5} unit="%" onChange={(v) => setK({ ...k, waterPct: v })} hint={`${t('sim.base')}: ${fmtVolume(farm.water_available_litres ?? 0, lang)}`} />
              <Knob label={t('sim.rain')} value={k.rain} min={0} max={100} step={5} unit=" mm" onChange={(v) => setK({ ...k, rain: v, prob: k.prob || 80 })} />
              <Knob label={t('sim.prob')} value={k.prob} min={0} max={100} step={5} unit="%" onChange={(v) => setK({ ...k, prob: v })} hint={t('sim.rain_hint')} />
              <Knob label={t('sim.temp')} value={k.temp} min={-5} max={10} step={1} unit=" °C" onChange={(v) => setK({ ...k, temp: v })} />
              <Knob label={t('sim.eff')} value={k.eff} min={0} max={95} step={5} unit={k.eff === 0 ? ` (${t('sim.unchanged')})` : '%'} onChange={(v) => setK({ ...k, eff: v === 0 ? 0 : Math.max(30, v) })} />
              <Knob label={t('sim.area')} value={k.area} min={50} max={200} step={10} unit="%" onChange={(v) => setK({ ...k, area: v })} />
              <Knob label={t('sim.delay')} value={k.delay} min={0} max={5} step={1} unit={` ${t('days')}`} onChange={(v) => setK({ ...k, delay: v })} />
              <Box>
                <Typography variant="body2" fontWeight={600} sx={{ mb: 1 }}>{t('priority.title')}</Typography>
                <PriorityControls fields={fieldList} value={prio} onChange={setPrio} />
              </Box>
            </Stack>
          </Panel>
          <Panel title={t('sim.presets')}>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>{t('sim.presets_help')}</Typography>
            <Stack direction="row" gap={1} flexWrap="wrap">
              {(presets.data ?? []).filter((p) => p.name !== 'normal').map((p) => (
                <Chip key={p.name} label={t(`preset.${p.name}`) === `preset.${p.name}` ? p.title : t(`preset.${p.name}`)} color={chosen.includes(p.name) ? 'primary' : 'default'} variant={chosen.includes(p.name) ? 'filled' : 'outlined'}
                  onClick={() => toggle(p.name)} sx={{ height: 40, fontSize: '0.9rem' }} aria-pressed={chosen.includes(p.name)} />
              ))}
            </Stack>
            <Typography variant="caption" color="text.secondary" sx={{ mt: 2, display: 'block' }}>{t('sim.weather_base', { s: weatherScenario })}</Typography>
          </Panel>
        </Grid>

        {run.error && <ErrorBlock error={run.error} />}
        {res && mine && (
          <>
            <Panel title={t('sim.before_after')}>
              <TableContainer>
                <Table size="small" aria-label={t('sim.before_after')}>
                  <TableHead><TableRow><TableCell /><TableCell align="right">{t('sim.before')}</TableCell><TableCell align="right">{t('sim.after')}</TableCell><TableCell align="right">Δ</TableCell></TableRow></TableHead>
                  <TableBody>
                    {([
                      [t('sim.m_requirement'), res.base.total_demand_litres, mine.total_demand_litres],
                      [t('sim.m_available'), res.base.available_litres, mine.available_litres],
                      [t('sim.m_allocated'), res.base.total_allocated_litres, mine.total_allocated_litres],
                      [t('sim.m_deficit'), res.base.deficit_litres, mine.deficit_litres],
                    ] as [string, number, number][]).map(([label, a, b]) => (
                      <TableRow key={label}><TableCell>{label}</TableCell><TableCell align="right">{fmtVolume(a, lang)}</TableCell><TableCell align="right">{fmtVolume(b, lang)}</TableCell>
                        <TableCell align="right" sx={{ color: b === a ? 'text.secondary' : 'text.primary' }}>{b === a ? '—' : `${b > a ? '+' : '−'}${fmtVolume(Math.abs(b - a), lang)}`}</TableCell></TableRow>
                    ))}
                    <TableRow><TableCell>{t('sim.m_rain')}</TableCell><TableCell align="right">{res.base.rainfall_contribution_mm} mm</TableCell><TableCell align="right">{mine.rainfall_contribution_mm} mm</TableCell><TableCell /></TableRow>
                    <TableRow><TableCell>{t('sim.m_risk')}</TableCell>
                      <TableCell align="right">{res.base.at_risk_fields.join(', ') || '—'}</TableCell><TableCell align="right">{mine.at_risk_fields.join(', ') || '—'}</TableCell><TableCell /></TableRow>
                    {Object.keys(mine.actions).map((f) => (
                      <TableRow key={f}><TableCell>{f}</TableCell><TableCell align="right"><ActionChip action={res.base.actions[f]} size="small" /></TableCell><TableCell align="right"><ActionChip action={mine.actions[f]} size="small" /></TableCell>
                        <TableCell align="right">{res.base.actions[f] !== mine.actions[f] ? <Chip size="small" color="warning" label={t('planner.changed')} /> : '—'}</TableCell></TableRow>
                    ))}
                  </TableBody>
                </Table>
              </TableContainer>
            </Panel>
            <Panel title={t('sim.compare')}>
              <ScenarioBars rows={[res.base, ...res.scenarios].map((s) => ({ name: s.name === 'normal' ? t('sim.before') : (t(`preset.${s.name}`) === `preset.${s.name}` ? s.title : t(`preset.${s.name}`)), demand: s.total_demand_litres, allocated: s.total_allocated_litres, deficit: s.deficit_litres }))} />
              <Stack spacing={1} sx={{ mt: 1 }}>
                {res.scenarios.filter((s) => s.name !== 'custom').map((s) => (
                  <Typography key={s.name} variant="body2"><b>{s.title}:</b> {s.description} {s.at_risk_fields.length > 0 && <Chip size="small" color="error" variant="outlined" label={`${t('sim.m_risk')}: ${s.at_risk_fields.length}`} />}</Typography>
                ))}
              </Stack>
            </Panel>
            <Alert severity="info">{res.disclaimer}</Alert>
          </>
        )}
      </Stack>
    </>
  )
}

export default function Simulator() {
  return <FarmGate>{(farm) => <SimulatorBody farm={farm} />}</FarmGate>
}
