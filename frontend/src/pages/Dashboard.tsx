import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { getContent, getProfile } from '../api/client'
import { useProfile } from '../components/useProfile'
import { useT } from '../i18n/useT'
import type { ContentRecord, Profile } from '../types'

export default function Dashboard() {
  const t = useT()
  const { active } = useProfile()
  const [profile, setProfile] = useState<Profile | null>(null)
  const [items, setItems] = useState<ContentRecord[]>([])

  useEffect(() => {
    if (!active) return
    getProfile(active).then(setProfile).catch(() => setProfile(null))
    getContent(active).then(setItems).catch(() => setItems([]))
  }, [active])

  const videos = items.filter((it) => it.video_url)
  const published = videos.filter((it) => it.youtube_url).length

  return (
    <div>
      <h1 style={{ marginTop: 0 }}>Dashboard</h1>
      {profile && (
        <p style={{ color: 'var(--text-muted)' }}>
          {t('dashboard.profileLabel')} <strong style={{ color: 'var(--text)' }}>{profile.name}</strong> · {t('dashboard.language')} {profile.language} ·
          LLM {profile.llm_provider} · {t('dashboard.image')} {profile.media.image_provider}
        </p>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 14, marginTop: 18 }}>
        <Stat label={t('dashboard.stat.videosGenerated')} value={videos.length} />
        <Stat label={t('dashboard.stat.publishedYoutube')} value={published} />
        <Stat label={t('dashboard.stat.youtubePrivacy')} value={profile?.youtube.privacy ?? '-'} />
        <Stat label={t('dashboard.stat.practiceMode')} value={profile?.youtube.practice_mode ? 'ON' : 'OFF'} />
      </div>

      <div style={{ marginTop: 24, display: 'flex', gap: 12 }}>
        <Link to="/matches" style={cta}>{t('dashboard.cta.matches')}</Link>
        <Link to="/create" style={ctaSecondary}>{t('dashboard.cta.create')}</Link>
        <Link to="/library" style={ctaSecondary}>{t('dashboard.cta.library')}</Link>
      </div>

      {/* Recent videos — fills the dashboard with the actual generated content */}
      <section style={{ marginTop: 36 }}>
        <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between' }}>
          <h2 style={{ fontSize: 20, margin: 0 }}>{t('dashboard.recentVideos')}</h2>
          {videos.length > 0 && (
            <Link to="/library" style={{ color: 'var(--accent)', fontSize: 14, fontWeight: 600 }}>
              {t('dashboard.viewWholeLibrary')}
            </Link>
          )}
        </div>

        {videos.length === 0 ? (
          <div style={{
            marginTop: 16, padding: '40px 24px', textAlign: 'center',
            background: 'var(--bg-surface)', border: '1px dashed var(--border)', borderRadius: 14,
          }}>
            <div style={{ fontSize: 40 }}>🎬</div>
            <p style={{ color: 'var(--text-muted)', margin: '10px 0 16px' }}>
              {t('dashboard.empty')}
            </p>
            <div style={{ display: 'flex', gap: 10, justifyContent: 'center' }}>
              <Link to="/matches" style={cta}>{t('dashboard.cta.matches')}</Link>
              <Link to="/create" style={ctaSecondary}>{t('dashboard.cta.create')}</Link>
            </div>
          </div>
        ) : (
          <div style={{
            marginTop: 16, display: 'grid', gap: 16,
            gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))',
          }}>
            {videos.slice(0, 8).map((it) => <VideoCard key={it.id ?? it.fixture_id} item={it} />)}
          </div>
        )}
      </section>
    </div>
  )
}

function VideoCard({ item }: { item: ContentRecord }) {
  const t = useT()
  const title = item.metadata?.title ?? item.scoreline ?? (item.day ? t('dashboard.daySummary', { day: item.day }) : t('dashboard.video'))
  const published = !!item.youtube_url
  return (
    <div style={{
      background: 'var(--bg-surface)', border: '1px solid var(--border)',
      borderRadius: 12, overflow: 'hidden',
    }}>
      <div style={{ position: 'relative', width: '100%', aspectRatio: '9 / 16', background: '#000', maxHeight: 320 }}>
        <video src={item.video_url} controls preload="metadata"
          style={{ width: '100%', height: '100%', objectFit: 'contain', display: 'block' }} />
        <PublishBadge published={published} t={t} />
      </div>
      <div style={{ padding: '10px 12px' }}>
        <div style={{
          fontWeight: 600, fontSize: 14, overflow: 'hidden',
          textOverflow: 'ellipsis', whiteSpace: 'nowrap',
        }}>{title}</div>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 4 }}>
          <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>{item.generated_at}</span>
          {published && (
            <a href={item.youtube_url} target="_blank" rel="noreferrer"
              style={{ color: 'var(--accent)', fontSize: 12, textDecoration: 'none' }}>
              YouTube ↗
            </a>
          )}
        </div>
      </div>
    </div>
  )
}

// Clear published / not-published status pill overlaid on the video thumbnail.
function PublishBadge({ published, t }: { published: boolean; t: ReturnType<typeof useT> }) {
  return (
    <span style={{
      position: 'absolute', top: 8, left: 8, zIndex: 1,
      display: 'inline-flex', alignItems: 'center', gap: 5,
      padding: '3px 9px', borderRadius: 999, fontSize: 11, fontWeight: 700,
      color: '#fff', backdropFilter: 'blur(4px)',
      background: published ? 'rgba(22,163,74,0.92)' : 'rgba(71,85,105,0.85)',
    }}>
      <span style={{
        width: 7, height: 7, borderRadius: '50%',
        background: published ? '#4ade80' : '#cbd5e1',
      }} />
      {published ? t('dashboard.published') : t('dashboard.unpublished')}
    </span>
  )
}

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div style={{
      padding: 18, background: 'var(--bg-surface)',
      border: '1px solid var(--border)', borderRadius: 12,
    }}>
      <div style={{ fontSize: 28, fontWeight: 800, color: 'var(--accent)' }}>{value}</div>
      <div style={{ color: 'var(--text-muted)', fontSize: 13 }}>{label}</div>
    </div>
  )
}

const cta: React.CSSProperties = {
  padding: '10px 16px', borderRadius: 10, background: 'var(--accent-2)',
  color: 'white', fontWeight: 600,
}

// Secondary CTA: light/neutral surface, so it needs the themed text colour and a
// border (white-on-white is unreadable in light mode otherwise).
const ctaSecondary: React.CSSProperties = {
  ...cta, background: 'var(--bg-elevated)', color: 'var(--text)',
  border: '1px solid var(--border)',
}
