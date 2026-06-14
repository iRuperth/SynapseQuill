import { useEffect, useState } from 'react'
import { ChevronDown } from 'lucide-react'
import { getArchitecture } from '../api/client'
import { useT } from '../i18n/useT'
import type { Architecture as Arch, ArchFlow, ArchService, ArchServiceGroup, ArchStep } from '../types'

type Mode = 'simple' | 'tech'

// Background/foreground colour for the "free?" badge; the label comes from i18n.
const FREE_COLOR: Record<string, { bg: string; fg: string }> = {
  yes: { bg: 'rgba(45,212,191,0.15)', fg: 'var(--accent)' },
  tier: { bg: 'rgba(99,102,241,0.15)', fg: '#a5b4fc' },
  key: { bg: 'rgba(99,102,241,0.15)', fg: '#a5b4fc' },
  local: { bg: 'rgba(148,163,184,0.15)', fg: '#94a3b8' },
  oauth: { bg: 'rgba(234,179,8,0.15)', fg: '#ca8a04' },
}

export default function Architecture() {
  const t = useT()
  const [arch, setArch] = useState<Arch | null>(null)
  const [mode, setMode] = useState<Mode>('simple')
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    getArchitecture().then(setArch).catch(() => setError(t('arch.error')))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
        <div>
          <h1 style={{ marginTop: 0, marginBottom: 4 }}>{t('arch.title')}</h1>
          <p style={{ color: 'var(--text-muted)', margin: 0 }}>{t('arch.intro')}</p>
        </div>
        {/* Mode toggle: simple / technical */}
        <div style={{ display: 'flex', gap: 4, background: 'var(--bg-elevated)', borderRadius: 999, padding: 4 }}>
          <button onClick={() => setMode('simple')} style={segBtn(mode === 'simple')}>{t('arch.mode.simple')}</button>
          <button onClick={() => setMode('tech')} style={segBtn(mode === 'tech')}>{t('arch.mode.tech')}</button>
        </div>
      </div>

      {error && <p style={{ color: '#f87171' }}>{error}</p>}
      {!arch && !error && <p style={{ color: 'var(--text-muted)' }}>{t('common.loading')}</p>}

      {arch && (
        <>
          {/* ── APIs / services ── */}
          <h2 style={sectionTitle}>{t('arch.services.title')}</h2>
          <p style={hint}>{t('arch.services.hint')}</p>
          <div style={{ display: 'grid', gap: 14, gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))' }}>
            {arch.services.map((g) => <ServiceGroup key={g.group} group={g} mode={mode} />)}
          </div>

          {/* ── Flows ── */}
          <h2 style={{ ...sectionTitle, marginTop: 32 }}>{t('arch.flows.title')}</h2>
          <p style={hint}>{t('arch.flows.hint')}</p>
          <div style={{ display: 'grid', gap: 16, gridTemplateColumns: 'repeat(auto-fill, minmax(340px, 1fr))' }}>
            {arch.flows.map((f) => <FlowCard key={f.id} flow={f} mode={mode} />)}
          </div>
        </>
      )}
    </div>
  )
}

function ServiceGroup({ group, mode }: { group: ArchServiceGroup; mode: Mode }) {
  return (
    <div style={card}>
      <div style={groupHeading}>{group.group}</div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {group.items.map((s) => <ServiceRow key={s.name} svc={s} mode={mode} />)}
      </div>
    </div>
  )
}

function ServiceRow({ svc, mode }: { svc: ArchService; mode: Mode }) {
  const t = useT()
  const [open, setOpen] = useState(false)
  const color = FREE_COLOR[svc.free] ?? FREE_COLOR.tier
  return (
    <div style={{ borderTop: '1px solid var(--border)', paddingTop: 8 }}>
      <button onClick={() => setOpen(!open)} style={accordionBtn}>
        <Chevron open={open} />
        <span style={{ fontWeight: 600, flex: 1 }}>{svc.name}</span>
        <span style={{ fontSize: 11, padding: '2px 8px', borderRadius: 999, background: color.bg, color: color.fg, flexShrink: 0 }}>
          {t(`arch.free.${svc.free}`)}
        </span>
      </button>
      <div style={{ fontSize: 13, color: 'var(--text-muted)', margin: '2px 0 0 24px' }}>{svc.easy}</div>
      {open && (
        <div style={{ margin: '8px 0 4px 24px' }}>
          <p style={detailText}>{svc.detail}</p>
          {mode === 'tech' && (
            <dl style={techDl}>
              <Row k={t('arch.field.model')} v={svc.model} />
              <Row k={t('arch.field.env')} v={svc.env} mono />
              <Row k={t('arch.field.file')} v={svc.file} mono />
            </dl>
          )}
        </div>
      )}
    </div>
  )
}

