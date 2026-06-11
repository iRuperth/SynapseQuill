import { useEffect, useRef, useState } from 'react'
import { cancelGeneration, generate, generateDigest, getContent, getMatchDetail, getMatches, getStatus } from '../api/client'
import { useProfile } from '../components/useProfile'
import { useT } from '../i18n/useT'
import type { GenerationStatus, Match, MatchDetail } from '../types'

// Pipeline steps that map to a friendly catalog label (matches.step.*).
const STEP_KEYS = [
  'start', 'enrich', 'narrate', 'guardrail', 'metadata',
  'media', 'voice', 'video', 'social', 'upload', 'done',
]

export default function Matches() {
  const t = useT()
  const { active } = useProfile()
  // Empty day = let the backend show the latest finished matches of the
  // configured competition (so La Liga 2023 / past seasons show up too).
  const [day, setDay] = useState<string>('')
  const [matches, setMatches] = useState<Match[]>([])
  const [error, setError] = useState<string>('')
  const [loading, setLoading] = useState(false)
  const [status, setStatus] = useState<GenerationStatus>({ state: 'idle' })
  const [format, setFormat] = useState<string>('reel')
  // Digest selection (empty = whole matchday) + free-form angle for intro/outro.
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [brief, setBrief] = useState<string>('')
  // Fixture ids that already have a generated video (→ "Created" instead of "Generate").
  const [createdIds, setCreatedIds] = useState<Set<number>>(new Set())
  const poll = useRef<number | null>(null)

  async function loadCreated() {
    if (!active) return
    try {
      const content = await getContent(active)
      setCreatedIds(new Set(content.map((c) => c.fixture_id).filter((x): x is number => !!x)))
    } catch { /* ignore — the "Created" badge is best-effort */ }
  }

  async function load() {
    if (!active) return
    setLoading(true); setError('')
    try {
      setMatches(await getMatches(active, day || undefined))
      loadCreated()
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? t('matches.loadError'))
      setMatches([])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() /* eslint-disable-next-line */ }, [active, day])

  // Clear the status poll when leaving the page.
  useEffect(() => () => { if (poll.current) window.clearInterval(poll.current) }, [])

  function startPolling() {
    if (poll.current) window.clearInterval(poll.current)
    poll.current = window.setInterval(async () => {
      if (!active) return
      const s = await getStatus(active)
      setStatus(s)
      if (s.state === 'done' || s.state === 'error' || s.state === 'idle') {
        if (poll.current) window.clearInterval(poll.current)
        if (s.state === 'done') loadCreated()   // refresh the "Created" badges
      }
    }, 1500)
  }

  async function onGenerate(m: Match) {
    if (!active) return
    setStatus({ state: 'running', step: 'start', message: t('matches.starting') })
    await generate(active, m.fixture_id, { do_video: true, do_upload: false, format })
    startPolling()
  }

  async function onDigest() {
    if (!active) return
    setStatus({ state: 'running', step: 'start', message: t('matches.preparingDigest') })
    await generateDigest(active, {
      day: day || undefined,
      // The recap is horizontal by default; honour an explicit reel choice.
      format: format === 'reel' ? 'reel' : 'youtube',
      fixture_ids: selected.size ? [...selected] : undefined,  // empty = whole matchday
      brief: brief.trim() || undefined,
    })
    startPolling()
  }

  function toggleSelect(id: number) {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id); else next.add(id)
      return next
    })
  }

  const busy = status.state === 'running'

  return (
    <div>
      <h1 style={{ marginTop: 0 }}>{t('matches.title')}</h1>
      <p style={{ color: 'var(--text-muted)' }}>
        {t('matches.intro')}
      </p>

      <div style={{ display: 'flex', gap: 12, alignItems: 'flex-end', margin: '16px 0', flexWrap: 'wrap' }}>
        <label style={{ display: 'grid', gap: 4 }}>
          <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>{t('matches.filterByDate')}</span>
          <input type="date" value={day} onChange={(e) => setDay(e.target.value)}
            style={inputStyle} />
        </label>
        <label style={{ display: 'grid', gap: 4 }}>
          <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>{t('matches.format')}</span>
          <select value={format} onChange={(e) => setFormat(e.target.value)} style={inputStyle}>
            <option value="reel">{t('matches.format.reel')}</option>
            <option value="youtube">{t('matches.format.youtube')}</option>
          </select>
        </label>
        {day && <button onClick={() => setDay('')} style={{ ...btnStyle, background: 'var(--bg-elevated)' }}>{t('matches.viewLatest')}</button>}
        <button onClick={load} style={btnStyle}>{t('matches.refresh')}</button>
        <button onClick={onDigest} disabled={busy}
          style={{ ...btnStyle, background: 'var(--accent)', color: '#04201c', opacity: busy ? 0.5 : 1 }}>
          🎬 {selected.size
            ? t('matches.digestSelected', { count: selected.size })
            : t('matches.dayDigest')}
        </button>
        {selected.size > 0 && (
          <button onClick={() => setSelected(new Set())} style={{ ...btnStyle, background: 'var(--bg-elevated)' }}>
            {t('matches.clearSelection')}
          </button>
        )}
      </div>

      {/* Recap angle (free-form): woven into the digest's intro + outro. */}
      <label style={{ display: 'grid', gap: 4, margin: '0 0 8px', maxWidth: 640 }}>
        <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>{t('matches.digestBriefLabel')}</span>
        <input value={brief} onChange={(e) => setBrief(e.target.value)}
          placeholder={t('matches.digestBriefPlaceholder')} style={inputStyle} />
      </label>

      <p style={{ color: 'var(--text-muted)', fontSize: 13, marginTop: -4 }}>
        {selected.size
          ? t('matches.digestHintSelected', { count: selected.size })
          : t('matches.digestHintWhole')}
      </p>

      {error && <div style={errorBox}>{error}</div>}
      {loading && <p>{t('common.loading')}</p>}

      {busy && (
        <div style={statusBox}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
            <span style={{ fontSize: 17 }}>
              🎬 <strong>{t('matches.generatingVideo')}</strong>
              <span style={{ color: 'var(--text-muted)', marginLeft: 8 }}>
                {status.step && STEP_KEYS.includes(status.step)
                  ? t(`matches.step.${status.step}`)
                  : status.message}
              </span>
            </span>
            <button onClick={() => active && cancelGeneration(active)}
              style={{ ...btnStyle, background: 'transparent', border: '1px solid var(--border)', padding: '4px 10px' }}>
              {t('common.cancel')}
            </button>
          </div>
          {/* Progress bar */}
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
      {status.state === 'done' && (
        <div style={{ ...statusBox, borderColor: 'var(--accent)' }}>
          ✅ {t('matches.done')}: {status.result?.scoreline}. {t('matches.doneSeeLibraryBefore')} <strong>{t('nav.library')}</strong> {t('matches.doneSeeLibraryAfter')}
        </div>
      )}

      <div style={{ display: 'grid', gap: 10, marginTop: 16 }}>
        {matches.map((m) => (
          <MatchRow key={m.fixture_id} profileId={active} match={m}
            busy={busy} created={createdIds.has(m.fixture_id)} onGenerate={onGenerate}
            checked={selected.has(m.fixture_id)} onToggle={() => toggleSelect(m.fixture_id)} />
        ))}
        {!loading && !matches.length && !error && (
          <p style={{ color: 'var(--text-muted)' }}>{t('matches.noMatches')}</p>
        )}
      </div>
    </div>
  )
}

function MatchRow({ profileId, match: m, busy, created, onGenerate, checked, onToggle }: {
  profileId: string; match: Match; busy: boolean; created: boolean
  onGenerate: (m: Match) => void
  checked: boolean; onToggle: () => void
}) {
  const t = useT()
  const [open, setOpen] = useState(false)
  const [detail, setDetail] = useState<MatchDetail | null>(null)
  const [loading, setLoading] = useState(false)

  async function toggle() {
    const next = !open
    setOpen(next)
    if (next && !detail) {
      setLoading(true)
      try {
        setDetail(await getMatchDetail(profileId, m.fixture_id))
      } catch { /* ignore */ } finally { setLoading(false) }
    }
  }

  const when = formatKickoff(m.kickoff || m.date)

  return (
    <div style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)', borderRadius: 12 }}>
      {/* Clickable header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '14px 16px', gap: 12, flexWrap: 'wrap' }}>
        {/* Select for the recap (finished matches only). */}
        {m.finished && (
          <input type="checkbox" checked={checked} onChange={onToggle}
            title={t('matches.selectForDigest')}
            style={{ width: 18, height: 18, cursor: 'pointer', accentColor: 'var(--accent)' }} />
        )}
        <button onClick={toggle} style={{
          display: 'flex', alignItems: 'center', gap: 10, background: 'none',
          border: 'none', color: 'var(--text)', cursor: 'pointer', textAlign: 'left', flex: 1, minWidth: 280,
        }}>
          <span style={{ color: 'var(--text-muted)', width: 14 }}>{open ? '▾' : '▸'}</span>
          {m.home_logo && <img src={m.home_logo} alt="" width={24} height={24} />}
          <strong>{m.home}</strong>
          <span style={{ color: 'var(--accent)' }}>{m.home_goals ?? '-'} : {m.away_goals ?? '-'}</span>
          <strong>{m.away}</strong>
          {m.away_logo && <img src={m.away_logo} alt="" width={24} height={24} />}
          <span style={statusPill(m.finished)}>{m.status}</span>
          {when && (
            <span style={{ color: 'var(--text-muted)', fontSize: 12, marginLeft: 4 }}>
              🗓 {when}
            </span>
          )}
        </button>
        {created ? (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginLeft: 'auto' }}>
            <span style={{ color: 'var(--accent)', fontSize: 13, fontWeight: 600 }}>✅ {t('matches.created')}</span>
            <button disabled={!m.finished || busy} onClick={() => onGenerate(m)}
              style={{ ...btnStyle, background: 'var(--bg-elevated)', color: 'var(--text)',
                border: '1px solid var(--border)', opacity: !m.finished || busy ? 0.5 : 1 }}>
              {t('matches.regenerate')}
            </button>
          </div>
        ) : (
          <button disabled={!m.finished || busy} onClick={() => onGenerate(m)}
            style={{ ...btnStyle, opacity: !m.finished || busy ? 0.5 : 1, marginLeft: 'auto' }}>
            {t('matches.generateVideo')}
          </button>
        )}
      </div>

      {/* Expandable detail */}
      {open && (
        <div style={{ padding: '0 16px 16px', borderTop: '1px solid var(--border)' }}>
          {loading && <p style={{ color: 'var(--text-muted)' }}>{t('matches.loadingDetail')}</p>}
          {detail && (
            <div style={{ display: 'grid', gap: 12, marginTop: 12 }}>
              <div style={{ color: 'var(--text-muted)', fontSize: 13 }}>
                {detail.competition} · {detail.date}
                {detail.venue && ` · ${detail.venue}`}
                {detail.city && `, ${detail.city}`}
              </div>

              {detail.goals.length > 0 && (
                <div>
                  <div style={sectionTitle}>⚽ {t('matches.goals')}</div>
                  {detail.goals.map((g, i) => (
                    <div key={i} style={{ fontSize: 14, padding: '3px 0' }}>
                      <span style={{ color: 'var(--accent)', fontWeight: 700 }}>{g.minute}'</span>{' '}
                      <strong>{g.player}</strong> <span style={{ color: 'var(--text-muted)' }}>({g.team})</span>
                      {g.kind !== 'Normal Goal' && <em style={{ color: 'var(--text-muted)' }}> · {g.kind}</em>}
                    </div>
                  ))}
                </div>
              )}

              {detail.cards.length > 0 && (
                <div>
                  <div style={sectionTitle}>🟨 {t('matches.cards')}</div>
                  {detail.cards.map((c, i) => (
                    <div key={i} style={{ fontSize: 14, padding: '3px 0' }}>
                      <span style={{
                        display: 'inline-block', width: 12, height: 16, borderRadius: 2, marginRight: 6,
                        background: c.color === 'Red' ? '#ef4444' : '#facc15', verticalAlign: 'middle',
                      }} />
                      <span style={{ color: 'var(--accent)', fontWeight: 700 }}>{c.minute}'</span>{' '}
                      {c.player} <span style={{ color: 'var(--text-muted)' }}>({c.team})</span>
                    </div>
                  ))}
                </div>
              )}

              {!detail.goals.length && !detail.cards.length && (
                <p style={{ color: 'var(--text-muted)' }}>{t('matches.noEvents')}</p>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// Format a kickoff time. Accepts a full ISO datetime ("2026-06-08T19:00Z") and
// shows local date + time; falls back to just the date for a "YYYY-MM-DD" value.
function formatKickoff(value?: string): string {
  if (!value) return ''
  const hasTime = value.includes('T')
  const d = new Date(value)
  if (isNaN(d.getTime())) return value            // unparseable → show raw
  const date = d.toLocaleDateString(undefined, { day: '2-digit', month: 'short', year: 'numeric' })
  if (!hasTime) return date
  const time = d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
  return `${date} · ${time}`
}

const sectionTitle: React.CSSProperties = {
  fontSize: 13, fontWeight: 700, color: 'var(--text)', marginBottom: 4, letterSpacing: 0.3,
}

const inputStyle: React.CSSProperties = {
  padding: '8px 10px', borderRadius: 8, background: 'var(--bg-elevated)',
  color: 'var(--text)', border: '1px solid var(--border)',
}
const btnStyle: React.CSSProperties = {
  padding: '8px 14px', borderRadius: 8, background: 'var(--accent-2)',
  color: 'white', border: 'none', cursor: 'pointer', fontWeight: 600,
}
const errorBox: React.CSSProperties = {
  padding: 12, background: '#3a1f2a', border: '1px solid #7a3650',
  borderRadius: 10, color: '#ffb3c7',
}
const statusBox: React.CSSProperties = {
  padding: 12, background: 'var(--bg-elevated)', border: '1px solid var(--border)',
  borderRadius: 10, margin: '8px 0',
}
const statusPill = (finished: boolean): React.CSSProperties => ({
  marginLeft: 8, padding: '2px 8px', borderRadius: 999, fontSize: 12,
  background: finished ? '#13392f' : '#2a3656',
  color: finished ? 'var(--accent)' : 'var(--text-muted)',
})
