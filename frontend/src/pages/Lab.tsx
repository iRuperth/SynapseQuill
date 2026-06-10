import { useCallback, useEffect, useState } from 'react'
import {
  deleteLabHistory, explainScience, financeNews, getLabHistory,
  getScienceTopics, routeAgent,
} from '../api/client'
import { useProfile } from '../components/useProfile'
import { useT } from '../i18n/useT'
import type { LabHistoryRecord } from '../types'

// "Laboratorio IA" — surfaces the advanced/expert features that previously
// lived only as API endpoints with no UI:
//   • Science RAG (arXiv + Graph RAG) — advanced + expert
//   • Live financial news (Finnhub)   — advanced
//   • Multi-agent supervisor routing  — expert
//
// Every request (and free-topic content from Crear) is saved to a per-profile
// history shown below, so past questions and answers can be revisited.

type Tab = 'science' | 'finance' | 'agents'
const TABS: { key: Tab; icon: string; labelKey: string }[] = [
  { key: 'science', icon: '🔬', labelKey: 'lab.tab.science' },
  { key: 'finance', icon: '📈', labelKey: 'lab.tab.finance' },
  { key: 'agents', icon: '🤖', labelKey: 'lab.tab.agents' },
]

export default function Lab() {
  const t = useT()
  const { active } = useProfile()
  const [tab, setTab] = useState<Tab>('science')
  // Bumped after each successful request so the history panel reloads.
  const [reloadKey, setReloadKey] = useState(0)
  const onSaved = useCallback(() => setReloadKey((k) => k + 1), [])

  return (
    <div>
      <h1 style={{ marginTop: 0 }}>{t('lab.title')}</h1>
      <p style={{ color: 'var(--text-muted)', marginTop: -8 }}>
        {t('lab.subtitle')}
      </p>
      <div style={{ display: 'flex', gap: 8, margin: '16px 0 20px', flexWrap: 'wrap' }}>
        {TABS.map((tb) => (
          <button key={tb.key} onClick={() => setTab(tb.key)} style={tabBtn(tab === tb.key)}>
            {tb.icon} {t(tb.labelKey)}
          </button>
        ))}
      </div>
      {tab === 'science' && <Science profileId={active} onSaved={onSaved} />}
      {tab === 'finance' && <Finance profileId={active} onSaved={onSaved} />}
      {tab === 'agents' && <Agents profileId={active} onSaved={onSaved} />}

      <History profileId={active} reloadKey={reloadKey} />
    </div>
  )
}

type FeatureProps = { profileId: string; onSaved: () => void }

// ── Science: arXiv RAG + Graph RAG ──────────────────────────────────
function Science({ profileId, onSaved }: FeatureProps) {
  const t = useT()
  const [topic, setTopic] = useState('')
  const [language, setLanguage] = useState('es')
  const [useGraph, setUseGraph] = useState(true)
  const [topics, setTopics] = useState<string[]>([])
  const { loading, error, out, run } = useAsync()
  const [text, setText] = useState('')

  useEffect(() => { getScienceTopics().then(setTopics).catch(() => {}) }, [])

  async function go() {
    const r = await run(() => explainScience(topic, language, useGraph, profileId))
    if (r) { setText(r.explanation); onSaved() }
  }

  return (
    <Panel>
      <p style={hint}>
        {t('lab.science.hint')}
      </p>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 12 }}>
        {topics.map((tp) => (
          <button key={tp} onClick={() => setTopic(tp)} style={chip(false)}>{tp}</button>
        ))}
      </div>
      <input style={input} value={topic} placeholder={t('lab.science.topicPlaceholder')}
        onChange={(e) => setTopic(e.target.value)} />
      <div style={{ display: 'flex', gap: 16, alignItems: 'center', marginTop: 10 }}>
        <select style={{ ...input, width: 120 }} value={language} onChange={(e) => setLanguage(e.target.value)}>
          {['es', 'en', 'fr', 'it'].map((l) => <option key={l} value={l}>{l.toUpperCase()}</option>)}
        </select>
        <label style={{ display: 'flex', gap: 6, alignItems: 'center', fontSize: 14 }}>
          <input type="checkbox" checked={useGraph} onChange={(e) => setUseGraph(e.target.checked)} />
          {t('lab.science.useGraph')}
        </label>
        <button onClick={go} disabled={loading || !topic.trim()} style={primaryBtn(loading || !topic.trim())}>
          {loading ? t('lab.science.indexing') : t('lab.science.explain')}
        </button>
      </div>
      <Note>{t('lab.science.note')}</Note>
      {error && <Err msg={error} />}
      {out && text && <Output text={text} />}
    </Panel>
  )
}

