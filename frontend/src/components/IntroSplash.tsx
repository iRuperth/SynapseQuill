import { useEffect, useRef, useState } from 'react'

/**
 * Full-screen F88tball splash shown on first load. The big logo fades (and
 * gently blurs/scales) away as the user scrolls down, revealing the app
 * underneath; once fully gone it unmounts. Shown once per browser session so it
 * doesn't nag on every navigation. Honours prefers-reduced-motion (skips it).
 */
const SESSION_KEY = 'f88_intro_seen'
// How far (in viewport heights) the user scrolls to fully dismiss the splash.
const FADE_DISTANCE = 0.9

export default function IntroSplash() {
  const reduceMotion = typeof window !== 'undefined'
    && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
  const alreadySeen = typeof window !== 'undefined'
    && sessionStorage.getItem(SESSION_KEY) === '1'

  const [active, setActive] = useState(!alreadySeen && !reduceMotion)
  const [progress, setProgress] = useState(0) // 0 = full splash, 1 = gone
  const spacerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!active) return
    // Lock the page behind the splash and give us room to scroll.
    const onScroll = () => {
      const dist = window.innerHeight * FADE_DISTANCE
      const p = Math.min(1, Math.max(0, window.scrollY / dist))
      setProgress(p)
      if (p >= 1) {
        sessionStorage.setItem(SESSION_KEY, '1')
        window.scrollTo(0, 0)
        setActive(false)
      }
    }
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [active])

  if (!active) return null

  const opacity = 1 - progress
  return (
    <>
      {/* Spacer: gives the document something to scroll while the splash lives,
          so the fade is driven by a natural downward scroll. */}
      <div ref={spacerRef} style={{ height: '160vh' }} aria-hidden />
      <div
        style={{
          position: 'fixed', inset: 0, zIndex: 1000,
          display: 'flex', flexDirection: 'column',
          alignItems: 'center', justifyContent: 'center', gap: 24,
          background: 'var(--bg, #0b1020)',
          opacity,
          filter: `blur(${progress * 8}px)`,
          transform: `scale(${1 + progress * 0.08})`,
          pointerEvents: progress > 0.5 ? 'none' : 'auto',
          transition: 'opacity 80ms linear',
        }}
      >
        <img
          src="/logo.png"
          alt="F88tball"
          style={{ width: 'min(70vw, 560px)', height: 'auto', display: 'block' }}
        />
        <div style={{
          color: 'var(--text-muted, #8b95ad)', fontSize: 14, letterSpacing: 1,
          display: 'flex', alignItems: 'center', gap: 8,
        }}>
          <span>Desliza para entrar</span>
          <span style={{ animation: 'f88bounce 1.2s ease-in-out infinite' }}>↓</span>
        </div>
        <style>{`@keyframes f88bounce {
          0%,100% { transform: translateY(0); opacity: .6 }
          50% { transform: translateY(5px); opacity: 1 }
        }`}</style>
      </div>
    </>
  )
}
