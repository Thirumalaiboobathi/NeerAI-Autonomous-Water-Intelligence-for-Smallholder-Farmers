import {
  Alert,
  Button,
  Card,
  CardContent,
  Chip,
  Dialog,
  DialogContent,
  DialogTitle,
} from '@mui/material'
import { Box, Stack, Typography } from '../components/mui'
import AutoAwesomeIcon from '@mui/icons-material/AutoAwesome'
import { Link as RouterLink } from 'react-router-dom'
import { useState } from 'react'
import { useAppState } from '../app/AppState'
import { AllocationChart, WaterBudgetChart } from '../components/charts'
import { ErrorBlock, Grid, Loading, PageHeader, Panel, StatTile } from '../components/common'
import { ActionChip, ActionCard, AgentTimeline, Disclaimer, Metric, WeatherCard } from '../components/domain'
import FarmGate from '../components/FarmGate'
import { useAssess, useExecutions, useOptions, useOverview } from '../hooks/useApi'
import { fmtVolume, refName, stageKey, useT } from '../i18n'
import type { AgentExecution, Farm } from '../types/api'

function DashboardBody({ farm }: { farm: Farm }) {
  const { t, lang } = useT()
  const { weatherScenario } = useAppState()
  const ov = useOverview(farm.id)
  const options = useOptions()
  const execs = useExecutions(farm.id)
  const assess = useAssess()
  const [open, setOpen] = useState<AgentExecution | null>(null)

  if (ov.isLoading) return <Loading rows={4} />
  if (ov.error) return <ErrorBlock error={ov.error} onRetry={() => ov.refetch()} />
  const data = ov.data!
  const r = data.result
  const needs = new Map(r?.crop_water.fields.map((n) => [n.field_id, n]))
  const decisions = new Map(r?.decision.decisions.map((d) => [d.field_id, d]))

  return (
    <>
      <PageHeader
        title={t('dash.title')}
        subtitle={`${farm.farm_name} · ${farm.village || farm.district}`}
        actions={
          <Button variant="contained" size="large" startIcon={<AutoAwesomeIcon />} disabled={assess.isPending}
            onClick={() => assess.mutate({ farm_id: farm.id, query: lang === 'ta' ? 'இன்று நீர்ப்பாசனம் செய்யலாமா?' : 'Should I irrigate today?' }, { onSuccess: (ex) => setOpen(ex) })}>
            {assess.isPending ? t('dash.running') : t('dash.run')}
          </Button>
        }
      />
      {assess.error && <Box sx={{ mb: 2 }}><ErrorBlock error={assess.error} /></Box>}
      {data.notes.map((n, i) => <Alert key={i} severity="info" sx={{ mb: 2 }}>{n}</Alert>)}

      {!r ? (
        <Alert severity="info" action={<Button component={RouterLink} to="/farms" color="inherit">{t('nav.farms')}</Button>}>{t('dash.nofields')}</Alert>
      ) : (
        <Stack spacing={2.5}>
          <ActionCard msg={r.messages[lang]} accent={r.allocation.scarcity_mode ? 'warning.main' : 'primary.main'} />

          <Grid cols={{ xs: 2, md: 4 }}>
            <StatTile label={t('dash.available')} value={fmtVolume(r.allocation.available_litres, lang)} hint={farm.water_is_estimate ? t('dash.estimate') : undefined} color="#1e88e5" />
            <StatTile label={t('dash.demand')} value={fmtVolume(r.allocation.total_demand_litres, lang)} color="#ef9a1a" />
            <StatTile label={t('dash.allocated')} value={fmtVolume(r.allocation.total_allocated_litres, lang)} color="#2e7d32" />
            <StatTile label={t('dash.deficit')} value={fmtVolume(r.allocation.deficit_litres, lang)} color={r.allocation.deficit_litres > 0 ? '#c62828' : undefined}
              hint={r.allocation.scarcity_mode ? t('scarcity.mode_on') : t('dash.no_deficit')} />
          </Grid>

          <Grid cols={{ xs: 1, lg: 2 }}>
            <WeatherCard w={r.weather} />
            <Panel title={t('dash.budget')}>
              <WaterBudgetChart plan={r.allocation} />
            </Panel>
          </Grid>

          <Panel title={t('dash.fields')} action={<Button component={RouterLink} to="/planner">{t('nav.planner')}</Button>}>
            <Grid cols={{ xs: 1, md: 2, xl: 3 }}>
              {data.fields.map((f) => {
                const d = decisions.get(f.id)
                const n = needs.get(f.id)
                return (
                  <Card key={f.id} variant="outlined">
                    <CardContent>
                      <Stack direction="row" justifyContent="space-between" alignItems="flex-start" spacing={1}>
                        <Box>
                          <Typography fontWeight={700}>{f.name}</Typography>
                          <Typography variant="body2" color="text.secondary">
                            {refName(options.data, 'crops', f.crop, lang)} · {t(stageKey(f.stage))} · {f.area_ha.toFixed(2)} ha
                          </Typography>
                        </Box>
                        {d && <ActionChip action={d.action} size="small" />}
                      </Stack>
                      {n && (
                        <Stack direction="row" spacing={3} sx={{ mt: 1.5 }}>
                          <Metric label={t('dash.need')} value={fmtVolume(n.volume_litres, lang)} />
                          <Metric label={t('dash.now')} value={d ? fmtVolume(d.recommended_volume_litres, lang) : '—'} />
                        </Stack>
                      )}
                      {n?.critical_stage && <Chip size="small" color="warning" variant="outlined" label={t('dash.critical')} sx={{ mt: 1 }} />}
                    </CardContent>
                  </Card>
                )
              })}
            </Grid>
          </Panel>

          <Grid cols={{ xs: 1, lg: 2 }}>
            <Panel title={t('dash.alloc')}><AllocationChart plan={r.allocation} /></Panel>
            <Panel title={t('dash.activity')}>
              {execs.isLoading ? <Loading rows={2} /> : (execs.data ?? []).length === 0 ? (
                <Typography color="text.secondary">{t('dash.noactivity')}</Typography>
              ) : (
                <Stack spacing={1}>
                  {execs.data!.slice(0, 5).map((e) => (
                    <Box key={e.id} onClick={() => setOpen(e)} role="button" tabIndex={0} onKeyDown={(k) => k.key === 'Enter' && setOpen(e)}
                      sx={{ p: 1.5, border: 1, borderColor: 'divider', borderRadius: 2, cursor: 'pointer', '&:hover': { bgcolor: 'action.hover' } }}>
                      <Typography variant="body2" fontWeight={600} noWrap>{e.query}</Typography>
                      <Typography variant="caption" color="text.secondary">
                        {new Date(e.created_at).toLocaleString()} · {e.steps.length} {t('timeline.steps')} · {e.duration_ms} ms
                      </Typography>
                    </Box>
                  ))}
                </Stack>
              )}
            </Panel>
          </Grid>
          <Disclaimer />
          <Typography variant="caption" color="text.secondary">{t('dash.scenario_note', { s: weatherScenario })}</Typography>
        </Stack>
      )}

      <Dialog open={!!open} onClose={() => setOpen(null)} fullWidth maxWidth="md" aria-labelledby="trace-title">
        <DialogTitle id="trace-title">{t('timeline.title')}</DialogTitle>
        <DialogContent>
          {open && (
            <Stack spacing={2}>
              <Typography fontWeight={600}>{open.query}</Typography>
              {open.message && <ActionCard msg={open.message} />}
              <AgentTimeline steps={open.steps} durationMs={open.duration_ms} mode={open.mode} />
            </Stack>
          )}
        </DialogContent>
      </Dialog>
    </>
  )
}

export default function Dashboard() {
  return <FarmGate>{(farm) => <DashboardBody farm={farm} />}</FarmGate>
}
