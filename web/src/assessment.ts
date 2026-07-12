// The tire-assessment API: its contract, the mapper from this app's state into it, and the one fetch.
// Design notes and the reasoning behind the clamping live in ../API_INTEGRATION.md.
//
// ponytail: one endpoint, one file. No client class or codegen. Development uses Vite's /api proxy;
// deployments that do not provide a same-origin reverse proxy can set VITE_API_BASE.
import { useMutation } from '@tanstack/react-query'
import { knownDefects, type DefectCode, type Tire } from './data.ts'
import { crosswindKt, trueGroundSpeedMps, type Landing } from './sim.ts'
import type { Attitude } from './landingEngine.ts'

export type Range = { minimum: number; most_likely: number; maximum: number }
export type RunwayCondition = 'DRY' | 'WET' | 'CONTAMINATED' | 'ROUGH'
export type ProfileId = 'pilot-main-v1' | 'pilot-nose-v1'

const ENV = (import.meta as ImportMeta & { env?: Record<string, string | undefined> }).env ?? {}
const API_BASE = (ENV.VITE_API_BASE ?? '').replace(/\/$/, '')

export type AssessmentRequest = {
  intended_use: 'SCENARIO_PLANNING'
  profile_id: ProfileId
  current_condition: {
    cycles_since_install: number
    current_tread_depth_mm: number
    measured_cold_pressure_psi: number
    reference_cold_pressure_psi: number
    tire_temperature_c: number
    retread_count: number
    known_defects: DefectCode[]
  }
  horizon_cycles: number
  simulation_runs: number
  random_seed: number
  future_conditions: {
    landing_weight_kg: Range
    touchdown_ground_speed_ms: Range
    crosswind_kt: Range
    touchdown_sink_rate_ms: Range
    touchdown_yaw_angle_deg: Range
    taxi_distance_km: Range
    average_taxi_speed_kt: Range
    outside_air_temperature_c: Range
    brake_temperature_c: Range
    heavy_braking_probability: number
    runway_condition: RunwayCondition
  }
}

type Summary = { p10: number; p50: number; p90: number }

/** Only what the UI renders. Widen as panels need more. */
export type AssessmentResponse = {
  assessment_id: string
  governance: {
    release_id: string
    lifecycle: string
    calibration_status: string
    validation_status: string
    authorization_status: string
    requested_use: string
    manifest_sha256: string
  }
  current_condition: { status: string; pressure_deficit_pct: number; known_defects: DefectCode[] }
  forecast: {
    horizon_cycles: number
    final_tread_depth_mm: Summary
    cycles_to_planning_threshold: Summary
    probability_threshold_within_horizon: number
  }
  pressure_policy_comparison: {
    current_pressure_policy_median_cycles: number
    maintained_reference_pressure_median_cycles: number
    estimated_median_cycle_difference: number
  }
  unscheduled_removal_risk: {
    synthetic_probability_pct: number
    modes: { mode: string; synthetic_probability_pct: number; drivers: string[] }[]
  }
  recommendation: { attention: string; message: string }
  confidence: { level: string; reason: string }
  scenario_drivers: string[]
  assumptions: string[]
  disclaimer: string
}

// ── Release envelope ────────────────────────────────────────────────────────────────────────────
// pilot-sim-2.0.0's modeled domain (app/model_releases/pilot-sim-2.0.0/parameters.json). Outside it the
// service returns 422 rather than extrapolate — so we clamp, and we tell the user we clamped.
//
// The weight row is the loud one: this envelope is a ~737. The aircraft in this app is a 777-300ER at
// 200 t. The backend spec is correct and stays; the mismatch is real and the UI's job is to *show* it,
// never to quietly launder 737 numbers as though they described the aircraft on screen.
export const ENVELOPE = {
  landing_weight_kg: [50_000, 73_500],
  touchdown_ground_speed_ms: [58, 82],
  crosswind_kt: [0, 25],
  touchdown_sink_rate_ms: [0, 4],
  touchdown_yaw_angle_deg: [0, 15],
  taxi_distance_km: [0.5, 8],
  average_taxi_speed_kt: [0, 30],
  outside_air_temperature_c: [5, 45],
  brake_temperature_c: [0, 600],
} as const satisfies Record<string, readonly [number, number]>

