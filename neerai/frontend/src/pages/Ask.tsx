import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Alert,
  Avatar,
  Chip,
  CircularProgress,
  IconButton,
  Paper,
  TextField,
} from '@mui/material'
import { Box, Stack, Typography } from '../components/mui'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import SendIcon from '@mui/icons-material/Send'
import SmartToyIcon from '@mui/icons-material/SmartToy'
import { useMutation } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { useAppState } from '../app/AppState'
import { ErrorBlock, Grid, PageHeader } from '../components/common'
import { ActionChip, ActionCard, AgentTimeline, ConfidenceChip, Disclaimer, Metric, WhyThisDecision } from '../components/domain'
import FarmGate from '../components/FarmGate'
import { useDemoInfo, useInvalidateData } from '../hooks/useApi'
import { fmtVolume, useT } from '../i18n'
import { api } from '../services/api'
import type { AgentExecution, Farm } from '../types/api'

type Msg = { role: 'user'; text: string } | { role: 'assistant'; ex: AgentExecution }

function Answer({ ex, onFollow }: { ex: AgentExecution; onFollow: (q: string) => void }) {
  const { t, lang } = useT()
  const d = ex.decision
  const top = d?.decisions.slice().sort((a, b) => b.recommended_volume_litres - a.recommended_volume_litres)[0]
  return (
    <Stack spacing={1.5}>
      {ex.status !== 'completed' && ex.decision?.headline_action !== 'INSUFFICIENT_DATA' && <Alert severity="warning">{t('ask.partial')}</Alert>}
      {d?.headline_action === 'INSUFFICIENT_DATA' && <Alert severity="info">{ex.answer}</Alert>}
      {d && d.headline_action !== 'INSUFFICIENT_DATA' && (
        <>
          <Typography sx={{ fontSize: '1.05rem', lineHeight: 1.6 }}>{ex.answer}</Typography>
          <Grid cols={{ xs: 2, sm: 4 }} gap={1.5}>
            <Metric label={t('ask.rec')} value={top ? t(`action.${top.action}`) : '—'} />
            <Metric label={t('ask.water_use')} value={fmtVolume(d.total_recommended_litres, lang)} />
            <Metric label={t('dash.available')} value={fmtVolume(d.available_litres, lang)} />
            <Box><Typography variant="caption" color="text.secondary">{t('confidence')}</Typography><Box>{top && <ConfidenceChip level={top.confidence} />}</Box></Box>
          </Grid>
          <Stack direction="row" gap={1} flexWrap="wrap">
            {d.decisions.map((x) => <Chip key={x.field_id} variant="outlined" label={<span>{x.field_name.split(' (')[0]}: <b>{t(`action.${x.action}`)}</b></span>} />)}
          </Stack>
          {ex.message && <ActionCard msg={ex.message} accent={d.scarcity_mode ? 'warning.main' : 'primary.main'} />}
          {ex.scenarios && (
            <Paper variant="outlined" sx={{ p: 1.5 }}>
              <Typography variant="subtitle2">{t('ask.scenarios')}</Typography>
              {ex.scenarios.scenarios.map((s) => (
                <Typography key={s.name} variant="body2">• {s.title}: {t('dash.demand')} {fmtVolume(s.total_demand_litres, lang)}, {t('dash.deficit')} {fmtVolume(s.deficit_litres, lang)}
                  {Object.keys(ex.scenarios!.changed_actions[s.name] ?? {}).length > 0 && ` (${t('planner.changed')})`}</Typography>
              ))}
              <Typography variant="caption" color="text.secondary">{ex.scenarios.disclaimer}</Typography>
            </Paper>
          )}
          <Box>
            <Typography variant="subtitle2" sx={{ mb: 0.5 }}>{t('ask.next')}</Typography>
            {d.decisions.filter((x) => x.action !== 'INSUFFICIENT_DATA').map((x) => (
              <Accordion key={x.field_id} disableGutters variant="outlined">
                <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                  <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
                    <Typography fontWeight={600}>{x.field_name.split(' (')[0]}</Typography><ActionChip action={x.action} size="small" />
                    <Typography variant="body2" color="text.secondary">{x.timing}</Typography>
                  </Stack>
                </AccordionSummary>
                <AccordionDetails><WhyThisDecision d={x} /></AccordionDetails>
              </Accordion>
            ))}
          </Box>
        </>
      )}
      <Accordion disableGutters variant="outlined">
        <AccordionSummary expandIcon={<ExpandMoreIcon />}><Typography fontWeight={600}>{t('timeline.title')} ({ex.steps.length})</Typography></AccordionSummary>
        <AccordionDetails><AgentTimeline steps={ex.steps} durationMs={ex.duration_ms} mode={ex.mode} /></AccordionDetails>
      </Accordion>
      <Typography variant="caption" color="text.secondary">{t('ask.sources')}: {ex.data_sources.join(' · ')}</Typography>
      {ex.follow_up_questions.length > 0 && (
        <Stack direction="row" gap={1} flexWrap="wrap">
          {ex.follow_up_questions.map((q) => <Chip key={q} label={q} onClick={() => onFollow(q)} color="primary" variant="outlined" sx={{ height: 36 }} />)}
        </Stack>
      )}
    </Stack>
  )
}

