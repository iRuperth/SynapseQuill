import { useEffect, useState } from 'react'
import { getPowerRanking, getWorldCupBracket } from '../api/client'
import { useT } from '../i18n/useT'
import type { Bracket, BracketMatch, BracketSlot, PowerRanking } from '../types'

const HOUR = 60 * 60 * 1000

export default function PowerRankings() {
  const t = useT()
  const [tab, setTab] = useState<'bracket' | 'power'>('power')
  const [bracket, setBracket] = useState<Bracket | null>(null)
  const [power, setPower] = useState<PowerRanking | null>(null)
  const [bracketErr, setBracketErr] = useState('')
  const [powerErr, setPowerErr] = useState('')

  // Load both data sets, then refresh hourly. A gentle setInterval — NOT a tight
  // poll — with cleanup on unmount and an `alive` guard so a late response can't
  // set state after we've navigated away.
  useEffect(() => {
    let alive = true
    const load = () => {
      getWorldCupBracket()
        .then((b) => alive && setBracket(b))
        .catch(() => alive && setBracketErr(t('ranking.error')))
      getPowerRanking()
        .then((p) => alive && setPower(p))
        .catch(() => alive && setPowerErr(t('ranking.error')))
    }
    load()
    const id = setInterval(load, HOUR)
    return () => {
      alive = false
      clearInterval(id)
    }
  }, [t])

  return (
    <div>
      <h1 style={{ marginTop: 0 }}>{t('ranking.title')}</h1>

      {/* Tabs */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 20 }}>
        <TabButton active={tab === 'power'} onClick={() => setTab('power')}>
          {t('ranking.tab.power')}
        </TabButton>
        <TabButton active={tab === 'bracket'} onClick={() => setTab('bracket')}>
          {t('ranking.tab.bracket')}
        </TabButton>
      </div>

      {tab === 'power'
        ? <PowerView power={power} error={powerErr} t={t} />
        : <BracketView bracket={bracket} error={bracketErr} t={t} />}
    </div>
  )
}

type T = ReturnType<typeof useT>

function TabButton({ active, onClick, children }: {
  active: boolean; onClick: () => void; children: React.ReactNode
}) {
  return (
    <button
      onClick={onClick}
      style={{
        padding: '8px 16px', borderRadius: 8, fontSize: 14, fontWeight: 600,
        cursor: 'pointer', border: '1px solid var(--border)',
        background: active ? 'var(--accent)' : 'var(--bg-surface)',
        color: active ? '#fff' : 'var(--text-muted)',
      }}
    >
      {children}
    </button>
  )
}

// ── World Cup bracket ──────────────────────────────────────────────
function BracketView({ bracket, error, t }: { bracket: Bracket | null; error: string; t: T }) {
  if (error) return <p style={{ color: '#ff9db1' }}>{error}</p>
  if (!bracket) return <p>{t('common.loading')}</p>

  const main = bracket.rounds.filter((r) => r.key !== 'third')
  const third = bracket.rounds.find((r) => r.key === 'third')

  return (
    <div>
      <style>{BRACKET_CSS}</style>
      <div className="bkt-grid">
        {main.map((round, ci) => (
          <div
            key={round.key}
            className="bkt-col"
            data-first={ci === 0 ? '' : undefined}
            data-last={ci === main.length - 1 ? '' : undefined}
          >
            <h3 className="bkt-round-title">{t(`ranking.round.${round.key}`)}</h3>
            <div className="bkt-matches">
              {round.matches.map((m) => <MatchCard key={m.num} m={m} t={t} />)}
            </div>
          </div>
        ))}
      </div>

      {third && third.matches[0] && (
        <div style={{ marginTop: 24, maxWidth: 230 }}>
          <h3 style={{ margin: '0 0 8px', fontSize: 14, color: 'var(--text-muted)' }}>
            {t('ranking.round.third')}
          </h3>
          <MatchCard m={third.matches[0]} t={t} />
        </div>
      )}

      <p style={{ color: 'var(--text-muted)', fontSize: 12, marginTop: 16 }}>
        {t('ranking.updated', { time: bracket.updated_at.replace('T', ' ') })}
      </p>
    </div>
  )
}

