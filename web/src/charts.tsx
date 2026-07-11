// Hand-rolled SVG marks. ponytail: no chart lib — these are polylines and rects.
// Add one (visx/recharts) only when a chart needs real axes or brushing.
// HUE is shared across both themes: as graphical marks these clear 3:1 on dark and light.
// Structural greys are themed (see index.css); small *text* uses the darker --warn/--crit vars.

// SVG presentation attributes don't accept var(), so these ride in `style` instead.
const AXIS = { stroke: 'var(--axis)' }
const INK = { stroke: 'var(--ink-3)' }

export const HUE = { primary: '#04a2c2', alt: '#6d7ff0', warn: '#c28409', ok: '#12a37f', crit: '#e0483d' }

/** Trend over time. One series → no legend; last point is direct-labeled. */
export function Sparkline({
  values,
  unit = '',
  limit,
  height = 56,
  color = HUE.primary,
}: {
  values: number[]
  unit?: string
  limit?: number // reference line (e.g. min service pressure)
  height?: number
  color?: string
}) {
  const w = 100
  const lo = Math.min(...values, limit ?? Infinity)
  const hi = Math.max(...values, limit ?? -Infinity)
  const pad = (hi - lo) * 0.15 || 1
  const y = (v: number) => height - 8 - ((v - lo + pad) / (hi - lo + pad * 2)) * (height - 16)
  const x = (i: number) => (i / (values.length - 1)) * w
  const pts = values.map((v, i) => `${x(i)},${y(v)}`).join(' ')
  const last = values[values.length - 1]

  return (
    <div className="flex items-end gap-2">
      <svg viewBox={`0 0 ${w} ${height}`} preserveAspectRatio="none" className="h-14 flex-1" role="img">
        <defs>
          <linearGradient id={`g-${color.slice(1)}`} x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity="0.28" />
            <stop offset="100%" stopColor={color} stopOpacity="0" />
          </linearGradient>
        </defs>
        {limit !== undefined && (
          <line x1="0" x2={w} y1={y(limit)} y2={y(limit)} stroke={HUE.warn} strokeWidth="1" strokeDasharray="3 3" opacity="0.7" />
        )}
        <polygon points={`0,${height} ${pts} ${w},${height}`} fill={`url(#g-${color.slice(1)})`} />
        <polyline points={pts} fill="none" stroke={color} strokeWidth="2" vectorEffect="non-scaling-stroke" strokeLinejoin="round" />
        {values.map((v, i) => (
          <circle key={i} cx={x(i)} cy={y(v)} r="4" fill="transparent">
            <title>{`T-${values.length - 1 - i} d · ${v}${unit}`}</title>
          </circle>
        ))}
        <circle cx={x(values.length - 1)} cy={y(last)} r="2.5" fill={color} vectorEffect="non-scaling-stroke" />
      </svg>
      <span className="tabular-nums text-sm font-medium text-[var(--ink)]">
        {last}
        <span className="text-[var(--ink-3)]">{unit}</span>
      </span>
    </div>
  )
}

/** Magnitude across a short ordered set. Bars: 4px rounded top, 2px surface gap. */
export function Bars({
  values,
  labels,
  unit = '',
  limit,
  color = HUE.primary,
  overColor = HUE.crit,
}: {
  values: number[]
  labels: string[]
  unit?: string
  limit?: number // above this = over-limit, painted with the status hue
  color?: string
  overColor?: string
}) {
  const hi = Math.max(...values, limit ?? 0) * 1.1
  return (
    <div className="flex h-16 items-end gap-[2px]">
      {values.map((v, i) => {
        const over = limit !== undefined && v > limit
        return (
          <div
            key={i}
            title={`${labels[i]} · ${v}${unit}`}
            style={{ height: `${(v / hi) * 100}%`, background: over ? overColor : color }}
            className="flex-1 rounded-t-[4px] opacity-90 transition-opacity hover:opacity-100"
          />
        )
      })}
    </div>
  )
}

/** Single measure against its band. Reads as a headline, not a chart. */
export function Gauge({
  value,
  min,
  max,
  target,
  unit,
  label,
  color = HUE.primary,
}: {
  value: number
  min: number
  max: number
  target?: number
  unit: string
  label: string
  color?: string
}) {
  const R = 42
  const arc = (t: number) => {
    const a = Math.PI * (1 - Math.min(1, Math.max(0, t)))
    return [50 + R * Math.cos(a), 50 - R * Math.sin(a)]
  }
  const t = (value - min) / (max - min)
  const [px, py] = arc(t)
  const len = Math.PI * R

  return (
    <div className="relative">
      <svg viewBox="0 0 100 58" className="w-full">
        <path d={`M 8 50 A ${R} ${R} 0 0 1 92 50`} fill="none" style={AXIS} strokeWidth="6" strokeLinecap="round" />
        <path
          d={`M 8 50 A ${R} ${R} 0 0 1 92 50`}
          fill="none"
          stroke={color}
          strokeWidth="6"
          strokeLinecap="round"
          strokeDasharray={`${len * t} ${len}`}
        />
        {target !== undefined && (
          <line
            x1={arc((target - min) / (max - min))[0]}
            y1={arc((target - min) / (max - min))[1] - 5}
            x2={arc((target - min) / (max - min))[0]}
            y2={arc((target - min) / (max - min))[1] + 5}
            style={INK}
            strokeWidth="1.5"
          />
        )}
        <circle cx={px} cy={py} r="3.5" fill={color} style={{ stroke: 'var(--panel)' }} strokeWidth="2" />
      </svg>
      <div className="-mt-6 text-center">
        <div className="text-2xl font-semibold tabular-nums text-[var(--ink)]">
          {value}
          <span className="ml-0.5 text-sm font-normal text-[var(--ink-3)]">{unit}</span>
        </div>
        <div className="mt-0.5 text-[10px] uppercase tracking-widest text-[var(--ink-3)]">{label}</div>
      </div>
    </div>
  )
}

/** Horizontal magnitude rows — used for groove depth and inner/outer turn load. */
export function RowBars({
  rows,
  max,
  unit,
  limit,
}: {
  rows: { label: string; value: number; color?: string }[]
  max: number
  unit: string
  limit?: number
}) {
  return (
    <div className="space-y-1.5">
      {rows.map((r) => {
        const under = limit !== undefined && r.value < limit
        return (
          <div key={r.label} className="flex items-center gap-2" title={`${r.label} · ${r.value}${unit}`}>
            <span className="w-16 shrink-0 text-[10px] uppercase tracking-wider text-[var(--ink-3)]">{r.label}</span>
            <div className="relative h-2 flex-1 rounded-full bg-[var(--track)]">
              {limit !== undefined && (
                <div className="absolute top-[-3px] h-[14px] w-px bg-[var(--ink-4)]" style={{ left: `${(limit / max) * 100}%` }} />
              )}
              <div
                className="h-2 rounded-full"
                style={{ width: `${Math.min(100, (r.value / max) * 100)}%`, background: under ? HUE.crit : r.color ?? HUE.primary }}
              />
            </div>
            <span className="w-14 shrink-0 text-right text-xs tabular-nums text-[var(--ink-2)]">
              {r.value}
              <span className="text-[var(--ink-4)]">{unit}</span>
            </span>
          </div>
        )
      })}
    </div>
  )
}
