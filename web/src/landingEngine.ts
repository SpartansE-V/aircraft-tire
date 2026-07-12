import { FLEET_TIRES, type Tire } from './data.ts'
import { aeroSideKN, CAL, canHydroplane, contactPatchDeg, crosswindKt, driftAngleDeg, flatSpotMm, G, GEAR, headwindKt, hydroplaneSpeedKt, OLEO, oleoResponse, rolloutDecelMps2, simulate, staticNoseShare, tirePressureScrubFactor, trueGroundSpeedMps, type Landing, type OleoRun, type SimResult } from './sim.ts'
import type { Track } from './tracks.ts'

export type Attitude = { pitchDeg: number; rollDeg: number; crabDeg: number; liftShare: number }

export type LandingPhase = 'approach' | 'flare' | 'touchdown' | 'spinup' | 'spoilers' | 'braking' | 'rollout' | 'stopped' | 'overrun'

export type PerWheelFrame = {
  loadKN: number
  scrubMm: number
  brakeMJ: number
  beadC: number
  contact: boolean
  /**
   * Which part of the tyre is touching the runway right now, as an angle around its own circumference.
   *
   * The tyre arrives at 140 kt *not turning at all*. For the first fraction of a second it is dragged
   * along the runway while friction spins it up, and it is not the whole tread that pays for that — it
   * is whichever arc happens to be underneath at the time. Knowing which arc is the entire reason to
   * track this: it is where the rubber actually went.
   */
  contactDeg: number
  /** Sliding speed at the contact patch: groundspeed minus the speed the tread is turning at. This is
   *  what abrades. It starts at the full 72 m/s and falls to zero as the wheel comes up to speed. */
  slipMps: number
}

export type LandingFrame = {
  tS: number
  phase: LandingPhase
  pose: Attitude & { xM: number; yM: number; zM: number }
  speedMps: number
  sinkMps: number
  liftShare: number
  brakeShare: number
  gearLoadKN: number // what the struts are pushing with right now — the wheel loads must add up to this
  /**
   * How far the fuselage has squatted *relative to how it sits parked*, with the wheels staying where
   * they are. Negative on approach — the gear hangs extended and the aircraft rides higher than parked.
   *
   * This is deliberately separate from `pose.yM`, and conflating them is what makes a landing look
   * wrong. A bounce moves the *whole aeroplane* (the wheels leave the runway; that is `pose.yM`). A
   * squat moves only the *airframe* (the wheels stay planted and the strut swallows the difference;
   * that is this). Apply a squat to the whole aircraft and the tyres sink through the tarmac.
   */
  squatM: number
  wheel: Record<string, PerWheelFrame>
  flags: string[]
}

export type PerWheelSummary = {
  peakLoadKN: number
  scrubMm: number
  brakeMJ: number
  beadPeakC: number
  touchedFirst: boolean
  /** The arc of tread that took the spin-up: where it starts, and how far round it goes before the
   *  wheel is up to speed and stops sliding. This is the rubber the landing actually cost. */
  impactDeg: number
  impactArcDeg: number
  /**
   * The flat spot, if the wheel locked: how deep it was ground, and where.
   *
   * A locked wheel does not turn, so every metre the aircraft slides is taken off the *same arc* — and
   * that is the whole difference from spin-up, where the tyre also slides hard but is turning while it
   * does, smearing the abrasion right round the circumference. One grinds a flat; the other does not.
   */
  flatSpotMm: number
  flatSpotDeg: number
  burst: boolean // it ran out of rubber before it ran out of runway
  locked: boolean
}

export type LandingSummary = SimResult & {
  touchdownOrder: string[]
  perWheel: Record<string, PerWheelSummary>
  bounces: number
  maxBounceM: number
  bottomedOut: boolean
  oleo: OleoRun // the whole strut history — peak, recoil, ring-down. This is the landing.
}

export type LandingScenario = {
  landing: Landing
  attitude: Attitude
  track: Track
  tires?: Tire[]
  selectedTireId?: string
  durationS?: number
  dtS?: number
}

export type LandingRun = {
  frames: LandingFrame[]
  summary: LandingSummary
}

const FPM_TO_MPS = 1 / 196.85
const MPS_PER_KT = 0.5144
const PRE_TOUCHDOWN_S = 6
export const SPINUP_S = 0.55
const MAX_ROLLOUT_S = 180
const TAILSTRIKE_PITCH_DEG = 11
const FLARE_FLOAT_PER_DEG_M = 8
const LIFT_DELAY_MAX_S = 1.8
const NOSE_DOWN_S = 3 // how long the nose stays flying after the mains touch, while the aircraft derotates
const BRAKES_BITE_S = CAL.rolloutDelayS // the wheels have been rolling for seconds by the time they lock

export function simulateLandingRun(scenario: LandingScenario): LandingRun {
  const tires = scenario.tires?.length ? scenario.tires : FLEET_TIRES
  const selected = tires.find((t) => t.id === scenario.selectedTireId) ?? tires[0]
  const base = simulate(scenario.landing, selected)
  // The arrival, integrated: gas spring, orifice damper, and whatever lift the crew left on the wing.
  // This is where peak load, the load history, and any bounce come from — the scalar model's peakG is
  // only a nominal-lift stand-in, and gets overridden below.
  const oleo = oleoResponse({
    massKg: scenario.landing.weightT * 1000,
    vSinkMps: scenario.landing.sinkFpm * FPM_TO_MPS,
    liftShare: liftShare(scenario.attitude),
    spoilerS: CAL.spoilerDumpS,
    durationS: 8,
  })
  const profile = rolloutProfile(scenario.landing, scenario.attitude, scenario.track, tires)
  const touchdownOrder = touchdownTires(tires, scenario.attitude)
  const perWheel = summarizeWheels(base, selected, tires, scenario.attitude, scenario.landing, touchdownOrder, profile.brakeAccel, oleo)
  const summary = summarizeSelected(base, selected, perWheel[selected.id], touchdownOrder, perWheel, profile, scenario.attitude, scenario.track, scenario.landing, tires, oleo)
  const frames = buildFrames(scenario, tires, summary, perWheel, touchdownOrder, profile, oleo)

  return { frames, summary }
}

