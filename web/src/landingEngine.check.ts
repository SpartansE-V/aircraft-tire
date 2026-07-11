import assert from 'node:assert/strict'
import { FLEET_TIRES } from './data.ts'
import { simulate } from './sim.ts'
import { simulateLandingRun, type Attitude } from './landingEngine.ts'

const track = {
  icao: 'KLAX',
  rwy: '25L',
  surface: 'dry',
  oatC: 21,
  env: 'coastal',
  note: 'check fixture',
  name: 'Los Angeles',
  city: 'Los Angeles',
  lengthM: 3382,
  elevFt: 125,
  headingDeg: 263,
  rwycc: 6,
} as const
const landing = {
  weightT: 62,
  sinkFpm: 240,
  gsKt: 138,
  brakeShare: 0.55,
  oatC: track.oatC,
  crosswindKt: 12,
  surface: track.surface,
  elevFt: track.elevFt,
  runwayM: track.lengthM,
}
const attitude: Attitude = { pitchDeg: 4, rollDeg: 0, crabDeg: 0 }
const selectedTireId = 'L1'
const tire = FLEET_TIRES.find((t) => t.id === selectedTireId)!
const scalar = simulate(landing, tire)
const run = simulateLandingRun({ landing, attitude, track, tires: FLEET_TIRES, selectedTireId })
const repeat = simulateLandingRun({ landing, attitude, track, tires: FLEET_TIRES, selectedTireId })

assert.ok(run.frames.length > 10, 'engine should expose a fixed-step timeline')
assert.equal(run.frames.at(-1)?.phase, 'stopped')
assert.equal(run.summary.status, scalar.status)
assert.ok(Math.abs(run.summary.stopDistM - scalar.stopDistM) < 1e-9, 'engine summary should preserve scalar stop distance')
assert.deepEqual(
  repeat.frames.map((f) => [f.tS, f.phase, Math.round(f.pose.xM), Math.round(f.speedMps)]),
  run.frames.map((f) => [f.tS, f.phase, Math.round(f.pose.xM), Math.round(f.speedMps)]),
  'same scenario should produce deterministic frames',
)

for (let i = 1; i < run.frames.length; i++) {
  assert.ok(run.frames[i].pose.xM >= run.frames[i - 1].pose.xM, 'runway distance must be monotonic')
  assert.ok(run.frames[i].speedMps >= 0, 'speed must never go negative')
}
assert.ok(Math.abs(run.frames.at(-1)!.pose.xM - run.summary.stopDistM) < 0.5, 'final frame should land on summary stop distance')

const levelNoWind = simulateLandingRun({ landing: { ...landing, crosswindKt: 0 }, attitude, track, tires: FLEET_TIRES, selectedTireId })
assert.ok(Math.abs(levelNoWind.summary.perWheel.L1.peakLoadKN - levelNoWind.summary.perWheel.R1.peakLoadKN) < 1e-9, 'wings-level/no-wind loads should be side-symmetric')

const banked = simulateLandingRun({ landing: { ...landing, crosswindKt: 0 }, attitude: { ...attitude, rollDeg: 8 }, track, tires: FLEET_TIRES, selectedTireId: 'R1' })
assert.ok(banked.summary.perWheel.R1.peakLoadKN > banked.summary.perWheel.L1.peakLoadKN, 'positive bank should load the right gear')
assert.ok(banked.summary.touchdownOrder.every((id) => id.startsWith('R')), 'positive bank should touch right mains first')

const crabbed = simulateLandingRun({ landing: { ...landing, crosswindKt: 0 }, attitude: { ...attitude, crabDeg: 12 }, track, tires: FLEET_TIRES, selectedTireId })
assert.ok(crabbed.summary.perWheel.L1.scrubMm > levelNoWind.summary.perWheel.L1.scrubMm, 'crab should add lateral scrub')

const lightBraking = simulateLandingRun({ landing: { ...landing, brakeShare: 0.25 }, attitude, track, tires: FLEET_TIRES, selectedTireId })
assert.ok(lightBraking.summary.stopDistM > run.summary.stopDistM, 'engine stop distance should follow brake share')
assert.ok(lightBraking.frames.length > run.frames.length, 'timeline should show longer slowing-down with less braking')

const overrun = simulateLandingRun({ landing: { ...landing, gsKt: 175, surface: 'contaminated', runwayM: 800 }, attitude, track, tires: FLEET_TIRES, selectedTireId })
assert.equal(overrun.frames.at(-1)?.phase, 'overrun', 'short contaminated runway should end as overrun')

console.log('landing engine ok ·', {
  frames: run.frames.length,
  phase: run.frames.at(-1)?.phase,
  stopM: Math.round(run.summary.stopDistM),
  selectedLoadKN: Math.round(run.summary.perWheel.L1.peakLoadKN),
})
