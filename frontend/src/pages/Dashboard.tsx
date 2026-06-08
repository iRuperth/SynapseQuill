import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { getContent, getProfile } from '../api/client'
import { useProfile } from '../components/useProfile'
import type { Profile } from '../types'

export default function Dashboard() {
  const { active } = useProfile()
  const [profile, setProfile] = useState<Profile | null>(null)
  const [count, setCount] = useState(0)

  useEffect(() => {
    if (!active) return
    getProfile(active).then(setProfile).catch(() => setProfile(null))
    getContent(active).then((c) => setCount(c.length)).catch(() => setCount(0))
  }, [active])

  return (
    <div>
      <h1 style={{ marginTop: 0 }}>Dashboard</h1>
      {profile && (
        <p style={{ color: 'var(--text-muted)' }}>
          Perfil <strong style={{ color: 'var(--text)' }}>{profile.name}</strong> · idioma {profile.language} ·
          LLM {profile.llm_provider} · imagen {profile.media.image_provider}
        </p>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 14, marginTop: 18 }}>
        <Stat label="Vídeos generados" value={count} />
        <Stat label="Privacidad YouTube" value={profile?.youtube.privacy ?? '-'} />
        <Stat label="Modo prueba" value={profile?.youtube.practice_mode ? 'ON' : 'OFF'} />
      </div>

      <div style={{ marginTop: 24, display: 'flex', gap: 12 }}>
        <Link to="/matches" style={cta}>Ver partidos →</Link>
        <Link to="/library" style={{ ...cta, background: 'var(--bg-elevated)' }}>Biblioteca →</Link>
      </div>
    </div>
  )
}

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div style={{
      padding: 18, background: 'var(--bg-surface)',
      border: '1px solid var(--border)', borderRadius: 12,
    }}>
      <div style={{ fontSize: 28, fontWeight: 800, color: 'var(--accent)' }}>{value}</div>
      <div style={{ color: 'var(--text-muted)', fontSize: 13 }}>{label}</div>
    </div>
  )
}

const cta: React.CSSProperties = {
  padding: '10px 16px', borderRadius: 10, background: 'var(--accent-2)',
  color: 'white', fontWeight: 600,
}
