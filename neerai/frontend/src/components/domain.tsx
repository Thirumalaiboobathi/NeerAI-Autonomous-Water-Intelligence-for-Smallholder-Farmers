import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Alert,
  Button,
  Card,
  CardContent,
  Chip,
  Divider,
  IconButton,
  LinearProgress,
  List,
  ListItem,
  ListItemIcon,
  ListItemText,
  ToggleButton,
  ToggleButtonGroup,
  Tooltip,
} from '@mui/material'
import { Box, Stack, Typography } from './mui'
import AirIcon from '@mui/icons-material/Air'
import BuildIcon from '@mui/icons-material/Build'
import CheckCircleIcon from '@mui/icons-material/CheckCircle'
import ErrorIcon from '@mui/icons-material/Error'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import SmartToyIcon from '@mui/icons-material/SmartToy'
import ThermostatIcon from '@mui/icons-material/Thermostat'
import UndoIcon from '@mui/icons-material/Undo'
import VolumeUpIcon from '@mui/icons-material/VolumeUp'
import WarningAmberIcon from '@mui/icons-material/WarningAmber'
import WaterDropIcon from '@mui/icons-material/WaterDrop'
import { useState } from 'react'
import { fmtVolume, stageKey, useT } from '../i18n'
import type { FarmerMessage, FieldAllocation, FieldRec, IrrigationDecision, TraceStep, WeatherAssessment } from '../types/api'
import { ActionChip, ConfidenceChip, Freshness, Grid } from './common'
import { RainTempChart } from './charts'

export function WhyThisDecision({ d }: { d: IrrigationDecision }) {
  const { t } = useT()
  const Block = ({ title, items }: { title: string; items: string[] }) => (
    <Box>
      <Typography variant="subtitle2" color="primary.dark" sx={{ mb: 0.5 }}>{title}</Typography>
      <Box component="ul" sx={{ m: 0, pl: 2.5 }}>
        {items.map((x, i) => <li key={i}><Typography variant="body2">{x}</Typography></li>)}
      </Box>
    </Box>
  )
  return (
    <Accordion disableGutters variant="outlined" sx={{ '&:before': { display: 'none' } }}>
      <AccordionSummary expandIcon={<ExpandMoreIcon />} aria-label={`${t('why.title')} ${d.field_name}`}>
        <Typography fontWeight={600}>{t('why.title')}</Typography>
      </AccordionSummary>
      <AccordionDetails>
        <Stack spacing={1.5}>
          <Block title={t('why.reasoning')} items={d.reasoning} />
          <Block title={t('why.weather')} items={d.weather_considerations} />
          <Block title={t('why.stage')} items={d.crop_stage_considerations} />
          <Block title={t('why.assumptions')} items={d.assumptions} />
          <Block title={t('why.change')} items={d.would_change_if} />
          <Alert severity="info" sx={{ py: 0 }}>{t('why.note')}</Alert>
        </Stack>
      </AccordionDetails>
    </Accordion>
  )
}

export function DecisionCard({ d, stage, area }: { d: IrrigationDecision; stage?: string; area?: number }) {
  const { t, lang } = useT()
  return (
    <Card>
      <CardContent>
        <Stack spacing={1.5}>
          <Stack direction="row" justifyContent="space-between" alignItems="flex-start" spacing={1} flexWrap="wrap" useFlexGap>
            <Box>
              <Typography variant="h6">{d.field_name}</Typography>
              <Typography variant="body2" color="text.secondary">
                {[stage && t(stageKey(stage as never)), area ? `${area.toFixed(2)} ha` : null].filter(Boolean).join(' · ')}
              </Typography>
            </Box>
            <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
              <ActionChip action={d.action} />
              <ConfidenceChip level={d.confidence} />
            </Stack>
          </Stack>
          <Grid cols={{ xs: 2, sm: 3 }} gap={1.5}>
            <Metric label={t('planner.volume')} value={d.recommended_volume_litres > 0 ? fmtVolume(d.recommended_volume_litres, lang) : '—'} />
            <Metric label={t('planner.depth')} value={d.recommended_depth_mm > 0 ? `${d.recommended_depth_mm.toFixed(0)} mm` : '—'} />
            <Box sx={{ gridColumn: { xs: 'span 2', sm: 'span 1' } }}><Metric label={t('planner.timing')} value={d.timing} small /></Box>
          </Grid>
          <WhyThisDecision d={d} />
        </Stack>
      </CardContent>
    </Card>
  )
}

export function Metric({ label, value, small }: { label: string; value: string; small?: boolean }) {
  return (
    <Box>
      <Typography variant="caption" color="text.secondary">{label}</Typography>
      <Typography variant={small ? 'body2' : 'subtitle1'} fontWeight={600}>{value}</Typography>
    </Box>
  )
}