function AskBody({ farm }: { farm: Farm }) {
  const { t, lang } = useT()
  const { weatherScenario } = useAppState()
  const demo = useDemoInfo()
  const invalidate = useInvalidateData()
  const [msgs, setMsgs] = useState<Msg[]>([])
  const [text, setText] = useState('')
  const end = useRef<HTMLDivElement>(null)
  const send = useMutation({
    mutationFn: (q: string) => api.chat({ farm_id: farm.id, message: q, language: lang, weather_scenario: weatherScenario }),
    onSuccess: (ex) => { setMsgs((m) => [...m, { role: 'assistant', ex }]); invalidate() },
  })
  useEffect(() => { end.current?.scrollIntoView?.({ behavior: 'smooth' }) }, [msgs.length, send.isPending])

  const ask = (q: string) => {
    const v = q.trim()
    if (!v || send.isPending) return
    setMsgs((m) => [...m, { role: 'user', text: v }])
    setText('')
    send.mutate(v)
  }
  const examples = lang === 'ta'
    ? ['இன்று என் நெல் வயலுக்கு நீர்ப்பாசனம் செய்யலாமா?', 'என்னிடம் 400 m3 தண்ணீர் மட்டுமே உள்ளது. எந்த வயலுக்கு முன்னுரிமை?', 'என் நீர் திட்டத்தை தமிழில் விளக்கவும்.', ...(demo.data?.chat_examples ?? []).slice(2, 4)]
    : demo.data?.chat_examples ?? []

  return (
    <>
      <PageHeader title={t('ask.title')} subtitle={t('ask.subtitle')} />
      <Stack spacing={2} sx={{ minHeight: '50vh' }}>
        {msgs.length === 0 && (
          <Paper variant="outlined" sx={{ p: 2.5 }}>
            <Typography variant="h6" sx={{ mb: 1 }}>{t('ask.try')}</Typography>
            <Stack gap={1}>
              {examples.map((q) => <Chip key={q} label={q} onClick={() => ask(q)} sx={{ height: 'auto', py: 1, '& .MuiChip-label': { whiteSpace: 'normal' }, justifyContent: 'flex-start' }} />)}
            </Stack>
            <Typography variant="caption" color="text.secondary" sx={{ mt: 2, display: 'block' }}>{t('ask.hint')}</Typography>
          </Paper>
        )}
        {msgs.map((m, i) => m.role === 'user' ? (
          <Box key={i} sx={{ alignSelf: 'flex-end', maxWidth: '85%' }}>
            <Paper sx={{ p: 1.5, bgcolor: 'primary.main', color: 'primary.contrastText', borderRadius: 3 }}><Typography>{m.text}</Typography></Paper>
          </Box>
        ) : (
          <Stack key={i} direction="row" spacing={1.5} alignItems="flex-start">
            <Avatar sx={{ bgcolor: 'primary.dark', width: 34, height: 34 }}><SmartToyIcon fontSize="small" /></Avatar>
            <Paper variant="outlined" sx={{ p: 2, flexGrow: 1, minWidth: 0 }}><Answer ex={m.ex} onFollow={ask} /></Paper>
          </Stack>
        ))}
        {send.isPending && <Stack direction="row" spacing={1.5} alignItems="center"><CircularProgress size={22} /><Typography color="text.secondary">{t('ask.thinking')}</Typography></Stack>}
        {send.error && <ErrorBlock error={send.error} />}
        <div ref={end} />
      </Stack>
      <Paper component="form" onSubmit={(e) => { e.preventDefault(); ask(text) }} sx={{ position: 'sticky', bottom: { xs: 72, md: 16 }, mt: 2, p: 1, display: 'flex', gap: 1, alignItems: 'center', border: 1, borderColor: 'divider' }}>
        <TextField fullWidth variant="standard" placeholder={t('ask.placeholder')} value={text} onChange={(e) => setText(e.target.value)} slotProps={{ htmlInput: { 'aria-label': t('ask.placeholder'), maxLength: 500 }, input: { disableUnderline: true, sx: { px: 1, fontSize: '1rem' } } }} />
        <IconButton type="submit" color="primary" aria-label={t('ask.send')} disabled={!text.trim() || send.isPending}><SendIcon /></IconButton>
      </Paper>
      <Disclaimer />
    </>
  )
}

export default function Ask() {
  return <FarmGate>{(farm) => <AskBody farm={farm} />}</FarmGate>
}
