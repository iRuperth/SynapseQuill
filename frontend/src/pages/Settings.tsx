import { useEffect, useState } from 'react'
import { getGlobalConfig, getProfile, updateProfile } from '../api/client'
import { useProfile } from '../components/useProfile'
import { useSettings } from '../i18n/settings'
import type { ThemePref } from '../i18n/settings'
import { useT } from '../i18n/useT'
import type { GlobalConfig, Profile } from '../types'

type Tab = 'app' | 'profile'

export default function Settings() {
  const t = useT()
  const [tab, setTab] = useState<Tab>('app')

  return (
    <div>
      <h1 style={{ marginTop: 0 }}>{t('settings.title')}</h1>
      <div style={{ display: 'flex', gap: 4, background: 'var(--bg-elevated)', borderRadius: 999, padding: 4, width: 'fit-content', marginBottom: 20 }}>
        <button onClick={() => setTab('app')} style={tabBtn(tab === 'app')}>{t('settings.tab.app')}</button>
        <button onClick={() => setTab('profile')} style={tabBtn(tab === 'profile')}>{t('settings.tab.profile')}</button>
      </div>

      {tab === 'app' ? <AppSettings /> : <ProfileSettings />}
    </div>
  )
}

// ── Tab 1: application (language + theme), saved in this browser ──
function AppSettings() {
  const t = useT()
  const { theme, setTheme, lang, setLang } = useSettings()
  const themeOpts: { v: ThemePref; label: string }[] = [
    { v: 'light', label: t('settings.theme.light') },
    { v: 'dark', label: t('settings.theme.dark') },
    { v: 'auto', label: t('settings.theme.auto') },
  ]
  return (
    <div style={{ display: 'grid', gap: 18, maxWidth: 520 }}>
      <p style={{ color: 'var(--text-muted)', fontSize: 14, margin: 0 }}>{t('settings.app.intro')}</p>

      <Field label={t('settings.language')}>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <Seg active={lang === 'es'} onClick={() => setLang('es')}>{t('settings.language.es')}</Seg>
          <Seg active={lang === 'en'} onClick={() => setLang('en')}>{t('settings.language.en')}</Seg>
        </div>
      </Field>

      <Field label={t('settings.theme')}>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          {themeOpts.map((o) => (
            <Seg key={o.v} active={theme === o.v} onClick={() => setTheme(o.v)}>{o.label}</Seg>
          ))}
        </div>
      </Field>
    </div>
  )
}

// ── Tab 2: football profile (the original settings) ──
function ProfileSettings() {
  const t = useT()
  const { active } = useProfile()
  const [profile, setProfile] = useState<Profile | null>(null)
  const [cfg, setCfg] = useState<GlobalConfig | null>(null)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    getGlobalConfig().then(setCfg)
    if (active) getProfile(active).then(setProfile)
  }, [active])

  if (!profile || !cfg) return <p>{t('common.loading')}</p>

  async function patch(updates: Record<string, unknown>) {
    if (!active) return
    const p = await updateProfile(active, updates)
    setProfile(p)
    setSaved(true)
    setTimeout(() => setSaved(false), 1500)
  }

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
        <strong style={{ fontSize: 15 }}>{profile.name}</strong>
        {saved && <span style={{ color: 'var(--accent)', fontSize: 13 }}>{t('settings.saved')} ✓</span>}
      </div>

      <div style={{ display: 'grid', gap: 16, maxWidth: 640 }}>
        <Field label={t('settings.competition')}>
          <select
            value={profile.competition.preset}
            onChange={(e) => patch({ competition: { preset: e.target.value } })}
            style={input}
          >
            {cfg.competitions.map((c) => (
              <option key={c.key} value={c.key}>
                {c.label}{c.scorers === 'full' ? ` · ${t('settings.scorers')} ✓` : ''}
              </option>
            ))}
          </select>
        </Field>

        <Field label={t('settings.narrationLang')}>
          <Select value={profile.language} options={cfg.languages}
            onChange={(v) => patch({ language: v })} />
        </Field>

        <Field label={t('settings.llmProvider')}>
          <Select value={profile.llm_provider} options={cfg.llm_providers}
            onChange={(v) => patch({ llm_provider: v })} />
        </Field>

        <Field label={t('settings.imageProvider')}>
          <Select value={profile.media.image_provider} options={cfg.image_providers}
            onChange={(v) => patch({ media: { image_provider: v } })} />
        </Field>

        <Field label={t('settings.voice')}>
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
          <strong style={{ fontSize: 14 }}>📤 {t('settings.youtube')}</strong>
          <label style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 14 }}>
            <input
              type="checkbox"
              checked={profile.youtube.auto_upload ?? false}
              onChange={(e) => patch({ youtube: { auto_upload: e.target.checked } })}
            />
            {t('settings.autoUpload')}
          </label>
          <Field label={t('settings.privacy')}>
            <select
              value={profile.youtube.privacy}
              onChange={(e) => patch({ youtube: { privacy: e.target.value } })}
              style={input}
              disabled={profile.youtube.practice_mode}
            >
              <option value="private">{t('settings.privacy.private')}</option>
              <option value="unlisted">{t('settings.privacy.unlisted')}</option>
              <option value="public">{t('settings.privacy.public')}</option>
            </select>
          </Field>
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

function Seg({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button onClick={onClick} style={{
      padding: '8px 16px', borderRadius: 8, cursor: 'pointer', fontSize: 14, fontWeight: active ? 600 : 500,
      background: active ? 'var(--accent)' : 'var(--bg-elevated)',
      color: active ? '#04211c' : 'var(--text)',
      border: `1px solid ${active ? 'var(--accent)' : 'var(--border)'}`,
    }}>{children}</button>
  )
}

function tabBtn(active: boolean): React.CSSProperties {
  return {
    padding: '8px 18px', borderRadius: 999, border: 'none', cursor: 'pointer', fontSize: 14, fontWeight: 600,
    background: active ? 'var(--accent)' : 'transparent',
    color: active ? '#04211c' : 'var(--text-muted)',
  }
}

const input: React.CSSProperties = {
  padding: '9px 12px', borderRadius: 8, background: 'var(--bg-elevated)',
  color: 'var(--text)', border: '1px solid var(--border)',
}
