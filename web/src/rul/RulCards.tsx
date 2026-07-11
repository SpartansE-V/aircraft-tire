// The RUL views' building blocks: a status badge, the P10–P90 credible-band fan, the /predict
// forecast card, the fleet worklist table, the six-wheel RUL map, and the per-wheel status panel.
// They read the api.ts response types directly and paint on the shared green→amber→red severity
// scale (positions.ts), so the RUL screens match the rest of the dashboard without restyling.

import type { PriorityWheel, RulPredictionResponse, RulSeverity, RulStatusValue, WheelPosition, WheelStatusResponse } from './api'
import {
  fmtDate,
  fmtLandings,
  fmtPct,
  POSITION_LABEL,
  POSITION_SHORT,
  POSITION_XY,
  RUL_STATUS_META,
  severityHue,
  severityInk,
} from './positions'

export function SeverityBadge({ status, severity }: { status: RulStatusValue; severity: RulSeverity }) {
  const meta = RUL_STATUS_META[status]
  const ink = severityInk(severity)
  return (
    <span
      className="inline-flex items-center gap-1.5 border px-2 py-1 text-[10px] uppercase tracking-widest"
      style={{ borderColor: ink, color: ink }}
    >
      {meta.glyph} {meta.label}
    </span>
  )
}

/** Remaining landings as a credible band: the coloured bar spans P10→P90, the strong tick is the
 *  median, the hollow tick is the mean. Zero (removal) sits at the left, so a short bar hugging the
 *  left edge reads as "little life left" without needing to parse the numbers. */
