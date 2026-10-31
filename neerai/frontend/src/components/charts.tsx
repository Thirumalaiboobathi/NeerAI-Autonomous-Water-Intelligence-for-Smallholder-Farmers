import { Box, Typography } from './mui'
import { Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { CHART_COLORS } from '../app/theme'
import { fmtVolume, useT } from '../i18n'
import type { DailyWeather, WaterAllocationPlan } from '../types/api'

const m3 = (l: number) => Math.round(l / 100) / 10

/** Available vs demand vs allocated vs deficit for the whole farm. */
export function WaterBudgetChart({ plan }: { plan: WaterAllocationPlan }) {
  const { t, lang } = useT()
  const data = [
    { name: t('chart.available'), v: m3(plan.available_litres), fill: CHART_COLORS.available },
    { name: t('chart.demand'), v: m3(plan.total_demand_litres), fill: CHART_COLORS.demand },
    { name: t('chart.allocated'), v: m3(plan.total_allocated_litres), fill: CHART_COLORS.allocated },
    { name: t('chart.deficit'), v: m3(plan.deficit_litres), fill: CHART_COLORS.unmet },
  ]
  return (
    <Box role="img" aria-label={t('chart.budget.aria', { available: fmtVolume(plan.available_litres, lang), demand: fmtVolume(plan.total_demand_litres, lang) })}
      sx={{ height: 260 }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 8, right: 8, left: -8, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="name" tick={{ fontSize: 12 }} interval={0} />
          <YAxis tick={{ fontSize: 12 }} unit=" m³" width={64} />
          <Tooltip formatter={(v) => [`${v} m³`, '']} />
          <Bar dataKey="v" radius={[6, 6, 0, 0]} isAnimationActive={false}>
            {data.map((d) => <Cell key={d.name} fill={d.fill} />)}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </Box>
  )
}

/** Per-field demand vs allocated vs unmet. */
export function AllocationChart({ plan, height = 280 }: { plan: WaterAllocationPlan; height?: number }) {
  const { t } = useT()
  const data = plan.allocations.map((a) => ({
    name: a.name.split(' (')[0],
    allocated: m3(a.allocated_litres),
    unmet: m3(a.unmet_litres),
  }))
  return (
    <Box role="img" aria-label={t('chart.alloc.aria')} sx={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 8, right: 8, left: -8, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="name" tick={{ fontSize: 12 }} interval={0} />
          <YAxis tick={{ fontSize: 12 }} unit=" m³" width={64} />
          <Tooltip formatter={(v) => `${v} m³`} />
          <Legend />
          <Bar dataKey="allocated" stackId="a" name={t('chart.allocated')} fill={CHART_COLORS.allocated} isAnimationActive={false} />
          <Bar dataKey="unmet" stackId="a" name={t('chart.unmet')} fill={CHART_COLORS.unmet} radius={[6, 6, 0, 0]} isAnimationActive={false} />
        </BarChart>
      </ResponsiveContainer>
    </Box>
  )
}

export function RainTempChart({ daily }: { daily: DailyWeather[] }) {
  const { t, lang } = useT()
  const data = daily.map((d) => ({
    day: new Date(d.date).toLocaleDateString(lang === 'ta' ? 'ta-IN' : 'en-IN', { weekday: 'short', day: 'numeric' }),
    rain: d.precip_mm, prob: d.precip_prob_pct, tmax: d.tmax_c, et0: d.et0_mm,
  }))
  return (
    <Box role="img" aria-label={t('chart.weather.aria')} sx={{ height: 200 }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 8, right: 8, left: -16, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="day" tick={{ fontSize: 12 }} />
          <YAxis tick={{ fontSize: 12 }} unit=" mm" width={56} />
          <Tooltip formatter={(v, n) => [n === 'rain' ? `${v} mm` : `${v}`, n === 'rain' ? t('weather.rain') : String(n)]} />
          <Bar dataKey="rain" name={t('weather.rain')} fill={CHART_COLORS.available} radius={[6, 6, 0, 0]} isAnimationActive={false} />
        </BarChart>
      </ResponsiveContainer>
    </Box>
  )
}

export function ScenarioBars({ rows }: { rows: { name: string; demand: number; allocated: number; deficit: number }[] }) {
  const { t } = useT()
  return (
    <Box role="img" aria-label={t('chart.scenario.aria')} sx={{ height: 300 }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={rows.map((r) => ({ ...r, demand: m3(r.demand), allocated: m3(r.allocated), deficit: m3(r.deficit) }))}
          margin={{ top: 8, right: 8, left: -8, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="name" tick={{ fontSize: 11 }} interval={0} />
          <YAxis tick={{ fontSize: 12 }} unit=" m³" width={64} />
          <Tooltip formatter={(v) => `${v} m³`} />
          <Legend />
          <Bar dataKey="demand" name={t('chart.demand')} fill={CHART_COLORS.demand} radius={[4, 4, 0, 0]} isAnimationActive={false} />
          <Bar dataKey="allocated" name={t('chart.allocated')} fill={CHART_COLORS.allocated} radius={[4, 4, 0, 0]} isAnimationActive={false} />
          <Bar dataKey="deficit" name={t('chart.deficit')} fill={CHART_COLORS.unmet} radius={[4, 4, 0, 0]} isAnimationActive={false} />
        </BarChart>
      </ResponsiveContainer>
    </Box>
  )
}

export function MiniLine({ values, label }: { values: number[]; label: string }) {
  return (
    <Box sx={{ height: 60 }} aria-label={label} role="img">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={values.map((v, i) => ({ i, v }))}>
          <Line type="monotone" dataKey="v" stroke={CHART_COLORS.allocated} dot={false} isAnimationActive={false} />
          <ReferenceLine y={0} stroke="#ccc" />
        </LineChart>
      </ResponsiveContainer>
      <Typography variant="caption" color="text.secondary">{label}</Typography>
    </Box>
  )
}
