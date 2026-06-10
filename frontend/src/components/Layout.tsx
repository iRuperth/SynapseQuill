import { NavLink, Outlet } from 'react-router-dom'
import { CalendarDays, FlaskConical, LayoutDashboard, ListVideo, Network, PenLine, Settings, Swords, Trophy } from 'lucide-react'
import { useT } from '../i18n/useT'

// Brand: the full F88tball logo (ball + wordmark). The wordmark is light, so a
// dark-text variant is shown in light mode. CSS swaps them by theme (handles the
// "auto" theme too, since data-theme is always resolved to light/dark on <html>).
const BRAND = { name: 'F88tball', logo: '/logo.png', logoLight: '/logo-light.png' }

const BRAND_CSS = `
.brand-logo-dark { display: block; }
.brand-logo-light { display: none; }
:root[data-theme='light'] .brand-logo-dark { display: none; }
:root[data-theme='light'] .brand-logo-light { display: block; }
`

const NAV = [
  { to: '/', key: 'nav.dashboard', icon: LayoutDashboard, end: true },
  { to: '/matches', key: 'nav.matches', icon: Trophy, end: false },
  { to: '/calendar', key: 'nav.calendar', icon: CalendarDays, end: false },
  { to: '/rankings', key: 'nav.rankings', icon: Swords, end: false },
  { to: '/create', key: 'nav.create', icon: PenLine, end: false },
  { to: '/lab', key: 'nav.lab', icon: FlaskConical, end: false },
  { to: '/library', key: 'nav.library', icon: ListVideo, end: false },
  { to: '/architecture', key: 'nav.architecture', icon: Network, end: false },
  { to: '/settings', key: 'nav.settings', icon: Settings, end: false },
]

export default function Layout() {
  const t = useT()
  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      {/* Top navbar — web-style: brand left, links center/right, profile far right */}
      <header style={{
        position: 'sticky', top: 0, zIndex: 20,
        background: 'var(--navbar-bg)', backdropFilter: 'blur(10px)',
        borderBottom: '1px solid var(--border)',
      }}>
        <nav style={{
          width: '100%', padding: '0 32px', minHeight: 60,
          display: 'flex', alignItems: 'center', gap: 18, flexWrap: 'wrap',
        }}>
          {/* Brand */}
          <style>{BRAND_CSS}</style>
          <NavLink to="/" end style={{
            display: 'flex', alignItems: 'center', marginRight: 8,
          }}>
            <img src={BRAND.logo} alt={BRAND.name} className="brand-logo-dark"
              style={{ height: 34, width: 'auto' }} />
            <img src={BRAND.logoLight} alt={BRAND.name} className="brand-logo-light"
              style={{ height: 34, width: 'auto' }} />
          </NavLink>

          {/* Nav links */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 2, flex: 1, flexWrap: 'wrap' }}>
            {NAV.map(({ to, key, icon: Icon, end }) => (
              <NavLink
                key={to}
                to={to}
                end={end}
                style={({ isActive }) => ({
                  display: 'flex', alignItems: 'center', gap: 7, padding: '8px 12px',
                  borderRadius: 8, fontSize: 14,
                  color: isActive ? 'var(--text)' : 'var(--text-muted)',
                  background: isActive ? 'var(--bg-elevated)' : 'transparent',
                  fontWeight: isActive ? 600 : 500,
                })}
              >
                <Icon size={17} /> {t(key)}
              </NavLink>
            ))}
          </div>
        </nav>
      </header>

      {/* Page content — full width */}
      <main style={{ flex: 1, width: '100%', padding: '32px' }}>
        <Outlet />
      </main>

      <footer style={{
        borderTop: '1px solid var(--border)', padding: '16px 24px', textAlign: 'center',
        fontSize: 12, color: 'var(--text-muted)',
      }}>
        {BRAND.name} · {t('footer.tagline')}
      </footer>
    </div>
  )
}
