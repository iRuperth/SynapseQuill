import { useEffect, useState } from 'react'
import { generateFreeform, getGlobalConfig } from '../api/client'
import { useProfile } from '../components/useProfile'
import { useT } from '../i18n/useT'
import type { FreeformResult, GlobalConfig } from '../types'

// Essential-level feature: the user provides any TOPIC + AUDIENCE and the app
// generates ready-to-publish copy for each platform, in the chosen language,
// personalised with the active profile's brand/persona preamble.

const ALL_PLATFORMS = ['blog', 'twitter', 'instagram', 'linkedin'] as const
const PLATFORM_META: Record<string, { label: string; icon: string }> = {
  blog: { label: 'Blog', icon: '📝' },
  twitter: { label: 'Twitter / X', icon: '🐦' },
  instagram: { label: 'Instagram', icon: '📸' },
  linkedin: { label: 'LinkedIn', icon: '💼' },
}
// Visible audience suggestions and topic examples are referenced by i18n key;
// the resolved labels double as the values shown/used in the free-text fields.
const AUDIENCE_PRESET_KEYS = [
  'create.audience.general',
  'create.audience.outreach',
  'create.audience.kids',
  'create.audience.expert',
  'create.audience.seo',
]
const TOPIC_EXAMPLE_KEYS = [
  'create.topicExample.offside',
  'create.topicExample.prep',
  'create.topicExample.champions',
  'create.topicExample.ai',
]

