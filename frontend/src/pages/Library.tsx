import { useCallback, useEffect, useRef, useState } from 'react'
import {
  cancelScheduledUpload, deleteContent, getContent, getPendingUploads,
  getStatus, getUploadSchedule, publishVideo, scheduleUpload, uploadAllPending,
} from '../api/client'
import { useProfile } from '../components/useProfile'
import type { ContentRecord, GenerationStatus } from '../types'

export default function Library() {
  const { active } = useProfile()
  const [items, setItems] = useState<ContentRecord[]>([])
  const [status, setStatus] = useState<GenerationStatus>({ state: 'idle' })
  const poll = useRef<number | null>(null)

  function reload() {
    if (active) getContent(active).then(setItems).catch(() => setItems([]))
  }
  useEffect(reload, [active])

  // Poll the generation status so the library shows "generating" too.
  useEffect(() => {
    if (!active) return
    if (poll.current) window.clearInterval(poll.current)
    poll.current = window.setInterval(async () => {
      const s = await getStatus(active).catch(() => ({ state: 'idle' }) as GenerationStatus)
      setStatus(s)
      if (s.state === 'done') reload()
    }, 1500)
    return () => { if (poll.current) window.clearInterval(poll.current) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active])

  const generating = status.state === 'running'

  return (
    <div>
      <h1 style={{ marginTop: 0 }}>Biblioteca</h1>
      <p style={{ color: 'var(--text-muted)' }}>Contenido generado para este perfil.</p>

      {generating && (
        <div style={{
          padding: 14, marginBottom: 16, borderRadius: 12,
          background: 'var(--bg-elevated)', border: '1px solid var(--accent)',
        }}>
          🎬 <strong>Se está generando el vídeo…</strong>
          <span style={{ color: 'var(--text-muted)', marginLeft: 8 }}>{status.message}</span>
          <div style={{ height: 10, borderRadius: 999, background: 'var(--bg)', overflow: 'hidden', marginTop: 8 }}>
            <div style={{
              height: '100%', width: `${status.progress ?? 0}%`,
              background: 'linear-gradient(90deg, var(--accent), var(--accent-2))',
              transition: 'width .4s ease',
            }} />
          </div>
        </div>
      )}

      {active && <UploadPanel profileId={active} onChanged={reload} />}

      {!items.length && !generating &&
        <p style={{ color: 'var(--text-muted)' }}>Aún no hay contenido generado.</p>}

      <div style={{ display: 'grid', gap: 14, marginTop: 16 }}>
        {items.map((it) => (
          <Card key={it.id ?? it.fixture_id} item={it} profileId={active} onChanged={reload} />
        ))}
      </div>
    </div>
  )
}

// ── Publication panel: bulk upload + scheduled-upload queue ──────────
function UploadPanel({ profileId, onChanged }: { profileId: string; onChanged: () => void }) {
  const [pending, setPending] = useState<string[]>([])
  const [schedule, setSchedule] = useState<Awaited<ReturnType<typeof getUploadSchedule>>>([])
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')

  const load = useCallback(() => {
    getPendingUploads(profileId).then(setPending).catch(() => setPending([]))
    getUploadSchedule(profileId).then(setSchedule).catch(() => setSchedule([]))
  }, [profileId])
  useEffect(load, [load])

  async function onBulk() {
    if (!pending.length || !confirm(`¿Subir ${pending.length} vídeo(s) a YouTube ahora?`)) return
    setBusy(true); setMsg('')
    try {
      const r = await uploadAllPending(profileId)
      const fails = r.results.filter((x) => !x.ok)
      setMsg(fails.length ? `Subidos ${r.uploaded.length}, ${fails.length} con error` : `✅ Subidos ${r.uploaded.length}`)
      load(); onChanged()
    } catch (e: any) {
      setMsg(e?.response?.data?.detail ?? 'Error al subir')
    } finally { setBusy(false) }
  }

  const upcoming = schedule.filter((s) => s.status === 'pending')

  return (
    <div style={{
      padding: 16, marginBottom: 18, borderRadius: 12,
      background: 'var(--bg-surface)', border: '1px solid var(--border)',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
        <strong style={{ fontSize: 15 }}>📤 Publicación a YouTube</strong>
        <button onClick={onBulk} disabled={busy || !pending.length} style={{
          padding: '8px 14px', borderRadius: 8, border: 'none', fontWeight: 600,
          cursor: busy || !pending.length ? 'not-allowed' : 'pointer',
          opacity: busy || !pending.length ? 0.6 : 1, background: '#ff0033', color: 'white',
        }}>
          {busy ? 'Subiendo…' : `Subir todos los pendientes (${pending.length})`}
        </button>
        {msg && <span style={{ color: 'var(--text-muted)', fontSize: 13 }}>{msg}</span>}
      </div>
      <p style={{ color: 'var(--text-muted)', fontSize: 12, margin: '8px 0 0' }}>
        Con la subida automática activada (Ajustes / .env) cada vídeo nuevo se publica solo.
        También puedes programar cada vídeo a una hora desde su tarjeta.
      </p>
      {upcoming.length > 0 && (
        <div style={{ marginTop: 12, display: 'grid', gap: 6 }}>
          <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>Programados:</span>
          {upcoming.map((s) => (
            <div key={s.content_id} style={{
              display: 'flex', alignItems: 'center', gap: 10, fontSize: 13,
              padding: '6px 10px', borderRadius: 8, background: 'var(--bg-elevated)',
            }}>
              <span>🕒 {new Date(s.when * 1000).toLocaleString()}</span>
              <span style={{ color: 'var(--text-muted)' }}>{s.content_id}</span>
              <button onClick={() => cancelScheduledUpload(profileId, s.content_id).then(load)}
                style={{ marginLeft: 'auto', background: 'transparent', border: '1px solid var(--border)',
                         borderRadius: 6, color: '#ff9db1', cursor: 'pointer', padding: '2px 8px' }}>
                Cancelar
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// Schedule a single content item to upload at a chosen local datetime.
export function useScheduleUpload(profileId: string) {
  return useCallback(async (contentId: string) => {
    const v = prompt('¿A qué hora subir? (formato: 2026-06-10 18:00)')
    if (!v) return
    const when = new Date(v.replace(' ', 'T')).getTime() / 1000
    if (Number.isNaN(when)) { alert('Fecha no válida'); return }
    await scheduleUpload(profileId, contentId, when)
    alert('Programado ✓')
  }, [profileId])
}

function Card({ item, profileId, onChanged }: {
  item: ContentRecord; profileId: string; onChanged: () => void
}) {
  const [open, setOpen] = useState(false)          // minimized by default
  const [privacy, setPrivacy] = useState('private')
  const [publishing, setPublishing] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const schedule = useScheduleUpload(profileId)

  const title = item.metadata?.title ?? item.scoreline ?? (item.day ? `Resumen ${item.day}` : 'Vídeo')

  async function onPublish() {
    if (item.fixture_id == null) return
    setPublishing(true); setMsg(null)
    try {
      const r = await publishVideo(profileId, item.fixture_id, privacy)
      setMsg({ ok: true, text: `Publicado (${r.privacy})` })
      onChanged()
    } catch (e: any) {
      setMsg({ ok: false, text: e?.response?.data?.detail ?? 'No se pudo publicar' })
    } finally {
      setPublishing(false)
    }
  }

  async function onDelete(e: React.MouseEvent) {
    e.stopPropagation()
    if (!item.id || !confirm(`¿Eliminar "${title}"?`)) return
    setDeleting(true)
    try {
      await deleteContent(profileId, item.id)
      onChanged()
    } catch {
      setDeleting(false)
    }
  }

  return (
    <div style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)', borderRadius: 12 }}>
      {/* Clickable header: minimize / maximize + delete */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '12px 16px' }}>
        <button onClick={() => setOpen(!open)} style={{
          flex: 1, display: 'flex', alignItems: 'center', gap: 10, background: 'none',
          border: 'none', color: 'var(--text)', cursor: 'pointer', textAlign: 'left',
        }}>
          <span style={{ color: 'var(--text-muted)', width: 14 }}>{open ? '▾' : '▸'}</span>
          {item.video_url ? '🎬' : '📄'}
          <strong style={{ fontSize: 16 }}>{title}</strong>
          {item.youtube_url && <span style={{ color: 'var(--accent)', fontSize: 12 }}>· en YouTube</span>}
        </button>
        <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>{item.generated_at}</span>
        <button onClick={onDelete} disabled={deleting} title="Eliminar"
          style={{
            background: 'transparent', border: '1px solid var(--border)', borderRadius: 8,
            color: '#ff9db1', cursor: 'pointer', padding: '4px 10px',
          }}>
          {deleting ? '…' : '🗑'}
        </button>
      </div>

      {/* Expandable detail */}
      {open && (
        <div style={{ padding: '0 16px 16px', borderTop: '1px solid var(--border)' }}>
          {item.video_url && (
            <div style={{
              width: 260, aspectRatio: '9 / 16', marginTop: 12,
              borderRadius: 12, overflow: 'hidden', background: '#000',
            }}>
              <video src={item.video_url} controls
                style={{ width: '100%', height: '100%', objectFit: 'contain', display: 'block' }} />
            </div>
          )}

          {item.narration && <p style={{ lineHeight: 1.5 }}>{item.narration}</p>}

          {item.metadata?.tags && (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 8 }}>
              {item.metadata.tags.map((t) => (
                <span key={t} style={{
                  fontSize: 12, padding: '2px 8px', borderRadius: 999,
                  background: 'var(--bg-elevated)', color: 'var(--text-muted)',
                }}>#{t}</span>
              ))}
            </div>
          )}

          {/* Publishing goes through the per-match endpoint (match_<fixture_id>),
              so it only applies to single-match videos. Digests have no
              fixture_id and are not publishable yet — hide the controls. */}
          {item.video_url && item.fixture_id != null && (
            <div style={{ marginTop: 14, display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
              {item.youtube_url ? (
                <a href={item.youtube_url} target="_blank" rel="noreferrer"
                  style={{ color: 'var(--accent)', fontWeight: 600 }}>
                  ✅ Publicado en YouTube ↗
                </a>
              ) : (
                <>
                  <select value={privacy} onChange={(e) => setPrivacy(e.target.value)} style={select}>
                    <option value="private">Privado</option>
                    <option value="unlisted">Oculto</option>
                    <option value="public">Público</option>
                  </select>
                  <button onClick={onPublish} disabled={publishing} style={publishBtn}>
                    {publishing ? 'Publicando…' : 'Enviar a YouTube'}
                  </button>
                  {item.id && (
                    <button onClick={() => schedule(item.id!)} style={select} title="Subir a una hora">
                      🕒 Programar
                    </button>
                  )}
                </>
              )}
              {msg && (
                <span style={{ color: msg.ok ? 'var(--accent)' : '#ff9db1', fontSize: 13 }}>
                  {msg.ok ? '✅' : '⚠️'} {msg.text}
                </span>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

const select: React.CSSProperties = {
  padding: '8px 10px', borderRadius: 8, background: 'var(--bg-elevated)',
  color: 'var(--text)', border: '1px solid var(--border)',
}
const publishBtn: React.CSSProperties = {
  padding: '8px 14px', borderRadius: 8, background: '#ff0033',
  color: 'white', border: 'none', cursor: 'pointer', fontWeight: 600,
}
