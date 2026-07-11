import { useMemo, useState } from 'react'
import type { Tire } from '../data'
import { Card, Open } from '../ui'
import { useRulPrediction } from './api'
import { RulForecastCard } from './RulCards'
import { buildPredictionRequest, DEFAULT_LANDINGS_PER_DAY, POSITION_LABEL, toCanonicalPosition } from './positions'

// Bridges the mock 3D dashboard to the live RUL model: it maps the selected wheel to its canonical
// position, synthesizes a fresh→current wear line from the tire's grooves, and posts /predict. The
// utilization slider is the model's what-if lever — more landings/day pulls the wear-to-limit dates in.

export default function RemainingLifeCard({ tire }: { tire: Tire }) {
  const [landingsPerDay, setLandingsPerDay] = useState(DEFAULT_LANDINGS_PER_DAY)
  const req = useMemo(() => buildPredictionRequest(tire, landingsPerDay), [tire, landingsPerDay])
  const q = useRulPrediction(req)

  return (
    <Card title="Remaining life" tag={`RUL · ${POSITION_LABEL[toCanonicalPosition(tire)]}`}>
      <div className="mb-3">
        <div className="flex items-baseline justify-between text-[10px] uppercase tracking-widest text-[var(--ink-3)]">
          <span>Utilization · what-if</span>
          <span className="tabular-nums text-[var(--ink-2)]">{landingsPerDay.toFixed(1)} ldg/day</span>
        </div>
        <input
          type="range"
          min={2}
          max={8}
          step={0.5}
          value={landingsPerDay}
          onChange={(e) => setLandingsPerDay(Number(e.target.value))}
          aria-label="Landings per day"
          className="mt-1.5 w-full accent-[var(--primary)]"
        />
      </div>

      {q.isLoading ? (
        <p className="py-8 text-center text-xs text-[var(--ink-4)]">Forecasting…</p>
      ) : q.error ? (
        <p className="py-6 text-center text-xs text-[var(--crit)]">{q.error.message}</p>
      ) : q.data ? (
        <RulForecastCard data={q.data} />
      ) : null}

      <Open>Grooves and cycles seed a fresh→current wear line — replace the synthetic history with real inspection readings and the band tightens</Open>
    </Card>
  )
}
