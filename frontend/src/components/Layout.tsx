import { NavLink, Outlet } from 'react-router-dom'
import { CalendarDays, LayoutDashboard, ListVideo, Settings, Trophy } from 'lucide-react'
import { useProfile } from './useProfile'

const NAV = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard, end: true },
  { to: '/matches', label: 'Partidos', icon: Trophy, end: false },
  { to: '/calendar', label: 'Calendario', icon: CalendarDays, end: false },
  { to: '/library', label: 'Biblioteca', icon: ListVideo, end: false },
  { to: '/settings', label: 'Ajustes', icon: Settings, end: false },
]

export default function Layout() {
  const { profiles, active, select } = useProfile()

  return (
    <div style={{ display: 'flex', minHeight: '100vh' }}>
      <aside style={{
        width: 230, background: 'var(--bg-surface)', borderRight: '1px solid var(--border)',
        padding: '20px 14px', display: 'flex', flexDirection: 'column', gap: 6,
      }}>
        <div style={{ fontWeight: 800, fontSize: 20, padding: '4px 10px 16px', letterSpacing: 0.5 }}>
          ⚽ Synapse<span style={{ color: 'var(--accent)' }}>Quill</span>
        </div>

        <select
          value={active}
          onChange={(e) => select(e.target.value)}
          style={{
            margin: '0 6px 14px', padding: '8px 10px', borderRadius: 8,
            background: 'var(--bg-elevated)', color: 'var(--text)',
            border: '1px solid var(--border)',
          }}
        >
          {profiles.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>

        {NAV.map(({ to, label, icon: Icon, end }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            style={({ isActive }) => ({
              display: 'flex', alignItems: 'center', gap: 10, padding: '10px 12px',
              borderRadius: 8, color: isActive ? 'var(--text)' : 'var(--text-muted)',
              background: isActive ? 'var(--bg-elevated)' : 'transparent',
              fontWeight: isActive ? 600 : 500,
            })}
          >
            <Icon size={18} /> {label}
          </NavLink>
        ))}

        <div style={{ marginTop: 'auto', fontSize: 12, color: 'var(--text-muted)', padding: 10 }}>
          POC · FIFA World Cup 2026
        </div>
      </aside>

      <main style={{ flex: 1, padding: '28px 36px', maxWidth: 1100 }}>
        <Outlet />
      </main>
    </div>
  )
}
