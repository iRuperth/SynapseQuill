/**
 * App-level settings: UI theme (light/dark/auto) and language (es/en).
 *
 * These are page/app preferences, separate from the football profile settings.
 * Stored in localStorage so they persist across sessions. "auto" theme follows
 * the OS via prefers-color-scheme.
 */
import { createContext, useContext, useEffect, useState } from 'react'
import type { ReactNode } from 'react'

export type ThemePref = 'light' | 'dark' | 'auto'
export type Lang = 'es' | 'en'

interface AppSettings {
  theme: ThemePref
  setTheme: (t: ThemePref) => void
  lang: Lang
  setLang: (l: Lang) => void
}

const Ctx = createContext<AppSettings | null>(null)

const THEME_KEY = 'sq_theme'
const LANG_KEY = 'sq_lang'

function systemDark(): boolean {
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ?? true
}

function applyTheme(pref: ThemePref) {
  const dark = pref === 'auto' ? systemDark() : pref === 'dark'
  document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light')
}

export function SettingsProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<ThemePref>(
    () => (localStorage.getItem(THEME_KEY) as ThemePref) || 'dark',
  )
  const [lang, setLangState] = useState<Lang>(
    () => (localStorage.getItem(LANG_KEY) as Lang) || 'es',
  )

  // Apply theme on mount and whenever it changes; react to OS changes in auto.
  useEffect(() => {
    applyTheme(theme)
    if (theme !== 'auto') return
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    const onChange = () => applyTheme('auto')
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [theme])

  useEffect(() => {
    document.documentElement.setAttribute('lang', lang)
  }, [lang])

  const setTheme = (t: ThemePref) => {
    localStorage.setItem(THEME_KEY, t)
    setThemeState(t)
  }
  const setLang = (l: Lang) => {
    localStorage.setItem(LANG_KEY, l)
    setLangState(l)
  }

  return <Ctx.Provider value={{ theme, setTheme, lang, setLang }}>{children}</Ctx.Provider>
}

export function useSettings(): AppSettings {
  const v = useContext(Ctx)
  if (!v) throw new Error('useSettings must be used within SettingsProvider')
  return v
}
