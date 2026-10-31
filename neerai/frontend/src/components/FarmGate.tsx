import {
  Alert,
  Button,
  Card,
  CardContent,
} from '@mui/material'
import { Stack, Typography } from './mui'
import { useMutation } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { Link as RouterLink } from 'react-router-dom'
import { useCurrentFarm, useInvalidateData } from '../hooks/useApi'
import { useT } from '../i18n'
import { api } from '../services/api'
import type { Farm } from '../types/api'
import { ErrorBlock, Loading } from './common'

/** Renders children once a farm is available; otherwise offers the sample farm / onboarding. */
export default function FarmGate({ children }: { children: (farm: Farm) => ReactNode }) {
  const { t } = useT()
  const { farm, isLoading, error, refetch } = useCurrentFarm()
  const invalidate = useInvalidateData()
  const load = useMutation({ mutationFn: () => api.loadDemo('madurai'), onSuccess: invalidate })
  if (isLoading) return <Loading />
  if (error) return <ErrorBlock error={error} onRetry={() => refetch()} />
  if (!farm)
    return (
      <Card>
        <CardContent>
          <Stack spacing={2} alignItems="flex-start">
            <Typography variant="h6">{t('nofarm.title')}</Typography>
            <Typography color="text.secondary">{t('nofarm.body')}</Typography>
            <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
              <Button variant="contained" onClick={() => load.mutate()} disabled={load.isPending}>{t('nofarm.load')}</Button>
              <Button component={RouterLink} to="/farms" variant="outlined">{t('nofarm.add')}</Button>
            </Stack>
            {load.error && <Alert severity="error">{(load.error as Error).message}</Alert>}
          </Stack>
        </CardContent>
      </Card>
    )
  return <>{children(farm)}</>
}
