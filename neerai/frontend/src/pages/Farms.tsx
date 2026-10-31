import {
  Alert,
  Button,
  Card,
  CardContent,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  IconButton,
  MenuItem,
  Step,
  StepLabel,
  Stepper,
  TextField,
} from '@mui/material'
import { Box, Stack, Typography } from '../components/mui'
import AddIcon from '@mui/icons-material/Add'
import DeleteIcon from '@mui/icons-material/Delete'
import EditIcon from '@mui/icons-material/Edit'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import L from 'leaflet'
import markerIcon2x from 'leaflet/dist/images/marker-icon-2x.png'
import markerIcon from 'leaflet/dist/images/marker-icon.png'
import markerShadow from 'leaflet/dist/images/marker-shadow.png'
import { useState } from 'react'
import { MapContainer, Marker, Popup, TileLayer, useMapEvents } from 'react-leaflet'
import { useAppState } from '../app/AppState'
import { ErrorBlock, Grid, Loading, PageHeader, Panel } from '../components/common'
import { useFarms, useInvalidateData, useOptions } from '../hooks/useApi'
import { fmtVolume, refName, stageKey, useT } from '../i18n'
import { api } from '../services/api'
import type { Farm, FieldCreateBody, FieldRec, Stage } from '../types/api'

L.Marker.prototype.options.icon = L.icon({ iconUrl: markerIcon, iconRetinaUrl: markerIcon2x, shadowUrl: markerShadow, iconSize: [25, 41], iconAnchor: [12, 41] })

function Picker({ onPick }: { onPick: (lat: number, lon: number) => void }) {
  useMapEvents({ click: (e) => onPick(Number(e.latlng.lat.toFixed(4)), Number(e.latlng.lng.toFixed(4))) })
  return null
}

interface FieldDraft { name: string; crop: string; area: string; area_unit: 'ha' | 'acre'; stage: Stage; soil_type: string; irrigation_method: string; sowing_date: string; soil_moisture_pct: string; days_since_irrigation: string }
const EMPTY_FIELD: FieldDraft = { name: '', crop: 'paddy', area: '1', area_unit: 'ha', stage: 'development', soil_type: '', irrigation_method: '', sowing_date: '', soil_moisture_pct: '', days_since_irrigation: '' }

function OnboardingDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t, lang } = useT()
  const options = useOptions()
  const invalidate = useInvalidateData()
  const { setFarmId } = useAppState()
  const [step, setStep] = useState(0)
  const [farm, setFarm] = useState({ farmer_name: '', farm_name: '', village: '', district: 'Madurai', latitude: 9.9252, longitude: 78.1198, water_source: 'borewell', water: '', unit: 'm3' as 'm3' | 'litres' })
  const [fields, setFields] = useState<FieldDraft[]>([])
  const [draft, setDraft] = useState<FieldDraft>(EMPTY_FIELD)
  const [err, setErr] = useState('')

  const create = useMutation({
    mutationFn: async (list: FieldDraft[]) => {
      const litres = farm.water === '' ? null : Number(farm.water) * (farm.unit === 'm3' ? 1000 : 1)
      const f = await api.createFarm({ farmer_name: farm.farmer_name || 'Farmer', farm_name: farm.farm_name || 'My farm', village: farm.village, district: farm.district, latitude: farm.latitude, longitude: farm.longitude, water_source: farm.water_source, water_available_litres: litres, water_is_estimate: true })
      for (const d of list) await api.createField(toBody(f.id, d))
      return f
    },
    onSuccess: (f) => { invalidate(); setFarmId(f.id); reset(); onClose() },
    onError: (e) => setErr((e as Error).message),
  })
  const reset = () => { setStep(0); setFields([]); setDraft(EMPTY_FIELD); setErr('') }

  const addDraft = () => {
    if (!draft.name.trim() || !(Number(draft.area) > 0)) { setErr(t('onboard.field_required')); return }
    setErr(''); setFields([...fields, draft]); setDraft(EMPTY_FIELD)
  }
  const crops = options.data?.crops ?? []
  const label = (o: { name_en: string; name_ta: string }) => (lang === 'ta' ? o.name_ta : o.name_en)

  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="sm" aria-labelledby="onb-title">
      <DialogTitle id="onb-title">{t('onboard.title')}</DialogTitle>
      <DialogContent>
        <Stepper activeStep={step} alternativeLabel sx={{ mb: 3 }}>
          {['onboard.s1', 'onboard.s2', 'onboard.s3'].map((k) => <Step key={k}><StepLabel>{t(k)}</StepLabel></Step>)}
        </Stepper>
        {step === 0 && (
          <Stack spacing={2}>
            <TextField label={t('onboard.farmer')} value={farm.farmer_name} onChange={(e) => setFarm({ ...farm, farmer_name: e.target.value })} helperText={t('onboard.optional')} />
            <TextField label={t('onboard.farm_name')} value={farm.farm_name} onChange={(e) => setFarm({ ...farm, farm_name: e.target.value })} />
            <Stack direction="row" spacing={2}>
              <TextField fullWidth label={t('onboard.village')} value={farm.village} onChange={(e) => setFarm({ ...farm, village: e.target.value })} />
              <TextField fullWidth label={t('onboard.district')} value={farm.district} onChange={(e) => setFarm({ ...farm, district: e.target.value })} />
            </Stack>
            <Typography variant="body2" color="text.secondary">{t('onboard.pick')}</Typography>
            <Box sx={{ height: 220, borderRadius: 2, overflow: 'hidden' }}>
              <MapContainer center={[farm.latitude, farm.longitude]} zoom={8} style={{ height: '100%' }} scrollWheelZoom={false}>
                <TileLayer attribution="&copy; OpenStreetMap contributors" url="https://tile.openstreetmap.org/{z}/{x}/{y}.png" />
                <Picker onPick={(la, lo) => setFarm({ ...farm, latitude: la, longitude: lo })} />
                <Marker position={[farm.latitude, farm.longitude]} />
              </MapContainer>
            </Box>
            <Stack direction="row" spacing={2}>
              <TextField fullWidth type="number" label={t('onboard.lat')} value={farm.latitude} onChange={(e) => setFarm({ ...farm, latitude: Number(e.target.value) })} />
              <TextField fullWidth type="number" label={t('onboard.lon')} value={farm.longitude} onChange={(e) => setFarm({ ...farm, longitude: Number(e.target.value) })} />
            </Stack>
          </Stack>
        )}
        {step === 1 && (
          <Stack spacing={2}>
            <TextField select label={t('onboard.source')} value={farm.water_source} onChange={(e) => setFarm({ ...farm, water_source: e.target.value })}>
              {['borewell', 'open well', 'canal', 'tank / pond', 'rain-fed'].map((s) => <MenuItem key={s} value={s}>{t(`source.${s}`)}</MenuItem>)}
            </TextField>
            <Stack direction="row" spacing={2}>
              <TextField fullWidth type="number" label={t('onboard.water')} value={farm.water} onChange={(e) => setFarm({ ...farm, water: e.target.value })} slotProps={{ htmlInput: { min: 0 } }} helperText={t('onboard.water_help')} />
              <TextField select sx={{ width: 140 }} label={t('onboard.unit')} value={farm.unit} onChange={(e) => setFarm({ ...farm, unit: e.target.value as 'm3' | 'litres' })}>
                <MenuItem value="m3">m³</MenuItem><MenuItem value="litres">{t('litres')}</MenuItem>
              </TextField>
            </Stack>
            <Alert severity="info">{t('onboard.skip_note')}</Alert>
          </Stack>
        )}
        {step === 2 && (
          <Stack spacing={2}>
            {fields.map((f, i) => (
              <Stack key={i} direction="row" justifyContent="space-between" alignItems="center" sx={{ p: 1, border: 1, borderColor: 'divider', borderRadius: 2 }}>
                <Typography>{f.name} · {refName(options.data, 'crops', f.crop, lang)} · {f.area} {f.area_unit}</Typography>
                <IconButton aria-label={t('delete')} onClick={() => setFields(fields.filter((_, j) => j !== i))}><DeleteIcon /></IconButton>
              </Stack>
            ))}
            <Typography variant="subtitle2">{t('onboard.add_field')}</Typography>
            <FieldForm d={draft} set={setDraft} crops={crops} options={options.data} label={label} />
            <Button startIcon={<AddIcon />} onClick={addDraft} variant="outlined">{t('onboard.add_btn')}</Button>
          </Stack>
        )}
        {err && <Alert severity="error" sx={{ mt: 2 }}>{err}</Alert>}
      </DialogContent>
      <DialogActions sx={{ p: 2 }}>
        <Button onClick={() => { reset(); onClose() }}>{t('cancel')}</Button>
        <Box sx={{ flexGrow: 1 }} />
        {step > 0 && <Button onClick={() => setStep(step - 1)}>{t('back')}</Button>}
        {step < 2 ? <Button variant="contained" onClick={() => setStep(step + 1)}>{step === 1 && farm.water === '' ? t('skip') : t('next')}</Button>
          : <Button variant="contained" disabled={create.isPending || (fields.length === 0 && !(draft.name.trim() && Number(draft.area) > 0))}
              onClick={() => create.mutate(draft.name.trim() && Number(draft.area) > 0 ? [...fields, draft] : fields)}>{t('onboard.finish')}</Button>}
      </DialogActions>
    </Dialog>
  )
}

