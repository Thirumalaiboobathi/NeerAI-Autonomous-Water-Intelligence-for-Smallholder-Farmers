import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { useAppState } from '../app/AppState'
import { api } from '../services/api'
import type { PlanRequest } from '../types/api'

export const useHealth = () => useQuery({ queryKey: ['health'], queryFn: api.health, retry: 1, refetchInterval: 60_000 })
export const useOptions = () => useQuery({ queryKey: ['options'], queryFn: api.options, staleTime: Infinity })
export const useFarms = () => useQuery({ queryKey: ['farms'], queryFn: api.farms })
export const useDemoInfo = () => useQuery({ queryKey: ['demo'], queryFn: api.demo, staleTime: Infinity })
export const useImpact = () => useQuery({ queryKey: ['impact'], queryFn: api.impact })
export const usePresets = () => useQuery({ queryKey: ['presets'], queryFn: api.presets, staleTime: Infinity })

/** The farm the user is working on: stored selection if it still exists, otherwise the first farm. */
export function useCurrentFarm() {
  const { farmId, setFarmId } = useAppState()
  const farms = useFarms()
  const list = farms.data ?? []
  const current = list.find((f) => f.id === farmId) ?? list[0] ?? null
  useEffect(() => {
    if (current && current.id !== farmId) setFarmId(current.id)
  }, [current, farmId, setFarmId])
  return { farm: current, farms: list, isLoading: farms.isLoading, error: farms.error as Error | null, refetch: farms.refetch }
}

export function useOverview(farmId: string | undefined) {
  const { weatherScenario } = useAppState()
  return useQuery({
    queryKey: ['overview', farmId, weatherScenario],
    queryFn: () => api.overview(farmId!, weatherScenario),
    enabled: !!farmId,
  })
}

export const useExecutions = (farmId: string | undefined) =>
  useQuery({ queryKey: ['executions', farmId], queryFn: () => api.executions(farmId), enabled: !!farmId })

/** Deterministic plan recalculation (planner / scarcity pages). Debounce on the caller side. */
export function usePlan(req: PlanRequest | null, kind: 'plan' | 'allocate' = 'plan') {
  const { weatherScenario } = useAppState()
  const body = req ? { ...req, weather_scenario: weatherScenario } : null
  return useQuery({
    queryKey: ['plan', kind, body],
    queryFn: () => (kind === 'plan' ? api.plan(body!) : api.allocate(body!)),
    enabled: !!body,
    placeholderData: (prev) => prev,
  })
}

export function useInvalidateData() {
  const qc = useQueryClient()
  return () => {
    for (const k of ['overview', 'executions', 'impact', 'farms', 'plan']) qc.invalidateQueries({ queryKey: [k] })
  }
}

export function useAssess() {
  const invalidate = useInvalidateData()
  const { lang, weatherScenario } = useAppState()
  return useMutation({
    mutationFn: (b: { farm_id: string; query?: string }) => api.assess({ ...b, language: lang, weather_scenario: weatherScenario }),
    onSuccess: invalidate,
  })
}

export function useDebounced<T>(value: T, ms = 300): T {
  const [v, setV] = useState(value)
  useEffect(() => {
    const id = setTimeout(() => setV(value), ms)
    return () => clearTimeout(id)
  }, [value, ms])
  return v
}