export type EnvelopeKey = keyof typeof ENVELOPE

/** One future input after clamping: what you asked for, what the model was actually given. */
export type Clamp = { key: EnvelopeKey; label: string; asked: number; sent: number; unit: string }

const FPM_TO_MS = 1 / 196.85

const clamp = (v: number, [lo, hi]: readonly [number, number]) => Math.min(hi, Math.max(lo, v))

/**
 * A future input as a range. The UI holds one number per input; the model wants a distribution over the
 * next N cycles. The slider value is the most-likely, and `spread` expresses how much the next N cycles
 * are expected to vary around it — not a confidence interval, just dispersion.
 *
 * Every bound is clamped independently, so a range that straddles the envelope edge gets flattened
 * against it rather than rejected.
 */
function range(value: number, spread: number, key: EnvelopeKey): Range {
  const e = ENVELOPE[key]
  return {
    minimum: clamp(value * (1 - spread), e),
    most_likely: clamp(value, e),
    maximum: clamp(value * (1 + spread), e),
  }
}

const RUNWAY: Record<Landing['surface'], RunwayCondition> = {
  dry: 'DRY',
  wet: 'WET',
  contaminated: 'CONTAMINATED',
}

export type ScenarioOpts = { horizonCycles?: number; simulationRuns?: number; randomSeed?: number }

/**
 * App state → one assessment request, plus the list of inputs we had to clamp to get there.
 *
 * The clamp list is not diagnostics. It is UI: the caller renders it, because a forecast built from a
 * clamped scenario that does not say so is the one genuinely dishonest thing this integration could do.
 */
