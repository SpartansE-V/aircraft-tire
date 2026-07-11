// Self-check for the landing model: node --experimental-strip-types src/sim.check.ts
import assert from 'node:assert/strict'
import { CAL, G, OLEO, oleoResponse, rolloutDecelMps2, simulate, trueGroundSpeedMps, wheelLoads, type Landing } from './sim.ts'

const TIRE = { grooves: [6.2, 6.0, 5.8, 6.1], grooveLimit: 2.4, psi: 200, psiTarget: 200 }
// Sea level, long dry runway — KLAX, roughly. The benign case everything else is measured against.
const NOMINAL: Landing = {
  weightT: 200, sinkFpm: 240, gsKt: 138, brakeShare: 0.55, oatC: 24, crosswindKt: 12,
  surface: 'dry', elevFt: 126, runwayM: 3685,
}

const base = simulate(NOMINAL, TIRE)

// A normal landing is unremarkable: under the g flag, under the fuse plug, tread left.
assert.equal(base.status, 'ok', 'nominal landing should not flag')
assert.ok(base.peakG > 1 && base.peakG < CAL.gLimit, `peak g out of range: ${base.peakG}`)
assert.ok(base.beadPeakC < CAL.fusePlugC, `bead too hot on a normal landing: ${base.beadPeakC}`)
assert.ok(base.cyclesToLimit > 50, `nominal wear should leave cycles: ${base.cyclesToLimit}`)

// MAGNITUDES, not just directions. Every assertion in this file used to be a `A > B`, which is how a
// 62 t "777" survived here for so long: it was wrong by 3x and still monotonic in everything.
// These pin the numbers to the real aircraft, so the weight cannot quietly become a narrowbody again.
assert.ok(NOMINAL.weightT >= 168, `a 777-300ER cannot land below its 168 t empty weight: ${NOMINAL.weightT} t`)
// A 52x21.0R22 main tire is rated to roughly 265 kN. A normal landing should use a real fraction of
// that — not 20 % of it (the old number), and not more than the rating.
assert.ok(base.loadPerTireKN > 120 && base.loadPerTireKN < 265, `load per tire is implausible: ${base.loadPerTireKN.toFixed(0)} kN`)
// A normal 777 landing puts 15–25 MJ into each brake. The old model said 8.
assert.ok(base.brakeEnergyMJ > 12 && base.brakeEnergyMJ < 30, `brake energy per wheel is implausible: ${base.brakeEnergyMJ.toFixed(1)} MJ`)
// Carbon brakes run hot — a few hundred °C is normal — while the bead stays cool.
assert.ok(base.brakePeakC > 150 && base.brakePeakC < 600, `brake pack temp is implausible: ${base.brakePeakC.toFixed(0)} °C`)
assert.ok(base.beadPeakC < 120, `bead should stay cool on a normal landing: ${base.beadPeakC.toFixed(0)} °C`)

// --- THE HEAT SOAK, and its timing, which is the whole point. The pack takes the energy during the
// stop and is then cooled hard by its own slipstream. The bead is heated only *through the wheel*, and
// that is slow — so it goes on climbing long after the pack has started falling, and it peaks well
// after the aircraft has parked. Fuse plugs let go on the taxiway and at the gate, never on the runway.
// The old model said the bead was hottest at the moment the wheels stopped, which is exactly backwards
// and inverts the turnaround call this app exists to support.
const stopS = CAL.rolloutDelayS + trueGroundSpeedMps(NOMINAL) / rolloutDecelMps2(NOMINAL)
assert.ok(base.beadPeakAtS > stopS + 300, `the bead must peak minutes AFTER the aircraft stops, not on the runway: peak at t+${(base.beadPeakAtS / 60).toFixed(0)} min, stopped at t+${(stopS / 60).toFixed(1)} min`)
assert.ok(base.beadPeakAtS > 600 && base.beadPeakAtS < 1800, `real bead peaks land 10-30 min after landing: ${(base.beadPeakAtS / 60).toFixed(0)} min`)
// The pack, meanwhile, peaks essentially immediately — the energy arrives during the stop.
const packPeakAtS = base.thermal.samples.reduce((a, s) => (s.packC > a.packC ? s : a)).tS
assert.ok(packPeakAtS < 120, `the brake pack peaks during the stop, not later: ${packPeakAtS} s`)
assert.ok(base.thermal.samples.at(-1)!.beadC < base.beadPeakC, 'the bead has to come back down again inside the window')

// And the fuse plug has to be reachable — otherwise the flag is decoration. Denver, max weight, max
// braking, thin air: 88 MJ a brake, and the bead goes through 180 °C half an hour after it parked.
const maxEnergy = simulate({ ...NOMINAL, elevFt: 5434, gsKt: 170, brakeShare: 1, weightT: 251, oatC: 35 }, TIRE)
assert.ok(maxEnergy.beadPeakC > CAL.fusePlugC, `a max-energy stop must be able to release a fuse plug: ${maxEnergy.beadPeakC.toFixed(0)} °C`)
assert.ok(maxEnergy.flags.some((f) => /fuse plug/i.test(f)), 'and it must say so')