// Connector lines drawn with CSS so the inline-styled cards stay untouched.
// Each match gets a stub that exits right (──) and, paired up, a vertical bracket
// (the second of every pair draws the joining line up to its sibling). The next
// column's matches get a short entry stub on the left. The first column emits no
// entry stub; the last (Final) emits no exit stub.
const CONNECT = 18           // horizontal stub length (half the column gap of 36)
const LINE = '2px solid var(--border)'
const BRACKET_CSS = `
.bkt-grid { display: grid; grid-auto-flow: column;
  grid-auto-columns: minmax(190px, 1fr); column-gap: ${CONNECT * 2}px;
  overflow-x: auto; align-items: stretch; padding-bottom: 8px; }
.bkt-col { display: flex; flex-direction: column; }
.bkt-round-title { margin: 0 0 8px; font-size: 14px; color: var(--accent); }
.bkt-matches { flex: 1; display: flex; flex-direction: column;
  justify-content: space-around; gap: 12px; }
.bkt-match { position: relative; }
/* exit stub: line going right out of every match (except the Final column) */
.bkt-col:not([data-last]) .bkt-match::after {
  content: ''; position: absolute; top: 50%; left: 100%;
  width: ${CONNECT}px; border-top: ${LINE}; }
/* vertical joiner: every even-indexed (2nd of a pair) match draws a line up to
   the previous sibling so the pair converges toward the next round */
.bkt-col:not([data-last]) .bkt-match:nth-child(even)::before {
  content: ''; position: absolute; right: -${CONNECT}px; bottom: 50%;
  height: calc(100% + 12px); border-right: ${LINE}; }
/* entry stub: line coming in from the left into every match (except column 1) */
.bkt-col:not([data-first]) .bkt-match .bkt-entry {
  position: absolute; top: 50%; right: 100%; width: ${CONNECT}px;
  border-top: ${LINE}; }
`

function MatchCard({ m, t }: { m: BracketMatch; t: T }) {
  return (
    <div className="bkt-match">
      <span className="bkt-entry" />
      <div style={{
        background: 'var(--bg-surface)', border: '1px solid var(--border)',
        borderRadius: 10, padding: '8px 10px',
        outline: m.status === 'LIVE' ? '2px solid var(--accent)' : 'none',
      }}>
        <SlotRow slot={m.team1} t={t} />
        <div style={{ height: 1, background: 'var(--border)', margin: '4px 0' }} />
        <SlotRow slot={m.team2} t={t} />
      </div>
    </div>
  )
}

function SlotRow({ slot, t }: { slot: BracketSlot; t: T }) {
  const resolved = !!slot.name
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 8,
      fontWeight: slot.winner ? 700 : 500,
      color: resolved ? 'var(--text)' : 'var(--text-muted)',
    }}>
      {slot.flag
        ? <img src={slot.flag} alt="" width={20} height={20} style={{ borderRadius: 3, objectFit: 'cover' }} />
        : <span style={{ width: 20, textAlign: 'center', opacity: 0.4 }}>·</span>}
      <span style={{ flex: 1, fontSize: 13, fontStyle: resolved ? 'normal' : 'italic' }}>
        {slot.name ?? (slot.label || t('ranking.tbd'))}
      </span>
      {slot.score != null && (
        <span style={{ fontVariantNumeric: 'tabular-nums', fontWeight: 700 }}>{slot.score}</span>
      )}
    </div>
  )
}

// ── Power ranking: the 48 WC teams by FIFA World Ranking ────────────
const MEDALS = ['🥇', '🥈', '🥉']

function PowerView({ power, error, t }: { power: PowerRanking | null; error: string; t: T }) {
  if (error) return <p style={{ color: '#ff9db1' }}>{error}</p>
  if (!power) return <p>{t('common.loading')}</p>

  const th: React.CSSProperties = {
    textAlign: 'right', padding: '8px 12px', fontSize: 12,
    color: 'var(--text-muted)', fontWeight: 600,
  }
  const td: React.CSSProperties = { textAlign: 'right', padding: '8px 12px', fontVariantNumeric: 'tabular-nums' }

  return (
    <div>
      <p style={{ color: 'var(--text-muted)', fontSize: 13, margin: '0 0 12px' }}>
        {t('ranking.power.subtitle', { source: power.source, date: power.as_of })}
      </p>
      <div style={{
        background: 'var(--bg-surface)', border: '1px solid var(--border)',
        borderRadius: 12, overflow: 'hidden',
      }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 14 }}>
          <thead>
            <tr style={{ borderBottom: '1px solid var(--border)' }}>
              <th style={{ ...th, textAlign: 'left' }}>{t('ranking.table.pos')}</th>
              <th style={{ ...th, textAlign: 'left' }}>{t('ranking.table.team')}</th>
              <th style={{ ...th, textAlign: 'left' }}>{t('ranking.table.group')}</th>
              <th style={th}>{t('ranking.table.fifaRank')}</th>
              <th style={{ ...th, color: 'var(--accent)' }}>{t('ranking.table.pts')}</th>
            </tr>
          </thead>
          <tbody>
            {power.rows.map((r) => (
              <tr key={r.team} style={{
                borderBottom: '1px solid var(--border)',
                background: r.pos <= 3 ? 'var(--bg-elevated)' : 'transparent',
              }}>
                <td style={{ ...td, textAlign: 'left', fontWeight: 700 }}>
                  {r.pos <= 3 ? MEDALS[r.pos - 1] : r.pos}
                </td>
                <td style={{ ...td, textAlign: 'left' }}>
                  <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    {r.flag && <img src={r.flag} alt="" width={22} height={22} style={{ borderRadius: 3, objectFit: 'cover' }} />}
                    {r.team}
                  </span>
                </td>
                <td style={{ ...td, textAlign: 'left', color: 'var(--text-muted)' }}>{r.group}</td>
                <td style={td}>{r.rank}</td>
                <td style={{ ...td, fontWeight: 800, color: 'var(--accent)' }}>
                  {r.points.toFixed(2)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