export default function Create() {
  const t = useT()
  const { active } = useProfile()
  const [cfg, setCfg] = useState<GlobalConfig | null>(null)
  const [topic, setTopic] = useState('')
  const [audience, setAudience] = useState('general')
  const [language, setLanguage] = useState('es')
  const [platforms, setPlatforms] = useState<string[]>([...ALL_PLATFORMS])
  const [extra, setExtra] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState<FreeformResult | null>(null)

  useEffect(() => {
    getGlobalConfig().then((c) => { setCfg(c); setLanguage(c.languages[0] ?? 'es') })
  }, [])

  function togglePlatform(p: string) {
    setPlatforms((cur) => (cur.includes(p) ? cur.filter((x) => x !== p) : [...cur, p]))
  }

  async function run() {
    if (!active || !topic.trim() || !platforms.length) return
    setLoading(true); setError(''); setResult(null)
    try {
      const r = await generateFreeform(active, { topic, audience, language, platforms, extra })
      setResult(r)
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(msg || t('create.error.generate'))
    } finally {
      setLoading(false)
    }
  }

  if (!cfg) return <p>{t('common.loading')}</p>
  if (!active) return <p>{t('create.selectProfile')}</p>

  const canRun = !loading && !!topic.trim() && !!platforms.length

  return (
    <div>
      <h1 style={{ marginTop: 0, display: 'flex', alignItems: 'center', gap: 10 }}>
        ✍️ {t('create.title')}
      </h1>
      <p style={{ color: 'var(--text-muted)', marginTop: -8, maxWidth: 720 }}>
        {t('create.subtitle')}
      </p>

      {/* Two-pane layout: form on the left, results fill the right */}
      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(360px, 460px) 1fr', gap: 24, marginTop: 20, alignItems: 'start' }}>
        {/* ── Form card ── */}
        <div style={{
          background: 'var(--bg-surface)', border: '1px solid var(--border)',
          borderRadius: 16, padding: 22, display: 'grid', gap: 18,
          position: 'sticky', top: 80,
        }}>
          <Field label={t('create.field.topic')}>
            <textarea
              style={{ ...input, minHeight: 64, resize: 'vertical', lineHeight: 1.4 }}
              value={topic} placeholder={t('create.topic.placeholder')}
              onChange={(e) => setTopic(e.target.value)}
            />
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 2 }}>
              {TOPIC_EXAMPLE_KEYS.map((key) => {
                const example = t(key)
                return (
                  <button key={key} type="button" onClick={() => setTopic(example)} style={exampleChip}>
                    {example.length > 34 ? example.slice(0, 34) + '…' : example}
                  </button>
                )
              })}
            </div>
          </Field>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 110px', gap: 14 }}>
            <Field label={t('create.field.audience')}>
              <input style={input} value={audience} list="audiences"
                onChange={(e) => setAudience(e.target.value)} />
              <datalist id="audiences">
                {AUDIENCE_PRESET_KEYS.map((key) => <option key={key} value={t(key)} />)}
              </datalist>
            </Field>
            <Field label={t('create.field.language')}>
              <select style={input} value={language} onChange={(e) => setLanguage(e.target.value)}>
                {cfg.languages.map((l) => <option key={l} value={l}>{l.toUpperCase()}</option>)}
              </select>
            </Field>
          </div>

          <Field label={t('create.field.platforms')}>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
              {ALL_PLATFORMS.map((p) => {
                const on = platforms.includes(p)
                return (
                  <button key={p} type="button" onClick={() => togglePlatform(p)} style={platformTile(on)}>
                    <span style={{ fontSize: 16 }}>{PLATFORM_META[p].icon}</span>
                    {PLATFORM_META[p].label}
                    {on && <span style={{ marginLeft: 'auto', color: 'var(--accent)' }}>✓</span>}
                  </button>
                )
              })}
            </div>
          </Field>

          <Field label={t('create.field.extra')}>
            <input style={input} value={extra} placeholder={t('create.extra.placeholder')}
              onChange={(e) => setExtra(e.target.value)} />
          </Field>

          <button onClick={run} disabled={!canRun} style={primaryBtn(!canRun)}>
            {loading ? t('create.generating') : `✨ ${t('create.generate')}`}
          </button>
          {error && <span style={{ color: '#f87171', fontSize: 14 }}>⚠️ {error}</span>}
        </div>

        {/* ── Results pane ── */}
        <div>
          {loading && <SkeletonResults platforms={platforms} />}

          {!loading && !result && (
            <div style={{
              padding: '60px 30px', textAlign: 'center', height: '100%',
              background: 'var(--bg-surface)', border: '1px dashed var(--border)', borderRadius: 16,
              display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
            }}>
              <div style={{ fontSize: 44 }}>📰</div>
              <p style={{ color: 'var(--text-muted)', maxWidth: 360, marginTop: 12 }}>
                {t('create.empty')}
              </p>
            </div>
          )}

          {!loading && result && (
            <div style={{ display: 'grid', gap: 16, gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))' }}>
              {Object.entries(result.content).map(([platform, text]) => (
                <ResultCard key={platform} platform={platform} text={text} />
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function SkeletonResults({ platforms }: { platforms: string[] }) {
  return (
    <div style={{ display: 'grid', gap: 16, gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))' }}>
      {platforms.map((p) => (
        <div key={p} style={{
          background: 'var(--bg-surface)', border: '1px solid var(--border)',
          borderRadius: 12, padding: 16, minHeight: 150,
        }}>
          <strong style={{ opacity: 0.8 }}>{PLATFORM_META[p]?.icon} {PLATFORM_META[p]?.label ?? p}</strong>
          <div style={{ marginTop: 12, display: 'grid', gap: 8 }}>
            {[100, 95, 88, 70].map((w, i) => (
              <div key={i} style={{
                height: 10, width: `${w}%`, borderRadius: 6,
                background: 'var(--bg-elevated)', animation: 'pulse 1.2s ease-in-out infinite',
              }} />
            ))}
          </div>
        </div>
      ))}
      <style>{`@keyframes pulse { 0%,100%{opacity:.4} 50%{opacity:.9} }`}</style>
    </div>
  )
}

function ResultCard({ platform, text }: { platform: string; text: string }) {
  const t = useT()
  const meta = PLATFORM_META[platform] ?? { label: platform, icon: '•' }
  const [copied, setCopied] = useState(false)
  function copy() {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true); setTimeout(() => setCopied(false), 1200)
    })
  }
  return (
    <div style={{
      background: 'var(--bg-surface)', border: '1px solid var(--border)',
      borderRadius: 12, padding: 16, display: 'flex', flexDirection: 'column',
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
        <strong style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
          <span style={{ fontSize: 16 }}>{meta.icon}</span> {meta.label}
        </strong>
        <button onClick={copy} style={chip(copied)}>{copied ? t('create.copied') : t('create.copy')}</button>
      </div>
      <pre style={{
        whiteSpace: 'pre-wrap', margin: 0, fontFamily: 'inherit', lineHeight: 1.55, flex: 1,
      }}>{text}</pre>
      <div style={{ color: 'var(--text-muted)', fontSize: 12, marginTop: 12, textAlign: 'right' }}>
        {t('create.charCount', { count: text.length })}
      </div>
    </div>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label style={{ display: 'grid', gap: 6 }}>
      <span style={{ color: 'var(--text-muted)', fontSize: 13, fontWeight: 600 }}>{label}</span>
      {children}
    </label>
  )
}

const input: React.CSSProperties = {
  padding: '10px 12px', borderRadius: 9, background: 'var(--bg-elevated)',
  color: 'var(--text)', border: '1px solid var(--border)', width: '100%', fontSize: 14,
}

const exampleChip: React.CSSProperties = {
  padding: '4px 10px', borderRadius: 999, cursor: 'pointer', fontSize: 12,
  background: 'transparent', color: 'var(--text-muted)', border: '1px solid var(--border)',
}

function platformTile(on: boolean): React.CSSProperties {
  return {
    display: 'flex', alignItems: 'center', gap: 8, padding: '10px 12px',
    borderRadius: 10, cursor: 'pointer', fontSize: 14, fontWeight: 500,
    background: on ? 'var(--bg-elevated)' : 'transparent',
    color: 'var(--text)',
    border: `1px solid ${on ? 'var(--accent)' : 'var(--border)'}`,
  }
}

function chip(activeChip: boolean): React.CSSProperties {
  return {
    padding: '6px 12px', borderRadius: 999, cursor: 'pointer', fontSize: 13,
    background: activeChip ? 'var(--accent)' : 'var(--bg-elevated)',
    color: activeChip ? '#04211c' : 'var(--text)',
    border: `1px solid ${activeChip ? 'var(--accent)' : 'var(--border)'}`,
  }
}

function primaryBtn(disabled: boolean): React.CSSProperties {
  return {
    padding: '12px 16px', borderRadius: 10, border: 'none', fontWeight: 700, fontSize: 15,
    cursor: disabled ? 'not-allowed' : 'pointer', opacity: disabled ? 0.6 : 1,
    background: 'var(--accent)', color: '#04211c',
  }
}
