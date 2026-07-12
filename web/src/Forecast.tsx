// The forecast panel: everything the assessment API says, rendered so nobody mistakes it for a
// measurement. The rules it implements — and why — are in ../API_INTEGRATION.md.
import { useState, type ReactNode } from 'react'
import { HUE } from './charts'
import { isWithheld, toAssessmentRequest, useAssessment, type AssessmentResponse, type Clamp } from './assessment'
import type { Tire } from './data'
import type { Attitude } from './landingEngine'
import { useMock } from './mock'
import type { Landing } from './sim'
import { Field } from './ui'

/**
 * The model surface. Every number inside one of these came from the demonstration model — not from an
 * instrument, and not from the physics in sim.ts. Nothing else in the app looks like this, on purpose.
 */
function ModelPanel({ state, children }: { state: string; children: ReactNode }) {
  return (
    <section className="model-surface flex flex-col p-3">
      <div className="mb-2 flex items-baseline justify-between gap-2">
        <h2 className="text-xs uppercase tracking-[0.2em] text-[var(--ink)]">
          <span className="mr-2 text-[var(--ink-4)]">MODEL ·</span>Forecast
        </h2>
        <span className="text-[9px] uppercase tracking-widest text-[var(--ink-4)]">{state}</span>
      </div>
      <div className="flex flex-1 flex-col">{children}</div>
    </section>
  )
}

/** Rule 7: round to the precision the model has earned. A trailing decimal it cannot support is a lie. */
const mm = (v: number) => v.toFixed(1)
const whole = (v: number) => Math.round(v)

/**
 * Rule 6: a probability from an uncalibrated model is not a probability. `0.37` invites arithmetic
 * nobody is entitled to do with it; three words do not.
 */
function likelihood(p: number) {
  return p < 0.15 ? 'unlikely' : p < 0.6 ? 'possible' : 'likely'
}

/** Rule 5: what you asked for, and what the model was actually given. The clamp, made impossible to miss. */
function InputTruth({ clamps }: { clamps: Clamp[] }) {
  if (clamps.length === 0) return null
  const n = clamps.length
  return (
    <div className="mt-3 border-t border-dashed border-[var(--warn-line)] pt-2">
      <div className="mb-1.5 flex items-baseline justify-between text-[9px] uppercase tracking-widest text-[var(--ink-4)]">
        <span>What the model was told</span>
        <span>your scenario → sent</span>
      </div>
      {clamps.map((c) => (
        <Field
          key={c.key}
          k={c.label}
          warn
          v={`${whole(c.asked).toLocaleString()} → ${whole(c.sent).toLocaleString()} ${c.unit}`}
        />
      ))}
      <p className="mt-2 text-[10px] leading-relaxed text-[var(--ink-3)]">
        {n === 1 ? '1 input was' : `${n} inputs were`} clamped to the model's domain. It is fitted to a
        50–73.5 t narrowbody; the aircraft on this screen is a 777-300ER at 200 t.{' '}
        <span className="text-[var(--warn)]">These numbers do not describe it.</span>
      </p>
    </div>
  )
}

/** Rule 2: the words, always available, never shouting. The surface already carries the warning. */
function Governance({ a }: { a: AssessmentResponse }) {
  const g = a.governance
  return (
    <details className="mt-3 border-t border-dashed border-[var(--warn-line)] pt-2">
      <summary className="cursor-pointer text-[10px] uppercase tracking-widest text-[var(--ink-4)] hover:text-[var(--ink-3)]">
        ▸ What this model is
      </summary>
      <div className="mt-2 space-y-1">
        <Field k="release" v={g.release_id} mono />
        <Field k="lifecycle" v={g.lifecycle} />
        <Field k="permitted use" v={g.requested_use} />
      </div>
    </details>
  )
}

/**
 * Rule 8: the most dangerous number in the response.
 *
 * `12% chance of removal` is what gets screenshotted into a slide with every caveat stripped off. The
 * defensible signal is the *ranking* — which mode dominates — so that is what the bars show. The
 * aggregate stays (hiding returned data is its own dishonesty) but it is labelled for what it is, and
 * none of it is ever red. Red means an instrument measured something.
 */
