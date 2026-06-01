import { useEffect, useState } from 'react'
import { getContent } from '../api/client'
import { useProfile } from '../components/useProfile'
import type { ContentRecord } from '../types'

export default function Library() {
  const { active } = useProfile()
  const [items, setItems] = useState<ContentRecord[]>([])

  useEffect(() => {
    if (active) getContent(active).then(setItems).catch(() => setItems([]))
  }, [active])

  return (
    <div>
      <h1 style={{ marginTop: 0 }}>Biblioteca</h1>
      <p style={{ color: 'var(--text-muted)' }}>Contenido generado para este perfil.</p>

      {!items.length && <p style={{ color: 'var(--text-muted)' }}>Aún no hay contenido generado.</p>}

      <div style={{ display: 'grid', gap: 14, marginTop: 16 }}>
        {items.map((it) => (
          <div key={it.fixture_id} style={{
            padding: 18, background: 'var(--bg-surface)',
            border: '1px solid var(--border)', borderRadius: 12,
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <strong style={{ fontSize: 18 }}>{it.metadata?.title ?? it.scoreline}</strong>
              <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>{it.generated_at}</span>
            </div>
            {it.video_url && (
              <video
                src={it.video_url}
                controls
                style={{ width: '100%', borderRadius: 8, marginTop: 10, background: '#000' }}
              />
            )}
            {it.narration && (
              <p style={{ color: 'var(--text)', lineHeight: 1.5 }}>{it.narration}</p>
            )}
            {it.metadata?.tags && (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 8 }}>
                {it.metadata.tags.map((t) => (
                  <span key={t} style={{
                    fontSize: 12, padding: '2px 8px', borderRadius: 999,
                    background: 'var(--bg-elevated)', color: 'var(--text-muted)',
                  }}>#{t}</span>
                ))}
              </div>
            )}
            {it.youtube_url && (
              <a href={it.youtube_url} target="_blank" rel="noreferrer"
                style={{ color: 'var(--accent)', display: 'inline-block', marginTop: 8 }}>
                Ver en YouTube ↗
              </a>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}
