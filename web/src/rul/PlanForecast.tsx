import { useEffect, useMemo, useRef, useState } from 'react'
import { Card } from '../ui'
import { useRulPrediction, useWheelStatus, useWorklist, type RulPredictionRequest, type WheelPosition } from './api'
import { RulForecastCard } from './RulCards'
import {
  CANON_POSITIONS,
  DEFAULT_LANDINGS_PER_DAY,
  fmtLandings,
  POSITION_LABEL,
  RUL_STATUS_META,
  severityInk,
} from './positions'

// Manual planning form: enter a wheel's position, utilization, and measured tread-depth readings,
// then run POST /predict. /predict itself is aircraft-agnostic, so the optional tail selector is a
// convenience: picking a real aircraft prefills the position's live utilization (from /wheel/status)
// so a what-if starts from the fleet baseline. The forecast still runs on the typed readings.
// Works with no tail (and even when the fleet dataset is offline) — /predict needs no fleet tables.

type ReadingDraft = { cycles: string; groove: string }

const DEFAULT_READINGS: ReadingDraft[] = [
  { cycles: '0', groove: '12.0' },
  { cycles: '120', groove: '8.5' },
  { cycles: '250', groove: '5.2' },
]

const inputCls =
  'w-full border border-[var(--line-2)] bg-[var(--panel)] px-2 py-1 text-xs tabular-nums text-[var(--ink-2)] outline-none focus:border-[var(--primary)]'

/** Parse the string-backed form into a valid request, or return the first blocking problem. Blank
 *  reading rows are dropped; the backend does the strict range checks and returns 422 messages. */
function buildRequest(
  position: WheelPosition,
  cycles: string,
  lpd: string,
  asOf: string,
  readings: ReadingDraft[],
): { req?: RulPredictionRequest; error?: string } {
  const current = Number(cycles)
  const lpdNum = Number(lpd)
  if (cycles.trim() === '' || !Number.isFinite(current) || current < 0) return { error: 'Current cycles must be a number ≥ 0.' }
  if (lpd.trim() === '' || !Number.isFinite(lpdNum) || lpdNum <= 0) return { error: 'Landings/day must be a number > 0.' }

  const parsed: RulPredictionRequest['readings'] = []
  for (const r of readings) {
    if (r.cycles.trim() === '' && r.groove.trim() === '') continue // an untouched row
    const c = Number(r.cycles)
    const g = Number(r.groove)
    if (!Number.isFinite(c) || c < 0) return { error: 'Every reading needs cycles ≥ 0.' }
    if (!Number.isFinite(g) || g <= 0) return { error: 'Every reading needs groove > 0 mm.' }
    parsed.push({ cycles_since_install: c, measured_groove_mm: g })
  }

  const req: RulPredictionRequest = { position, current_cycles: current, landings_per_day: lpdNum, readings: parsed }
  if (asOf) req.as_of_date = asOf
  return { req }
}