function RemovalModes({ a }: { a: AssessmentResponse }) {
  const modes = [...a.unscheduled_removal_risk.modes].sort((x, y) => y.synthetic_probability_pct - x.synthetic_probability_pct)
  const top = Math.max(...modes.map((m) => m.synthetic_probability_pct), 0.01)
  return (
    <div className="mt-3">
      <div className="mb-1.5 flex items-baseline justify-between gap-2">
        <span className="text-[9px] uppercase tracking-widest text-[var(--ink-4)]">Removal drivers, ranked</span>
        <span className="text-[9px] uppercase tracking-widest text-[var(--ink-4)]">
          synthetic — not a failure rate
        </span>
      </div>
      <div className="space-y-1">
        {modes.slice(0, 5).map((m) => (
          <div key={m.mode} className="flex items-center gap-2" title={m.drivers.join(' · ')}>
            <span className="w-32 shrink-0 text-[10px] uppercase tracking-wider text-[var(--ink-3)]">
              {m.mode.replace(/_/g, ' ').toLowerCase()}
            </span>
            <div className="h-1.5 flex-1 rounded-full bg-[var(--track)]">
              <div
                className="h-1.5 rounded-full"
                style={{ width: `${(m.synthetic_probability_pct / top) * 100}%`, background: HUE.alt }}
              />
            </div>
          </div>
        ))}
      </div>
      <p className="mt-2 text-[10px] leading-relaxed text-[var(--ink-4)]">
        Aggregate over {a.forecast.horizon_cycles} cycles:{' '}
        <span className="tabular-nums text-[var(--ink-3)]">{whole(a.unscheduled_removal_risk.synthetic_probability_pct)}%</span>{' '}
        — a synthetic demonstration figure, not an observed failure rate.
      </p>
    </div>
  )
}

function Result({ a, clamps }: { a: AssessmentResponse; clamps: Clamp[] }) {
  const tread = a.forecast.final_tread_depth_mm
  const cyc = a.forecast.cycles_to_planning_threshold
  return (
    <>
      {/* Rule 6: never a naked p50. The width of the band is the honest part of the answer. */}
      <div className="grid grid-cols-2 gap-2">
        <div className="border border-dashed border-[var(--line-2)] p-2">
          <div className="text-[10px] uppercase tracking-widest text-[var(--ink-4)]">
            Tread in {a.forecast.horizon_cycles} cycles
          </div>
          <div className="mt-1 text-xl font-semibold tabular-nums text-[var(--ink-2)]">
            {mm(tread.p50)}
            <span className="ml-1 text-xs font-normal text-[var(--ink-4)]">mm</span>
          </div>
          <div className="text-[10px] tabular-nums text-[var(--ink-4)]">
            p10–p90 {mm(tread.p10)}–{mm(tread.p90)} mm
          </div>
        </div>
        <div className="border border-dashed border-[var(--line-2)] p-2">
          <div className="text-[10px] uppercase tracking-widest text-[var(--ink-4)]">To planning threshold</div>
          <div className="mt-1 text-xl font-semibold tabular-nums text-[var(--ink-2)]">
            {whole(cyc.p10)}–{whole(cyc.p90)}
            <span className="ml-1 text-xs font-normal text-[var(--ink-4)]">cycles</span>
          </div>
          <div className="text-[10px] tabular-nums text-[var(--ink-4)]">median {whole(cyc.p50)}</div>
        </div>
      </div>

      {/*
        Rule 4: the app's ●/◆/▲ status vocabulary means "an instrument measured a real problem". The
        model does not get to speak it. It gets its own words, in its own ink, on its own surface.
      */}
      <div className="mt-3 border-t border-dashed border-[var(--line-2)] pt-2">
        <div className="text-[10px] uppercase tracking-[0.2em] text-[var(--ink-3)]">
          {a.recommendation.attention.replace(/_/g, ' ')}
        </div>
        <p className="mt-1 text-[10px] leading-relaxed text-[var(--ink-4)]">{a.recommendation.message}</p>
      </div>

      <div className="mt-2 space-y-1">
        <Field
          k={`Threshold within ${a.forecast.horizon_cycles} cycles`}
          v={likelihood(a.forecast.probability_threshold_within_horizon)}
        />
        <Field
          k="Holding reference pressure"
          v={`${a.pressure_policy_comparison.estimated_median_cycle_difference >= 0 ? '+' : ''}${whole(
            a.pressure_policy_comparison.estimated_median_cycle_difference,
          )} cycles`}
        />
      </div>

      {a.scenario_drivers.length > 0 && (
        <p className="mt-2 text-[10px] leading-relaxed text-[var(--ink-4)]">
          Drivers: {a.scenario_drivers.join(' · ')}
        </p>
      )}

      <InputTruth clamps={clamps} />
      <RemovalModes a={a} />
      <Governance a={a} />
    </>
  )
}

/**
 * Rule 3: a withheld assessment is a *layout*, not an error.
 *
 * Most tyres in this fleet land here, because most of them have damage recorded — and the model
 * declining to forecast a damaged tyre is the most valuable thing this endpoint demonstrates. Same
 * panel, same position, no red, no ⚠. The blank space where the numbers would be is the message.
 */
