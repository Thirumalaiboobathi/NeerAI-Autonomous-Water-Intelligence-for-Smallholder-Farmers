import {
  Alert,
  Button,
  Chip,
  Slider,
  Snackbar,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
} from '@mui/material'
import { Box, Stack, Typography } from '../components/mui'
import DownloadIcon from '@mui/icons-material/Download'
import PushPinIcon from '@mui/icons-material/PushPin'
import SaveIcon from '@mui/icons-material/Save'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { useAppState } from '../app/AppState'
import { AllocationChart } from '../components/charts'
import { ErrorBlock, Grid, Loading, PageHeader, Panel, StatTile } from '../components/common'
import { ActionChip, DecisionCard, Disclaimer, PriorityControls } from '../components/domain'
import FarmGate from '../components/FarmGate'
import { useDebounced, useOverview, usePlan } from '../hooks/useApi'
import { fmtVolume, useT } from '../i18n'
import { downloadText } from '../lib/download'
import { api } from '../services/api'
import type { Farm, PlanResult } from '../types/api'

function Compare({ base, cur }: { base: PlanResult; cur: PlanResult }) {
  const { t, lang } = useT()
  const rows: [string, number, number][] = [
    [t('dash.available'), base.allocation.available_litres, cur.allocation.available_litres],
    [t('dash.demand'), base.allocation.total_demand_litres, cur.allocation.total_demand_litres],
    [t('dash.allocated'), base.allocation.total_allocated_litres, cur.allocation.total_allocated_litres],
    [t('dash.deficit'), base.allocation.deficit_litres, cur.allocation.deficit_litres],
  ]
  const baseByField = new Map(base.decision.decisions.map((d) => [d.field_id, d]))
  return (
    <Panel title={t('planner.compare')}>
      <TableContainer>
        <Table size="small" aria-label={t('planner.compare')}>
          <TableHead><TableRow><TableCell /><TableCell align="right">{t('planner.pinned')}</TableCell><TableCell align="right">{t('planner.current')}</TableCell><TableCell align="right">Δ</TableCell></TableRow></TableHead>
          <TableBody>
            {rows.map(([k, a, b]) => (
              <TableRow key={k}><TableCell>{k}</TableCell><TableCell align="right">{fmtVolume(a, lang)}</TableCell><TableCell align="right">{fmtVolume(b, lang)}</TableCell>
                <TableCell align="right" sx={{ color: b - a === 0 ? 'text.secondary' : b > a ? 'success.main' : 'error.main' }}>{b - a === 0 ? '—' : `${b > a ? '+' : '−'}${fmtVolume(Math.abs(b - a), lang)}`}</TableCell></TableRow>
            ))}
            {cur.decision.decisions.map((d) => {
              const o = baseByField.get(d.field_id)
              return (
                <TableRow key={d.field_id}><TableCell>{d.field_name}</TableCell>
                  <TableCell align="right">{o ? <ActionChip action={o.action} size="small" /> : '—'}</TableCell>
                  <TableCell align="right"><ActionChip action={d.action} size="small" /></TableCell>
                  <TableCell align="right">{o && o.action !== d.action ? <Chip size="small" color="warning" label={t('planner.changed')} /> : '—'}</TableCell></TableRow>
              )
            })}
          </TableBody>
        </Table>
      </TableContainer>
    </Panel>
  )
}

