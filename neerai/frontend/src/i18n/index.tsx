import { useCallback } from 'react'
import { useAppState } from '../app/AppState'
import type { Action, Lang, Options, RefOption, Stage } from '../types/api'
import { en } from './en'
import { ta } from './ta'

export const dictionaries: Record<Lang, Record<string, string>> = { en, ta }

export function translate(lang: Lang, key: string, vars?: Record<string, string | number>): string {
  let s = dictionaries[lang][key] ?? dictionaries.en[key] ?? key
  if (vars) for (const [k, v] of Object.entries(vars)) s = s.split(`{${k}}`).join(String(v))
  return s
}

export function useT() {
  const { lang } = useAppState()
  const t = useCallback((key: string, vars?: Record<string, string | number>) => translate(lang, key, vars), [lang])
  return { t, lang }
}

export const nf = (n: number, lang: Lang = 'en') => new Intl.NumberFormat(lang === 'ta' ? 'en-IN' : 'en-IN', { maximumFractionDigits: 0 }).format(n)

/** Volume formatter: litres below 10,000 L, cubic metres above. Numerals stay Arabic in both languages. */
export function fmtVolume(litres: number, lang: Lang): string {
  const unit = lang === 'ta' ? { l: 'லிட்டர்', m3: 'கன மீட்டர்' } : { l: 'L', m3: 'm³' }
  if (Math.abs(litres) >= 10000) return `${new Intl.NumberFormat('en-IN', { maximumFractionDigits: 1 }).format(litres / 1000)} ${unit.m3}`
  return `${nf(litres)} ${unit.l}`
}

export function actionKey(a: Action): string {
  return `action.${a}`
}
export function stageKey(s: Stage): string {
  return `stage.${s}`
}

export function refName(options: Options | undefined, group: 'crops' | 'soils' | 'methods', key: string | null | undefined, lang: Lang): string {
  if (!key) return '—'
  const o: RefOption | undefined = options?.[group].find((x) => x.key === key)
  if (!o) return key
  return lang === 'ta' ? o.name_ta : o.name_en
}
