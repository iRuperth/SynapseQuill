import { useEffect, useState } from 'react'
import { listProfiles } from '../api/client'
import type { ProfileSummary } from '../types'

const KEY = 'sq.activeProfile'

// Tiny shared hook: which profile is currently selected (persisted).
export function useProfile() {
  const [profiles, setProfiles] = useState<ProfileSummary[]>([])
  const [active, setActive] = useState<string>(() => localStorage.getItem(KEY) ?? '')

  useEffect(() => {
    listProfiles().then((ps) => {
      setProfiles(ps)
      if (!active && ps.length) select(ps[0].id)
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function select(id: string) {
    setActive(id)
    localStorage.setItem(KEY, id)
  }

  return { profiles, active, select }
}
