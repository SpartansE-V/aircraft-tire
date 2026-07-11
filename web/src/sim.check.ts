// Self-check for the landing model: node --experimental-strip-types src/sim.check.ts
import assert from 'node:assert/strict'
import { CAL, simulate, wheelLoads, type Landing } from './sim.ts'

const TIRE = { grooves: [6.2, 6.0, 5.8, 6.1], grooveLimit: 2.4, psi: 200, psiTarget: 200 }
// Sea level, long dry runway — KLAX, roughly. The benign case everything else is measured against.
const NOMINAL: Landing = {
  weightT: 62, sinkFpm: 240, gsKt: 138, brakeShare: 0.55, oatC: 24, crosswindKt: 12,
  surface: 'dry', elevFt: 126, runwayM: 3685,
}

const base = simulate(NOMINAL, TIRE)

// A normal landing is unremarkable: under the g flag, under the fuse plug, tread left.
assert.equal(base.status, 'ok', 'nominal landing should not flag')
assert.ok(base.peakG > 1 && base.peakG < CAL.gLimit, `peak g out of range: ${base.peakG}`)
assert.ok(base.beadPeakC < CAL.fusePlugC, `bead too hot on a normal landing: ${base.beadPeakC}`)
assert.ok(base.cyclesToLimit > 50, `nominal wear should leave cycles: ${base.cyclesToLimit}`)

// Monotonic in the things that should drive it.
assert.ok(simulate({ ...NOMINAL, sinkFpm: 640 }, TIRE).peakG > base.peakG, 'harder sink → higher g')
assert.ok(simulate({ ...NOMINAL, gsKt: 165 }, TIRE).scrubMm > base.scrubMm, 'faster touchdown → more scrub')
assert.ok(simulate({ ...NOMINAL, weightT: 78 }, TIRE).brakeEnergyMJ > base.brakeEnergyMJ, 'heavier → more brake energy')
assert.ok(simulate({ ...NOMINAL, surface: 'contaminated' }, TIRE).stopDistM > base.stopDistM, 'lower µ → longer stop')
assert.ok(simulate({ ...NOMINAL, brakeShare: 0.25 }, TIRE).stopDistM > base.stopDistM, 'less wheel braking → longer stop')
assert.ok(simulate({ ...NOMINAL, crosswindKt: 35 }, TIRE).stopDistM > base.stopDistM, 'strong crosswind → less braking efficiency')

// A slammed-on hard landing has to trip the FOQA flag.
assert.equal(simulate({ ...NOMINAL, sinkFpm: 700 }, TIRE).status, 'action', 'hard landing should be actionable')

// Under-inflation scrubs more rubber than a correctly inflated tire.
assert.ok(simulate(NOMINAL, { ...TIRE, psi: 170 }).scrubMm > base.scrubMm, 'under-inflated → more scrub')

// Runway length is not decoration: a long runway is fine, a short one is an overrun, and the flag
// has to be the thing that says so.
assert.ok(base.stopMarginM > 0, 'a long dry runway should not be an overrun')
// A 777 does not stop in 700 m. If the rollout delay ever goes missing, this is what catches it.
assert.ok(base.stopDistM > 900 && base.stopDistM < 1600, `dry stop distance is implausible: ${base.stopDistM}`)

// The overrun case is the one worth being able to reach: fast, contaminated, a mile up, and the
// shortest runway in the set (Tan Son Nhat). Every one of those is needed — this is the point.
const worst = simulate({ ...NOMINAL, gsKt: 175, surface: 'contaminated', elevFt: 5434, runwayM: 3048 }, TIRE)
assert.ok(worst.stopMarginM < 0, 'fast + contaminated + high should not fit on 3048 m')
assert.equal(worst.status, 'action', 'an overrun must be actionable')
assert.ok(worst.flags.some((f) => /overrun/i.test(f)), 'an overrun must say so')
// Same aircraft, same runway, only µ changes — a contaminated runway is what turns it into an overrun.
assert.ok(simulate({ ...NOMINAL, surface: 'contaminated' }, TIRE).stopMarginM < base.stopMarginM, 'lower µ eats the margin')

// Field elevation: thinner air, faster touchdown for the same indicated speed, and energy goes with
// the square. Denver has to cost more than sea level on every energy term.
const denver = simulate({ ...NOMINAL, elevFt: 5434 }, TIRE)
assert.ok(denver.gsTrueKt > base.gsTrueKt, 'thin air -> faster over the ground')
assert.ok(denver.brakeEnergyMJ > base.brakeEnergyMJ, 'a mile up costs brake energy')
assert.ok(denver.stopDistM > base.stopDistM, 'a mile up costs runway')
assert.ok(denver.scrubMm > base.scrubMm, 'a mile up costs rubber')

// Crosswind moves load onto the downwind wheels but conserves the total.
const w = wheelLoads(base, 20)
assert.ok(w.downwind > w.upwind, 'crosswind loads the downwind gear')
assert.ok(Math.abs((w.downwind + w.upwind) / 2 - base.loadPerTireKN) < 1e-9, 'wheel loads must average to the mean')

console.log('sim ok ·', {
  peakG: base.peakG.toFixed(2),
  loadKN: Math.round(base.loadPerTireKN),
  scrubMm: base.scrubMm.toFixed(3),
  brakeMJ: base.brakeEnergyMJ.toFixed(1),
  beadC: Math.round(base.beadPeakC),
  stopM: Math.round(base.stopDistM),
  cyclesLeft: base.cyclesToLimit,
})
