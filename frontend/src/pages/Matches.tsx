import { useEffect, useRef, useState } from 'react'
import { cancelGeneration, generate, getMatches, getStatus } from '../api/client'
import { useProfile } from '../components/useProfile'
import type { GenerationStatus, Match } from '../types'

// Friendly Spanish label for each pipeline step.
const STEP_LABEL: Record<string, string> = {
  start: 'Preparando…',
  enrich: 'Buscando goleadores…',
  narrate: 'Escribiendo la narración…',
  guardrail: 'Verificando los datos…',
  metadata: 'Generando título y etiquetas…',
  media: 'Creando las imágenes…',
  voice: 'Grabando la voz y subtítulos…',
  video: 'Montando el vídeo…',
  social: 'Generando texto para redes…',
  upload: 'Subiendo a YouTube…',
  done: 'Casi listo…',
}

export default function Matches() {
  const { active } = useProfile()
  // Empty day = let the backend show the latest finished matches of the
  // configured competition (so La Liga 2023 / past seasons show up too).
  const [day, setDay] = useState<string>('')
  const [matches, setMatches] = useState<Match[]>([])
  const [error, setError] = useState<string>('')
  const [loading, setLoading] = useState(false)
  const [status, setStatus] = useState<GenerationStatus>({ state: 'idle' })
  const poll = useRef<number | null>(null)

  async function load() {
    if (!active) return
    setLoading(true); setError('')
    try {
      setMatches(await getMatches(active, day || undefined))
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? 'No se pudieron cargar los partidos. ¿Falta APIFOOTBALL_KEY?')
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
      }
    }, 1500)
  }

  async function onGenerate(m: Match) {
    if (!active) return
    setStatus({ state: 'running', step: 'start', message: 'Iniciando...' })
    await generate(active, m.fixture_id, { do_video: true, do_upload: false })
    startPolling()
  }

  const busy = status.state === 'running'

  return (
    <div>
      <h1 style={{ marginTop: 0 }}>Partidos</h1>
      <p style={{ color: 'var(--text-muted)' }}>
        Elige un partido finalizado y genera su resumen en vídeo (narración + imágenes + subtítulos).
        Por defecto se muestran los últimos partidos; puedes filtrar por fecha.
      </p>

      <div style={{ display: 'flex', gap: 12, alignItems: 'flex-end', margin: '16px 0' }}>
        <label style={{ display: 'grid', gap: 4 }}>
          <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>Filtrar por fecha (opcional)</span>
          <input type="date" value={day} onChange={(e) => setDay(e.target.value)}
            style={inputStyle} />
        </label>
        {day && <button onClick={() => setDay('')} style={{ ...btnStyle, background: 'var(--bg-elevated)' }}>Ver últimos</button>}
        <button onClick={load} style={btnStyle}>Actualizar</button>
      </div>

      <p style={{ color: 'var(--text-muted)', fontSize: 13, marginTop: -4 }}>
        {day ? `Mostrando partidos del ${day}` : 'Mostrando los últimos partidos finalizados'}
      </p>

      {error && <div style={errorBox}>{error}</div>}
      {loading && <p>Cargando…</p>}

      {busy && (
        <div style={statusBox}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
            <span style={{ fontSize: 17 }}>
              🎬 <strong>Generando vídeo…</strong>
              <span style={{ color: 'var(--text-muted)', marginLeft: 8 }}>
                {STEP_LABEL[status.step ?? ''] ?? status.message}
              </span>
            </span>
            <button onClick={() => active && cancelGeneration(active)}
              style={{ ...btnStyle, background: 'transparent', border: '1px solid var(--border)', padding: '4px 10px' }}>
              Cancelar
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
          ✅ Listo: {status.result?.scoreline}. Mira la <strong>Biblioteca</strong> para verlo y publicarlo.
        </div>
      )}

      <div style={{ display: 'grid', gap: 10, marginTop: 16 }}>
        {matches.map((m) => (
          <div key={m.fixture_id} style={cardStyle}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              {m.home_logo && <img src={m.home_logo} alt="" width={24} height={24} />}
              <strong>{m.home}</strong>
              <span style={{ color: 'var(--accent)' }}>
                {m.home_goals ?? '-'} : {m.away_goals ?? '-'}
              </span>
              <strong>{m.away}</strong>
              {m.away_logo && <img src={m.away_logo} alt="" width={24} height={24} />}
              <span style={statusPill(m.finished)}>{m.status}</span>
            </div>
            <button
              disabled={!m.finished || busy}
              onClick={() => onGenerate(m)}
              style={{ ...btnStyle, opacity: !m.finished || busy ? 0.5 : 1 }}
            >
              Generar vídeo
            </button>
          </div>
        ))}
        {!loading && !matches.length && !error && (
          <p style={{ color: 'var(--text-muted)' }}>No hay partidos ese día.</p>
        )}
      </div>
    </div>
  )
}

const inputStyle: React.CSSProperties = {
  padding: '8px 10px', borderRadius: 8, background: 'var(--bg-elevated)',
  color: 'var(--text)', border: '1px solid var(--border)',
}
const btnStyle: React.CSSProperties = {
  padding: '8px 14px', borderRadius: 8, background: 'var(--accent-2)',
  color: 'white', border: 'none', cursor: 'pointer', fontWeight: 600,
}
const cardStyle: React.CSSProperties = {
  display: 'flex', justifyContent: 'space-between', alignItems: 'center',
  padding: '14px 16px', background: 'var(--bg-surface)',
  border: '1px solid var(--border)', borderRadius: 12,
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