/** Tamil/English action card: large text, optional text-to-speech (never required). */
export function ActionCard({ msg, accent = 'primary.main' }: { msg: FarmerMessage; accent?: string }) {
  const { t } = useT()
  const [speaking, setSpeaking] = useState(false)
  const canSpeak = typeof window !== 'undefined' && 'speechSynthesis' in window
  const speak = () => {
    if (!canSpeak) return
    window.speechSynthesis.cancel()
    const u = new SpeechSynthesisUtterance(msg.voice_text)
    u.lang = msg.language === 'ta' ? 'ta-IN' : 'en-IN'
    u.onend = () => setSpeaking(false)
    u.onerror = () => setSpeaking(false)
    setSpeaking(true)
    window.speechSynthesis.speak(u)
  }
  return (
    <Card sx={{ borderLeft: 6, borderLeftColor: accent, bgcolor: '#fbfaf5' }} aria-label={t('action.card')}>
      <CardContent>
        <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1 }}>
          <Chip size="small" color="primary" label={msg.language === 'ta' ? 'தமிழ்' : 'English'} />
          {canSpeak && (
            <Tooltip title={t('action.listen')}>
              <IconButton onClick={speak} aria-label={t('action.listen')} color={speaking ? 'secondary' : 'default'}><VolumeUpIcon /></IconButton>
            </Tooltip>
          )}
        </Stack>
        <Typography variant="h6" sx={{ fontSize: { xs: '1.1rem', sm: '1.25rem' }, lineHeight: 1.5 }}>{msg.headline}</Typography>
        <List dense disablePadding sx={{ mt: 1 }}>
          {msg.steps.map((s, i) => (
            <ListItem key={i} alignItems="flex-start" disableGutters>
              <ListItemIcon sx={{ minWidth: 30, mt: 0.5, color: 'primary.main' }}><Typography fontWeight={700}>{i + 1}.</Typography></ListItemIcon>
              <ListItemText primary={s} slotProps={{ primary: { sx: { fontSize: '1rem', lineHeight: 1.6 } } }} />
            </ListItem>
          ))}
        </List>
      </CardContent>
    </Card>
  )
}

export function WeatherCard({ w }: { w: WeatherAssessment }) {
  const { t } = useT()
  const heat = w.heat_risk
  return (
    <Card>
      <CardContent>
        <Stack direction="row" justifyContent="space-between" alignItems="center" flexWrap="wrap" useFlexGap spacing={1} sx={{ mb: 1 }}>
          <Typography variant="h6">{t('weather.title')}</Typography>
          <Freshness weather={w} />
        </Stack>
        <Grid cols={{ xs: 2, sm: 4 }} gap={1.5}>
          <Metric label={t('weather.rain48')} value={`${w.rain_probability_48h_pct.toFixed(0)} %`} />
          <Metric label={t('weather.expected')} value={`${w.expected_rain_48h_mm.toFixed(1)} mm`} />
          <Metric label={t('weather.tmax')} value={`${w.max_temp_c.toFixed(0)} °C`} />
          <Metric label={t('weather.confidence')} value={t(`confidence.${w.forecast_confidence}`)} />
        </Grid>
        <Stack direction="row" spacing={1} sx={{ my: 1 }} flexWrap="wrap" useFlexGap>
          <Chip size="small" icon={<ThermostatIcon />} color={heat === 'none' ? 'default' : heat === 'moderate' ? 'warning' : 'error'} label={`${t('weather.heat')}: ${t(`heat.${heat}`)}`} />
          <Chip size="small" icon={<AirIcon />} variant="outlined" label={`ET₀ ${w.avg_et0_mm_day.toFixed(1)} mm/${t('day')}`} />
        </Stack>
        <RainTempChart daily={w.daily} />
        <Typography variant="caption" color="text.secondary" display="block">{t('weather.source')}: {w.source}</Typography>
        {w.notes.map((n, i) => (
          <Typography key={i} variant="caption" color="text.secondary" display="block"><WarningAmberIcon sx={{ fontSize: 14, mr: 0.5, verticalAlign: 'text-bottom' }} />{n}</Typography>
        ))}
      </CardContent>
    </Card>
  )
}

const KIND_ICON = { agent: <SmartToyIcon fontSize="small" />, tool: <BuildIcon fontSize="small" />, fallback: <UndoIcon fontSize="small" />, validation: <CheckCircleIcon fontSize="small" /> }

