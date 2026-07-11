// Landing-event model. Pure functions, no React — so the numbers can be checked without a browser
// (`npm run check:sim`) and later swapped for the real FOQA-fitted model behind the same shape.

export type Surface = 'dry' | 'wet' | 'contaminated'

export type Landing = {
  weightT: number // landing weight
  sinkFpm: number // vertical speed at touchdown
  gsKt: number // indicated approach speed — true speed over the ground rises with field elevation
  brakeShare: number // 0..1 — fraction of kinetic energy taken by brakes (rest: reverse thrust + drag)
  oatC: number
  crosswindKt: number
  surface: Surface
  elevFt: number // field elevation — thin air means a faster touchdown for the same indicated speed
  runwayM: number // landing distance available; what the stop has to fit inside
}

// ponytail: these are the calibration knobs — first-order physics with fitted coefficients, not a
// gear model. Refit each against FOQA once real landings are joined to serials; the shapes hold.
export const CAL = {
  mainGearShare: 0.95, // fraction of weight on the mains at touchdown
  mainWheels: 12, // 777-300ER: two six-wheel bogies
  strokeM: 0.45, // effective oleo stroke absorbing the sink — sets peak G
  scrubK: 0.035, // mm of tread per landing at reference load + reference speed
  refGsKt: 140,
  brakeHeatSinkJK: 45_000, // steel heat pack: ~90 kg × 500 J/kg·K
  beadSoak: 0.35, // fraction of brake ΔT that reaches the bead through the wheel
  fusePlugC: 180, // fusible plug releases here — tire deflates rather than bursts
  gLimit: 1.8, // FOQA hard-landing flag
  tasPctPer1000ft: 2, // thin air: true (and ground) speed climbs ~2 % per 1000 ft for the same IAS
  marginM: 300, // stop margin below this is uncomfortably tight, even though it isn't an overrun
  // Nothing decelerates at touchdown: the nose has to come down, spoilers deploy, reversers unstow,
  // brakes take hold. At 70 m/s those seconds are most of a kilometre, and leaving them out made a
  // 777 stop in 640 m — which would have made every runway in the list look roomy.
  rolloutDelayS: 5,
  brakeDecelBase: 0.72, // baseline wheel braking effectiveness before brake-share input
  brakeDecelGain: 0.5, // higher brake share means harder wheel braking and a shorter rollout
  crosswindDecelLossMax: 0.12, // directional-control margin: strong crosswind costs braking efficiency
  mu: { dry: 0.4, wet: 0.25, contaminated: 0.15 } as Record<Surface, number>,
  scrubSurface: { dry: 1, wet: 1.25, contaminated: 1.6 } as Record<Surface, number>, // slip → more scrub
}

const G = 9.81
const MS_PER_FPM = 1 / 196.85
const MS_PER_KT = 0.5144

export type SimResult = ReturnType<typeof simulate>

