import { useEffect, useState } from 'react'
import { getWorldCupCalendar } from '../api/client'
import type { CalendarSummary } from '../types'

export default function Calendar() {
  const [cal, setCal] = useState<CalendarSummary | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    getWorldCupCalendar().then(setCal).catch(() => setError('No se pudo cargar el calendario.'))
  }, [])

  if (error) return <div><h1>Calendario</h1><p style={{ color: '#ff9db1' }}>{error}</p></div>
  if (!cal) return <div><h1>Calendario</h1><p>Cargando…</p></div>

  return (
    <div>
      <h1 style={{ marginTop: 0 }}>Calendario · Mundial 2026</h1>

      {/* Summary cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 20 }}>
        <Stat label="Partidos" value={cal.total_matches} />
        <Stat label="Días con partidos" value={cal.total_days} />
        <Stat label="Próximo día" value={cal.next_match_day ?? '—'} />
        <Stat label="Faltan" value={cal.days_until_next != null ? `${cal.days_until_next} días` : '—'} />
      </div>
      <p style={{ color: 'var(--text-muted)' }}>
        Del {cal.start} al {cal.end}. El próximo día con partidos hay{' '}
        <strong>{cal.next_match_day_count}</strong> juego(s) → resumen de ~
        {Math.min(3, Math.ceil(cal.next_match_day_count * 25 / 60))} min (reel).
      </p>

      {/* Day-by-day timeline */}
      <div style={{ display: 'grid', gap: 10, marginTop: 16 }}>
        {cal.days.map((d) => (
          <div key={d.date} style={{
            background: 'var(--bg-surface)', border: '1px solid var(--border)',
            borderRadius: 12, padding: '12px 16px',
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6 }}>
              <strong>{d.date}</strong>
              <span style={{
                fontSize: 12, padding: '2px 8px', borderRadius: 999,
                background: 'var(--bg-elevated)', color: 'var(--accent)',
              }}>{d.count} partido{d.count !== 1 ? 's' : ''}</span>
              <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>{d.phase}</span>
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
              {d.matches.map((m, i) => (
                <span key={i} style={{
                  fontSize: 13, padding: '3px 8px', borderRadius: 8,
                  background: 'var(--bg-elevated)', color: 'var(--text)',
                }}>
                  {m.team1} <span style={{ color: 'var(--text-muted)' }}>vs</span> {m.team2}
                </span>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div style={{ padding: 16, background: 'var(--bg-surface)', border: '1px solid var(--border)', borderRadius: 12 }}>
      <div style={{ fontSize: 24, fontWeight: 800, color: 'var(--accent)' }}>{value}</div>
      <div style={{ color: 'var(--text-muted)', fontSize: 13 }}>{label}</div>
    </div>
  )
}
