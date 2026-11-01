import { Alert, Button, CircularProgress } from '@mui/material'
import { useEffect, useState, type ReactNode } from 'react'
import { useT } from '../i18n'
import { authEnabled, handleCallback, isSignedIn, login } from '../services/auth'
import { Stack, Typography } from './mui'

/** Shows the app only for signed-in users when Cognito is configured; otherwise (local demo) renders children directly. */
export default function AuthGate({ children }: { children: ReactNode }) {
  const { t } = useT()
  const [state, setState] = useState<'checking' | 'in' | 'out' | 'failed'>(authEnabled ? 'checking' : 'in')

  useEffect(() => {
    if (!authEnabled) return
    let live = true
    const hadCode = new URLSearchParams(window.location.search).has('code')
    handleCallback().then((ok) => {
      if (live) setState(ok || isSignedIn() ? 'in' : hadCode ? 'failed' : 'out')
    }).catch(() => live && setState('failed'))
    return () => { live = false }
  }, [])

  if (state === 'in') return <>{children}</>
  if (state === 'checking') return <Stack alignItems="center" sx={{ mt: 10 }}><CircularProgress aria-label="loading" /></Stack>
  return (
    <Stack spacing={2} alignItems="center" sx={{ mt: 10, px: 2, textAlign: 'center' }}>
      <Typography variant="h5">{t('auth.title')}</Typography>
      <Typography color="text.secondary">{t('auth.body')}</Typography>
      {state === 'failed' && <Alert severity="error">{t('auth.failed')}</Alert>}
      <Button variant="contained" size="large" onClick={() => void login()}>{t('auth.signin')}</Button>
    </Stack>
  )
}