function Withheld({ code, message, clamps }: { code: string; message: string; clamps: Clamp[] }) {
  const outsideDomain = code === 'MODEL_INPUT_OUTSIDE_RELEASE_DOMAIN'
  return (
    <>
      <p className="text-sm text-[var(--ink-2)]">
        {outsideDomain ? 'This scenario is outside what the model was built for.' : 'No forecast for this tyre.'}
      </p>
      <p className="mt-2 text-[11px] leading-relaxed text-[var(--ink-3)]">{message}</p>
      {!outsideDomain && (
        <p className="mt-2 text-[11px] leading-relaxed text-[var(--ink-4)]">
          The model does not forecast a tyre in this condition. That is a job for a qualified inspection,
          not a projection.
        </p>
      )}
      <Field k="reason" v={code.replace(/_/g, ' ').toLowerCase()} mono />
      <InputTruth clamps={clamps} />
    </>
  )
}

export default function Forecast({ tire, landing, attitude }: { tire: Tire; landing: Landing; attitude: Attitude }) {
  const { mutate, data, error, isPending, reset } = useAssessment()
  const mockAllowed = useMock()
  // Rebuilt every render because the sliders move; cheap, and it keeps the clamp list honest for the
  // *current* scenario even before anything is sent.
  const { request, clamps } = toAssessmentRequest(tire, landing, attitude)
  const [submitted, setSubmitted] = useState<{ request: typeof request; clamps: Clamp[] } | null>(null)
  const scenarioChanged = submitted !== null && JSON.stringify(submitted.request) !== JSON.stringify(request)

  /*
    The endpoint is real. Everything we tell it about the tyre is not.
    `current_condition` — tread depth, pressure, cycles, retreads, defects — is read straight out of
    FLEET_TIRES, which is invented. So with mock telemetry off there is no assessment to make: we would
    be asking a real model a made-up question and printing the answer as though it meant something.
    A real forecast needs a real tyre, and no feed supplies one yet.
  */
  if (!mockAllowed) {
    return (
      <ModelPanel state="no input">
        <p className="text-sm text-[var(--ink-2)]">Nothing to assess.</p>
        <p className="mt-2 text-[11px] leading-relaxed text-[var(--ink-3)]">
          The assessment endpoint is real and connected. What it needs — measured tread, pressure, cycles,
          retreads, defects — is not: all of it comes from mock telemetry. With that switched off there is no
          tyre to ask about.
        </p>
        <p className="mt-2 text-[11px] leading-relaxed text-[var(--ink-4)]">
          Wire TPMS and the tread scanner into <code>current_condition</code> and this panel works against
          real tyres unchanged.
        </p>
      </ModelPanel>
    )
  }

  const state = scenarioChanged
    ? 'scenario changed'
    : isPending
      ? 'running'
      : data
        ? `${data.forecast.horizon_cycles} cycles`
        : error
          ? isWithheld(error)
            ? 'withheld'
            : 'error'
          : 'idle'
  const submittedClamps = submitted?.clamps ?? clamps

  return (
    <ModelPanel state={state}>
      {/* Not on every slider move: this is a 1000-sample Monte-Carlo run, and the physics beside it is
          already instant and local. The user asks for a forecast; they do not stumble into one. */}
      <button
        type="button"
        onClick={() => {
          reset()
          setSubmitted({ request, clamps })
          mutate(request)
        }}
        disabled={isPending}
        className="mb-3 w-full border border-[var(--line-2)] px-2 py-1.5 text-[10px] uppercase tracking-widest text-[var(--ink-3)] hover:border-[var(--primary-dim)] hover:text-[var(--ink)] disabled:opacity-50"
      >
        {isPending
          ? 'Assessing…'
          : scenarioChanged
            ? 'Assess changed scenario'
            : data || error
              ? 'Re-assess this scenario'
              : 'Assess next 50 cycles'}
      </button>

      {scenarioChanged && (
        <p className="text-[11px] leading-relaxed text-[var(--ink-3)]">
          The landing inputs or selected tire changed. Run the assessment again; results from the previous
          scenario are hidden so they cannot be mistaken for the current one.
        </p>
      )}

      {data && !scenarioChanged && <Result a={data} clamps={submittedClamps} />}

      {error && !scenarioChanged &&
        (isWithheld(error) ? (
          <Withheld code={error.code} message={error.message} clamps={submittedClamps} />
        ) : (
          // The only true error state: the service is broken, and retrying is the right move.
          <p className="text-[11px] leading-relaxed" style={{ color: 'var(--crit)' }}>
            ⚠ {error.message}
          </p>
        ))}

      {!data && !error && !isPending && !scenarioChanged && (
        <p className="text-[10px] leading-relaxed text-[var(--ink-4)]">
          Projects this tyre's tread over the next 50 cycles from the scenario on the left. Uncalibrated
          demonstration model — it does not decide serviceability.
        </p>
      )}
    </ModelPanel>
  )
}
