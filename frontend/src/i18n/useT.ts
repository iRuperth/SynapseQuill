/**
 * Tiny translation hook. `t('key')` returns the string for the current language.
 *
 * Keys live in ./catalog.ts as { es, en }. Missing keys fall back to the key
 * itself so nothing crashes mid-translation. Supports {placeholders}:
 *   t('lab.greeting', { name: 'Rup' })
 */
import { useCallback } from 'react'
import { useSettings } from './settings'
import { CATALOG } from './catalog'

export function useT() {
  const { lang } = useSettings()
  // Memoize on `lang` so `t` keeps a stable identity between renders. Without
  // this, every render returns a brand-new function, so any effect that lists
  // `t` as a dependency re-runs forever (e.g. the Calendar fetch loop).
  return useCallback(
    (key: string, vars?: Record<string, string | number>): string => {
      const entry = CATALOG[key]
      let s = (entry && entry[lang]) ?? key
      if (vars) {
        for (const [k, v] of Object.entries(vars)) {
          s = s.replace(new RegExp(`\\{${k}\\}`, 'g'), String(v))
        }
      }
      return s
    },
    [lang],
  )
}