// ── Finance: live market news ───────────────────────────────────────
function Finance({ profileId, onSaved }: FeatureProps) {
  const t = useT()
  const [ticker, setTicker] = useState('')
  const { loading, error, out, run } = useAsync()
  const [text, setText] = useState('')

  async function go() {
    const r = await run(() => financeNews(ticker.toUpperCase().trim(), profileId))
    if (r) { setText(r.summary); onSaved() }
  }
  return (
    <Panel>
      <p style={hint}>{t('lab.finance.hint')}</p>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 12 }}>
        {/* Football-flavoured tickers: listed clubs + sportswear brands. */}
        {[['MANU', 'Man United'], ['JUVE.MI', 'Juventus'], ['BVB.DE', 'Dortmund'],
          ['NKE', 'Nike'], ['ADS.DE', 'Adidas']].map(([tk, label]) => (
          <button key={tk} onClick={() => setTicker(tk)} style={chip(false)}>{label}</button>
        ))}
      </div>
      <div style={{ display: 'flex', gap: 12 }}>
        <input style={input} value={ticker} placeholder={t('lab.finance.tickerPlaceholder')}
          onChange={(e) => setTicker(e.target.value)} />
        <button onClick={go} disabled={loading || !ticker.trim()} style={primaryBtn(loading || !ticker.trim())}>
          {loading ? t('lab.finance.loading') : t('lab.finance.go')}
        </button>
      </div>
      {error && <Err msg={error} />}
      {out && text && <Output text={text} />}
    </Panel>
  )
}

// ── Agents: multi-agent supervisor routing ──────────────────────────
function Agents({ profileId, onSaved }: FeatureProps) {
  const t = useT()
  const [request, setRequest] = useState('')
  const { loading, error, out, run } = useAsync()
  const [text, setText] = useState('')

  async function go() {
    const r = await run(() => routeAgent(request.trim(), profileId))
    if (r) { setText(r.result); onSaved() }
  }
  return (
    <Panel>
      <p style={hint}>
        {t('lab.agents.hint')}
      </p>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 12 }}>
        {[
          t('lab.agents.example1'),
          t('lab.agents.example2'),
          t('lab.agents.example3'),
        ].map((q) => (
          <button key={q} onClick={() => setRequest(q)} style={chip(false)}>{q}</button>
        ))}
      </div>
      <textarea style={{ ...input, minHeight: 90, resize: 'vertical' }} value={request}
        placeholder={t('lab.agents.placeholder')} onChange={(e) => setRequest(e.target.value)} />
      <button onClick={go} disabled={loading || !request.trim()}
        style={{ ...primaryBtn(loading || !request.trim()), marginTop: 10 }}>
        {loading ? t('lab.agents.routing') : t('lab.agents.go')}
      </button>
      {error && <Err msg={error} />}
      {out && text && <Output text={text} />}
    </Panel>
  )
}

// ── History: every Lab + free-topic request, newest first ───────────
const KIND_META: Record<string, { icon: string; labelKey: string }> = {
  science: { icon: '🔬', labelKey: 'lab.kind.science' },
  finance: { icon: '📈', labelKey: 'lab.kind.finance' },
  agents: { icon: '🤖', labelKey: 'lab.kind.agents' },
  freeform: { icon: '✍️', labelKey: 'lab.kind.freeform' },
}

function History({ profileId, reloadKey }: { profileId: string; reloadKey: number }) {
  const t = useT()
  const [items, setItems] = useState<LabHistoryRecord[]>([])

  const load = useCallback(() => {
    if (profileId) getLabHistory(profileId).then(setItems).catch(() => setItems([]))
  }, [profileId])
  useEffect(load, [load, reloadKey])

  async function onDelete(id: string) {
    if (!confirm(t('lab.history.confirmDelete'))) return
    try { await deleteLabHistory(profileId, id); load() } catch { /* ignore */ }
  }

  return (
    <div style={{ marginTop: 36, maxWidth: 760 }}>
      <h2 style={{ fontSize: 18, marginBottom: 4 }}>{t('lab.history.title')}</h2>
      <p style={{ color: 'var(--text-muted)', fontSize: 13, marginTop: 0 }}>
        {t('lab.history.subtitle')}
      </p>
      {!items.length && (
        <p style={{ color: 'var(--text-muted)', fontSize: 14 }}>{t('lab.history.empty')}</p>
      )}
      <div style={{ display: 'grid', gap: 10 }}>
        {items.map((it) => <HistoryRow key={it.id} item={it} onDelete={() => onDelete(it.id)} />)}
      </div>
    </div>
  )
}