function summarizeWheels(base: SimResult, selected: Tire, tires: Tire[], attitude: Attitude, landing: Landing, touchdownOrder: string[], brakeAccel: number, oleo: OleoRun): Record<string, PerWheelSummary> {
  const mains = tires.filter((t) => t.gear !== 'nose')
  const first = new Set(touchdownOrder)

  // A wheel's worst moment is one of two, and which one it is depends on where it sits. For a main on
  // the truck that arrives first, it is the arrival. For the nose, the arrival is a non-event — it is
  // still in the air — and its worst moment is derotation under braking. Taking the max over both is
  // what lets one function serve fourteen wheels that fail in two completely different ways.
  const aeroKN = aeroSideKN(landing, attitude.crabDeg)

  // Walk the arrival millisecond by millisecond rather than evaluating it at one guessed instant. The
  // load is climbing through the tyres while the truck is simultaneously rotating flat, so the worst
  // moment for the lead axle and the worst moment for the aircraft are not the same moment. Only the
  // strut's own history knows where they are, and the spin-up scrub falls out of the same walk.
  const arrivalPeak: Record<string, number> = Object.fromEntries(tires.map((t) => [t.id, 0]))
  const arrivalPeakAtS: Record<string, number> = Object.fromEntries(tires.map((t) => [t.id, 0]))
  const spinupWork: Record<string, number> = Object.fromEntries(tires.map((t) => [t.id, 0]))
  const step = Math.max(1, Math.round(0.005 / (oleo.samples[1].tS - oleo.samples[0].tS)))
  for (let i = 0; i < oleo.samples.length; i += step) {
    const s = oleo.samples[i]
    if (s.tS > SPINUP_S + 1) break
    const level = bogieLevel(s.strokeM + s.tyreM)
    const onTruck = (t: Tire) => t.gear !== 'nose' && first.has(t.id) && (level >= 1 || t.axle === LEAD_AXLE)
    const loads = wheelLoadsKN({
      tires,
      contact: new Set(tires.filter(onTruck).map((t) => t.id)),
      totalKN: s.loadKN,
      crabDeg: attitude.crabDeg,
      decelMps2: 0,
      aeroKN,
      bogieLevel: level,
    })
    for (const t of tires) {
      if (loads[t.id] > arrivalPeak[t.id]) {
        arrivalPeak[t.id] = loads[t.id]
        arrivalPeakAtS[t.id] = s.tS // the instant this tyre was hit hardest — and so, which arc took it
      }
      // Spin-up scrub goes with load × slip, and every tyre still turning is at full slip — so while
      // the lead axle is down alone, it is doing all of the scrubbing, for all six.
      if (s.tS < SPINUP_S) spinupWork[t.id] += loads[t.id]
    }
  }
  // Braking happens seconds later, once the oleo has settled — so it is a 1 g event, not a peakG one.
  // Using the arrival's g here would credit the nose gear with an impact it was airborne for.
  const atBraking = wheelLoadsKN({
    tires,
    contact: new Set(tires.map((t) => t.id)),
    totalKN: landing.weightT * G, // by now the spoilers have killed the lift and it weighs what it weighs
    crabDeg: attitude.crabDeg,
    decelMps2: brakeAccel,
    aeroKN,
  })

  // Brake heat is a rollout quantity, so it follows the *rolling* load share. Scrub is not: it is a
  // spin-up quantity, and spin-up happens while the trucks are still rotating flat — so it follows the
  // work each tyre did during those first few hundred milliseconds, which is emphatically not equal.
  // Only the mains have brakes; the nose gear has none, and never has.
  const mainRollKN = mains.reduce((a, t) => a + atBraking[t.id], 0) || 1
  const spinupTotal = mains.reduce((a, t) => a + spinupWork[t.id], 0) || 1
  const selectedPressure = tirePressureScrubFactor(selected)
  // No (1 − liftShare) factor here. `base.scrubMm` already carries the load through peakG, and lift is
  // now inside *that*. Scaling by it again — as this did — divided the fleet's wear by ten the moment
  // liftShare became the physical ~0.9 instead of the old model's decorative 0.18.
  const totalScrub = (base.scrubMm * mains.length) / selectedPressure
  const totalBrake = base.brakeEnergyMJ * mains.length

  return Object.fromEntries(
    tires.map((t) => {
      const active = t.gear !== 'nose'
      const peakLoadKN = Math.max(arrivalPeak[t.id], atBraking[t.id])
      const share = active ? spinupWork[t.id] / spinupTotal : 0
      const brakeShare = active ? atBraking[t.id] / mainRollKN : 0
      const condition = wheelCondition(t)
      // Lateral scrub from the crab, as the spec always claimed it worked: a side force of
      // µ_side · load · sin(crab) dragging across the tread, not a linear fudge on the crab angle.
      const sideKN = GEAR.muSide * peakLoadKN * Math.abs(Math.sin((attitude.crabDeg * Math.PI) / 180))
      const crabScrub = active ? (sideKN / Math.max(base.loadPerTireKN, 1)) * CAL.scrubK : 0
      // The arc of tread that was against the runway when this tyre was hit hardest. It is the tyre's
      // arbitrary clocking at touchdown plus however far it had turned by then — and the arc is wider
      // the harder it was hit, because a squashed tyre touches along a longer patch.
      const spin = spinUp(arrivalPeakAtS[t.id], scenarioSpeedMps(landing), t.radiusM)

      // The flat spot. Only the mains have brakes, so only the mains can lock — and when they do, the
      // wheel has already spun up and been rolling for seconds, so the arc it stops on is wherever it
      // happened to be. Everything the aircraft slides after that is ground off that one arc.
      const locked = active && base.locked
      // Capped at the rubber THIS tyre has. The scalar model caps against its own selected tyre, which
      // is not this one — and uncapped, a locked wheel reported 36.8 mm of flat on a tyre carrying
      // 5.8 mm of tread. A flat spot cannot be deeper than the tyre is thick; past that it is a burst.
      const rubberMm = Math.min(...t.grooves) + CAL.carcassMarginMm
      const ground = locked ? flatSpotMm(atBraking[t.id], base.slideDistM, landing) * condition.scrubFactor : 0
      const flat = Math.min(ground, rubberMm)
      const atLock = spinUp(BRAKES_BITE_S, scenarioSpeedMps(landing), t.radiusM)

      return [
        t.id,
        {
          impactDeg: (t.clockDeg + contactDeg(spin.thetaRad)) % 360,
          impactArcDeg: contactPatchDeg(peakLoadKN, t.radiusM),
          flatSpotMm: flat,
          flatSpotDeg: (t.clockDeg + contactDeg(atLock.thetaRad)) % 360,
          burst: ground > rubberMm,
          locked,
          peakLoadKN,
          scrubMm: active ? totalScrub * share * tirePressureScrubFactor(t) * condition.scrubFactor + crabScrub : 0,
          brakeMJ: active ? totalBrake * brakeShare * condition.heatFactor : 0,
          beadPeakC: active ? landing.oatC + (base.beadPeakC - landing.oatC) * condition.heatFactor : landing.oatC,
          touchedFirst: first.has(t.id),
        },
      ]
    }),
  )
}