export function AgentTimeline({ steps, durationMs, mode }: { steps: TraceStep[]; durationMs?: number; mode?: string }) {
  const { t } = useT()
  return (
    <Box>
      <Stack direction="row" spacing={1} sx={{ mb: 1 }} flexWrap="wrap" useFlexGap>
        <Chip size="small" label={`${steps.length} ${t('timeline.steps')}`} />
        {durationMs !== undefined && <Chip size="small" variant="outlined" label={`${durationMs} ms`} />}
        {mode && <Chip size="small" variant="outlined" color={mode === 'bedrock' ? 'success' : 'warning'} label={mode === 'bedrock' ? 'Amazon Bedrock' : t('timeline.demo')} />}
      </Stack>
      <List dense disablePadding aria-label={t('timeline.title')}>
        {steps.map((s, i) => (
          <Box key={s.seq}>
            {i > 0 && <Divider component="li" />}
            <ListItem alignItems="flex-start" sx={{ pl: s.kind === 'agent' ? 0 : 3, bgcolor: s.kind === 'agent' ? 'rgba(46,125,50,0.06)' : 'transparent', borderRadius: 1 }}>
              <ListItemIcon sx={{ minWidth: 34, mt: 0.5, color: s.status === 'ok' ? 'success.main' : s.status === 'fallback' ? 'warning.main' : 'error.main' }}>
                {s.status === 'error' ? <ErrorIcon fontSize="small" /> : KIND_ICON[s.kind]}
              </ListItemIcon>
              <ListItemText
                primary={
                  <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
                    <Typography variant="body2" fontWeight={600}>{s.kind === 'agent' ? s.tool?.replace('_specialist', '').replaceAll('_', ' ') + ' →' : s.tool ?? s.agent}</Typography>
                    <Chip size="small" variant="outlined" label={s.agent} />
                    <Chip size="small" color={s.status === 'ok' ? 'success' : s.status === 'fallback' ? 'warning' : 'error'} label={t(`status.${s.status}`)} sx={{ height: 20 }} />
                    <Typography variant="caption" color="text.secondary">{s.duration_ms} ms · {new Date(s.started_at).toLocaleTimeString()}</Typography>
                  </Stack>
                }
                secondary={s.summary}
                slotProps={{ secondary: { sx: { wordBreak: 'break-word' } } }}
              />
            </ListItem>
          </Box>
        ))}
      </List>
    </Box>
  )
}

/** Low / Normal / High priority per field (maps to multipliers 0.5 / 1 / 2). */
export function PriorityControls({ fields, value, onChange }: { fields: Pick<FieldRec, 'id' | 'name'>[]; value: Record<string, number>; onChange: (v: Record<string, number>) => void }) {
  const { t } = useT()
  return (
    <Stack spacing={1.5}>
      {fields.map((f) => {
        const cur = value[f.id] ?? 1
        const sel = cur >= 1.5 ? 'high' : cur <= 0.5 ? 'low' : 'normal'
        return (
          <Stack key={f.id} direction={{ xs: 'column', sm: 'row' }} justifyContent="space-between" alignItems={{ sm: 'center' }} spacing={1}>
            <Typography variant="body2" fontWeight={600}>{f.name}</Typography>
            <ToggleButtonGroup exclusive size="small" value={sel} aria-label={`${t('priority.title')} ${f.name}`}
              onChange={(_, v) => {
                if (!v) return
                const m = v === 'high' ? 2 : v === 'low' ? 0.5 : 1
                const next = { ...value }
                if (m === 1) delete next[f.id]
                else next[f.id] = m
                onChange(next)
              }}>
              <ToggleButton value="low" sx={{ minWidth: 80 }}>{t('priority.low')}</ToggleButton>
              <ToggleButton value="normal" sx={{ minWidth: 80 }}>{t('priority.normal')}</ToggleButton>
              <ToggleButton value="high" sx={{ minWidth: 80 }}>{t('priority.high')}</ToggleButton>
            </ToggleButtonGroup>
          </Stack>
        )
      })}
    </Stack>
  )
}

export function RankingTable({ rows }: { rows: FieldAllocation[] }) {
  const { t, lang } = useT()
  return (
    <Stack spacing={1.5}>
      {rows.map((a) => (
        <Card key={a.field_id} variant="outlined">
          <CardContent sx={{ py: 1.5, '&:last-child': { pb: 1.5 } }}>
            <Stack direction="row" justifyContent="space-between" alignItems="center" spacing={1} flexWrap="wrap" useFlexGap>
              <Stack direction="row" spacing={1.5} alignItems="center">
                <Chip label={a.rank > 0 ? `#${a.rank}` : '—'} color={a.rank === 1 ? 'primary' : 'default'} />
                <Box>
                  <Typography fontWeight={700}>{a.name}</Typography>
                  <Typography variant="caption" color="text.secondary">{t(`tier.${a.tier}`)} · {t('scarcity.score')} {a.score.toFixed(2)}</Typography>
                </Box>
              </Stack>
              <Typography fontWeight={600}>{fmtVolume(a.allocated_litres, lang)} / {fmtVolume(a.demand_litres, lang)}</Typography>
            </Stack>
            <LinearProgress variant="determinate" value={Math.min(100, a.fraction_met * 100)} color={a.fraction_met >= 0.99 ? 'success' : a.fraction_met > 0 ? 'warning' : 'error'} sx={{ my: 1, height: 8, borderRadius: 4 }} />
            {a.unmet_litres > 0 && <Typography variant="body2" color="error">{t('scarcity.unmet')}: {fmtVolume(a.unmet_litres, lang)}</Typography>}
            {a.rationale.map((r, i) => <Typography key={i} variant="caption" display="block" color="text.secondary">• {r}</Typography>)}
          </CardContent>
        </Card>
      ))}
    </Stack>
  )
}

export function Disclaimer() {
  const { t } = useT()
  return <Alert icon={<WaterDropIcon />} severity="info" sx={{ mt: 2 }}>{t('disclaimer.decision_support')}</Alert>
}

export function ReloadButton({ onClick, label }: { onClick: () => void; label: string }) {
  return <Button onClick={onClick}>{label}</Button>
}

export { ActionChip, ConfidenceChip } from './common'
