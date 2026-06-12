import { useEffect, useRef, useState } from 'react'
import {
  generateFreeform, generateTopicVideo, getGlobalConfig, getStatus,
} from '../api/client'
import { useProfile } from '../components/useProfile'
import { useT } from '../i18n/useT'
import type { FreeformResult, GenerationStatus, GlobalConfig } from '../types'

// Create has two modes:
//   • text  — multi-platform copy for any TOPIC + AUDIENCE (essential level).
//   • video — a topic/educational video (clean crowd backdrop + logo +
//             narration + subtitles), reel (9:16) or YouTube (16:9). The topic
//             can be a free subject the model explains, or the user's own pasted
//             content, which the narration is grounded in (never invented).

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

// Pipeline steps surfaced for the video progress bar (catalog: create.step.*).
const VIDEO_STEP_KEYS = ['start', 'narrate', 'polish', 'metadata', 'media', 'voice', 'video', 'upload', 'done']

export default function Create() {
  const t = useT()
  const { active } = useProfile()
  const [cfg, setCfg] = useState<GlobalConfig | null>(null)
  const [mode, setMode] = useState<'text' | 'video'>('text')

  // Shared
  const [topic, setTopic] = useState('')
  const [audience, setAudience] = useState('general')
  const [language, setLanguage] = useState('es')

  // Text mode
  const [platforms, setPlatforms] = useState<string[]>([...ALL_PLATFORMS])
  const [extra, setExtra] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState<FreeformResult | null>(null)

  // Video mode
  const [videoFormat, setVideoFormat] = useState<'reel' | 'youtube'>('reel')
  const [inputMode, setInputMode] = useState<'topic' | 'source'>('topic')
  const [sourceText, setSourceText] = useState('')
  const [status, setStatus] = useState<GenerationStatus>({ state: 'idle' })
  const poll = useRef<number | null>(null)

  useEffect(() => {
    getGlobalConfig().then((c) => { setCfg(c); setLanguage(c.languages[0] ?? 'es') })
  }, [])

  // Stop polling when leaving the page.
  useEffect(() => () => { if (poll.current) window.clearInterval(poll.current) }, [])

  function togglePlatform(p: string) {
    setPlatforms((cur) => (cur.includes(p) ? cur.filter((x) => x !== p) : [...cur, p]))
  }

  async function runText() {
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

  function startPolling() {
    if (poll.current) window.clearInterval(poll.current)
    poll.current = window.setInterval(async () => {
      if (!active) return
      const s = await getStatus(active)
      setStatus(s)
      if (s.state === 'done' || s.state === 'error' || s.state === 'idle') {
        if (poll.current) window.clearInterval(poll.current)
      }
    }, 1500)
  }

  async function runVideo() {
    if (!active || !topic.trim()) return
    setError('')
    setStatus({ state: 'running', step: 'start', message: t('create.video.starting') })
    try {
      await generateTopicVideo(active, {
        topic,
        source_text: inputMode === 'source' ? sourceText : '',
        audience,
        format: videoFormat,
      })
      startPolling()
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(msg || t('create.error.generate'))
      setStatus({ state: 'idle' })
    }
  }

  if (!cfg) return <p>{t('common.loading')}</p>
  if (!active) return <p>{t('create.selectProfile')}</p>

  const busy = status.state === 'running'
  const canRunText = !loading && !!topic.trim() && !!platforms.length
  const canRunVideo = !busy && !!topic.trim() && (inputMode === 'topic' || !!sourceText.trim())
  const doneVideo = status.state === 'done' && status.result
  const videoUrl = doneVideo && status.result?.id
    ? `/api/profiles/${active}/video/${status.result.id}`
    : null

  return (
    <div>
      <h1 style={{ marginTop: 0, display: 'flex', alignItems: 'center', gap: 10 }}>
        ✍️ {t('create.title')}
      </h1>
      <p style={{ color: 'var(--text-muted)', marginTop: -8, maxWidth: 720 }}>
        {t('create.subtitle')}
      </p>

      {/* Mode switch: text copy vs video */}
      <div style={{ display: 'flex', gap: 8, margin: '16px 0' }}>
        <button type="button" onClick={() => setMode('text')} style={tab(mode === 'text')}>
          📰 {t('create.mode.text')}
        </button>
        <button type="button" onClick={() => setMode('video')} style={tab(mode === 'video')}>
          🎬 {t('create.mode.video')}
        </button>
      </div>

      {/* Two-pane layout: form on the left, results fill the right */}
      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(360px, 460px) 1fr', gap: 24, marginTop: 8, alignItems: 'start' }}>
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

          {/* Video mode: optionally paste your own content to narrate. */}
          {mode === 'video' && (
            <Field label={t('create.video.inputMode')}>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
                <button type="button" onClick={() => setInputMode('topic')} style={segBtn(inputMode === 'topic')}>
                  💡 {t('create.video.inputMode.topic')}
                </button>
                <button type="button" onClick={() => setInputMode('source')} style={segBtn(inputMode === 'source')}>
                  📋 {t('create.video.inputMode.source')}
                </button>
              </div>
              {inputMode === 'source' && (
                <textarea
                  style={{ ...input, minHeight: 110, resize: 'vertical', lineHeight: 1.4, marginTop: 8 }}
                  value={sourceText} placeholder={t('create.video.source.placeholder')}
                  onChange={(e) => setSourceText(e.target.value)}
                />
              )}
              <span style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 4 }}>
                {inputMode === 'source' ? t('create.video.source.hint') : t('create.video.topic.hint')}
              </span>
            </Field>
          )}

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

          {/* ── Text-only controls ── */}
          {mode === 'text' && (
            <>
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

              <button onClick={runText} disabled={!canRunText} style={primaryBtn(!canRunText)}>
                {loading ? t('create.generating') : `✨ ${t('create.generate')}`}
              </button>
            </>
          )}

          {/* ── Video-only controls ── */}
          {mode === 'video' && (
            <>
              <Field label={t('create.video.format')}>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
                  <button type="button" onClick={() => setVideoFormat('reel')} style={segBtn(videoFormat === 'reel')}>
                    📱 {t('create.video.format.reel')}
                  </button>
                  <button type="button" onClick={() => setVideoFormat('youtube')} style={segBtn(videoFormat === 'youtube')}>
                    🖥️ {t('create.video.format.youtube')}
                  </button>
                </div>
              </Field>

              <button onClick={runVideo} disabled={!canRunVideo} style={primaryBtn(!canRunVideo)}>
                {busy ? t('create.video.generating') : `🎬 ${t('create.video.generate')}`}
              </button>
            </>
          )}

          {error && <span style={{ color: '#f87171', fontSize: 14 }}>⚠️ {error}</span>}
        </div>

        {/* ── Results pane ── */}
        <div>
          {/* Text results */}
          {mode === 'text' && (
            <>
              {loading && <SkeletonResults platforms={platforms} />}
              {!loading && !result && <EmptyHint text={t('create.empty')} />}
              {!loading && result && (
                <div style={{ display: 'grid', gap: 16, gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))' }}>
                  {Object.entries(result.content).map(([platform, text]) => (
                    <ResultCard key={platform} platform={platform} text={text} />
                  ))}
                </div>
              )}
            </>
          )}

          {/* Video progress + result */}
          {mode === 'video' && (
            <>
              {busy && (
                <div style={statusBox}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
                    <span style={{ fontSize: 16 }}>
                      🎬 <strong>{t('create.video.working')}</strong>
                      <span style={{ color: 'var(--text-muted)', marginLeft: 8 }}>
                        {status.step && VIDEO_STEP_KEYS.includes(status.step)
                          ? t(`create.step.${status.step}`)
                          : status.message}
                      </span>
                    </span>
                  </div>
                  <div style={{ height: 12, borderRadius: 999, background: 'var(--bg)', overflow: 'hidden' }}>
                    <div style={{
                      height: '100%', width: `${status.progress ?? 0}%`,
                      background: 'linear-gradient(90deg, var(--accent), var(--accent-2))',
                      transition: 'width .4s ease',
                    }} />
                  </div>
                  <div style={{ textAlign: 'right', fontSize: 12, color: 'var(--text-muted)', marginTop: 4 }}>
                    {status.progress ?? 0}%
                  </div>
                </div>
              )}

              {status.state === 'error' && (
                <div style={{ ...statusBox, borderColor: '#7a3650' }}>
                  ⚠️ {status.message || t('create.error.generate')}
                </div>
              )}

              {doneVideo && (
                <div style={{ display: 'grid', gap: 12 }}>
                  <div style={{ ...statusBox, borderColor: 'var(--accent)' }}>
                    ✅ {t('create.video.done')}
                  </div>
                  {videoUrl && (
                    <video
                      src={videoUrl} controls
                      style={{
                        width: '100%', maxWidth: videoFormat === 'reel' ? 360 : '100%',
                        borderRadius: 12, background: '#000', margin: '0 auto', display: 'block',
                      }}
                    />
                  )}
                  {status.result?.metadata?.title && (
                    <div style={{
                      background: 'var(--bg-surface)', border: '1px solid var(--border)',
                      borderRadius: 12, padding: 16,
                    }}>
                      <strong>{status.result.metadata.title}</strong>
                      <p style={{ color: 'var(--text-muted)', marginBottom: 0 }}>
                        {status.result.metadata.description}
                      </p>
                    </div>
                  )}
                </div>
              )}

              {!busy && !doneVideo && status.state !== 'error' && (
                <EmptyHint text={t('create.video.empty')} icon="🎬" />
              )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}

function EmptyHint({ text, icon = '📰' }: { text: string; icon?: string }) {
  return (
    <div style={{
      padding: '60px 30px', textAlign: 'center', height: '100%',
      background: 'var(--bg-surface)', border: '1px dashed var(--border)', borderRadius: 16,
      display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
    }}>
      <div style={{ fontSize: 44 }}>{icon}</div>
      <p style={{ color: 'var(--text-muted)', maxWidth: 360, marginTop: 12 }}>{text}</p>
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

function tab(on: boolean): React.CSSProperties {
  return {
    padding: '10px 18px', borderRadius: 10, cursor: 'pointer', fontSize: 14, fontWeight: 700,
    background: on ? 'var(--accent)' : 'var(--bg-surface)',
    color: on ? '#04211c' : 'var(--text)',
    border: `1px solid ${on ? 'var(--accent)' : 'var(--border)'}`,
  }
}

function segBtn(on: boolean): React.CSSProperties {
  return {
    display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6,
    padding: '9px 12px', borderRadius: 10, cursor: 'pointer', fontSize: 13, fontWeight: 600,
    background: on ? 'var(--bg-elevated)' : 'transparent',
    color: 'var(--text)',
    border: `1px solid ${on ? 'var(--accent)' : 'var(--border)'}`,
  }
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

const statusBox: React.CSSProperties = {
  padding: 12, background: 'var(--bg-elevated)', border: '1px solid var(--border)',
  borderRadius: 10, margin: '8px 0',
}
