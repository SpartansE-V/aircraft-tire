import { useEffect, useState, type ReactNode } from 'react'
import { HUE } from './charts'
import { AIRCRAFT, type Status } from './data'

export type Theme = 'dark' | 'light'

// ponytail: History API + one listener instead of a router dep — two static routes, no params.
// Swap for react-router when a route needs params, nesting, or loaders.
export function nav(to: string) {
  history.pushState(null, '', to)
  dispatchEvent(new PopStateEvent('popstate'))
}

export function useRoute() {
  const [path, setPath] = useState(location.pathname)
  useEffect(() => {
    const sync = () => setPath(location.pathname)
    addEventListener('popstate', sync)
    return () => removeEventListener('popstate', sync)
  }, [])
  return path
}

// Honour the OS preference on first load, then remember the explicit choice.
export function useTheme() {
  const [theme, setTheme] = useState<Theme>(
    () =>
      (localStorage.getItem('theme') as Theme | null) ??
      (matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark'),
  )
  useEffect(() => {
    document.documentElement.dataset.theme = theme
    localStorage.setItem('theme', theme)
  }, [theme])
  return [theme, setTheme] as const
}

// hue = hex, for SVG marks and alpha-append (`${hue}33`). ink = themed var, for text —
// the mark hues drop under 4.5:1 on the light surface.
export const STATUS = {
  ok: { hue: HUE.ok, ink: 'var(--ok)', glyph: '●', text: 'NOMINAL' },
  watch: { hue: HUE.warn, ink: 'var(--warn)', glyph: '◆', text: 'MONITOR' },
  action: { hue: HUE.crit, ink: 'var(--crit)', glyph: '▲', text: 'ACTION' },
} satisfies Record<Status, { hue: string; ink: string; glyph: string; text: string }>

const TABS = [
  { path: '/tyres', label: 'Tyres' },
  { path: '/rul', label: 'Tire Remaining Useful Life Prediction' },
  { path: '/simulate-landing', label: 'Simulate landing' },
]

export function Header({
  status,
  theme,
  onTheme,
  path,
}: {
  status: Status
  theme: Theme
  onTheme: (t: Theme) => void
  path: string
}) {
  const s = STATUS[status]
  return (
    <header className="mb-3 flex flex-wrap items-center justify-between gap-3 border border-[var(--line)] bg-[var(--panel)]/80 px-4 py-3">
      <div className="flex flex-wrap items-baseline gap-3">
        <h1 className="text-sm uppercase tracking-[0.3em]" style={{ color: 'var(--primary)' }}>
          Tire Ops
        </h1>
        <span className="text-xs text-[var(--ink-3)]">
          {AIRCRAFT.reg} · {AIRCRAFT.type} · GATE {AIRCRAFT.gate}
        </span>
        <nav className="flex gap-2 text-[10px] uppercase tracking-widest">
          {TABS.map((t) => {
            const on = path === t.path
            return (
              <a
                key={t.path}
                href={t.path}
                aria-current={on ? 'page' : undefined}
                onClick={(e) => {
                  e.preventDefault()
                  nav(t.path)
                }}
                className="border px-2 py-1 transition-colors"
                style={{
                  borderColor: on ? 'var(--primary)' : 'var(--line-2)',
                  color: on ? 'var(--primary)' : 'var(--ink-3)',
                }}
              >
                {t.label}
              </a>
            )
          })}
        </nav>
      </div>
      <div className="flex items-center gap-4 text-[10px] uppercase tracking-widest">
        <span className="text-[var(--ink-3)]">{AIRCRAFT.phase}</span>
        <button
          onClick={() => onTheme(theme === 'dark' ? 'light' : 'dark')}
          aria-pressed={theme === 'light'}
          className="flex items-center gap-1.5 border border-[var(--line-2)] px-2 py-1 uppercase tracking-widest text-[var(--ink-3)] transition-colors hover:text-[var(--ink)]"
        >
          {theme === 'dark' ? '☾ Dark' : '☀ Light'}
        </button>
        <span className="flex items-center gap-1.5 border px-2 py-1" style={{ borderColor: s.ink, color: s.ink }}>
          {s.glyph} {s.text}
        </span>
      </div>
    </header>
  )
}

export function Card({ title, tag, children, className = '' }: { title: string; tag: string; children: ReactNode; className?: string }) {
  return (
    <section className={`flex flex-col border border-[var(--line)] bg-[var(--panel)]/80 p-3 ${className}`}>
      <div className="mb-2 flex items-baseline justify-between gap-2">
        <h2 className="text-xs uppercase tracking-[0.2em] text-[var(--ink)]">{title}</h2>
        <span className="text-[9px] uppercase tracking-widest text-[var(--ink-4)]">{tag}</span>
      </div>
      <div className="flex flex-1 flex-col justify-between">{children}</div>
    </section>
  )
}

/** The open question behind each feed — what still has to be solved before it can be trusted. */
export function Open({ children }: { children: ReactNode }) {
  return (
    <p className="mt-3 border-t border-dashed border-[var(--warn-line)] pt-2 text-[10px] leading-relaxed">
      <span className="tracking-widest" style={{ color: 'var(--warn)' }}>
        OPEN ▸{' '}
      </span>
      <span className="text-[var(--ink-3)]">{children}</span>
    </p>
  )
}

export function Kpi({ label, value, unit, sub, bad }: { label: string; value: number | string; unit: string; sub: string; bad?: boolean }) {
  return (
    <div className="border border-[var(--line)] bg-[var(--panel)]/80 p-3">
      <div className="text-[10px] uppercase tracking-widest text-[var(--ink-3)]">{label}</div>
      <div className="mt-1 text-xl font-semibold tabular-nums" style={{ color: bad ? 'var(--crit)' : 'var(--ink)' }}>
        {value}
        <span className="ml-1 text-xs font-normal text-[var(--ink-3)]">{unit}</span>
      </div>
      <div className="text-[10px] text-[var(--ink-4)]">{sub}</div>
    </div>
  )
}

export function Mini({ label, value, bad }: { label: string; value: string; bad?: boolean }) {
  return (
    <div className="border border-[var(--line)] bg-[var(--panel)] px-2 py-1.5">
      <div className="text-[9px] uppercase tracking-widest text-[var(--ink-4)]">{label}</div>
      <div className="text-sm tabular-nums" style={{ color: bad ? 'var(--crit)' : 'var(--ink-2)' }}>
        {bad && '⚠ '}
        {value}
      </div>
    </div>
  )
}

export function Field({ k, v, warn, mono }: { k: string; v: string; warn?: boolean; mono?: boolean }) {
  return (
    <div className="flex items-baseline justify-between gap-2 text-xs">
      <span className="text-[var(--ink-4)]">{k}</span>
      <span className={`tabular-nums ${mono ? 'tracking-wider' : ''}`} style={{ color: warn ? 'var(--warn)' : 'var(--ink-2)' }}>
        {warn && '⚠ '}
        {v}
      </span>
    </div>
  )
}