function FlowCard({ flow, mode }: { flow: ArchFlow; mode: Mode }) {
  const t = useT()
  return (
    <div style={card}>
      <div style={{ fontWeight: 700, fontSize: 16 }}>{flow.title}</div>
      <p style={{ fontSize: 13, color: 'var(--text-muted)', margin: '6px 0 12px' }}>{flow.easy}</p>

      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 12 }}>
        <IO label={t('arch.io.in')} value={flow.input} />
        <IO label={t('arch.io.out')} value={flow.output} />
      </div>

      {mode === 'tech' && (
        <dl style={{ ...techDl, marginBottom: 6 }}>
          <Row k={t('arch.field.orchestrator')} v={flow.orchestrator} mono />
          <Row k={t('arch.field.endpoint')} v={flow.endpoint} mono />
        </dl>
      )}

      {/* Numbered, expandable steps */}
      <ol style={{ listStyle: 'none', margin: '8px 0 0', padding: 0, display: 'flex', flexDirection: 'column', gap: 6 }}>
        {flow.steps.map((s, i) => <StepRow key={i} step={s} index={i} mode={mode} />)}
      </ol>
    </div>
  )
}

function StepRow({ step, index, mode }: { step: ArchStep; index: number; mode: Mode }) {
  const [open, setOpen] = useState(false)
  return (
    <li style={{ borderTop: index === 0 ? 'none' : '1px solid var(--border)', paddingTop: index === 0 ? 0 : 6 }}>
      <button onClick={() => setOpen(!open)} style={{ ...accordionBtn, alignItems: 'flex-start' }}>
        <span style={stepNum}>{index + 1}</span>
        <span style={{ flex: 1, fontSize: 14, textAlign: 'left' }}>{step.easy}</span>
        <Chevron open={open} />
      </button>
      {open && (
        <div style={{ margin: '6px 0 4px 32px' }}>
          <p style={detailText}>{step.detail}</p>
          {mode === 'tech' && (
            <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 6 }}>
              <code style={mono}>{step.tech}</code>
              <div style={{ color: '#64748b', marginTop: 2 }}>{step.file}</div>
            </div>
          )}
        </div>
      )}
    </li>
  )
}

function Chevron({ open }: { open: boolean }) {
  return (
    <ChevronDown
      size={16}
      style={{ flexShrink: 0, color: 'var(--text-muted)', transform: open ? 'rotate(180deg)' : 'none', transition: 'transform 0.15s' }}
    />
  )
}

function IO({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ flex: 1, minWidth: 130, background: 'var(--bg-elevated)', borderRadius: 8, padding: '8px 10px' }}>
      <div style={{ fontSize: 11, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: 0.5 }}>{label}</div>
      <div style={{ fontSize: 13 }}>{value}</div>
    </div>
  )
}

function Row({ k, v, mono: isMono }: { k: string; v: string; mono?: boolean }) {
  return (
    <div style={{ display: 'flex', gap: 8, fontSize: 12 }}>
      <dt style={{ color: 'var(--text-muted)', minWidth: 64 }}>{k}</dt>
      <dd style={{ margin: 0, flex: 1, ...(isMono ? mono : {}) }}>{v}</dd>
    </div>
  )
}

// ── styles ──
const card: React.CSSProperties = {
  background: 'var(--bg-surface)', border: '1px solid var(--border)',
  borderRadius: 12, padding: 16,
}
const groupHeading: React.CSSProperties = {
  fontWeight: 700, fontSize: 13, color: 'var(--accent)', marginBottom: 10,
  textTransform: 'uppercase', letterSpacing: 0.5,
}
const accordionBtn: React.CSSProperties = {
  display: 'flex', alignItems: 'center', gap: 8, width: '100%',
  background: 'transparent', border: 'none', cursor: 'pointer', padding: 0,
  color: 'var(--text)', textAlign: 'left',
}
const detailText: React.CSSProperties = { fontSize: 13, lineHeight: 1.5, color: 'var(--text)', margin: 0 }
const sectionTitle: React.CSSProperties = { fontSize: 18, marginBottom: 4, marginTop: 24 }
const hint: React.CSSProperties = { color: 'var(--text-muted)', fontSize: 14, marginTop: 0, marginBottom: 14 }
const techDl: React.CSSProperties = { display: 'flex', flexDirection: 'column', gap: 3, margin: '8px 0 0' }
const mono: React.CSSProperties = { fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace', fontSize: 12, color: '#cbd5e1' }
const stepNum: React.CSSProperties = {
  flexShrink: 0, width: 22, height: 22, borderRadius: 999, background: 'var(--bg-elevated)',
  border: '1px solid var(--border)', color: 'var(--accent)', fontSize: 12, fontWeight: 700,
  display: 'flex', alignItems: 'center', justifyContent: 'center',
}
function segBtn(active: boolean): React.CSSProperties {
  return {
    padding: '6px 16px', borderRadius: 999, border: 'none', cursor: 'pointer', fontSize: 13, fontWeight: 600,
    background: active ? 'var(--accent)' : 'transparent',
    color: active ? '#04211c' : 'var(--text-muted)',
  }
}
