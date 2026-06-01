import { useEffect, useState } from 'react'
import { getContent, publishVideo } from '../api/client'
import { useProfile } from '../components/useProfile'
import type { ContentRecord } from '../types'

export default function Library() {
  const { active } = useProfile()
  const [items, setItems] = useState<ContentRecord[]>([])

  function reload() {
    if (active) getContent(active).then(setItems).catch(() => setItems([]))
  }
  useEffect(reload, [active])

  return (
    <div>
      <h1 style={{ marginTop: 0 }}>Biblioteca</h1>
      <p style={{ color: 'var(--text-muted)' }}>Contenido generado para este perfil.</p>

      {!items.length && <p style={{ color: 'var(--text-muted)' }}>Aún no hay contenido generado.</p>}

      <div style={{ display: 'grid', gap: 14, marginTop: 16 }}>
        {items.map((it) => (
          <Card key={it.fixture_id} item={it} profileId={active} onPublished={reload} />
        ))}
      </div>
    </div>
  )
}

function Card({ item, profileId, onPublished }: {
  item: ContentRecord; profileId: string; onPublished: () => void
}) {
  const [privacy, setPrivacy] = useState('private')
  const [publishing, setPublishing] = useState(false)
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)

  async function onPublish() {
    setPublishing(true); setMsg(null)
    try {
      const r = await publishVideo(profileId, item.fixture_id, privacy)
      setMsg({ ok: true, text: `Publicado (${r.privacy})` })
      onPublished()
    } catch (e: any) {
      setMsg({ ok: false, text: e?.response?.data?.detail ?? 'No se pudo publicar' })
    } finally {
      setPublishing(false)
    }
  }

  return (
    <div style={{
      padding: 18, background: 'var(--bg-surface)',
      border: '1px solid var(--border)', borderRadius: 12,
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between' }}>
        <strong style={{ fontSize: 18 }}>{item.metadata?.title ?? item.scoreline}</strong>
        <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>{item.generated_at}</span>
      </div>

      {item.video_url && (
        <video src={item.video_url} controls
          style={{ width: '100%', borderRadius: 8, marginTop: 10, background: '#000' }} />
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

      {/* Publish to YouTube */}
      {item.video_url && (
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