function toBody(farmId: string, d: FieldDraft): FieldCreateBody {
  return {
    farm_id: farmId, name: d.name.trim(), area: Number(d.area), area_unit: d.area_unit, crop: d.crop, stage: d.stage,
    soil_type: d.soil_type || null, irrigation_method: d.irrigation_method || null, sowing_date: d.sowing_date || null,
    soil_moisture_pct: d.soil_moisture_pct === '' ? null : Number(d.soil_moisture_pct),
    days_since_irrigation: d.days_since_irrigation === '' ? null : Number(d.days_since_irrigation),
  }
}

function FieldForm({ d, set, crops, options, label }: { d: FieldDraft; set: (d: FieldDraft) => void; crops: { key: string; name_en: string; name_ta: string }[]; options: ReturnType<typeof useOptions>['data']; label: (o: { name_en: string; name_ta: string }) => string }) {
  const { t } = useT()
  return (
    <Stack spacing={2}>
      <TextField required label={t('field.name')} value={d.name} onChange={(e) => set({ ...d, name: e.target.value })} />
      <Stack direction="row" spacing={2}>
        <TextField select fullWidth label={t('field.crop')} value={d.crop} onChange={(e) => set({ ...d, crop: e.target.value })}>
          {crops.map((c) => <MenuItem key={c.key} value={c.key}>{label(c)}</MenuItem>)}
        </TextField>
        <TextField select fullWidth label={t('field.stage')} value={d.stage} onChange={(e) => set({ ...d, stage: e.target.value as Stage })}>
          {(options?.stages ?? []).map((s) => <MenuItem key={s} value={s}>{t(stageKey(s))}</MenuItem>)}
        </TextField>
      </Stack>
      <Stack direction="row" spacing={2}>
        <TextField required fullWidth type="number" label={t('field.area')} value={d.area} onChange={(e) => set({ ...d, area: e.target.value })} slotProps={{ htmlInput: { min: 0, step: 0.1 } }} />
        <TextField select sx={{ width: 150 }} label={t('onboard.unit')} value={d.area_unit} onChange={(e) => set({ ...d, area_unit: e.target.value as 'ha' | 'acre' })}>
          <MenuItem value="ha">{t('unit.ha')}</MenuItem><MenuItem value="acre">{t('unit.acre')}</MenuItem>
        </TextField>
      </Stack>
      <Stack direction="row" spacing={2}>
        <TextField select fullWidth label={t('field.soil')} value={d.soil_type} onChange={(e) => set({ ...d, soil_type: e.target.value })} helperText={t('onboard.optional')}>
          <MenuItem value="">{t('notsure')}</MenuItem>{(options?.soils ?? []).map((s) => <MenuItem key={s.key} value={s.key}>{label(s)}</MenuItem>)}
        </TextField>
        <TextField select fullWidth label={t('field.method')} value={d.irrigation_method} onChange={(e) => set({ ...d, irrigation_method: e.target.value })} helperText={t('onboard.optional')}>
          <MenuItem value="">{t('notsure')}</MenuItem>{(options?.methods ?? []).map((s) => <MenuItem key={s.key} value={s.key}>{label(s)}</MenuItem>)}
        </TextField>
      </Stack>
      <Stack direction="row" spacing={2}>
        <TextField fullWidth type="date" label={t('field.sowing')} value={d.sowing_date} onChange={(e) => set({ ...d, sowing_date: e.target.value })} slotProps={{ inputLabel: { shrink: true } }} />
        <TextField fullWidth type="number" label={t('field.moisture')} value={d.soil_moisture_pct} onChange={(e) => set({ ...d, soil_moisture_pct: e.target.value })} helperText={t('onboard.optional')} slotProps={{ htmlInput: { min: 0, max: 60 } }} />
        <TextField fullWidth type="number" label={t('field.days')} value={d.days_since_irrigation} onChange={(e) => set({ ...d, days_since_irrigation: e.target.value })} helperText={t('onboard.optional')} slotProps={{ htmlInput: { min: 0 } }} />
      </Stack>
    </Stack>
  )
}

