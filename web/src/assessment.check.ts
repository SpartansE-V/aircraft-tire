// Self-check for the API mapper: node --experimental-strip-types src/assessment.check.ts
//
// The unit conversions are the whole risk here. kt→m/s, fpm→m/s, t→kg all produce plausible-looking
// numbers when they are wrong, and a wrong one is a silently bad forecast rather than a crash.
import assert from 'node:assert/strict'
import { ENVELOPE, toAssessmentRequest, type EnvelopeKey } from './assessment.ts'
import { FLEET_TIRES, knownDefects } from './data.ts'
import type { Attitude } from './landingEngine.ts'
import type { Landing } from './sim.ts'

const LEVEL: Attitude = { pitchDeg: 4, rollDeg: 0, crabDeg: 0, liftShare: 0.9 }

// KLAX-ish, and the app's actual defaults: a 777 at 200 t. Wind 290° onto runway 250° — off the nose
// and from the right, so the crosswind component is positive.
const NOMINAL: Landing = {
  weightT: 200, sinkFpm: 240, gsKt: 138, brakeShare: 0.55, oatC: 24,
  windKt: 14, windDirDeg: 290, runwayHeadingDeg: 250, antiskid: true,
  surface: 'dry', elevFt: 126, runwayM: 3685,
}

const TIRE = FLEET_TIRES.find((t) => t.gear !== 'nose')!
const { request: req, clamps } = toAssessmentRequest(TIRE, NOMINAL, LEVEL)
const f = req.future_conditions
const near = (a: number, b: number, tol: number, what: string) =>
  assert.ok(Math.abs(a - b) < tol, `${what}: expected ~${b}, got ${a}`)

// ── Unit conversions ────────────────────────────────────────────────────────────────────────────
// 138 kt is 71 m/s. If this ever reads 138 or 255, a conversion was dropped or doubled.
near(f.touchdown_ground_speed_ms.most_likely, 71.0, 0.5, 'kt → m/s')
// 240 fpm is 1.22 m/s. Reading 4.0 means we sent feet per *second*; 240 means we sent it raw.
near(f.touchdown_sink_rate_ms.most_likely, 1.22, 0.02, 'fpm → m/s')
// 200 t is 200 000 kg — which the envelope caps at 73 500. Both halves matter: the ×1000 happened,
// and the clamp caught it.
assert.equal(f.landing_weight_kg.most_likely, 73_500, 't → kg then clamped to envelope ceiling')

// ── The clamp is reported, in the units the user reads ──────────────────────────────────────────
// This is the honesty guarantee: a clamped input the UI never hears about is a laundered number.
const weight = clamps.find((c) => c.key === 'landing_weight_kg')
assert.ok(weight, '200 t against a 73.5 t ceiling must be reported as clamped')
assert.equal(weight.sent, 73_500)
near(weight.asked, 200_000, 1, 'clamp reports what was asked for, not the clamped value')
// Nothing inside the envelope may be reported as clamped, or the UI cries wolf on every forecast.
assert.ok(
  !clamps.some((c) => c.key === 'touchdown_ground_speed_ms'),
  '71 m/s is inside 58–82 and must not be flagged',
)

// ── Crosswind is a magnitude, not a signed component ────────────────────────────────────────────
// The app's crosswind is signed (from the left is negative). The model's is 0–25. Send the sign and
// every left-hand crosswind becomes a 422.
const fromLeft = toAssessmentRequest(TIRE, { ...NOMINAL, windDirDeg: 210 }, LEVEL).request
assert.ok(fromLeft.future_conditions.crosswind_kt.most_likely > 0, 'a crosswind from the left must not go negative')

// ── The invariant that actually prevents 422s ───────────────────────────────────────────────────
// Every tyre, every surface, every plausible landing: no bound may ever leave the envelope, and the
// distribution must stay ordered. If this holds, a well-formed request cannot be rejected on domain.
const SURFACES: Landing['surface'][] = ['dry', 'wet', 'contaminated']
const EXTREMES: Partial<Landing>[] = [
  {},
  { weightT: 45, sinkFpm: 20, gsKt: 60, brakeShare: 0, oatC: -40, windKt: 0 }, // absurdly light, freezing
  { weightT: 400, sinkFpm: 900, gsKt: 200, brakeShare: 1, oatC: 55, windKt: 60 }, // absurdly heavy, hot, hard
]

for (const tire of FLEET_TIRES) {
  for (const surface of SURFACES) {
    for (const extreme of EXTREMES) {
      for (const crabDeg of [-30, 0, 30]) {
        const l: Landing = { ...NOMINAL, ...extreme, surface }
        const { request } = toAssessmentRequest(tire, l, { ...LEVEL, crabDeg })
        const where = `${tire.id}/${surface}/crab${crabDeg}`

        for (const key of Object.keys(ENVELOPE) as EnvelopeKey[]) {
          const { minimum, most_likely, maximum } = request.future_conditions[key]
          const [lo, hi] = ENVELOPE[key]
          assert.ok(minimum <= most_likely && most_likely <= maximum, `${where}: ${key} range out of order`)
          for (const [name, v] of [['minimum', minimum], ['most_likely', most_likely], ['maximum', maximum]] as const) {
            assert.ok(v >= lo && v <= hi, `${where}: ${key}.${name} = ${v} outside envelope ${lo}–${hi}`)
          }
        }

        const cc = request.current_condition
        assert.ok(cc.measured_cold_pressure_psi <= cc.reference_cold_pressure_psi, `${where}: over-inflation must be capped at reference`)
        const deficit = 1 - cc.measured_cold_pressure_psi / cc.reference_cold_pressure_psi
        assert.ok(deficit >= 0 && deficit < 0.1, `${where}: pressure deficit ${deficit} must be inside 0–10%`)
        assert.ok(cc.current_tread_depth_mm <= 10.9, `${where}: tread above the profile's initial depth`)
        const p = request.future_conditions.heavy_braking_probability
        assert.ok(p >= 0 && p <= 1, `${where}: heavy_braking_probability out of 0–1`)
        assert.deepEqual(cc.known_defects, knownDefects(tire), `${where}: defects must reach the model unchanged`)
      }
    }
  }
}

// The nose tyre is a different profile, and getting this wrong forecasts the wrong tyre entirely.
const nose = FLEET_TIRES.find((t) => t.gear === 'nose')!
assert.equal(toAssessmentRequest(nose, NOMINAL, LEVEL).request.profile_id, 'pilot-nose-v1')
assert.equal(toAssessmentRequest(TIRE, NOMINAL, LEVEL).request.profile_id, 'pilot-main-v1')

console.log(`ok — mapper holds the envelope across ${FLEET_TIRES.length} tyres × ${SURFACES.length} surfaces × ${EXTREMES.length} landings; ${clamps.length} inputs clamped on the nominal 777 scenario`)