function summarizeSelected(
  base: SimResult,
  selected: Tire,
  selectedWheel: PerWheelSummary | undefined,
  touchdownOrder: string[],
  perWheel: Record<string, PerWheelSummary>,
  profile: RolloutProfile,
  attitude: Attitude,
  track: Track,
  landing: Landing,
  tires: Tire[],
  oleo: OleoRun,
): LandingSummary {
  const flags = adjustedFlags(base.flags, profile, attitude, selected, track, landing, tires, oleo, perWheel)
  // peakG comes from the strut run with the crew's actual lift, not the scalar model's nominal one.
  const arrival = { peakG: oleo.peakG, bounces: oleo.bounces, maxBounceM: oleo.maxBounceM, bottomedOut: oleo.bottomedOut, oleo }
  if (!selectedWheel || selected.gear === 'nose') {
    return { ...base, ...arrival, stopDistM: profile.stopDistM, stopMarginM: profile.stopMarginM, flags, status: statusFor(base.status, flags, profile, attitude, oleo), touchdownOrder, perWheel }
  }
  const minGroove = Math.min(...selected.grooves)
  // The scrub *and* the flat spot both come out of the same rubber, and neither can take it below zero.
  const grooveAfter = Math.max(0, minGroove - selectedWheel.scrubMm - selectedWheel.flatSpotMm)
  const cyclesToLimit = Math.max(0, Math.floor((minGroove - selected.grooveLimit) / selectedWheel.scrubMm))
  const selectedFlags = [...flags]
  if (grooveAfter < selected.grooveLimit && !selectedFlags.some((f) => /Groove|burst/i.test(f))) {
    selectedFlags.push(`Groove ${grooveAfter.toFixed(2)} mm lands under the ${selected.grooveLimit} mm limit`)
  }
  const severe =
    base.status === 'action' ||
    grooveAfter < selected.grooveLimit ||
    profile.stopMarginM < 0 ||
    attitude.pitchDeg > TAILSTRIKE_PITCH_DEG ||
    oleo.peakG > CAL.gLimit ||
    oleo.bottomedOut ||
    // A tyre carrying half again its rated load is actionable on its own terms — it does not need the
    // g flag's permission, and a banked arrival can overload one axle without ever tripping it.
    selectedFlags.some((f) => /overloaded/i.test(f))
  return {
    ...base,
    ...arrival,
    loadPerTireKN: selectedWheel.peakLoadKN,
    scrubMm: selectedWheel.scrubMm,
    brakeEnergyMJ: selectedWheel.brakeMJ,
    grooveAfter,
    cyclesToLimit,
    stopDistM: profile.stopDistM,
    stopMarginM: profile.stopMarginM,
    flags: selectedFlags,
    status: selectedFlags.length === 0 ? 'ok' : severe ? 'action' : 'watch',
    touchdownOrder,
    perWheel,
  }
}

