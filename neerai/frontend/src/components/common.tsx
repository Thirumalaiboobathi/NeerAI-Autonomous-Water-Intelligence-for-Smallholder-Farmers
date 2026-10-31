import {
  Alert,
  AlertTitle,
  Button,
  Card,
  CardContent,
  Chip,
  Skeleton,
} from '@mui/material'
import { Box, Stack, Typography } from './mui'
import type { ReactNode } from 'react'
import { ACTION_COLOR } from '../app/theme'
import { actionKey, useT } from '../i18n'
import type { Action, Confidence, WeatherAssessment } from '../types/api'
import ScienceIcon from '@mui/icons-material/Science'
import AccessTimeIcon from '@mui/icons-material/AccessTime'
import RefreshIcon from '@mui/icons-material/Refresh'

export function ActionChip({ action, size = 'medium' }: { action: Action; size?: 'small' | 'medium' }) {
  const { t } = useT()
  return <Chip size={size} color={ACTION_COLOR[action] ?? 'default'} label={t(actionKey(action))} />
}

export function ConfidenceChip({ level }: { level: Confidence }) {
  const { t } = useT()
  const color = level === 'high' ? 'success' : level === 'medium' ? 'warning' : 'error'
  return <Chip size="small" variant="outlined" color={color} label={`${t('confidence')}: ${t(`confidence.${level}`)}`} />
}

export function SimulatedChip({ simulated }: { simulated: boolean }) {
  const { t } = useT()
  return simulated ? (
    <Chip size="small" icon={<ScienceIcon />} color="warning" variant="outlined" label={t('weather.simulated')} />
  ) : (
    <Chip size="small" color="success" variant="outlined" label={t('weather.live')} />
  )
}

export function Freshness({ weather }: { weather: WeatherAssessment }) {
  const { t, lang } = useT()
  const when = new Date(weather.fetched_at).toLocaleTimeString(lang === 'ta' ? 'ta-IN' : 'en-IN', { hour: '2-digit', minute: '2-digit' })
  return (
    <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
      <SimulatedChip simulated={weather.simulated} />
      <Chip size="small" variant="outlined" icon={<AccessTimeIcon />} label={`${t('updated')} ${when}`} />
    </Stack>
  )
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: string; actions?: ReactNode }) {
  return (
    <Stack direction={{ xs: 'column', sm: 'row' }} justifyContent="space-between" alignItems={{ sm: 'center' }} spacing={1.5} sx={{ mb: 2.5 }}>
      <Box>
        <Typography variant="h4" component="h1" sx={{ fontSize: { xs: '1.5rem', sm: '2rem' } }}>{title}</Typography>
        {subtitle && <Typography color="text.secondary">{subtitle}</Typography>}
      </Box>
      {actions && <Box>{actions}</Box>}
    </Stack>
  )
}

export function Panel({ title, action, children, sx }: { title?: ReactNode; action?: ReactNode; children: ReactNode; sx?: object }) {
  return (
    <Card sx={sx}>
      <CardContent>
        {(title || action) && (
          <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1.5 }} spacing={1}>
            {title && <Typography variant="h6">{title}</Typography>}
            {action}
          </Stack>
        )}
        {children}
      </CardContent>
    </Card>
  )
}

export function StatTile({ label, value, hint, color }: { label: string; value: ReactNode; hint?: string; color?: string }) {
  return (
    <Card sx={{ height: '100%' }}>
      <CardContent>
        <Typography variant="body2" color="text.secondary">{label}</Typography>
        <Typography variant="h5" sx={{ color, mt: 0.5, wordBreak: 'break-word' }}>{value}</Typography>
        {hint && <Typography variant="caption" color="text.secondary">{hint}</Typography>}
      </CardContent>
    </Card>
  )
}

export function Loading({ rows = 3 }: { rows?: number }) {
  return (
    <Stack spacing={1.5} aria-busy="true" aria-label="loading">
      {Array.from({ length: rows }).map((_, i) => <Skeleton key={i} variant="rounded" height={72} />)}
    </Stack>
  )
}

export function ErrorBlock({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const { t } = useT()
  const msg = error instanceof Error ? error.message : String(error)
  return (
    <Alert severity="error" action={onRetry && <Button color="inherit" size="small" startIcon={<RefreshIcon />} onClick={onRetry}>{t('retry')}</Button>}>
      <AlertTitle>{t('error.title')}</AlertTitle>
      {msg}
    </Alert>
  )
}

export function Grid({ cols, children, gap = 2 }: { cols: Record<string, number> | number; children: ReactNode; gap?: number }) {
  const tpl = typeof cols === 'number'
    ? `repeat(${cols}, minmax(0, 1fr))`
    : Object.fromEntries(Object.entries(cols).map(([bp, n]) => [bp, `repeat(${n}, minmax(0, 1fr))`]))
  return <Box sx={{ display: 'grid', gap, gridTemplateColumns: tpl }}>{children}</Box>
}
