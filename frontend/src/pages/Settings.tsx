import { useEffect, useState } from 'react'
import { getGlobalConfig, getProfile, updateProfile } from '../api/client'
import { useProfile } from '../components/useProfile'
import type { GlobalConfig, Profile } from '../types'

export default function Settings() {
  const { active } = useProfile()
  const [profile, setProfile] = useState<Profile | null>(null)
  const [cfg, setCfg] = useState<GlobalConfig | null>(null)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    getGlobalConfig().then(setCfg)
    if (active) getProfile(active).then(setProfile)
  }, [active])

  if (!profile || !cfg) return <p>Cargando…</p>

  async function patch(updates: Record<string, unknown>) {
    if (!active) return
    const p = await updateProfile(active, updates)
    setProfile(p)
    setSaved(true)
    setTimeout(() => setSaved(false), 1500)
  }

  return (
    <div>
      <h1 style={{ marginTop: 0 }}>Ajustes · {profile.name}</h1>
      {saved && <span style={{ color: 'var(--accent)' }}>Guardado ✓</span>}

      <div style={{ display: 'grid', gap: 16, maxWidth: 640, marginTop: 16 }}>
        <Field label="Competición (liga o torneo)">
          <select
            value={profile.competition.preset}
            onChange={(e) => patch({ competition: { preset: e.target.value } })}
            style={input}
          >
            {cfg.competitions.map((c) => (
              <option key={c.key} value={c.key}>
                {c.label}{c.scorers === 'full' ? ' · goleadores ✓' : ''}
              </option>
            ))}
          </select>
        </Field>

        <Field label="Idioma de narración">
          <Select value={profile.language} options={cfg.languages}
            onChange={(v) => patch({ language: v })} />
        </Field>

        <Field label="Proveedor LLM (texto)">
          <Select value={profile.llm_provider} options={cfg.llm_providers}
            onChange={(v) => patch({ llm_provider: v })} />
        </Field>

        <Field label="Proveedor de imagen">
          <Select value={profile.media.image_provider} options={cfg.image_providers}
            onChange={(v) => patch({ media: { image_provider: v } })} />
        </Field>

        <Field label="Voz del narrador">
          <select
            value={profile.voice.preset}
            onChange={(e) => patch({ voice: { preset: e.target.value } })}
            style={input}
          >
            {cfg.voices.map((v) => (
              <option key={v.key} value={v.key}>{v.label}</option>
            ))}
          </select>
        </Field>

        {/* YouTube publishing automation */}
        <div style={{ borderTop: '1px solid var(--border)', paddingTop: 16, display: 'grid', gap: 14 }}>
          <strong style={{ fontSize: 14 }}>📤 Subida a YouTube</strong>
          <label style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 14 }}>
            <input
              type="checkbox"
              checked={profile.youtube.auto_upload ?? false}
              onChange={(e) => patch({ youtube: { auto_upload: e.target.checked } })}
            />
            Subir automáticamente cada vídeo generado
          </label>
          <Field label="Privacidad de las subidas">
            <select
              value={profile.youtube.privacy}
              onChange={(e) => patch({ youtube: { privacy: e.target.value } })}
              style={input}
              disabled={profile.youtube.practice_mode}
            >
              <option value="private">Privado</option>
              <option value="unlisted">Oculto (no listado)</option>
              <option value="public">Público</option>
            </select>
          </Field>
          {profile.youtube.practice_mode && (
            <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>
              Modo prueba activo (.env PRACTICE_MODE): todo se sube como privado.
            </span>
          )}
        </div>
      </div>
    </div>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label style={{ display: 'grid', gap: 6 }}>
      <span style={{ color: 'var(--text-muted)', fontSize: 13 }}>{label}</span>
      {children}
    </label>
  )
}

function Select({ value, options, onChange }: {
  value: string; options: string[]; onChange: (v: string) => void
}) {
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)} style={input}>
      {options.map((o) => <option key={o} value={o}>{o}</option>)}
    </select>
  )
}

const input: React.CSSProperties = {
  padding: '9px 12px', borderRadius: 8, background: 'var(--bg-elevated)',
  color: 'var(--text)', border: '1px solid var(--border)',
}
