import {
  Alert,
  Chip,
} from '@mui/material'
import { Stack, Typography } from '../components/mui'
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { CHART_COLORS } from '../app/theme'
import { ErrorBlock, Grid, Loading, PageHeader, Panel, StatTile } from '../components/common'
import { useFarms, useImpact } from '../hooks/useApi'
import { fmtVolume, useT } from '../i18n'

const KIND_COLOR = { estimated_potential: 'warning', simulated: 'info', measured: 'default' } as const

export default function Impact() {
  const { t, lang } = useT()
  const impact = useImpact()
  const farms = useFarms()
  if (impact.isLoading) return <Loading rows={4} />
  if (impact.error) return <ErrorBlock error={impact.error} onRetry={() => impact.refetch()} />
  const s = impact.data!
  const names = new Map((farms.data ?? []).map((f) => [f.id, f.farm_name]))
  const chart = s.by_farm.map((f) => ({
    name: (names.get(f.farm_id) ?? f.farm_id).slice(0, 22),
    baseline: Math.round(f.baseline_litres / 100) / 10, need: Math.round(f.need_litres / 100) / 10, allocated: Math.round(f.allocated_litres / 100) / 10,
  }))
  return (
    <>
      <PageHeader title={t('impact.title')} subtitle={t('impact.subtitle')} />
      <Stack spacing={2.5}>
        <Grid cols={{ xs: 2, md: 4 }}>
          <StatTile label={t('impact.decisions')} value={s.decisions_generated} />
          <StatTile label={t('impact.fields')} value={s.fields_supported} hint={`${s.farms} ${t('impact.farms')}`} />
          <StatTile label={t('impact.scenarios')} value={s.scenarios_evaluated} />
          <StatTile label={t('impact.deficit')} value={fmtVolume(s.latest_water_deficit_litres, lang)} color={s.latest_water_deficit_litres > 0 ? '#c62828' : undefined} hint={t('impact.latest')} />
        </Grid>
        <Grid cols={{ xs: 1, md: 3 }}>
          <StatTile label={t('impact.total_demand')} value={fmtVolume(s.latest_total_demand_litres, lang)} hint={t('impact.latest')} color="#ef9a1a" />
          <StatTile label={t('impact.total_alloc')} value={fmtVolume(s.latest_total_allocation_litres, lang)} hint={t('impact.latest')} color="#2e7d32" />
          <StatTile label={t('impact.cum_demand')} value={fmtVolume(s.cumulative_demand_litres, lang)} hint={`${t('impact.cum_alloc')}: ${fmtVolume(s.cumulative_allocated_litres, lang)}`} />
        </Grid>

        <Panel title={t('impact.savings')}>
          <Alert severity="warning" sx={{ mb: 2 }}>{t('impact.honesty')}</Alert>
          <Stack spacing={1.5}>
            {s.savings.map((b) => (
              <Stack key={b.kind} direction={{ xs: 'column', sm: 'row' }} justifyContent="space-between" spacing={1} sx={{ p: 1.5, border: 1, borderColor: 'divider', borderRadius: 2 }}>
                <div>
                  <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
                    <Chip size="small" color={KIND_COLOR[b.kind]} label={t(`impact.kind.${b.kind}`)} />
                    <Typography fontWeight={600}>{b.label}</Typography>
                  </Stack>
                  <Typography variant="body2" color="text.secondary">{b.note}</Typography>
                </div>
                <Typography variant="h6" sx={{ whiteSpace: 'nowrap' }}>{b.kind === 'measured' && b.litres === 0 ? t('impact.not_measured') : fmtVolume(b.litres, lang)}</Typography>
              </Stack>
            ))}
            {s.additional_need_vs_baseline_litres > 0 && (
              <Typography variant="body2" color="text.secondary">{t('impact.extra', { v: fmtVolume(s.additional_need_vs_baseline_litres, lang) })}</Typography>
            )}
          </Stack>
        </Panel>

        <Panel title={t('impact.baseline')}>
          <Typography variant="body2" sx={{ mb: 2 }}>{s.baseline_definition}</Typography>
          {chart.length > 0 ? (
            <div role="img" aria-label={t('impact.chart_aria')} style={{ height: 280 }}>
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={chart} margin={{ top: 8, right: 8, left: -8, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="name" tick={{ fontSize: 12 }} /><YAxis unit=" m³" width={64} tick={{ fontSize: 12 }} /><Tooltip formatter={(v) => `${v} m³`} /><Legend />
                  <Bar dataKey="baseline" name={t('impact.bar_baseline')} fill={CHART_COLORS.baseline} isAnimationActive={false} />
                  <Bar dataKey="need" name={t('impact.bar_need')} fill={CHART_COLORS.demand} isAnimationActive={false} />
                  <Bar dataKey="allocated" name={t('chart.allocated')} fill={CHART_COLORS.allocated} isAnimationActive={false} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          ) : <Typography color="text.secondary">{t('impact.empty')}</Typography>}
        </Panel>
      </Stack>
    </>
  )
}
