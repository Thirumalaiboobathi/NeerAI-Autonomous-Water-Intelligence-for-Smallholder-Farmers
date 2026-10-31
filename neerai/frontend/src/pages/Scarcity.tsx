import {
  Alert,
  AlertTitle,
  Button,
  LinearProgress,
  Slider,
} from '@mui/material'
import { Box, Stack, Typography } from '../components/mui'
import OpacityIcon from '@mui/icons-material/Opacity'
import { useMemo, useState } from 'react'
import { AllocationChart, WaterBudgetChart } from '../components/charts'
import { ErrorBlock, Grid, Loading, PageHeader, Panel, StatTile } from '../components/common'
import { Disclaimer, PriorityControls, RankingTable } from '../components/domain'
import FarmGate from '../components/FarmGate'
import { useDebounced, useOverview, usePlan } from '../hooks/useApi'
import { fmtVolume, useT } from '../i18n'
import type { Farm } from '../types/api'

function ScarcityBody({ farm }: { farm: Farm }) {
  const { t, lang } = useT()
  const ov = useOverview(farm.id)
  const [waterM3, setWaterM3] = useState<number | null>(null)
  const [prio, setPrio] = useState<Record<string, number>>({})
  const req = useMemo(() => ({ farm_id: farm.id, available_water: waterM3, available_water_unit: 'm3' as const, priority_overrides: prio }), [farm.id, waterM3, prio])
  const plan = usePlan(useDebounced(req, 250), 'allocate')
  const dem = ov.data?.result?.allocation.total_demand_litres ?? 0

  if (plan.isLoading || ov.isLoading) return <Loading rows={4} />
  if (plan.error && !plan.data) return <ErrorBlock error={plan.error} onRetry={() => plan.refetch()} />
  const r = plan.data
  if (!r) return null
  const a = r.allocation
  const demand = a.total_demand_litres || dem
  const curM3 = waterM3 ?? a.available_litres / 1000
  const maxM3 = Math.max(50, Math.ceil((demand * 1.4) / 10000) * 10)
  const covered = demand > 0 ? Math.min(100, (a.total_allocated_litres / demand) * 100) : 100
  const critical = a.allocations.filter((x) => x.tier === 'critical')

  return (
    <>
      <PageHeader title={t('scarcity.title')} subtitle={t('scarcity.subtitle')} />
      {a.scarcity_mode ? (
        <Alert severity="warning" icon={<OpacityIcon />} sx={{ mb: 2 }}>
          <AlertTitle>{t('scarcity.mode_on')}</AlertTitle>
          {t('scarcity.banner', { d: fmtVolume(a.deficit_litres, lang) })} {critical.length > 0 && t('scarcity.critical_first', { n: critical.length })}
        </Alert>
      ) : (
        <Alert severity="success" sx={{ mb: 2 }}><AlertTitle>{t('scarcity.mode_off')}</AlertTitle>{t('scarcity.enough')}</Alert>
      )}

      <Stack spacing={2.5}>
        <Panel title={t('scarcity.slider')}>
          <Stack direction="row" spacing={1} sx={{ mb: 1 }} flexWrap="wrap" useFlexGap>
            {[1, 0.75, 0.5, 0.25].map((p) => (
              <Button key={p} size="small" variant="outlined" onClick={() => setWaterM3(Math.round((demand * p) / 100) / 10)}>{Math.round(p * 100)}% {t('scarcity.of_demand')}</Button>
            ))}
            <Button size="small" onClick={() => setWaterM3(null)}>{t('planner.reset_water')}</Button>
          </Stack>
          <Stack direction="row" spacing={2} alignItems="center">
            <Slider value={curM3} min={0} max={maxM3} step={5} onChange={(_, v) => setWaterM3(v as number)} valueLabelDisplay="auto" aria-label={t('scarcity.slider')} sx={{ flexGrow: 1 }} />
            <Typography fontWeight={700} sx={{ minWidth: 90, textAlign: 'right' }}>{curM3.toFixed(0)} m³</Typography>
          </Stack>
          <Box sx={{ mt: 1 }}>
            <Typography variant="caption" color="text.secondary">{t('scarcity.coverage')}: {covered.toFixed(0)}%</Typography>
            <LinearProgress variant="determinate" value={covered} color={covered >= 99 ? 'success' : covered > 50 ? 'warning' : 'error'} sx={{ height: 10, borderRadius: 5 }} />
          </Box>
        </Panel>

        <Grid cols={{ xs: 2, md: 4 }}>
          <StatTile label={t('dash.available')} value={fmtVolume(a.available_litres, lang)} color="#1e88e5" />
          <StatTile label={t('dash.demand')} value={fmtVolume(a.total_demand_litres, lang)} color="#ef9a1a" />
          <StatTile label={t('dash.allocated')} value={fmtVolume(a.total_allocated_litres, lang)} color="#2e7d32" />
          <StatTile label={t('scarcity.unmet')} value={fmtVolume(a.deficit_litres, lang)} color={a.deficit_litres > 0 ? '#c62828' : undefined} />
        </Grid>

        <Grid cols={{ xs: 1, lg: 2 }}>
          <Panel title={t('dash.budget')}><WaterBudgetChart plan={a} /></Panel>
          <Panel title={t('dash.alloc')}><AllocationChart plan={a} /></Panel>
        </Grid>

        <Grid cols={{ xs: 1, lg: 2 }}>
          <Panel title={t('scarcity.ranking')}>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>{t('scarcity.criteria')}</Typography>
            <RankingTable rows={a.allocations} />
          </Panel>
          <Panel title={t('priority.title')}>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>{t('priority.help')}</Typography>
            <PriorityControls fields={ov.data?.fields ?? []} value={prio} onChange={setPrio} />
            {Object.keys(prio).length > 0 && <Button size="small" sx={{ mt: 1.5 }} onClick={() => setPrio({})}>{t('priority.reset')}</Button>}
          </Panel>
        </Grid>
        <Typography variant="caption" color="text.secondary">{a.method}</Typography>
        <Disclaimer />
      </Stack>
    </>
  )
}

export default function Scarcity() {
  return <FarmGate>{(farm) => <ScarcityBody farm={farm} />}</FarmGate>
}