function EditField({ field, onClose }: { field: FieldRec | null; onClose: () => void }) {
  const { t } = useT()
  const options = useOptions()
  const invalidate = useInvalidateData()
  const [stage, setStage] = useState<Stage>(field?.stage ?? 'mid')
  const [moist, setMoist] = useState(field?.soil_moisture_pct?.toString() ?? '')
  const [days, setDays] = useState(field?.days_since_irrigation?.toString() ?? '')
  const save = useMutation({
    mutationFn: () => api.patchField(field!.id, { stage, soil_moisture_pct: moist === '' ? null : Number(moist), days_since_irrigation: days === '' ? null : Number(days) }),
    onSuccess: () => { invalidate(); onClose() },
  })
  if (!field) return null
  return (
    <Dialog open onClose={onClose} fullWidth maxWidth="xs">
      <DialogTitle>{field.name}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          <TextField select label={t('field.stage')} value={stage} onChange={(e) => setStage(e.target.value as Stage)}>
            {(options.data?.stages ?? []).map((s) => <MenuItem key={s} value={s}>{t(stageKey(s))}</MenuItem>)}
          </TextField>
          <TextField type="number" label={t('field.moisture')} value={moist} onChange={(e) => setMoist(e.target.value)} />
          <TextField type="number" label={t('field.days')} value={days} onChange={(e) => setDays(e.target.value)} />
          {save.error && <Alert severity="error">{(save.error as Error).message}</Alert>}
        </Stack>
      </DialogContent>
      <DialogActions><Button onClick={onClose}>{t('cancel')}</Button><Button variant="contained" onClick={() => save.mutate()} disabled={save.isPending}>{t('save')}</Button></DialogActions>
    </Dialog>
  )
}

