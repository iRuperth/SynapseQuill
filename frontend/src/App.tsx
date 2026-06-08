import { Route, Routes } from 'react-router-dom'
import IntroSplash from './components/IntroSplash'
import Layout from './components/Layout'
import Dashboard from './pages/Dashboard'
import Matches from './pages/Matches'
import Library from './pages/Library'
import Settings from './pages/Settings'
import Calendar from './pages/Calendar'
import Create from './pages/Create'
import Lab from './pages/Lab'
import Architecture from './pages/Architecture'
import PowerRankings from './pages/PowerRankings'

export default function App() {
  return (
    <>
    <IntroSplash />
    <Routes>
      <Route path="/" element={<Layout />}>
        <Route index element={<Dashboard />} />
        <Route path="create" element={<Create />} />
        <Route path="matches" element={<Matches />} />
        <Route path="calendar" element={<Calendar />} />
        <Route path="rankings" element={<PowerRankings />} />
        <Route path="lab" element={<Lab />} />
        <Route path="library" element={<Library />} />
        <Route path="architecture" element={<Architecture />} />
        <Route path="settings" element={<Settings />} />
      </Route>
    </Routes>
    </>
  )
}