function PlannerBody({ farm }: { farm: Farm }) {
  const { t, lang } = useT()
  const { weatherScenario } = useAppState()
  const qc = useQueryClient()
  const ov = useOverview(farm.id)
  const [waterM3, setWaterM3] = useState<number | null>(null)
  const [prio, setPrio] = useState<Record<string, number>>({})
  const [pinned, setPinned] = useState<PlanResult | null>(null)
  const [toast, setToast] = useState('')

  const req = useMemo(() => ({ farm_id: farm.id, available_water: waterM3, available_water_unit: 'm3' as const, priority_overrides: prio }), [farm.id, waterM3, prio])
  const debounced = useDebounced(req, 300)
  const plan = usePlan(debounced)
  const saved = useQuery({ queryKey: ['plans', farm.id], queryFn: () => api.plans(farm.id) })
  const save = useMutation({
    mutationFn: () => api.plan({ ...req, weather_scenario: weatherScenario, save: true, label: `${new Date().toLocaleString()}` }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['plans'] }); setToast(t('planner.saved')) },
  })
  const exportReport = useMutation({
    mutationFn: () => api.report({ ...req, weather_scenario: weatherScenario }),
    onSuccess: (md) => downloadText(`neerai-plan-${farm.farm_name.replace(/\W+/g, '-')}.md`, md),
  })

  if (plan.isLoading || ov.isLoading) return <Loading rows={4} />
  if (plan.error && !plan.data) return <ErrorBlock error={plan.error} onRetry={() => plan.refetch()} />
  const r = plan.data
  if (!r) return null
  const fields = ov.data?.fields ?? []
  const byId = new Map(fields.map((f) => [f.id, f]))
  const needs = new Map(r.crop_water.fields.map((n) => [n.field_id, n]))
  const allocs = new Map(r.allocation.allocations.map((a) => [a.field_id, a]))
  const curM3 = waterM3 ?? r.allocation.available_litres / 1000
  const maxM3 = Math.max(50, Math.ceil((Math.max(r.allocation.total_demand_litres, r.allocation.available_litres) * 1.5) / 10000) * 10)

  return (
    <>
      <PageHeader title={t('planner.title')} subtitle={t('planner.subtitle')}
        actions={
          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
            <Button startIcon={<PushPinIcon />} variant="outlined" onClick={() => setPinned(r)}>{t('planner.pin')}</Button>
            <Button startIcon={<SaveIcon />} variant="outlined" onClick={() => save.mutate()} disabled={save.isPending}>{t('planner.save')}</Button>
            <Button startIcon={<DownloadIcon />} variant="contained" onClick={() => exportReport.mutate()} disabled={exportReport.isPending}>{t('planner.export')}</Button>
          </Stack>
        } />
      {r.allocation.scarcity_mode && <Alert severity="warning" sx={{ mb: 2 }}>{t('scarcity.banner', { d: fmtVolume(r.allocation.deficit_litres, lang) })}</Alert>}
      {(save.error || exportReport.error) && <ErrorBlock error={save.error ?? exportReport.error} />}

      <Stack spacing={2.5}>
        <Grid cols={{ xs: 1, lg: 2 }}>
          <Panel title={t('planner.water')}>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
              {r.water_input_source === 'farmer-adjusted value' ? t('planner.src_adjusted') : t('planner.src_profile')}
            </Typography>
            <Stack direction="row" spacing={2} alignItems="center">
              <Slider value={curM3} min={0} max={maxM3} step={5} onChange={(_, v) => setWaterM3(v as number)} aria-label={t('planner.water')} valueLabelDisplay="auto" sx={{ flexGrow: 1 }} />
              <TextField size="small" type="number" value={Math.round(curM3 * 10) / 10} onChange={(e) => setWaterM3(Math.max(0, Number(e.target.value)))}
                slotProps={{ htmlInput: { min: 0, 'aria-label': t('planner.water_input') }, input: { endAdornment: <Typography variant="body2">m³</Typography> } }} sx={{ width: 150 }} />
            </Stack>
            {waterM3 !== null && <Button size="small" sx={{ mt: 1 }} onClick={() => setWaterM3(null)}>{t('planner.reset_water')}</Button>}
            <Box sx={{ mt: 2 }}>
              <Typography variant="subtitle2" sx={{ mb: 1 }}>{t('priority.title')}</Typography>
              <PriorityControls fields={fields} value={prio} onChange={setPrio} />
            </Box>
          </Panel>
          <Panel title={t('dash.alloc')}><AllocationChart plan={r.allocation} /></Panel>
        </Grid>

        <Grid cols={{ xs: 2, md: 4 }}>
          <StatTile label={t('dash.available')} value={fmtVolume(r.allocation.available_litres, lang)} color="#1e88e5" />
          <StatTile label={t('dash.demand')} value={fmtVolume(r.allocation.total_demand_litres, lang)} color="#ef9a1a" />
          <StatTile label={t('dash.allocated')} value={fmtVolume(r.allocation.total_allocated_litres, lang)} color="#2e7d32" />
          <StatTile label={t('dash.deficit')} value={fmtVolume(r.allocation.deficit_litres, lang)} color={r.allocation.deficit_litres > 0 ? '#c62828' : undefined} />
        </Grid>

        <Panel title={t('planner.table')}>
          <TableContainer>
            <Table size="small" aria-label={t('planner.table')}>
              <TableHead>
                <TableRow>
                  <TableCell>{t('field')}</TableCell><TableCell>{t('planner.action')}</TableCell><TableCell align="right">{t('planner.depth')}</TableCell>
                  <TableCell align="right">{t('planner.volume')}</TableCell><TableCell align="right">{t('planner.demand')}</TableCell><TableCell align="right">{t('planner.deficit')}</TableCell>
                  <TableCell>{t('planner.timing')}</TableCell><TableCell>{t('planner.priority')}</TableCell><TableCell>{t('planner.weather_impact')}</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {r.decision.decisions.map((d) => {
                  const n = needs.get(d.field_id)
                  const a = allocs.get(d.field_id)
                  return (
                    <TableRow key={d.field_id} hover>
                      <TableCell sx={{ fontWeight: 600 }}>{byId.get(d.field_id)?.name ?? d.field_name}</TableCell>
                      <TableCell><ActionChip action={d.action} size="small" /></TableCell>
                      <TableCell align="right">{d.recommended_depth_mm > 0 ? `${d.recommended_depth_mm.toFixed(0)} mm` : '—'}</TableCell>
                      <TableCell align="right">{d.recommended_volume_litres > 0 ? fmtVolume(d.recommended_volume_litres, lang) : '—'}</TableCell>
                      <TableCell align="right">{n ? fmtVolume(n.volume_litres, lang) : '—'}</TableCell>
                      <TableCell align="right" sx={{ color: (a?.unmet_litres ?? 0) > 0 ? 'error.main' : undefined }}>{a && a.unmet_litres > 0 ? fmtVolume(a.unmet_litres, lang) : '—'}</TableCell>
                      <TableCell sx={{ minWidth: 200 }}>{d.timing}</TableCell>
                      <TableCell>{a && a.rank > 0 ? `#${a.rank} · ${t(`tier.${a.tier}`)}` : t('tier.deferred')}</TableCell>
                      <TableCell>{n ? (n.defer_for_rain ? t('planner.rain_defers') : n.rain_covers ? t('planner.rain_covers') : `${n.effective_rain_mm.toFixed(1)} mm ${t('planner.useful_rain')}`) : '—'}</TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
          </TableContainer>
        </Panel>

        {pinned && <Compare base={pinned} cur={r} />}

        <Typography variant="h6">{t('planner.why')}</Typography>
        <Grid cols={{ xs: 1, lg: 2 }}>
          {r.decision.decisions.map((d) => <DecisionCard key={d.field_id} d={d} stage={needs.get(d.field_id)?.stage} area={needs.get(d.field_id)?.area_ha} />)}
        </Grid>

        <Panel title={t('planner.saved_plans')}>
          {(saved.data ?? []).length === 0 ? <Typography color="text.secondary">{t('planner.no_saved')}</Typography> : (
            <Stack spacing={1}>
              {saved.data!.map((p) => (
                <Stack key={p.id} direction="row" justifyContent="space-between" alignItems="center" spacing={1} flexWrap="wrap" useFlexGap sx={{ p: 1, border: 1, borderColor: 'divider', borderRadius: 2 }}>
                  <Box>
                    <Typography variant="body2" fontWeight={600}>{p.label}</Typography>
                    <Typography variant="caption" color="text.secondary">{fmtVolume(p.total_allocated_litres, lang)} / {fmtVolume(p.available_litres, lang)} · {p.weather_simulated ? t('weather.simulated') : t('weather.live')}</Typography>
                  </Box>
                  <Button size="small" startIcon={<DownloadIcon />} onClick={async () => downloadText(`neerai-plan-${p.id}.md`, await api.planReport(p.id))}>{t('planner.export')}</Button>
                </Stack>
              ))}
            </Stack>
          )}
        </Panel>
        <Disclaimer />
      </Stack>
      <Snackbar open={!!toast} autoHideDuration={3000} onClose={() => setToast('')} message={toast} />
    </>
  )
}

export default function Planner() {
  return <FarmGate>{(farm) => <PlannerBody farm={farm} />}</FarmGate>
}