function buildFrames(
  scenario: LandingScenario,
  tires: Tire[],
  summary: LandingSummary,
  perWheel: Record<string, PerWheelSummary>,
  touchdownOrder: string[],
  profile: RolloutProfile,
  oleo: OleoRun,
): LandingFrame[] {
  const dt = saneDt(scenario.dtS)
  const v0 = scenarioSpeedMps(scenario.landing)
  const sink0 = scenarioSinkMps(scenario.landing)
  const approachHeightM = Math.max(8, sink0 * PRE_TOUCHDOWN_S)
  const touchdownS = PRE_TOUCHDOWN_S + profile.flareFloatS
  const rolloutS = Math.min(MAX_ROLLOUT_S, profile.delayS + profile.brakeS)
  const endS = Math.min(scenario.durationS ?? touchdownS + rolloutS, touchdownS + MAX_ROLLOUT_S)
  const first = new Set(touchdownOrder)
  // Where the airframe finally comes to rest on its gear. The scene's aircraft is modelled parked, so
  // this is its datum: on approach the gear hangs extended and it rides this much *higher* than parked.
  const staticDropM = oleo.samples.at(-1)!.dropM
  // When each wheel first met the runway. Its spin-up clock starts there and nowhere else — the truck
  // that lands first has its tyres up to speed before the other one has touched at all.
  const touchedAtS: Record<string, number> = {}
  const frames: LandingFrame[] = []

  for (let t = 0; t <= endS + dt / 2; t += dt) {
    const post = Math.max(0, t - touchdownS)
    const brakingT = Math.max(0, post - CAL.rolloutDelayS)
    const effectiveBrakingT = Math.max(0, post - profile.delayS)
    const speedMps = t < touchdownS ? v0 : brakingSpeedMps(profile, v0, effectiveBrakingT)
    const rolloutM = v0 * Math.min(post, profile.delayS) + brakingDistM(profile, v0, effectiveBrakingT)
    const xM = t < touchdownS ? profile.touchdownXM - v0 * (touchdownS - t) : Math.min(summary.stopDistM, profile.touchdownXM + rolloutM)
    const stopped = post >= rolloutS - dt / 2 || speedMps <= 0.1
    const overrun = xM > scenario.landing.runwayM && !stopped
    const phase = framePhase(t, touchdownS, post, speedMps, stopped, overrun)
    // If the strut threw it back into the air, it is not touching anything — no load, no contact, no
    // braking, no scrub. A bounce is a hole in the landing, and this is where it becomes one.
    const strut = oleoSampleAt(oleo, post)
    const airborne = t >= touchdownS && strut.airborne
    const level = t < touchdownS ? 0 : bogieLevel(strut.strokeM + strut.tyreM)
    const contactIds = airborne ? new Set<string>() : contactSet(t, touchdownS, tires, first, Math.abs(scenario.attitude.rollDeg), level)
    for (const id of contactIds) if (touchedAtS[id] === undefined) touchedAtS[id] = t
    const progress = stopped ? 1 : Math.max(0, Math.min(1, post / Math.max(rolloutS, 1)))
    const spoilerProgress = Math.max(0, Math.min(1, post / Math.max(profile.liftDelayS, 0.1)))
    const frameLiftShare = t < touchdownS ? liftShare(scenario.attitude) : liftShare(scenario.attitude) * (1 - spoilerProgress)

    // The load the gear is actually carrying right now, read straight off the integrated strut: the
    // arrival spike, the recoil, the ring-down, and zero while it is off the ground. The old version
    // faked this with `peakG · exp(−t/0.4)`, which is a shape, not a strut.
    const totalKN = t < touchdownS ? 0 : strut.loadKN
    // While it is hydroplaning it is barely decelerating, so it barely pitches onto the nose either.
    const decelNow = airborne || effectiveBrakingT <= 0 || speedMps <= 0.1 ? 0 : effectiveBrakingT < profile.hydroS ? profile.hydroAccel : profile.brakeAccel
    const loadsKN = wheelLoadsKN({
      tires,
      contact: contactIds,
      totalKN,
      crabDeg: scenario.attitude.crabDeg,
      decelMps2: decelNow,
      aeroKN: aeroSideKN(scenario.landing, scenario.attitude.crabDeg),
      bogieLevel: level,
    })

    frames.push({
      tS: +t.toFixed(3),
      phase,
      pose: {
        pitchDeg: scenario.attitude.pitchDeg * (1 - Math.min(1, post / 4)),
        rollDeg: scenario.attitude.rollDeg * (1 - Math.min(1, post / 3)),
        crabDeg: scenario.attitude.crabDeg * (1 - Math.min(1, post / 2)),
        xM,
        // How high the *wheels* are off the runway: the approach, and then — if the gear recoils hard
        // enough — the bounce. Zero while it is rolling. This used to be pinned to 0 from the instant
        // of touchdown, which left the whole arrival trapped inside the numbers while the aeroplane on
        // screen hung rigid, in the one place it should have been impossible to miss.
        yM: t < touchdownS ? approachHeightM * ((touchdownS - t) / touchdownS) ** 1.15 : strut.hM,
        zM: 0,
        liftShare: frameLiftShare,
      },
      speedMps,
      sinkMps: t < touchdownS ? sink0 * (1 - t / touchdownS) : 0,
      liftShare: frameLiftShare,
      gearLoadKN: totalKN,
      // On approach the gear hangs fully extended, so the airframe rides a whole static-stroke higher
      // than it does parked. It squats through that on touchdown, springs part of the way back out as
      // the gas pushes, and finally settles to 0 — parked.
      squatM: (t < touchdownS ? 0 : strut.strokeM + strut.tyreM) - staticDropM,
      brakeShare: post <= CAL.rolloutDelayS ? 0 : scenario.landing.brakeShare * Math.min(1, brakingT / 2),
      wheel: frameWheels(perWheel, contactIds, progress, loadsKN, tires, touchedAtS, t, v0, speedMps, effectiveBrakingT > 0),
      flags: [...summary.flags],
    })

    if (stopped) break
  }

  const last = frames.at(-1)
  if (last && summary.stopDistM > scenario.landing.runwayM) last.phase = 'overrun'
  return frames
}

// The load on each wheel *at this instant*, solved fresh from whoever is touching the ground right
// now. The old version handed every contacting wheel its precomputed peak and gave everyone else zero,
// which is why a one-truck frame reacted 69 % of an aeroplane: the wheels that were up had been
// allocated load they could not possibly carry, and it simply vanished with them.
function frameWheels(
  perWheel: Record<string, PerWheelSummary>,
  contactIds: Set<string>,
  progress: number,
  loadsKN: Record<string, number>,
  tires: Tire[],
  touchedAtS: Record<string, number>,
  tS: number,
  groundMps: number,
  speedNowMps: number,
  braking: boolean,
): Record<string, PerWheelFrame> {
  return Object.fromEntries(
    tires.map((t) => {
      const w = perWheel[t.id]
      const since = touchedAtS[t.id] === undefined ? -1 : tS - touchedAtS[t.id]
      const spin = spinUp(since, groundMps, t.radiusM)
      // A locked wheel has stopped turning. It is not rolling down the runway any more, it is being
      // dragged along it — so the contact patch stops moving round the tread and the whole slide is
      // taken out of the arc it froze on. That is the flat spot, and this is the moment it is made.
      const skidding = w.locked && braking && contactIds.has(t.id) && speedNowMps > 0.1
      return [
        t.id,
        {
          loadKN: loadsKN[t.id] ?? 0,
          scrubMm: w.scrubMm * progress,
          brakeMJ: w.brakeMJ * progress,
          beadC: w.beadPeakC * progress,
          contact: contactIds.has(t.id),
          // Where the runway is touching it, in the tyre's own frame — its arbitrary clocking at
          // touchdown, plus however far it has turned since. Unless it is locked, in which case: here.
          contactDeg: skidding ? w.flatSpotDeg : since < 0 ? t.clockDeg : (t.clockDeg + contactDeg(spin.thetaRad)) % 360,
          slipMps: skidding ? speedNowMps : since < 0 ? 0 : spin.slipMps,
        },
      ]
    }),
  )
}