export function toAssessmentRequest(
  tire: Tire,
  l: Landing,
  att: Attitude,
  opts: ScenarioOpts = {},
): { request: AssessmentRequest; clamps: Clamp[] } {
  const asked = {
    landing_weight_kg: l.weightT * 1000,
    // `gsKt` is indicated approach speed. The assessment contract asks for speed over the runway,
    // which also includes field-elevation and head/tailwind effects already modeled by the simulator.
    touchdown_ground_speed_ms: trueGroundSpeedMps(l),
    // The app's crosswind is signed (from the left / from the right). The model wants a magnitude.
    crosswind_kt: Math.abs(crosswindKt(l)),
    touchdown_sink_rate_ms: l.sinkFpm * FPM_TO_MS,
    touchdown_yaw_angle_deg: Math.abs(att.crabDeg),
    taxi_distance_km: tire.taxiKm,
    average_taxi_speed_kt: tire.taxiAvgKt,
    outside_air_temperature_c: l.oatC,
    // ponytail: the app models brakeShare (an energy split), not a temperature. Straight-line proxy off
    // the OAT — cold brakes at no braking, ~500 °C at full. Replace when the sim carries a real brake
    // thermal model; it is the one input here with no honest source.
    brake_temperature_c: l.oatC + l.brakeShare * 500,
  } satisfies Record<EnvelopeKey, number>

  const future: AssessmentRequest['future_conditions'] = {
    landing_weight_kg: range(asked.landing_weight_kg, 0.08, 'landing_weight_kg'),
    touchdown_ground_speed_ms: range(asked.touchdown_ground_speed_ms, 0.06, 'touchdown_ground_speed_ms'),
    crosswind_kt: range(asked.crosswind_kt, 0.5, 'crosswind_kt'),
    touchdown_sink_rate_ms: range(asked.touchdown_sink_rate_ms, 0.4, 'touchdown_sink_rate_ms'),
    touchdown_yaw_angle_deg: range(asked.touchdown_yaw_angle_deg, 0.6, 'touchdown_yaw_angle_deg'),
    taxi_distance_km: range(asked.taxi_distance_km, 0.25, 'taxi_distance_km'),
    average_taxi_speed_kt: range(asked.average_taxi_speed_kt, 0.25, 'average_taxi_speed_kt'),
    outside_air_temperature_c: range(asked.outside_air_temperature_c, 0.2, 'outside_air_temperature_c'),
    brake_temperature_c: range(asked.brake_temperature_c, 0.3, 'brake_temperature_c'),
    heavy_braking_probability: Math.min(1, Math.max(0, l.brakeShare)),
    runway_condition: RUNWAY[l.surface],
  }

  const UNITS: Record<EnvelopeKey, string> = {
    landing_weight_kg: 'kg',
    touchdown_ground_speed_ms: 'm/s',
    crosswind_kt: 'kt',
    touchdown_sink_rate_ms: 'm/s',
    touchdown_yaw_angle_deg: '°',
    taxi_distance_km: 'km',
    average_taxi_speed_kt: 'kt',
    outside_air_temperature_c: '°C',
    brake_temperature_c: '°C',
  }
  const LABELS: Record<EnvelopeKey, string> = {
    landing_weight_kg: 'Landing weight',
    touchdown_ground_speed_ms: 'Touchdown speed',
    crosswind_kt: 'Crosswind',
    touchdown_sink_rate_ms: 'Sink rate',
    touchdown_yaw_angle_deg: 'Yaw angle',
    taxi_distance_km: 'Taxi distance',
    average_taxi_speed_kt: 'Taxi speed',
    outside_air_temperature_c: 'OAT',
    brake_temperature_c: 'Brake temp',
  }

  // A clamp is reported on the most-likely value: that is the number the user actually dialled in.
  const clamps: Clamp[] = (Object.keys(ENVELOPE) as EnvelopeKey[])
    .map((key) => ({ key, label: LABELS[key], asked: asked[key], sent: future[key].most_likely, unit: UNITS[key] }))
    .filter((c) => Math.abs(c.asked - c.sent) > 1e-6)

  // Tread depth: the shallowest groove governs. A defect-free tyre reports no defects — see
  // knownDefects(). Do not coerce current measurements into the release domain here: the backend's
  // fail-closed gate must withhold unsupported condition data rather than receive altered telemetry.
  const treadMm = Math.min(...tire.grooves)

  return {
    clamps,
    request: {
      intended_use: 'SCENARIO_PLANNING',
      profile_id: tire.gear === 'nose' ? 'pilot-nose-v1' : 'pilot-main-v1',
      current_condition: {
        cycles_since_install: tire.cycles,
        current_tread_depth_mm: treadMm,
        measured_cold_pressure_psi: tire.psi,
        reference_cold_pressure_psi: tire.psiTarget,
        tire_temperature_c: tire.oatC,
        retread_count: tire.retreads,
        known_defects: knownDefects(tire),
      },
      horizon_cycles: opts.horizonCycles ?? 50,
      simulation_runs: opts.simulationRuns ?? 1000,
      random_seed: opts.randomSeed ?? 42,
      future_conditions: future,
    },
  }
}

// ── The call ────────────────────────────────────────────────────────────────────────────────────

/** A withhold or an out-of-domain input is an *answer*, not a crash. The code is what the UI renders. */
// ponytail: plain fields, not parameter properties — the *.check.ts files run under
// `node --experimental-strip-types`, which cannot compile those away.
export class AssessmentError extends Error {
  code: string
  status: number
  constructor(code: string, message: string, status: number) {
    super(message)
    this.name = 'AssessmentError'
    this.code = code
    this.status = status
  }
}

/** True when the model declined to answer — a designed outcome, not a transport or routing fault. */
export const isWithheld = (e: unknown): e is AssessmentError =>
  e instanceof AssessmentError &&
  (e.status === 409 || (e.status === 422 && e.code === 'MODEL_INPUT_OUTSIDE_RELEASE_DOMAIN'))

export async function assessTire(request: AssessmentRequest): Promise<AssessmentResponse> {
  let res: Response
  try {
    res = await fetch(`${API_BASE}/api/v1/tire-assessments`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(request),
    })
  } catch {
    throw new AssessmentError('NETWORK', 'Cannot reach the tire-assessment service.', 0)
  }
  if (!res.ok) {
    const body = await res.json().catch(() => null)
    throw new AssessmentError(
      body?.error?.code ?? 'UNKNOWN',
      body?.error?.message ?? `Assessment failed (${res.status})`,
      res.status,
    )
  }
  return res.json()
}

export const useAssessment = () =>
  useMutation({
    mutationFn: assessTire,
    // A withheld assessment will be withheld again. Retrying only delays showing the user the answer.
    retry: false,
  })
