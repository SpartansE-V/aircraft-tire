import { useEffect, useState } from 'react'
import { Card, Header, useTheme } from '../ui'
import type { Status } from '../data'
import { useWheelStatus, useWorklist, type WheelPosition } from './api'
import { WheelDetail, WheelRulMap, WorklistTable, type WheelCell } from './RulCards'
import PlanForecast from './PlanForecast'
import { fmtDate } from './positions'

const STATIONS = ['SGN', 'DAD', 'HAN'] as const
const TOP_N_OPTIONS = [10, 20, 30, 50]

type Selection = { tail: string; position: WheelPosition }

export default function Rul() {
  const [theme, setTheme] = useTheme()
  const [station, setStation] = useState<string | null>(null)
  const [topN, setTopN] = useState(20)
  const [selected, setSelected] = useState<Selection | null>(null)

  const worklist = useWorklist(topN, station)
  const wheels = worklist.data?.wheels ?? []

  // Land on the top-priority wheel once the fleet loads, but never yank a selection the user made.
  // Depend on the primitives (not the array) so the effect settles instead of firing every render.
  const firstTail = wheels[0]?.tail_number
  const firstPosition = wheels[0]?.position
  useEffect(() => {
    if (!selected && firstTail && firstPosition) setSelected({ tail: firstTail, position: firstPosition })
  }, [selected, firstTail, firstPosition])

  // Fleet status for the header light: the worst crossing probability across the worklist.
  const topP = wheels.reduce((m, w) => Math.max(m, w.p_cross_before_next_check), 0)
  const headerStatus: Status = topP >= 0.5 ? 'action' : topP >= 0.2 ? 'watch' : 'ok'

  const fleetOffline = worklist.error?.status === 503 || worklist.error?.code === 'FLEET_DATA_UNAVAILABLE'

  return (
    <div className="min-h-screen p-4 font-mono text-[var(--ink-2)] lg:p-6">
      <Header status={headerStatus} theme={theme} onTheme={setTheme} path="/rul" />

      <div className="grid gap-3 lg:grid-cols-12">
        {/* left: the dashboard — ranked fleet worklist */}
        <div className="lg:col-span-5">
          <Card title="Fleet worklist" tag="RUL · priority = P(cross) × consequence">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <div className="flex gap-1">
                <FilterChip label="All" on={station === null} onClick={() => setStation(null)} />
                {STATIONS.map((s) => (
                  <FilterChip key={s} label={s} on={station === s} onClick={() => setStation(s)} />
                ))}
              </div>
              <label className="flex items-center gap-1.5 text-[10px] uppercase tracking-widest text-[var(--ink-4)]">
                Top
                <select
                  value={topN}
                  onChange={(e) => setTopN(Number(e.target.value))}
                  className="border border-[var(--line-2)] bg-[var(--panel)] px-1 py-0.5 text-[var(--ink-2)]"
                >
                  {TOP_N_OPTIONS.map((n) => (
                    <option key={n} value={n}>{n}</option>
                  ))}
                </select>
              </label>
            </div>

            {worklist.isLoading ? (
              <p className="py-8 text-center text-xs text-[var(--ink-4)]">Loading worklist…</p>
            ) : fleetOffline ? (
              <FleetOfflineNotice />
            ) : worklist.error ? (
              <ErrorNotice message={worklist.error.message} onRetry={() => worklist.refetch()} />
            ) : (
              <WorklistTable
                wheels={wheels}
                selected={selected}
                onSelect={(tail, position) => setSelected({ tail, position })}
              />
            )}

            <div className="mt-3 flex justify-between border-t border-dashed border-[var(--line)] pt-2 text-[9px] uppercase tracking-widest text-[var(--ink-4)]">
              <span>{worklist.data ? `Snapshot ${fmtDate(worklist.data.as_of_date)}` : 'Fleet snapshot'}</span>
              <span>Ranked, not raw RUL</span>
            </div>
          </Card>
        </div>

        {/* centre: the RUL mapping — six-wheel gear map for the selected aircraft */}
        <div className="lg:col-span-3">
          <Card title={selected ? `${selected.tail} · wheel map` : 'Wheel map'} tag="RUL by position">
            {selected ? (
              <AircraftWheelMap
                tail={selected.tail}
                selected={selected.position}
                onSelect={(position) => setSelected({ tail: selected.tail, position })}
              />
            ) : (
              <p className="py-10 text-center text-xs text-[var(--ink-4)]">Select a wheel from the worklist.</p>
            )}
            <p className="mt-2 text-[10px] leading-relaxed text-[var(--ink-4)]">
              Every physical wheel maps to one of six fitted priors: 2 nose, plus inboard/outboard on each main bogie.
            </p>
          </Card>
        </div>

        {/* right: the selected wheel's condition + forecast */}
        <div className="lg:col-span-4">
          <Card title="Wheel Remaining Useful Life Prediction" tag="GET /wheel/status">
            {selected ? (
              <SelectedWheel tail={selected.tail} position={selected.position} />
            ) : (
              <p className="py-10 text-center text-xs text-[var(--ink-4)]">No wheel selected.</p>
            )}
          </Card>
        </div>
      </div>

      {/* full-width: manual planning forecast — type in readings and run /predict */}
      <div className="mt-3">
        <PlanForecast />
      </div>

      <footer className="mt-4 flex flex-wrap justify-between gap-2 text-[10px] uppercase tracking-widest text-[var(--ink-4)]">
        <span>Live · /api/v1/tire_rul · fleet worklist + per-wheel status + planner</span>
        <span>Decision-support only — not an approval for service</span>
      </footer>
    </div>
  )
}