/**
 * Vertical load on every wheel, from a moment balance about the contact points.
 *
 * This replaces a pair of hand-tuned skew factors (`rollSkew`, `windSkew`) whose shares were never
 * required to add up — and didn't: they dropped 31 % of the aeroplane on a one-truck arrival and left
 * the nose gear at exactly zero forever. Nothing here is a free parameter. The loads are what has to
 * be true for the aircraft not to rotate, so they sum to what the aircraft demands *by construction*,
 * and two behaviours the old fudges had to fake now fall out for free:
 *
 *   - a one-truck arrival really does put ~2x on each wheel that is down, because six wheels are
 *     reacting what twelve normally share. That is not a coefficient, it is division.
 *   - the nose gear takes load the moment it touches, and more of it under braking.
 */
/** Which axle of the truck reaches the runway first. */
export const LEAD_AXLE = GEAR.bogieAftAxleFirst ? 2 : 0

/**
 * How level the truck is: 0 = still hanging tilted on its lead axle, 1 = flat on all three.
 *
 * Driven by how far the airframe has *dropped* — tyre squash plus strut stroke — because the tyre is
 * the softer of the two and moves first. Gating this on strut stroke alone leaves the truck tilted
 * while the load builds, and charges the lead axle several times its rated load.
 */
export function bogieLevel(dropM: number) {
  return Math.min(1, Math.max(0, dropM / GEAR.bogieLevelDropM))
}

/**
 * Share of a truck's load taken by each of its three axles.
 *
 * Tilted (level 0), the lead axle has the whole truck to itself — it is the only one touching. Flat
 * (level 1) they share, except that braking drags at the contact patch below the truck pivot and
 * pitches the truck onto its forward axle. So the aft tyres are punished on arrival and the forward
 * tyres are punished on the brakes, and neither set gets to be the lucky one.
 */
function axleShares(level: number, decelMps2: number): [number, number, number] {
  const pitch = Math.min(0.3, (decelMps2 / G) * GEAR.bogieBrakePitchPerG)
  const w: [number, number, number] = [0, 0, 0]
  for (let a = 0; a < 3; a++) {
    const flat = (1 / 3) * (1 + pitch * (1 - a)) // braking leans it forward: +pitch on axle 0, −pitch on axle 2
    w[a] = (1 - level) * (a === LEAD_AXLE ? 1 : 0) + level * flat
  }
  const sum = w[0] + w[1] + w[2] || 1
  return [w[0] / sum, w[1] / sum, w[2] / sum]
}

export function wheelLoadsKN(args: {
  tires: Tire[]
  contact: Set<string>
  totalKN: number
  crabDeg: number
  decelMps2: number
  aeroKN?: number
  bogieLevel?: number
}): Record<string, number> {
  const { tires, contact, totalKN, crabDeg, decelMps2, aeroKN = 0, bogieLevel: level = 1 } = args
  const loads: Record<string, number> = Object.fromEntries(tires.map((t) => [t.id, 0]))
  const down = tires.filter((t) => contact.has(t.id))
  if (!down.length) return loads

  const nose = down.filter((t) => t.gear === 'nose')
  const left = down.filter((t) => t.gear === 'left')
  const right = down.filter((t) => t.gear === 'right')
  const mains = [...left, ...right]

  // Longitudinal. The CG sits ahead of the mains, so the nose carries a share — but only once it is
  // on the ground, which is why it is zero through the whole touchdown and spin-up. Braking then
  // pitches the aircraft forward about the mains and moves more load onto it: this is why nose-gear
  // load roughly doubles under heavy braking, and why it was never going to be a constant.
  let noseKN = 0
  if (nose.length && mains.length) {
    const brakingShare = (decelMps2 * GEAR.cgHeightM) / (GEAR.wheelbaseM * G)
    noseKN = totalKN * Math.min(0.35, staticNoseShare + brakingShare)
  } else if (nose.length) {
    noseKN = totalKN // nose-only contact is not a landing, but the books still have to balance
  }
  const mainKN = totalKN - noseKN

  // Lateral. Side force acts at the contact patch, a CG-height below the CG, so it rolls load onto the
  // downwind truck. If only one truck is down it takes all of it — and note there is no skew factor
  // here at all: the one-wheel touchdown IS just the contact set having one truck in it.
  // Split one truck's load across the wheels of it that are actually touching, by axle.
  const shares = axleShares(level, decelMps2)
  const spreadTruck = (truck: Tire[], kN: number) => {
    if (!truck.length) return
    const w = truck.map((t) => shares[t.axle] / truck.filter((x) => x.axle === t.axle).length)
    const sum = w.reduce((a, b) => a + b, 0) || 1
    truck.forEach((t, i) => (loads[t.id] = (kN * w[i]) / sum))
  }

  if (!left.length || !right.length) {
    spreadTruck(mains, mainKN)
  } else {
    // Two lateral forces, and they are not the same thing.
    //
    //   - the airframe is *pushed* sideways by whatever drift was not crabbed out — an aero force on
    //     the fin and fuselage, acting up at CG height.
    //   - the tyres are *dragged* sideways by the crab — a cornering force down at the contact patch.
    //
    // Summing moments about the ground line, the aero force rolls the aircraft directly, while the
    // tyre force rolls it only through the inertia it produces. Both terms collapse to the same shape,
    // but the tyre one carries the opposite sign: a car leans *away* from the way its tyres push it,
    // onto the outer wheels, and so does an aeroplane. Get that backwards and a de-crabbed landing
    // starts unloading the gear it should be punishing.
    //
    // Both mechanisms end up loading the *downwind* truck, which is the point: crabbing out a
    // crosswind does not spare the gear the side load, it only converts it from drift into scrub.
    const tyreSideKN = GEAR.muSide * mainKN * Math.sin((crabDeg * Math.PI) / 180)
    const transferKN = ((aeroKN - tyreSideKN) * GEAR.cgHeightM) / GEAR.trackM
    const rightKN = Math.min(mainKN, Math.max(0, mainKN / 2 + transferKN))
    spreadTruck(right, rightKN)
    spreadTruck(left, mainKN - rightKN)
  }
  for (const t of nose) loads[t.id] = noseKN / nose.length
  return loads
}