export function simulate(l: Landing, tire: { grooves: number[]; grooveLimit: number; psi: number; psiTarget: number }) {
  const vSink = l.sinkFpm * MS_PER_FPM
  // Field elevation is not decoration: the same indicated speed is a faster touchdown up high, and
  // every energy term below goes with its square. This is the whole reason Denver is in the list.
  const vGround = trueGroundSpeedMps(l)
  const gsTrueKt = vGround / MS_PER_KT
  const massKg = l.weightT * 1000

  // Peak vertical g: the oleo turns the sink energy into deceleration over its stroke.
  const peakG = 1 + vSink ** 2 / (2 * G * CAL.strokeM)
  const loadPerTireKN = (massKg * G * peakG * CAL.mainGearShare) / CAL.mainWheels / 1000

  // Spin-up scrub: the tire goes 0 → groundspeed against the runway. Loss scales with load and v².
  const refLoadKN = (massKg * G * CAL.mainGearShare) / CAL.mainWheels / 1000
  const scrubMm =
    CAL.scrubK *
    (loadPerTireKN / refLoadKN) *
    (gsTrueKt / CAL.refGsKt) ** 2 *
    CAL.scrubSurface[l.surface] *
    tirePressureScrubFactor(tire)

  // Braking: total kinetic energy is fixed by mass and speed; the surface only sets how far it takes.
  const keMJ = (0.5 * massKg * vGround ** 2) / 1e6
  const brakeEnergyMJ = (keMJ * l.brakeShare) / CAL.mainWheels
  const brakeRiseC = (brakeEnergyMJ * 1e6) / CAL.brakeHeatSinkJK
  const brakePeakC = l.oatC + brakeRiseC
  const beadPeakC = l.oatC + brakeRiseC * CAL.beadSoak
  // Roll at speed while the aircraft gets configured, then decelerate at whatever µ the surface gives.
  const stopDistM = vGround * CAL.rolloutDelayS + vGround ** 2 / (2 * rolloutDecelMps2(l))
  // What the runway has left over. Negative is an overrun, and no tire number matters after that.
  const stopMarginM = l.runwayM - stopDistM

  // Tread budget after this landing.
  const minGroove = Math.min(...tire.grooves)
  const grooveAfter = minGroove - scrubMm
  const cyclesToLimit = Math.max(0, Math.floor((minGroove - tire.grooveLimit) / scrubMm))

  const overrun = stopMarginM < 0
  const flags = [
    overrun && `Overrun — the stop needs ${Math.round(stopDistM)} m and the runway is ${l.runwayM} m`,
    !overrun && stopMarginM < CAL.marginM && `Tight — only ${Math.round(stopMarginM)} m of runway left after the stop`,
    peakG > CAL.gLimit && `Hard landing — ${peakG.toFixed(2)} G exceeds the ${CAL.gLimit} G FOQA flag`,
    beadPeakC > CAL.fusePlugC && `Bead at ${Math.round(beadPeakC)} °C — fuse plug releases above ${CAL.fusePlugC} °C`,
    grooveAfter < tire.grooveLimit && `Groove ${grooveAfter.toFixed(2)} mm lands under the ${tire.grooveLimit} mm limit`,
    Math.abs(tire.psi - tire.psiTarget) / tire.psiTarget > 0.05 && `Tire is ${Math.round(((tire.psi - tire.psiTarget) / tire.psiTarget) * 100)} % off target psi before the event`,
  ].filter((f): f is string => typeof f === 'string')

  const severe = overrun || peakG > CAL.gLimit || beadPeakC > CAL.fusePlugC || grooveAfter < tire.grooveLimit
  const status = flags.length === 0 ? 'ok' : severe ? 'action' : 'watch'

  return { peakG, loadPerTireKN, scrubMm, keMJ, brakeEnergyMJ, brakePeakC, beadPeakC, stopDistM, stopMarginM, gsTrueKt, grooveAfter, cyclesToLimit, flags, status } as const
}

// Under-inflation flexes the sidewall and drags the shoulder — more scrub, hotter carcass.
export function tirePressureScrubFactor(tire: { psi: number; psiTarget: number }) {
  return 1 + Math.max(0, (tire.psiTarget - tire.psi) / tire.psiTarget) * 2
}

export function trueGroundSpeedMps(l: Landing) {
  return l.gsKt * (1 + (CAL.tasPctPer1000ft / 100) * (l.elevFt / 1000)) * MS_PER_KT
}

export function rolloutDecelMps2(l: Landing) {
  const brakeShare = Math.min(1, Math.max(0, l.brakeShare))
  const brakeFactor = CAL.brakeDecelBase + CAL.brakeDecelGain * brakeShare
  const crosswindLoss = Math.min(CAL.crosswindDecelLossMax, l.crosswindKt / 300)
  return Math.max(0.1, CAL.mu[l.surface] * G * brakeFactor * (1 - crosswindLoss))
}

/** Brake-pack temperature over the rollout: rises through the stop, then soaks/cools on the taxi. */
export function brakeCurve(r: SimResult, oatC: number, n = 14) {
  return Array.from({ length: n }, (_, i) => {
    const t = i / (n - 1)
    const heat = Math.min(1, t / 0.45) // energy in during the stop
    const cool = Math.exp(-Math.max(0, t - 0.45) * 1.6) // then radiates on the taxi
    return Math.round(oatC + (r.brakePeakC - oatC) * heat * cool)
  })
}

// Per-wheel vertical load: crosswind rolls the aircraft onto the downwind gear.
export function wheelLoads(r: SimResult, crosswindKt: number) {
  const skew = Math.min(0.35, crosswindKt / 100)
  return { upwind: r.loadPerTireKN * (1 - skew), downwind: r.loadPerTireKN * (1 + skew) }
}