export function QuantileFan({
  p10,
  median,
  p90,
  mean,
  severity,
}: {
  p10: number
  median: number
  p90: number
  mean: number
  severity: RulSeverity
}) {
  const hue = severityHue(severity)
  const max = Math.max(p90, mean, median, 1) * 1.12
  const x = (v: number) => `${Math.min(100, Math.max(0, (v / max) * 100))}%`
  return (
    <div>
      <div className="relative h-3 rounded-full bg-[var(--track)]">
        <div
          className="absolute inset-y-0 rounded-full"
          style={{ left: x(p10), right: `${100 - (Math.min(100, (p90 / max) * 100))}%`, background: `${hue}55` }}
        />
        <div className="absolute inset-y-[-2px] w-[2px]" style={{ left: x(median), background: hue }} title={`median ${fmtLandings(median)}`} />
        <div className="absolute inset-y-0 w-px bg-[var(--ink-3)]" style={{ left: x(mean) }} title={`mean ${fmtLandings(mean)}`} />
      </div>
      <div className="mt-2 grid grid-cols-3 text-center">
        {[
          { k: 'P10 · earliest', v: p10 },
          { k: 'Median', v: median },
          { k: 'P90 · latest', v: p90 },
        ].map((c, i) => (
          <div key={c.k} className={i === 1 ? '' : 'text-[var(--ink-3)]'}>
            <div className="text-[9px] uppercase tracking-widest text-[var(--ink-4)]">{c.k}</div>
            <div className="text-sm tabular-nums" style={{ color: i === 1 ? severityInk(severity) : undefined }}>
              {fmtLandings(c.v)}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

/** A 0–100% meter for P(cross the wear limit before the next scheduled check). */
function ProbMeter({ p, severity }: { p: number; severity: RulSeverity }) {
  return (
    <div className="flex items-center gap-2">
      <div className="relative h-2 flex-1 rounded-full bg-[var(--track)]">
        <div className="h-2 rounded-full" style={{ width: `${Math.round(p * 100)}%`, background: severityHue(severity) }} />
      </div>
      <span className="w-9 shrink-0 text-right text-xs tabular-nums" style={{ color: severityInk(severity) }}>
        {fmtPct(p)}
      </span>
    </div>
  )
}

function DateLadder({ earliest, median, latest }: { earliest: string; median: string; latest: string }) {
  return (
    <div className="grid grid-cols-3 gap-2">
      {[
        { k: 'Earliest (P10)', v: earliest, warn: true },
        { k: 'Median', v: median, warn: false },
        { k: 'Latest (P90)', v: latest, warn: false },
      ].map((d) => (
        <div key={d.k} className="border border-[var(--line)] bg-[var(--panel)] px-2 py-1.5">
          <div className="text-[9px] uppercase tracking-widest text-[var(--ink-4)]">{d.k}</div>
          <div className="text-sm tabular-nums" style={{ color: d.warn ? 'var(--warn)' : 'var(--ink-2)' }}>{fmtDate(d.v)}</div>
        </div>
      ))}
    </div>
  )
}

/** The /predict result rendered for a single wheel: headline, credible band, wear-to-limit dates,
 *  crossing probability, and the recommended planning action. */
export function RulForecastCard({ data }: { data: RulPredictionResponse }) {
  const { rul_landings: q, wear_to_limit_dates: dates, status } = data
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <SeverityBadge status={status.status} severity={status.severity} />
        {data.low_confidence && (
          <span className="border border-[var(--warn-line)] px-2 py-1 text-[9px] uppercase tracking-widest" style={{ color: 'var(--warn)' }}>
            ⚠ Low confidence · {data.readings_used} readings
          </span>
        )}
      </div>
      <p className="text-xs leading-relaxed text-[var(--ink-2)]">{status.headline}</p>

      <div>
        <div className="mb-1 text-[10px] uppercase tracking-widest text-[var(--ink-3)]">Remaining landings · Monte-Carlo band</div>
        <QuantileFan p10={q.p10} median={q.median} p90={q.p90} mean={q.mean} severity={status.severity} />
      </div>

      <div>
        <div className="mb-1 text-[10px] uppercase tracking-widest text-[var(--ink-3)]">Wear-to-limit dates · to {data.wear_limit_mm} mm</div>
        <DateLadder earliest={dates.earliest_credible_p10} median={dates.median} latest={dates.p90} />
      </div>

      <div>
        <div className="mb-1 flex items-baseline justify-between">
          <span className="text-[10px] uppercase tracking-widest text-[var(--ink-3)]">P(cross before next check)</span>
          <span className="text-[9px] uppercase tracking-widest text-[var(--ink-4)]">{data.landings_per_day}/day util</span>
        </div>
        <ProbMeter p={data.p_cross_before_next_check} severity={status.severity} />
      </div>

      <div className="border-t border-[var(--line)] pt-2">
        <div className="text-[10px] uppercase tracking-widest text-[var(--ink-4)]">Recommended action</div>
        <p className="mt-0.5 text-xs leading-relaxed" style={{ color: severityInk(status.severity) }}>{status.recommended_action}</p>
      </div>
    </div>
  )
}

/** Fleet worklist: one row per wheel, ranked by composite priority. Selecting a row lifts its
 *  tail+position up so the map and detail panel follow. */
export function WorklistTable({
  wheels,
  selected,
  onSelect,
}: {
  wheels: PriorityWheel[]
  selected: { tail: string; position: WheelPosition } | null
  onSelect: (tail: string, position: WheelPosition) => void
}) {
  if (wheels.length === 0) {
    return <p className="py-8 text-center text-xs text-[var(--ink-4)]">No wheels above the attention threshold.</p>
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-xs">
        <thead>
          <tr className="text-left text-[9px] uppercase tracking-widest text-[var(--ink-4)]">
            <th className="py-1 pr-2 font-normal">#</th>
            <th className="py-1 pr-2 font-normal">Tail</th>
            <th className="py-1 pr-2 font-normal">Position</th>
            <th className="py-1 pr-2 font-normal">Stn</th>
            <th className="py-1 pr-2 text-right font-normal">P·cross</th>
            <th className="py-1 pr-2 text-right font-normal">RUL med</th>
            <th className="py-1 font-normal">Earliest</th>
          </tr>
        </thead>
        <tbody>
          {wheels.map((w) => {
            const on = selected?.tail === w.tail_number && selected?.position === w.position
            // The worklist has no severity field; derive a band from crossing probability so the row
            // colour matches the wheel/status detail without a second round-trip.
            const sev: RulSeverity = w.p_cross_before_next_check >= 0.5 ? 'critical' : w.p_cross_before_next_check >= 0.2 ? 'warning' : 'info'
            return (
              <tr
                key={`${w.tail_number}-${w.position}`}
                onClick={() => onSelect(w.tail_number, w.position)}
                aria-selected={on}
                className="cursor-pointer border-t border-[var(--line)] transition-colors hover:bg-[var(--primary-soft)]"
                style={on ? { background: 'var(--primary-soft)' } : undefined}
                title={`${w.reason} — ${w.action}`}
              >
                <td className="py-1.5 pr-2 tabular-nums text-[var(--ink-4)]">{w.rank}</td>
                <td className="py-1.5 pr-2 tabular-nums text-[var(--ink)]">{w.tail_number}</td>
                <td className="py-1.5 pr-2 text-[var(--ink-3)]">{POSITION_SHORT[w.position]}</td>
                <td className="py-1.5 pr-2 text-[var(--ink-3)]">{w.station}</td>
                <td className="py-1.5 pr-2 text-right tabular-nums" style={{ color: severityInk(sev) }}>{fmtPct(w.p_cross_before_next_check)}</td>
                <td className="py-1.5 pr-2 text-right tabular-nums text-[var(--ink-2)]">{fmtLandings(w.rul_median_landings)}</td>
                <td className="py-1.5 tabular-nums text-[var(--ink-3)]">{fmtDate(w.earliest_credible_date)}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

export type WheelCell = { status?: WheelStatusResponse; loading: boolean; error?: boolean }

/** Six-wheel top-down map for one aircraft. Each position paints with its RUL severity; unknown /
 *  loading cells stay neutral. Click to select. Mirrors the gear map on the /tyres page. */
export function WheelRulMap({
  cells,
  selected,
  onSelect,
}: {
  cells: Record<WheelPosition, WheelCell>
  selected: WheelPosition | null
  onSelect: (position: WheelPosition) => void
}) {
  const positions = Object.keys(POSITION_XY) as WheelPosition[]
  return (
    <svg viewBox="0 0 100 82" className="w-full">
      <path d="M50 4 L50 78" style={{ stroke: 'var(--line-2)' }} strokeWidth="1" />
      <path d="M50 30 L14 56 M50 30 L86 56" style={{ stroke: 'var(--line-2)' }} strokeWidth="1" />
      <path d="M14 66 L86 66" style={{ stroke: 'var(--line)' }} strokeWidth="1" strokeDasharray="2 2" />
      {positions.map((pos) => {
        const [x, y] = POSITION_XY[pos]
        const cell = cells[pos]
        const on = pos === selected
        const hue = cell?.status ? severityHue(cell.status.severity) : 'var(--axis)'
        const label = cell?.status
          ? `${POSITION_LABEL[pos]} · ${RUL_STATUS_META[cell.status.status].label} · ${fmtLandings(cell.status.rul_median_landings)} ldg`
          : cell?.error
            ? `${POSITION_LABEL[pos]} · no data`
            : `${POSITION_LABEL[pos]} · loading`
        return (
          <g key={pos} onClick={() => onSelect(pos)} className="cursor-pointer">
            <title>{label}</title>
            <rect
              x={x - 5}
              y={y - 7}
              width="10"
              height="14"
              rx="2"
              fill={cell?.status ? (on ? hue : `${severityHue(cell.status.severity)}33`) : 'transparent'}
              style={{ stroke: on ? 'var(--ink)' : hue, opacity: cell?.loading ? 0.5 : 1 }}
              strokeWidth={on ? 1.2 : 0.7}
            />
            <text x={x} y={y + 15} textAnchor="middle" fontSize="4.2" style={{ fill: on ? 'var(--ink)' : 'var(--ink-4)' }}>
              {POSITION_SHORT[pos]}
            </text>
          </g>
        )
      })}
    </svg>
  )
}

/** Full condition + forecast panel for one mounted wheel (GET /wheel/status). */
export function WheelDetail({ data }: { data: WheelStatusResponse }) {
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <div className="text-sm text-[var(--ink)]">{data.tail_number}</div>
          <div className="text-[10px] uppercase tracking-widest text-[var(--ink-3)]">{POSITION_LABEL[data.position]} · {data.station}</div>
        </div>
        <SeverityBadge status={data.status} severity={data.severity} />
      </div>

      <p className="text-xs leading-relaxed text-[var(--ink-2)]">{data.headline}</p>
      <p className="text-[11px] leading-relaxed text-[var(--ink-3)]">{data.explanation}</p>

      <div className="grid grid-cols-2 gap-2">
        <Metric label="RUL median" value={`${fmtLandings(data.rul_median_landings)} ldg`} />
        <Metric label="RUL P10" value={`${fmtLandings(data.rul_p10_landings)} ldg`} warn />
        <Metric label="Earliest limit" value={fmtDate(data.earliest_credible_date)} warn />
        <Metric label="Utilization" value={`${data.utilization_landings_per_day}/day`} />
        <Metric
          label="Pressure"
          value={data.pressure_pct === null ? '—' : `${data.pressure_pct.toFixed(1)}%`}
          warn={data.pressure_action !== 'ok'}
        />
        <Metric label="Spares · station" value={`${data.spares_on_hand}`} warn={data.spares_on_hand === 0} />
      </div>

      <div>
        <div className="mb-1 text-[10px] uppercase tracking-widest text-[var(--ink-3)]">P(cross before next check)</div>
        <ProbMeter p={data.p_cross_before_next_check} severity={data.severity} />
      </div>

      <div className="border-t border-[var(--line)] pt-2">
        <div className="text-[10px] uppercase tracking-widest text-[var(--ink-4)]">Recommended action</div>
        <p className="mt-0.5 text-xs leading-relaxed" style={{ color: severityInk(data.severity) }}>{data.recommended_action}</p>
      </div>
      {data.low_confidence && (
        <p className="text-[10px] uppercase tracking-widest" style={{ color: 'var(--warn)' }}>⚠ Low confidence — few readings, fleet prior dominates</p>
      )}
    </div>
  )
}

function Metric({ label, value, warn }: { label: string; value: string; warn?: boolean }) {
  return (
    <div className="border border-[var(--line)] bg-[var(--panel)] px-2 py-1.5">
      <div className="text-[9px] uppercase tracking-widest text-[var(--ink-4)]">{label}</div>
      <div className="text-sm tabular-nums" style={{ color: warn ? 'var(--warn)' : 'var(--ink-2)' }}>{value}</div>
    </div>
  )
}