/**
 * Wheel spin-up: the tyre touches down at 140 kt and is not turning at all.
 *
 * Friction at the contact patch drags it up to speed over a few tenths of a second, and until it gets
 * there the tread is *sliding*, not rolling. That slide is the spin-up scrub — it is where the rubber
 * goes, and it lands on whichever arc of the tyre happens to be underneath while it happens.
 *
 * Returns, at `tS` after this wheel touched: the tyre's own rotation angle, and how fast the contact
 * patch is still sliding. A wheel that has come up to speed rolls, and rolling costs nothing.
 */
function spinUp(tS: number, groundMps: number, radiusM: number) {
  const wFull = groundMps / Math.max(radiusM, 0.01) // rad/s once it is rolling
  if (tS <= 0) return { thetaRad: 0, slipMps: groundMps, spun: false }
  // Constant angular acceleration is the honest first cut: friction torque is roughly µ·load·r, and
  // both load and µ are near enough constant across the tenths of a second this takes.
  const t = Math.min(tS, SPINUP_S)
  const w = wFull * (t / SPINUP_S)
  const theta = 0.5 * wFull * (t * t) / SPINUP_S + (tS > SPINUP_S ? wFull * (tS - SPINUP_S) : 0)
  return { thetaRad: theta, slipMps: Math.max(0, groundMps - w * radiusM), spun: tS >= SPINUP_S }
}

/** Where the runway is touching the tyre, in the tyre's own frame. As the wheel turns forward by θ,
 *  the patch of tread against the ground runs backwards around it by the same angle. */
function contactDeg(thetaRad: number) {
  return (((-thetaRad * 180) / Math.PI) % 360 + 360) % 360
}

/** The strut's state at `tS` after touchdown. Samples are on a fixed grid, so this is an index. */
function oleoSampleAt(oleo: OleoRun, tS: number) {
  const dt = oleo.samples[1].tS - oleo.samples[0].tS
  const i = Math.min(oleo.samples.length - 1, Math.max(0, Math.round(tS / dt)))
  return oleo.samples[i]
}

type RolloutProfile = {
  brakeAccel: number
  hydroAccel: number
  vpMps: number // hydroplaning speed of the first tyre to give up. 0 on a dry runway.
  vBrakeMps: number // the speed at which real braking finally begins — v0 unless it is aquaplaning
  hydroS: number // how long it spends riding on water before the brakes bite
  brakeS: number
  delayS: number
  liftDelayS: number
  flareFloatS: number
  touchdownXM: number
  stopDistM: number
  stopMarginM: number
}

/** Speed and distance during the braking phase — piecewise, because a hydroplaning rollout has two
 *  decelerations, not one: almost nothing above Vp, then the real thing below it. */
function brakingSpeedMps(p: RolloutProfile, v0: number, tS: number) {
  if (tS <= 0) return v0
  if (tS < p.hydroS) return Math.max(0, v0 - p.hydroAccel * tS)
  return Math.max(0, p.vBrakeMps - p.brakeAccel * (tS - p.hydroS))
}

function brakingDistM(p: RolloutProfile, v0: number, tS: number) {
  if (tS <= 0) return 0
  if (tS < p.hydroS) return v0 * tS - 0.5 * p.hydroAccel * tS ** 2
  const hydroM = (v0 ** 2 - p.vBrakeMps ** 2) / (2 * p.hydroAccel)
  const b = Math.min(tS - p.hydroS, p.vBrakeMps / p.brakeAccel)
  return hydroM + p.vBrakeMps * b - 0.5 * p.brakeAccel * b ** 2
}

function rolloutProfile(l: Landing, attitude: Attitude, track: Track, tires: Tire[]): RolloutProfile {
  const v0 = scenarioSpeedMps(l)
  const grip = trackGripFactor(track, l) * fleetGripFactor(tires)
  const brakeAccel = rolloutDecelMps2(l) * grip
  const hydroAccel = rolloutDecelMps2(l, CAL.muHydroplane) * grip
  const liftDelayS = liftShare(attitude) * LIFT_DELAY_MAX_S
  const flareFloatM = Math.max(0, attitude.pitchDeg - 4) * FLARE_FLOAT_PER_DEG_M
  const flareFloatS = flareFloatM / Math.max(v0, 1)
  const delayS = CAL.rolloutDelayS + liftDelayS

  // The tyre that gives up first is the one with the least air in it, and one is enough to start the
  // slide — so the fleet hydroplanes at the *lowest* Vp on the aircraft, not the average.
  const vpKt = canHydroplane(l.surface) ? Math.min(...tires.filter((t) => t.gear !== 'nose').map((t) => hydroplaneSpeedKt(t.psi))) : 0
  const vpMps = vpKt * MPS_PER_KT
  // Real braking only begins once it is slow enough to be touching the runway. On a dry runway, or if
  // it never got fast enough to aquaplane, that is simply the touchdown speed.
  const aquaplanes = vpMps > 0 && v0 > vpMps
  const vBrakeMps = aquaplanes ? vpMps : v0
  const hydroS = (v0 - vBrakeMps) / hydroAccel
  const hydroM = (v0 ** 2 - vBrakeMps ** 2) / (2 * hydroAccel)

  const brakeS = hydroS + vBrakeMps / brakeAccel
  const stopDistM = flareFloatM + v0 * delayS + hydroM + vBrakeMps ** 2 / (2 * brakeAccel)
  return { brakeAccel, hydroAccel, vpMps, vBrakeMps, hydroS, brakeS, delayS, liftDelayS, flareFloatS, touchdownXM: flareFloatM, stopDistM, stopMarginM: l.runwayM - stopDistM }
}

