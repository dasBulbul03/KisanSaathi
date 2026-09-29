/**
 * Language state and the `t()` function.
 *
 * `t()` is a plain function rather than a hook so non-component code (formatters,
 * validators, endpoint labels) can translate too. Components read the language
 * from context; anything else can call `translate(language, key, vars)`.
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'

import { dictionaries, type TranslationKey } from './dictionaries'

export type Language = 'en' | 'mr'

const STORAGE_KEY = 'kisansaathi.lang'
const DEFAULT_LANGUAGE: Language = 'en'

function readStoredLanguage(): Language {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored === 'en' || stored === 'mr') return stored
    // Honour the browser preference once, before the user chooses explicitly.
    if (navigator.language?.toLowerCase().startsWith('mr')) return 'mr'
  } catch {
    // Storage or navigator unavailable; fall through to the default.
  }
  return DEFAULT_LANGUAGE
}

function interpolate(template: string, vars?: Record<string, string | number>): string {
  if (!vars) return template
  return template.replace(/\{(\w+)\}/g, (match, name: string) =>
    name in vars ? String(vars[name]) : match,
  )
}

export function translate(
  language: Language,
  key: TranslationKey,
  vars?: Record<string, string | number>,
): string {
  const dict = dictionaries[language] ?? dictionaries.en
  // An English fallback keeps the UI readable if a key is ever added to `en`
  // before its Marathi counterpart lands; the type system catches the omission.
  return interpolate(dict[key] ?? dictionaries.en[key] ?? key, vars)
}

/** BCP-47 locale for `Intl`. Marathi numbers stay in Devanagari digits. */
export function localeFor(language: Language): string {
  return language === 'mr' ? 'mr-IN' : 'en-IN'
}

export function formatNumber(value: number | null | undefined, language: Language): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  return new Intl.NumberFormat(localeFor(language)).format(value)
}

/** Rupees with the Indian lakh/crore grouping and the ₹ sign. */
export function formatMoney(value: number | null | undefined, language: Language): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  return new Intl.NumberFormat(localeFor(language), {
    style: 'currency',
    currency: 'INR',
    maximumFractionDigits: 2,
  }).format(value)
}

/** Abbreviates to '₹1.2L' / '₹3.4Cr' once the number is long enough to be noisy. */
export function formatMoneyCompact(value: number | null | undefined, language: Language): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  if (Math.abs(value) < 100000) return formatMoney(value, language)
  return new Intl.NumberFormat(localeFor(language), {
    style: 'currency',
    currency: 'INR',
    notation: 'compact',
    maximumFractionDigits: 1,
  }).format(value)
}

export function formatDate(value: string | null | undefined, language: Language): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return new Intl.DateTimeFormat(localeFor(language), {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  }).format(date)
}

export function formatDateTime(value: string | null | undefined, language: Language): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return new Intl.DateTimeFormat(localeFor(language), {
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date)
}

/** "3 days ago" / "आज" style relative time for notification feeds. */
export function formatRelative(value: string | null | undefined, language: Language): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  const diffSeconds = Math.round((date.getTime() - Date.now()) / 1000)
  const rtf = new Intl.RelativeTimeFormat(localeFor(language), { numeric: 'auto' })
  const units: Array<[Intl.RelativeTimeFormatUnit, number]> = [
    ['year', 31536000],
    ['month', 2592000],
    ['day', 86400],
    ['hour', 3600],
    ['minute', 60],
  ]
  for (const [unit, seconds] of units) {
    if (Math.abs(diffSeconds) >= seconds) {
      return rtf.format(Math.round(diffSeconds / seconds), unit)
    }
  }
  return rtf.format(diffSeconds, 'second')
}

interface I18nValue {
  language: Language
  setLanguage: (language: Language) => void
  toggle: () => void
  t: (key: TranslationKey, vars?: Record<string, string | number>) => string
  /** Formats and date helpers bound to the active language. */
  number: (value: number | null | undefined) => string
  money: (value: number | null | undefined) => string
  moneyCompact: (value: number | null | undefined) => string
  date: (value: string | null | undefined) => string
  dateTime: (value: string | null | undefined) => string
  relative: (value: string | null | undefined) => string
  /** Switches the document language so screen readers and fonts follow. */
  direction: 'ltr'
}

const I18nContext = createContext<I18nValue | null>(null)

export function I18nProvider({ children }: { children: ReactNode }) {
  const [language, setLanguageState] = useState<Language>(readStoredLanguage)

  useEffect(() => {
    document.documentElement.lang = language
    try {
      localStorage.setItem(STORAGE_KEY, language)
    } catch {
      // Preference simply will not persist; the app still works.
    }
  }, [language])

  const setLanguage = useCallback((next: Language) => setLanguageState(next), [])
  const toggle = useCallback(
    () => setLanguageState((current) => (current === 'en' ? 'mr' : 'en')),
    [],
  )

  const value = useMemo<I18nValue>(() => {
    const t = (key: TranslationKey, vars?: Record<string, string | number>) =>
      translate(language, key, vars)
    return {
      language,
      setLanguage,
      toggle,
      t,
      number: (v) => formatNumber(v, language),
      money: (v) => formatMoney(v, language),
      moneyCompact: (v) => formatMoneyCompact(v, language),
      date: (v) => formatDate(v, language),
      dateTime: (v) => formatDateTime(v, language),
      relative: (v) => formatRelative(v, language),
      direction: 'ltr',
    }
  }, [language, setLanguage, toggle])

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>
}

export function useI18n(): I18nValue {
  const context = useContext(I18nContext)
  if (!context) throw new Error('useI18n must be used inside <I18nProvider>')
  return context
}