export default function PlanForecast() {
  const [tail, setTail] = useState('') // '' = none / manual
  const [position, setPosition] = useState<WheelPosition>('mlg_l_outbd')
  const [cycles, setCycles] = useState('250')
  const [lpd, setLpd] = useState(String(DEFAULT_LANDINGS_PER_DAY))
  const [asOf, setAsOf] = useState('')
  const [readings, setReadings] = useState<ReadingDraft[]>(DEFAULT_READINGS)
  const [clientError, setClientError] = useState<string | null>(null)
  // Run once on mount with the defaults so the panel opens on a worked example, then on each Run.
  const [submitted, setSubmitted] = useState<RulPredictionRequest | null>(
    () => buildRequest('mlg_l_outbd', '250', String(DEFAULT_LANDINGS_PER_DAY), '', DEFAULT_READINGS).req ?? null,
  )

  // Aircraft list is sourced from the worklist (no dedicated list-tails endpoint); an unfiltered
  // top-50 pull covers the fleet. Degrades to manual-only when the fleet dataset is offline (503).
  const fleet = useWorklist(50, null)
  const tails = useMemo(
    () => [...new Set((fleet.data?.wheels ?? []).map((w) => w.tail_number))].sort(),
    [fleet.data],
  )
  const fleetOffline = fleet.error?.status === 503 || fleet.error?.code === 'FLEET_DATA_UNAVAILABLE'

  // Live status for the chosen tail+position — prefills utilization and shows the fleet baseline.
  const live = useWheelStatus(tail || null, position)
  const prefilledRef = useRef<string | null>(null)
  useEffect(() => {
    const d = live.data
    if (!d) return
    const key = `${d.tail_number}:${d.position}`
    if (prefilledRef.current === key) return // only prefill once per tail+position, never over an edit
    prefilledRef.current = key
    setLpd(String(d.utilization_landings_per_day))
  }, [live.data])

  const q = useRulPrediction(submitted)

  const setReading = (i: number, key: keyof ReadingDraft, value: string) =>
    setReadings((rs) => rs.map((r, j) => (j === i ? { ...r, [key]: value } : r)))
  const addReading = () => setReadings((rs) => [...rs, { cycles: '', groove: '' }])
  const removeReading = (i: number) => setReadings((rs) => (rs.length > 1 ? rs.filter((_, j) => j !== i) : rs))

  const run = () => {
    const { req, error } = buildRequest(position, cycles, lpd, asOf, readings)
    if (error) {
      setClientError(error)
      return
    }
    setClientError(null)
    setSubmitted(req ?? null)
  }

  return (
    <Card title="Plan a forecast" tag="POST /predict · manual inspection data">
      <div className="grid gap-4 lg:grid-cols-2">
        {/* left: the input form */}
        <div className="space-y-3">
          <label className="block">
            <span className="flex items-baseline justify-between text-[10px] uppercase tracking-widest text-[var(--ink-4)]">
              <span>Aircraft (tail) <span className="text-[var(--ink-4)]">— optional, prefills utilization</span></span>
              {fleetOffline && <span style={{ color: 'var(--warn)' }}>fleet offline · manual only</span>}
            </span>
            <select value={tail} onChange={(e) => setTail(e.target.value)} className={`${inputCls} mt-1`} disabled={fleetOffline}>
              <option value="">— none (manual) —</option>
              {tails.map((t) => (
                <option key={t} value={t}>{t}</option>
              ))}
            </select>
          </label>

          {tail && (
            <p className="-mt-1 text-[10px] leading-relaxed">
              {live.isLoading ? (
                <span className="text-[var(--ink-4)]">Loading live wheel status…</span>
              ) : live.data ? (
                <span className="text-[var(--ink-4)]">
                  Fleet baseline:{' '}
                  <span style={{ color: severityInk(live.data.severity) }}>{RUL_STATUS_META[live.data.status].label}</span>
                  {' '}· median {fmtLandings(live.data.rul_median_landings)} ldg · util {live.data.utilization_landings_per_day}/day — utilization prefilled below.
                </span>
              ) : live.error?.status === 404 ? (
                <span className="text-[var(--ink-4)]">No live wheel at {POSITION_LABEL[position]} for {tail}.</span>
              ) : null}
            </p>
          )}

          <div className="grid grid-cols-2 gap-2">
            <label className="block">
              <span className="text-[10px] uppercase tracking-widest text-[var(--ink-4)]">Position</span>
              <select value={position} onChange={(e) => setPosition(e.target.value as WheelPosition)} className={`${inputCls} mt-1`}>
                {CANON_POSITIONS.map((p) => (
                  <option key={p} value={p}>{POSITION_LABEL[p]}</option>
                ))}
              </select>
            </label>
            <label className="block">
              <span className="text-[10px] uppercase tracking-widest text-[var(--ink-4)]">Current cycles</span>
              <input type="number" min={0} value={cycles} onChange={(e) => setCycles(e.target.value)} className={`${inputCls} mt-1`} />
            </label>
            <label className="block">
              <span className="text-[10px] uppercase tracking-widest text-[var(--ink-4)]">Landings / day</span>
              <input type="number" min={0} step={0.5} value={lpd} onChange={(e) => setLpd(e.target.value)} className={`${inputCls} mt-1`} />
            </label>
            <label className="block">
              <span className="text-[10px] uppercase tracking-widest text-[var(--ink-4)]">As-of date <span className="text-[var(--ink-4)]">(opt)</span></span>
              <input type="date" value={asOf} onChange={(e) => setAsOf(e.target.value)} className={`${inputCls} mt-1`} />
            </label>
          </div>

          <div>
            <div className="mb-1 flex items-center justify-between">
              <span className="text-[10px] uppercase tracking-widest text-[var(--ink-4)]">Tread-depth readings</span>
              <button onClick={addReading} className="text-[10px] uppercase tracking-widest text-[var(--primary)] hover:text-[var(--ink)]">+ Add</button>
            </div>
            <div className="grid grid-cols-[1fr_1fr_auto] gap-1.5 text-[9px] uppercase tracking-widest text-[var(--ink-4)]">
              <span>Cycles since install</span>
              <span>Groove mm</span>
              <span />
            </div>
            <div className="mt-1 space-y-1.5">
              {readings.map((r, i) => (
                <div key={i} className="grid grid-cols-[1fr_1fr_auto] items-center gap-1.5">
                  <input type="number" min={0} value={r.cycles} onChange={(e) => setReading(i, 'cycles', e.target.value)} className={inputCls} placeholder="0" />
                  <input type="number" min={0} step={0.1} value={r.groove} onChange={(e) => setReading(i, 'groove', e.target.value)} className={inputCls} placeholder="mm" />
                  <button
                    onClick={() => removeReading(i)}
                    aria-label={`Remove reading ${i + 1}`}
                    disabled={readings.length <= 1}
                    className="px-1.5 text-[var(--ink-4)] transition-colors hover:text-[var(--crit)] disabled:opacity-30"
                  >
                    ✕
                  </button>
                </div>
              ))}
            </div>
            <p className="mt-1.5 text-[10px] leading-relaxed text-[var(--ink-4)]">
              Leave readings empty to forecast from the fleet/position prior alone (flagged low-confidence).
            </p>
          </div>

          <div className="flex items-center gap-3">
            <button
              onClick={run}
              className="border border-[var(--primary)] px-3 py-1.5 text-[10px] uppercase tracking-widest text-[var(--primary)] transition-colors hover:bg-[var(--primary-soft)]"
            >
              ▸ Run forecast
            </button>
            {clientError && <span className="text-[10px] text-[var(--crit)]">{clientError}</span>}
          </div>
        </div>

        {/* right: the result */}
        <div className="border-t border-[var(--line)] pt-3 lg:border-l lg:border-t-0 lg:pl-4 lg:pt-0">
          {q.isLoading ? (
            <p className="py-8 text-center text-xs text-[var(--ink-4)]">Forecasting…</p>
          ) : q.error ? (
            <p className="py-6 text-center text-xs text-[var(--crit)]">{q.error.message}</p>
          ) : q.data ? (
            <RulForecastCard data={q.data} />
          ) : (
            <p className="py-8 text-center text-xs text-[var(--ink-4)]">Enter data and run a forecast.</p>
          )}
        </div>
      </div>
    </Card>
  )
}
