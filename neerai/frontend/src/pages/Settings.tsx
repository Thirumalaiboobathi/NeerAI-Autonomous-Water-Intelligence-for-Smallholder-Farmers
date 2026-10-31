import {
  Alert,
  Button,
  MenuItem,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
} from '@mui/material'
import { Stack, Typography } from '../components/mui'
import { useMutation } from '@tanstack/react-query'
import { useState } from 'react'
import { useAppState } from '../app/AppState'
import { Grid, PageHeader, Panel } from '../components/common'
import FarmGate from '../components/FarmGate'
import { useDemoInfo, useHealth, useInvalidateData, useOptions } from '../hooks/useApi'
import { useT } from '../i18n'
import { api } from '../services/api'
import type { Farm } from '../types/api'

function WaterEditor({ farm }: { farm: Farm }) {
  const { t } = useT()
  const invalidate = useInvalidateData()
  const [v, setV] = useState(farm.water_available_litres != null ? String(farm.water_available_litres / 1000) : '')
  const save = useMutation({
    mutationFn: () => api.patchFarm(farm.id, { water_available_litres: v === '' ? null : Number(v) * 1000 }),
    onSuccess: invalidate,
  })
  return (
    <Stack spacing={1.5}>
      <Typography variant="body2" color="text.secondary">{farm.farm_name}</Typography>
      <TextField type="number" label={`${t('onboard.water')} (m³)`} value={v} onChange={(e) => setV(e.target.value)} slotProps={{ htmlInput: { min: 0 } }} />
      <Button variant="contained" onClick={() => save.mutate()} disabled={save.isPending}>{t('save')}</Button>
      {save.isSuccess && <Alert severity="success">{t('settings.saved')}</Alert>}
      {save.error && <Alert severity="error">{(save.error as Error).message}</Alert>}
    </Stack>
  )
}

export default function Settings() {
  const { t, lang } = useT()
  const { setLang, weatherScenario, setWeatherScenario } = useAppState()
  const health = useHealth()
  const options = useOptions()
  const demo = useDemoInfo()
  const invalidate = useInvalidateData()
  const reload = useMutation({ mutationFn: () => api.loadDemo('madurai', true), onSuccess: invalidate })
  const desc = new Map((demo.data?.weather_scenarios ?? []).map((s) => [s.key, s.description]))

  return (
    <>
      <PageHeader title={t('settings.title')} />
      <Grid cols={{ xs: 1, lg: 2 }}>
        <Panel title={t('settings.language')}>
          <ToggleButtonGroup exclusive value={lang} onChange={(_, v) => v && setLang(v)} aria-label={t('lang.toggle')}>
            <ToggleButton value="ta" sx={{ px: 4 }}>தமிழ்</ToggleButton>
            <ToggleButton value="en" sx={{ px: 4 }}>English</ToggleButton>
          </ToggleButtonGroup>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 1.5 }}>{t('settings.voice_note')}</Typography>
        </Panel>
        <Panel title={t('settings.weather')}>
          <TextField select fullWidth label={t('settings.weather_scenario')} value={weatherScenario} onChange={(e) => setWeatherScenario(e.target.value)}
            helperText={desc.get(weatherScenario) ?? ''}>
            {(options.data?.weather_scenarios ?? ['uncertain_rain']).map((s) => <MenuItem key={s} value={s}>{s.replace('_', ' ')}</MenuItem>)}
          </TextField>
          <Alert severity="warning" sx={{ mt: 1.5 }}>{t('settings.weather_note')}</Alert>
        </Panel>
        <Panel title={t('settings.water')}>
          <FarmGate>{(farm) => <WaterEditor key={farm.id + farm.water_available_litres} farm={farm} />}</FarmGate>
        </Panel>
        <Panel title={t('settings.system')}>
          {health.data ? (
            <Stack spacing={0.5}>
              <Typography variant="body2">{t('settings.agent_mode')}: <b>{health.data.agent_mode === 'bedrock' ? 'Amazon Bedrock (Strands)' : t('settings.demo_mode')}</b></Typography>
              <Typography variant="body2">{t('settings.weather_provider')}: <b>{health.data.weather_provider}</b></Typography>
              <Typography variant="body2">{t('settings.repo')}: <b>{health.data.repository}</b></Typography>
            </Stack>
          ) : <Alert severity="error">{t('settings.offline')}</Alert>}
          <Button sx={{ mt: 2 }} variant="outlined" onClick={() => reload.mutate()} disabled={reload.isPending}>{t('settings.reload_demo')}</Button>
          {reload.isSuccess && <Alert severity="success" sx={{ mt: 1 }}>{t('settings.saved')}</Alert>}
          <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 2 }}>{options.data?.disclaimer}</Typography>
        </Panel>
      </Grid>
    </>
  )
}