// --- THE STRUT. Gas spring + orifice damper + the tyre under it, integrated, rather than `1+v²/(2gs)`.
const arrival = (fpm: number, lift = CAL.liftAtTouchdown) => oleoResponse({ massKg: 200_000, vSinkMps: fpm / 196.85, liftShare: lift, spoilerS: CAL.spoilerDumpS, durationS: 8 })
// A normal arrival reads about 1.1 G on the gear, which is what a FOQA trace shows, and the hard
// landing flag has to be reachable without being trigger-happy.
assert.ok(arrival(240).peakG > 1.05 && arrival(240).peakG < 1.25, `a normal arrival should read ~1.1 G: ${arrival(240).peakG.toFixed(2)}`)
assert.ok(arrival(240).peakG < CAL.gLimit, 'a normal arrival must not trip the hard-landing flag')
assert.ok(arrival(700).peakG > CAL.gLimit, `a 700 fpm slam must trip it: ${arrival(700).peakG.toFixed(2)} G`)
assert.ok(arrival(720).peakG > arrival(600).peakG && arrival(600).peakG > arrival(240).peakG, 'harder arrivals must load the gear harder')

// It has to actually settle. Pure ẋ|ẋ| damping vanishes as ẋ → 0, so without the linear term the strut
// rings almost undamped around its static point forever — it sat 7 % above the aircraft's own weight
// eight seconds after landing, and reported its "peak" at t = 2.5 s, which was the spoilers dumping
// lift rather than the touchdown. An aeroplane parked on its gear weighs exactly what it weighs.
const settled = arrival(240).samples.at(-1)!
assert.ok(Math.abs(settled.loadKN / (200_000 * G / 1000) - 1) < 0.02, `the strut must settle onto the aircraft's own weight: ${settled.loadKN.toFixed(0)} kN vs ${((200_000 * G) / 1000).toFixed(0)} kN`)

// The load has to come up through the rubber. The tyre is a spring in series below the strut, so the
// gear cannot be at full load the instant it touches — the first frame of a landing is nearly unloaded,
// and the peak lands ~0.1 s later. Without the tyre in the model the damper handed the aeroplane 3.5 MN
// at t = 0 with 3 mm of stroke, and peak G jumped discontinuously with sink rate.
const hard = arrival(600)
assert.ok(hard.samples[0].loadKN < 0.1 * (200_000 * G) / 1000, `the gear must be nearly unloaded at first contact: ${hard.samples[0].loadKN.toFixed(0)} kN`)
const peakAt = hard.samples.reduce((a, s) => (s.loadKN > a.loadKN ? s : a)).tS
assert.ok(peakAt > 0.03 && peakAt < 0.3, `the arrival should peak a beat after contact, not on it: ${peakAt.toFixed(3)} s`)

// RECOIL, and what it produces. A normal arrival must keep its tyres on the ground...
for (const fpm of [240, 360, 480]) {
  for (const lift of [0.7, 0.9, 1]) {
    assert.equal(arrival(fpm, lift).bounces, 0, `a normal arrival must not skip: ${fpm} fpm at ${lift} lift left the runway`)
  }
}
// ...but a hard one recoils enough to unload the gear completely and lift the tyres clear, and they
// come back down and hit again. Unreachable before the strut was integrated, and it is the second
// impact that costs tread. Note the SIZE: this is centimetres. It is wheel hop, and the model must not
// be read as producing a ballooned bounce — that is an aerodynamic event, and this page has no flight
// dynamics by design. If this ever starts reporting metres, something has broken, not improved.
assert.ok(arrival(600).bounces > 0, 'a hard arrival should lift the tyres off the runway')
assert.ok(arrival(700).bounces > 0, 'a slam certainly should')
assert.ok(arrival(700).maxBounceM < 0.3, `this is wheel hop, not a balloon: ${(arrival(700).maxBounceM * 100).toFixed(1)} cm`)
assert.ok(arrival(700).maxBounceM > arrival(600).maxBounceM, 'a harder slam should skip higher')

// And this is the recoil itself: the strut does not merely absorb and stay put. It compresses hard,
// and then the gas spring pushes a third of that stroke straight back out before it settles. Energy
// went in, energy came back — which is exactly what `1 + v²/(2gs)` could never say, because nothing in
// it stored anything. It is also what makes the aircraft in the 3D scene visibly rebound.
const stroke = hard.samples.map((s) => s.strokeM)
const maxStroke = Math.max(...stroke)
const reboundTo = Math.min(...stroke.slice(stroke.indexOf(maxStroke)))
assert.ok(reboundTo < maxStroke * 0.75, `the gas spring must push the stroke back out: peaked at ${maxStroke.toFixed(3)} m, recoiled only to ${reboundTo.toFixed(3)} m`)

// An honest note on what this does NOT show. Opening the rebound orifice right up — even to a tenth of
// the compression damping, which no gear on earth is built like — does not make a normal landing pogo.
// The asymmetry is real engineering and it is in the model, but what actually decides whether THIS
// aircraft bounces is lift against sink rate, not the recoil orifice. Asserting otherwise would be
// asserting a story rather than the model, so the assertion that used to live here has been deleted.

// Monotonic in the things that should drive it.
assert.ok(simulate({ ...NOMINAL, sinkFpm: 640 }, TIRE).peakG > base.peakG, 'harder sink → higher g')
assert.ok(simulate({ ...NOMINAL, gsKt: 165 }, TIRE).scrubMm > base.scrubMm, 'faster touchdown → more scrub')
assert.ok(simulate({ ...NOMINAL, weightT: 240 }, TIRE).brakeEnergyMJ > base.brakeEnergyMJ, 'heavier → more brake energy')
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