function adjustedFlags(flags: readonly string[], profile: RolloutProfile, attitude: Attitude, selected: Tire, track: Track, landing: Landing, tires: Tire[], oleo: OleoRun, perWheel: Record<string, PerWheelSummary>) {
  // The scalar model's hard-landing flag was computed at nominal lift; this run knows the real one.
  const out = flags.filter((f) => !/^(Overrun|Tight|Hydroplaning|Hard landing)/i.test(f))
  if (oleo.peakG > CAL.gLimit) out.push(`Hard landing — ${oleo.peakG.toFixed(2)} G exceeds the ${CAL.gLimit} G FOQA flag`)

  // Recoil, and what it actually produces. The gas spring gives back what it stored, and on a hard
  // arrival it gives back enough to unload the gear completely and lift the tyres clear of the runway —
  // a few centimetres — before they drop back and take the impact a second time. The tread pays for
  // that second impact, which is the whole reason a tyre app should care.
  //
  // Call it what it is: this is wheel hop, not a ballooned bounce. A bounced landing in the sense a
  // crew means it — the aircraft back in the air by several metres, arriving again nose-low — is an
  // aerodynamic event, driven by lift and pitch. That needs flight dynamics, and this page is on rails
  // by design. Do not let the flag imply otherwise.
  if (oleo.bounces > 0) {
    out.push(
      `Wheels left the runway — the gear recoiled hard enough to unload completely and lift the tyres ${(oleo.maxBounceM * 100).toFixed(1)} cm clear, with ${Math.round(liftShare(attitude) * 100)} % lift still on the wing; they come back down and the tread takes a second impact`,
    )
  }
  // Out of stroke: past here the strut has stopped absorbing and the airframe is taking it directly.
  if (oleo.bottomedOut) out.push(`Gear bottomed out — the strut ran out of its ${OLEO.strokeM} m of stroke and the airframe is taking the rest`)

  // Overload. The truck lands on one axle, so two tyres carry a whole bogie for a moment — and if the
  // arrival is banked as well, two tyres carry the whole *aeroplane*. A landing transient is allowed to
  // run over the sidewall's rated load; the question a tyre shop actually asks is by how much, and on
  // which position. This is the number that answer needs, and it only exists because the bogie pitches.
  const overloaded = tires
    .filter((t) => perWheel[t.id] && perWheel[t.id].peakLoadKN > t.ratedLoadKN * 1.5)
    .sort((a, b) => perWheel[b.id].peakLoadKN / b.ratedLoadKN - perWheel[a.id].peakLoadKN / a.ratedLoadKN)
  const worst = overloaded[0]
  if (worst) {
    const x = perWheel[worst.id].peakLoadKN / worst.ratedLoadKN
    out.push(
      `${worst.id} overloaded — ${Math.round(perWheel[worst.id].peakLoadKN)} kN is ${x.toFixed(1)}x its ${worst.ratedLoadKN} kN rating${
        overloaded.length > 1 ? ` (${overloaded.length} tyres over)` : ''
      }. It is on the axle that lands first, and it carries the truck alone until the bogie rotates flat`,
    )
  }
  if (profile.stopMarginM < 0) out.unshift(`Overrun — the stop needs ${Math.round(profile.stopDistM)} m and the runway is ${Math.round(profile.stopDistM + profile.stopMarginM)} m`)
  else if (profile.stopMarginM < CAL.marginM) out.unshift(`Tight — only ${Math.round(profile.stopMarginM)} m of runway left after the stop`)
  if (attitude.pitchDeg > TAILSTRIKE_PITCH_DEG) out.push(`Tailstrike risk — pitch ${attitude.pitchDeg.toFixed(1)}° exceeds ${TAILSTRIKE_PITCH_DEG}°`)

  // The crab the crosswind actually demands. Carry less than this and the aircraft is drifting off the
  // centreline with the wind on its side; carry more and you are scrubbing rubber for nothing. Before
  // this coupling existed you could dial 35 kt of crosswind against 0° of crab and nothing objected.
  const drift = driftAngleDeg(landing)
  const xw = Math.abs(crosswindKt(landing))
  const uncorrected = drift + attitude.crabDeg
  if (Math.abs(uncorrected) > 3) {
    out.push(
      Math.abs(attitude.crabDeg) < Math.abs(drift)
        ? `Drifting — ${xw.toFixed(0)} kt of crosswind needs ${Math.abs(drift).toFixed(1)}° of crab and the aircraft is carrying ${Math.abs(attitude.crabDeg).toFixed(1)}°; the gear takes the difference as side load`
        : `Over-crabbed by ${Math.abs(uncorrected).toFixed(1)}° — more side scrub than the ${xw.toFixed(0)} kt crosswind calls for`,
    )
  }

  // A headwind is free runway, and it is worth saying so — the model spent its whole life unable to
  // feel one, so the only thing wind could ever do was make things worse.
  const hw = headwindKt(landing)
  if (hw < -5) out.push(`Tailwind ${Math.abs(hw).toFixed(0)} kt — the aircraft touches down that much faster over the ground, and every energy term goes with the square`)

  // Hydroplaning. Named per tyre, because it *is* per tyre: the softest one gives up first, and one is
  // enough to start the slide. (The scalar model raises its own single-tyre version of this flag; the
  // fleet view supersedes it, so drop that one rather than say it twice.)
  if (canHydroplane(landing.surface)) {
    const mains = tires.filter((t) => t.gear !== 'nose')
    const touchdownKt = trueGroundSpeedMps(landing) / MPS_PER_KT
    const riding = mains.filter((t) => touchdownKt > hydroplaneSpeedKt(t.psi))
    if (riding.length) {
      const worst = riding.reduce((a, t) => (t.psi < a.psi ? t : a))
      out.push(
        `Hydroplaning — ${riding.length} of ${mains.length} mains ride up on water at ${Math.round(touchdownKt)} kt; ${worst.id} goes first at ${Math.round(hydroplaneSpeedKt(worst.psi))} kt (${Math.round(worst.psi)} psi)`,
      )
    }
  }
  for (const flag of trackConditionFlags(track, landing)) out.push(flag)
  for (const flag of wheelCondition(selected).flags) out.push(flag)
  return out
}