function toCell(q: ReturnType<typeof useWheelStatus>): WheelCell {
  return { status: q.data, loading: q.isLoading, error: q.isError }
}

/** Calls /wheel/status once per canonical position (fixed order → rules-of-hooks safe) and paints
 *  the six-wheel map. React Query dedupes the detail panel's identical query, so this is 6 requests. */
function AircraftWheelMap({
  tail,
  selected,
  onSelect,
}: {
  tail: string
  selected: WheelPosition
  onSelect: (position: WheelPosition) => void
}) {
  const nlgL = useWheelStatus(tail, 'nlg_l')
  const nlgR = useWheelStatus(tail, 'nlg_r')
  const mlgLOut = useWheelStatus(tail, 'mlg_l_outbd')
  const mlgLIn = useWheelStatus(tail, 'mlg_l_inbd')
  const mlgRIn = useWheelStatus(tail, 'mlg_r_inbd')
  const mlgROut = useWheelStatus(tail, 'mlg_r_outbd')
  const cells: Record<WheelPosition, WheelCell> = {
    nlg_l: toCell(nlgL),
    nlg_r: toCell(nlgR),
    mlg_l_outbd: toCell(mlgLOut),
    mlg_l_inbd: toCell(mlgLIn),
    mlg_r_inbd: toCell(mlgRIn),
    mlg_r_outbd: toCell(mlgROut),
  }
  return <WheelRulMap cells={cells} selected={selected} onSelect={onSelect} />
}

function SelectedWheel({ tail, position }: { tail: string; position: WheelPosition }) {
  const q = useWheelStatus(tail, position)
  if (q.isLoading) return <p className="py-10 text-center text-xs text-[var(--ink-4)]">Loading forecast…</p>
  if (q.error?.status === 404) {
    return <p className="py-10 text-center text-xs text-[var(--ink-4)]">No current wheel at {position} for {tail}.</p>
  }
  if (q.error) return <ErrorNotice message={q.error.message} onRetry={() => q.refetch()} />
  return q.data ? <WheelDetail data={q.data} /> : null
}

function FilterChip({ label, on, onClick }: { label: string; on: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      aria-pressed={on}
      className="border px-2 py-1 text-[10px] uppercase tracking-widest transition-colors"
      style={{ borderColor: on ? 'var(--primary)' : 'var(--line-2)', color: on ? 'var(--primary)' : 'var(--ink-3)' }}
    >
      {label}
    </button>
  )
}

function FleetOfflineNotice() {
  return (
    <div className="py-6 text-center">
      <p className="text-xs text-[var(--warn)]">Fleet dataset / AI stack not available on this deployment.</p>
      <p className="mt-2 text-[11px] leading-relaxed text-[var(--ink-4)]">
        The worklist and per-wheel status read the fleet parquet tables. Per-wheel RUL forecasting via{' '}
        <span className="text-[var(--ink-3)]">POST /predict</span> still works — see the Remaining-life card on the Tyres page.
      </p>
    </div>
  )
}

function ErrorNotice({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="py-6 text-center">
      <p className="text-xs text-[var(--crit)]">{message}</p>
      <button
        onClick={onRetry}
        className="mt-2 border border-[var(--line-2)] px-3 py-1 text-[10px] uppercase tracking-widest text-[var(--ink-3)] transition-colors hover:text-[var(--ink)]"
      >
        Retry
      </button>
    </div>
  )
}
