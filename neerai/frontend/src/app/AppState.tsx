import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import type { Lang } from '../types/api'

interface AppStateValue {
  lang: Lang
  setLang: (l: Lang) => void
  farmId: string | null
  setFarmId: (id: string | null) => void
  weatherScenario: string
  setWeatherScenario: (s: string) => void
}

const Ctx = createContext<AppStateValue | null>(null)

function load(key: string, fallback: string): string {
  try {
    return localStorage.getItem(key) ?? fallback
  } catch {
    return fallback
  }
}
function save(key: string, value: string) {
  try {
    localStorage.setItem(key, value)
  } catch { /* storage may be unavailable (private mode) */ }
}

export function AppStateProvider({ children, initialLang = 'ta' }: { children: ReactNode; initialLang?: Lang }) {
  const [lang, setLangState] = useState<Lang>(() => (load('neerai.lang', initialLang) === 'en' ? 'en' : 'ta'))
  const [farmId, setFarmIdState] = useState<string | null>(() => load('neerai.farm', '') || null)
  const [weatherScenario, setWsState] = useState<string>(() => load('neerai.weather', 'uncertain_rain'))

  useEffect(() => {
    document.documentElement.lang = lang
  }, [lang])

  const setLang = useCallback((l: Lang) => { setLangState(l); save('neerai.lang', l) }, [])
  const setFarmId = useCallback((id: string | null) => { setFarmIdState(id); save('neerai.farm', id ?? '') }, [])
  const setWeatherScenario = useCallback((s: string) => { setWsState(s); save('neerai.weather', s) }, [])

  const value = useMemo(
    () => ({ lang, setLang, farmId, setFarmId, weatherScenario, setWeatherScenario }),
    [lang, setLang, farmId, setFarmId, weatherScenario, setWeatherScenario],
  )
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useAppState(): AppStateValue {
  const v = useContext(Ctx)
  if (!v) throw new Error('useAppState must be used inside AppStateProvider')
  return v
}