function HistoryRow({ item, onDelete }: { item: LabHistoryRecord; onDelete: () => void }) {
  const t = useT()
  const [open, setOpen] = useState(false)
  const meta = KIND_META[item.kind]
  const m = { icon: meta?.icon ?? '•', label: meta ? t(meta.labelKey) : item.kind }
  return (
    <div style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)', borderRadius: 10 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '10px 14px' }}>
        <button onClick={() => setOpen(!open)} style={{
          flex: 1, display: 'flex', alignItems: 'center', gap: 10, background: 'none',
          border: 'none', color: 'var(--text)', cursor: 'pointer', textAlign: 'left',
        }}>
          <span style={{ color: 'var(--text-muted)', width: 12 }}>{open ? '▾' : '▸'}</span>
          <span style={{
            fontSize: 12, padding: '2px 8px', borderRadius: 999,
            background: 'var(--bg-elevated)', color: 'var(--text-muted)', whiteSpace: 'nowrap',
          }}>{m.icon} {m.label}</span>
          <strong style={{ fontSize: 14, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {item.prompt}
          </strong>
        </button>
        <span style={{ color: 'var(--text-muted)', fontSize: 12, whiteSpace: 'nowrap' }}>{item.created_at}</span>
        <button onClick={onDelete} title={t('common.delete')} style={{
          background: 'transparent', border: '1px solid var(--border)', borderRadius: 8,
          color: '#ff9db1', cursor: 'pointer', padding: '3px 9px',
        }}>🗑</button>
      </div>
      {open && (
        <div style={{ padding: '0 14px 14px', borderTop: '1px solid var(--border)' }}>
          <Output text={item.result} />
        </div>
      )}
    </div>
  )
}

// ── Shared helpers ──────────────────────────────────────────────────
function useAsync() {
  const t = useT()
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [out, setOut] = useState(false)
  async function run<T>(fn: () => Promise<T>): Promise<T | null> {
    setLoading(true); setError(''); setOut(false)
    try {
      const r = await fn(); setOut(true); return r
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(msg || t('lab.requestError')); return null
    } finally { setLoading(false) }
  }
  return { loading, error, out, run }
}

function Panel({ children }: { children: React.ReactNode }) {
  return <div style={{ maxWidth: 760 }}>{children}</div>
}
function Output({ text }: { text: string }) {
  return (
    <pre style={{
      whiteSpace: 'pre-wrap', marginTop: 16, lineHeight: 1.55, fontFamily: 'inherit',
      background: 'var(--bg-elevated)', border: '1px solid var(--border)',
      borderRadius: 12, padding: 16,
    }}>{text}</pre>
  )
}
function Note({ children }: { children: React.ReactNode }) {
  return <p style={{ color: 'var(--text-muted)', fontSize: 12, marginTop: 8 }}>{children}</p>
}
function Err({ msg }: { msg: string }) {
  return <p style={{ color: '#f87171', marginTop: 12 }}>{msg}</p>
}

const hint: React.CSSProperties = { color: 'var(--text-muted)', fontSize: 14, marginTop: 0 }
const input: React.CSSProperties = {
  padding: '9px 12px', borderRadius: 8, background: 'var(--bg-elevated)',
  color: 'var(--text)', border: '1px solid var(--border)', flex: 1, width: '100%',
}
function tabBtn(activeTab: boolean): React.CSSProperties {
  return {
    padding: '8px 14px', borderRadius: 8, cursor: 'pointer', fontSize: 14,
    background: activeTab ? 'var(--accent)' : 'var(--bg-elevated)',
    color: activeTab ? '#04211c' : 'var(--text)',
    border: `1px solid ${activeTab ? 'var(--accent)' : 'var(--border)'}`,
  }
}
function chip(activeChip: boolean): React.CSSProperties {
  return {
    padding: '6px 12px', borderRadius: 999, cursor: 'pointer', fontSize: 13,
    background: activeChip ? 'var(--accent)' : 'var(--bg-elevated)',
    color: activeChip ? '#04211c' : 'var(--text)',
    border: `1px solid ${activeChip ? 'var(--accent)' : 'var(--border)'}`,
  }
}
function primaryBtn(disabled: boolean): React.CSSProperties {
  return {
    padding: '10px 16px', borderRadius: 8, border: 'none', fontWeight: 600,
    cursor: disabled ? 'not-allowed' : 'pointer', opacity: disabled ? 0.6 : 1,
    background: 'var(--accent)', color: '#04211c', whiteSpace: 'nowrap',
  }
}