export default function Farms() {
  const { t, lang } = useT()
  const farms = useFarms()
  const options = useOptions()
  const { farmId, setFarmId } = useAppState()
  const invalidate = useInvalidateData()
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [edit, setEdit] = useState<FieldRec | null>(null)
  const fields = useQuery({ queryKey: ['fields-all'], queryFn: api.fields })
  const demo = useMutation({ mutationFn: (k: string) => api.loadDemo(k), onSuccess: () => { invalidate(); qc.invalidateQueries({ queryKey: ['fields-all'] }) } })
  const del = useMutation({ mutationFn: (id: string) => api.deleteFarm(id), onSuccess: () => { invalidate(); qc.invalidateQueries({ queryKey: ['fields-all'] }) } })
  const delField = useMutation({ mutationFn: (id: string) => api.deleteField(id), onSuccess: () => { invalidate(); qc.invalidateQueries({ queryKey: ['fields-all'] }) } })

  if (farms.isLoading) return <Loading />
  if (farms.error) return <ErrorBlock error={farms.error} onRetry={() => farms.refetch()} />
  const list = farms.data ?? []
  const center: [number, number] = list[0] ? [list[0].latitude, list[0].longitude] : [10.0, 78.1]

  return (
    <>
      <PageHeader title={t('farms.title')} subtitle={t('farms.subtitle')}
        actions={<Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
          <Button variant="outlined" onClick={() => demo.mutate('madurai')} disabled={demo.isPending}>{t('farms.load_demo')}</Button>
          <Button variant="contained" startIcon={<AddIcon />} onClick={() => setOpen(true)}>{t('farms.add')}</Button>
        </Stack>} />
      {demo.error && <ErrorBlock error={demo.error} />}
      <Stack spacing={2.5}>
        {list.length > 0 && (
          <Panel title={t('farms.map')}>
            <Box sx={{ height: 280, borderRadius: 2, overflow: 'hidden' }} role="region" aria-label={t('farms.map')}>
              <MapContainer center={center} zoom={8} style={{ height: '100%' }} scrollWheelZoom={false}>
                <TileLayer attribution="&copy; OpenStreetMap contributors" url="https://tile.openstreetmap.org/{z}/{x}/{y}.png" />
                {list.map((f) => <Marker key={f.id} position={[f.latitude, f.longitude]}><Popup>{f.farm_name}<br />{f.district}</Popup></Marker>)}
              </MapContainer>
            </Box>
          </Panel>
        )}
        <Grid cols={{ xs: 1, lg: 2 }}>
          {list.map((f: Farm) => (
            <Card key={f.id} sx={{ outline: f.id === farmId ? '2px solid #2e7d32' : 'none' }}>
              <CardContent>
                <Stack direction="row" justifyContent="space-between" alignItems="flex-start" spacing={1}>
                  <Box>
                    <Typography variant="h6">{f.farm_name}</Typography>
                    <Typography variant="body2" color="text.secondary">{f.farmer_name} · {f.village || '—'}, {f.district}</Typography>
                  </Box>
                  <Stack direction="row" spacing={0.5} alignItems="center">
                    {f.is_demo && <Chip size="small" color="warning" variant="outlined" label={t('farms.sample')} />}
                    <IconButton aria-label={t('delete')} onClick={() => confirm(t('farms.confirm_delete')) && del.mutate(f.id)}><DeleteIcon /></IconButton>
                  </Stack>
                </Stack>
                <Stack direction="row" spacing={1} sx={{ my: 1.5 }} flexWrap="wrap" useFlexGap>
                  <Chip size="small" label={`${t('farms.water')}: ${f.water_available_litres == null ? t('farms.unknown') : fmtVolume(f.water_available_litres, lang)}`} color="info" variant="outlined" />
                  <Chip size="small" variant="outlined" label={t(`source.${f.water_source}`)} />
                </Stack>
                {(fields.data ?? []).filter((x) => x.farm_id === f.id).map((x) => (
                  <Stack key={x.id} direction="row" justifyContent="space-between" alignItems="center" sx={{ py: 0.5, borderTop: 1, borderColor: 'divider' }}>
                    <Box>
                      <Typography variant="body2" fontWeight={600}>{x.name}</Typography>
                      <Typography variant="caption" color="text.secondary">{refName(options.data, 'crops', x.crop, lang)} · {t(stageKey(x.stage))} · {x.area_ha.toFixed(2)} ha · {refName(options.data, 'methods', x.irrigation_method, lang)}</Typography>
                    </Box>
                    <Stack direction="row">
                      <IconButton aria-label={t('edit')} onClick={() => setEdit(x)}><EditIcon /></IconButton>
                      <IconButton aria-label={t('delete')} onClick={() => confirm(t('farms.confirm_delete')) && delField.mutate(x.id)}><DeleteIcon /></IconButton>
                    </Stack>
                  </Stack>
                ))}
                <Button sx={{ mt: 1 }} variant={f.id === farmId ? 'contained' : 'outlined'} onClick={() => setFarmId(f.id)}>{f.id === farmId ? t('farms.selected') : t('farms.use')}</Button>
              </CardContent>
            </Card>
          ))}
        </Grid>
      </Stack>
      <OnboardingDialog open={open} onClose={() => { setOpen(false); qc.invalidateQueries({ queryKey: ['fields-all'] }) }} />
      {edit && <EditField key={edit.id} field={edit} onClose={() => setEdit(null)} />}
    </>
  )
}