function statusFor(baseStatus: SimResult['status'], flags: string[], profile: RolloutProfile, attitude: Attitude, oleo: OleoRun) {
  if (!flags.length) return 'ok'
  const severe = baseStatus === 'action' || profile.stopMarginM < 0 || attitude.pitchDeg > TAILSTRIKE_PITCH_DEG || oleo.peakG > CAL.gLimit || oleo.bottomedOut
  return severe ? 'action' : 'watch'
}

function touchdownTires(tires: Tire[], attitude: Attitude) {
  const mains = tires.filter((t) => t.gear !== 'nose')
  if (Math.abs(attitude.rollDeg) < 0.5) return mains.map((t) => t.id)
  const gear = attitude.rollDeg > 0 ? 'right' : 'left'
  return mains.filter((t) => t.gear === gear).map((t) => t.id)
}

// Who is actually on the ground, and when. This is the whole one-wheel-touchdown story: with any bank
// on, only the downwind truck is in this set for the first half-second, so the moment balance has no
// choice but to put the entire aircraft through six tyres.
function contactSet(t: number, touchdownS: number, tires: Tire[], first: Set<string>, absRollDeg: number, level: number) {
  if (t < touchdownS) return new Set<string>()
  const post = t - touchdownS
  const mains = tires.filter((x) => x.gear !== 'nose')
  // Whichever trucks are down, they are down on their lead axle only until the strut has stroked far
  // enough to rotate them flat. Six wheels on a bogie, two of them taking the first bite.
  const onTruck = (t2: Tire) => level >= 1 || t2.axle === LEAD_AXLE
  const down = (absRollDeg >= 0.5 && post < SPINUP_S ? mains.filter((x) => first.has(x.id)) : mains).filter(onTruck)
  // The nose is still flying at touchdown and comes down as the aircraft derotates. Until it lands,
  // the mains carry everything — and when it does land, it lands into the braking.
  if (post < NOSE_DOWN_S) return new Set(down.map((x) => x.id))
  return new Set([...down.map((x) => x.id), ...tires.filter((x) => x.gear === 'nose').map((x) => x.id)])
}

function framePhase(t: number, touchdownS: number, post: number, speedMps: number, stopped: boolean, overrun: boolean): LandingPhase {
  if (overrun) return 'overrun'
  if (stopped) return 'stopped'
  if (t < touchdownS * 0.55) return 'approach'
  if (t < touchdownS) return 'flare'
  if (post < 0.15) return 'touchdown'
  if (post < SPINUP_S) return 'spinup'
  if (post < CAL.rolloutDelayS) return 'spoilers'
  if (speedMps > 0) return 'braking'
  return 'rollout'
}

function liftShare(attitude: Attitude) {
  // Up to 1.0 now: the wing really can still be carrying the whole aeroplane as the wheels touch, and
  // that is the case where the strut has energy to give back. The old 0.9 cap was arbitrary.
  return Math.min(1, Math.max(0, attitude.liftShare))
}

function wheelCondition(t: Tire) {
  const minGroove = Math.min(...t.grooves)
  const treadUsed = Math.max(0, Math.min(1, 1 - (minGroove - t.grooveLimit) / 6))
  const severeDefects = t.defects.filter((d) => d.severity === 'high').length
  const mediumDefects = t.defects.filter((d) => d.severity === 'med').length
  const retreadFactor = 1 + t.retreads * 0.035
  const defectScrub = 1 + severeDefects * 0.18 + mediumDefects * 0.08
  const scrubFactor = retreadFactor * defectScrub * (1 + treadUsed * 0.18)
  const heatFactor = retreadFactor * (1 + severeDefects * 0.16 + mediumDefects * 0.06)
  const gripFactor = Math.max(0.72, 1 - treadUsed * 0.08 - severeDefects * 0.08 - Math.max(0, (t.psiTarget - t.psi) / t.psiTarget) * 0.18)
  const flags = [
    minGroove < t.grooveLimit + 0.8 && `${t.id} tread reserve low — ${minGroove.toFixed(2)} mm near ${t.grooveLimit.toFixed(1)} mm limit`,
    severeDefects > 0 && `${t.id} high-severity defect increases scrub and heat risk`,
    t.retreads >= 3 && `${t.id} at R${t.retreads} retread limit — heat margin reduced`,
  ].filter((f): f is string => typeof f === 'string')
  return { scrubFactor, heatFactor, gripFactor, flags }
}

function fleetGripFactor(tires: Tire[]) {
  const mains = tires.filter((t) => t.gear !== 'nose')
  if (!mains.length) return 1
  const grip = mains.map((t) => wheelCondition(t).gripFactor)
  return Math.min(...grip) * 0.35 + (grip.reduce((a, b) => a + b, 0) / grip.length) * 0.65
}

function trackGripFactor(track: Track, landing: Landing) {
  const rwycc = Math.min(track.rwycc, { dry: 6, wet: 4, contaminated: 2 }[landing.surface])
  const rwyccFactor = 0.82 + (rwycc / 6) * 0.18
  const coldLoss = landing.oatC < 0 && landing.surface !== 'dry' ? 0.9 : 1
  const hotLoss = landing.oatC > 38 && landing.surface === 'dry' ? 0.96 : 1
  return rwyccFactor * coldLoss * hotLoss
}

function trackConditionFlags(track: Track, landing: Landing) {
  const rwycc = Math.min(track.rwycc, { dry: 6, wet: 4, contaminated: 2 }[landing.surface])
  return [
    rwycc < 5 && `Runway condition RWYCC ${rwycc} reduces braking grip`,
    landing.oatC < 0 && landing.surface !== 'dry' && `Freezing ${landing.surface} runway costs additional braking margin`,
    landing.oatC > 38 && landing.surface === 'dry' && `Hot dry runway reduces tire heat margin`,
  ].filter((f): f is string => typeof f === 'string')
}

function saneDt(dtS: number | undefined) {
  return Math.min(0.25, Math.max(0.02, dtS ?? 0.05))
}

export function scenarioSpeedMps(l: Landing) {
  return trueGroundSpeedMps(l)
}

export function scenarioSinkMps(l: Landing) {
  return l.sinkFpm * FPM_TO_MPS
}
