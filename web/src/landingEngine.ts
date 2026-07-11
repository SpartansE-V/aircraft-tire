import { FLEET_TIRES, type Tire } from './data.ts'
import { CAL, rolloutDecelMps2, simulate, tirePressureScrubFactor, trueGroundSpeedMps, type Landing, type SimResult } from './sim.ts'
import type { Track } from './tracks.ts'

export type Attitude = { pitchDeg: number; rollDeg: number; crabDeg: number; liftShare: number }

export type LandingPhase = 'approach' | 'flare' | 'touchdown' | 'spinup' | 'spoilers' | 'braking' | 'rollout' | 'stopped' | 'overrun'

export type PerWheelFrame = {
  loadKN: number
  scrubMm: number
  brakeMJ: number
  beadC: number
  contact: boolean
}

export type LandingFrame = {
  tS: number
  phase: LandingPhase
  pose: Attitude & { xM: number; yM: number; zM: number }
  speedMps: number
  sinkMps: number
  liftShare: number
  brakeShare: number
  wheel: Record<string, PerWheelFrame>
  flags: string[]
}

export type PerWheelSummary = {
  peakLoadKN: number
  scrubMm: number
  brakeMJ: number
  beadPeakC: number
  touchedFirst: boolean
}

export type LandingSummary = SimResult & {
  touchdownOrder: string[]
  perWheel: Record<string, PerWheelSummary>
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
const PRE_TOUCHDOWN_S = 6
const SPINUP_S = 0.55
const MAX_ROLLOUT_S = 180
const TAILSTRIKE_PITCH_DEG = 11
const FLARE_FLOAT_PER_DEG_M = 8
const LIFT_DELAY_MAX_S = 1.8

export function simulateLandingRun(scenario: LandingScenario): LandingRun {
  const tires = scenario.tires?.length ? scenario.tires : FLEET_TIRES
  const selected = tires.find((t) => t.id === scenario.selectedTireId) ?? tires[0]
  const base = simulate(scenario.landing, selected)
  const profile = rolloutProfile(scenario.landing, scenario.attitude, scenario.track, tires)
  const touchdownOrder = touchdownTires(tires, scenario.attitude)
  const perWheel = summarizeWheels(base, selected, tires, scenario.attitude, scenario.landing, touchdownOrder)
  const summary = summarizeSelected(base, selected, perWheel[selected.id], touchdownOrder, perWheel, profile, scenario.attitude, scenario.track, scenario.landing)
  const frames = buildFrames(scenario, tires, summary, perWheel, touchdownOrder, profile)

  return { frames, summary }
}

function summarizeWheels(base: SimResult, selected: Tire, tires: Tire[], attitude: Attitude, landing: Landing, touchdownOrder: string[]): Record<string, PerWheelSummary> {
  const mains = tires.filter((t) => t.gear !== 'nose')
  const liftLoadFactor = Math.max(0.05, 1 - liftShare(attitude))
  const totalMainLoad = base.loadPerTireKN * mains.length * liftLoadFactor
  const selectedPressure = tirePressureScrubFactor(selected)
  const totalScrub = base.scrubMm * mains.length * liftLoadFactor / selectedPressure
  const totalBrake = base.brakeEnergyMJ * mains.length
  const weights = Object.fromEntries(mains.map((t) => [t.id, wheelWeight(t, attitude, landing)]))
  const weightTotal = Object.values(weights).reduce((a, b) => a + b, 0) || 1
  const first = new Set(touchdownOrder)

  return Object.fromEntries(
    tires.map((t) => {
      const active = t.gear !== 'nose'
      const share = active ? weights[t.id] / weightTotal : 0
      const loadKN = totalMainLoad * share
      const crabScrub = Math.abs(attitude.crabDeg) * 0.002 * (loadKN / Math.max(base.loadPerTireKN, 1))
      const condition = wheelCondition(t)
      const scrubMm = active ? totalScrub * share * tirePressureScrubFactor(t) * condition.scrubFactor + crabScrub : 0
      return [
        t.id,
        {
          peakLoadKN: loadKN,
          scrubMm,
          brakeMJ: active ? totalBrake * share * condition.heatFactor : 0,
          beadPeakC: active ? landing.oatC + (base.beadPeakC - landing.oatC) * condition.heatFactor : 0,
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
): LandingSummary {
  const flags = adjustedFlags(base.flags, profile, attitude, selected, track, landing)
  if (!selectedWheel || selected.gear === 'nose') {
    return { ...base, stopDistM: profile.stopDistM, stopMarginM: profile.stopMarginM, flags, status: statusFor(base.status, flags, profile, attitude), touchdownOrder, perWheel }
  }
  const minGroove = Math.min(...selected.grooves)
  const grooveAfter = minGroove - selectedWheel.scrubMm
  const cyclesToLimit = Math.max(0, Math.floor((minGroove - selected.grooveLimit) / selectedWheel.scrubMm))
  const selectedFlags = [...flags]
  if (grooveAfter < selected.grooveLimit && !selectedFlags.some((f) => /Groove/.test(f))) {
    selectedFlags.push(`Groove ${grooveAfter.toFixed(2)} mm lands under the ${selected.grooveLimit} mm limit`)
  }
  const severe = base.status === 'action' || grooveAfter < selected.grooveLimit || profile.stopMarginM < 0 || attitude.pitchDeg > TAILSTRIKE_PITCH_DEG
  return {
    ...base,
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
): LandingFrame[] {
  const dt = saneDt(scenario.dtS)
  const v0 = scenarioSpeedMps(scenario.landing)
  const sink0 = scenarioSinkMps(scenario.landing)
  const approachHeightM = Math.max(8, sink0 * PRE_TOUCHDOWN_S)
  const touchdownS = PRE_TOUCHDOWN_S + profile.flareFloatS
  const rolloutS = Math.min(MAX_ROLLOUT_S, profile.delayS + profile.brakeS)
  const endS = Math.min(scenario.durationS ?? touchdownS + rolloutS, touchdownS + MAX_ROLLOUT_S)
  const first = new Set(touchdownOrder)
  const frames: LandingFrame[] = []

  for (let t = 0; t <= endS + dt / 2; t += dt) {
    const post = Math.max(0, t - touchdownS)
    const brakingT = Math.max(0, post - CAL.rolloutDelayS)
    const effectiveBrakingT = Math.max(0, post - profile.delayS)
    const speedMps = t < touchdownS ? v0 : Math.max(0, v0 - profile.brakeAccel * effectiveBrakingT)
    const rolloutM = v0 * Math.min(post, profile.delayS) + v0 * effectiveBrakingT - 0.5 * profile.brakeAccel * effectiveBrakingT ** 2
    const xM = t < touchdownS ? profile.touchdownXM - v0 * (touchdownS - t) : Math.min(summary.stopDistM, profile.touchdownXM + rolloutM)
    const stopped = post >= rolloutS - dt / 2 || speedMps <= 0.1
    const overrun = xM > scenario.landing.runwayM && !stopped
    const phase = framePhase(t, touchdownS, post, speedMps, stopped, overrun)
    const contactIds = contactSet(t, touchdownS, tires, first, Math.abs(scenario.attitude.rollDeg))
    const progress = stopped ? 1 : Math.max(0, Math.min(1, post / Math.max(rolloutS, 1)))
    const spoilerProgress = Math.max(0, Math.min(1, post / Math.max(profile.liftDelayS, 0.1)))
    const frameLiftShare = t < touchdownS ? liftShare(scenario.attitude) : liftShare(scenario.attitude) * (1 - spoilerProgress)

    frames.push({
      tS: +t.toFixed(3),
      phase,
      pose: {
        pitchDeg: scenario.attitude.pitchDeg * (1 - Math.min(1, post / 4)),
        rollDeg: scenario.attitude.rollDeg * (1 - Math.min(1, post / 3)),
        crabDeg: scenario.attitude.crabDeg * (1 - Math.min(1, post / 2)),
        xM,
        yM: t < touchdownS ? approachHeightM * ((touchdownS - t) / touchdownS) ** 1.15 : 0,
        zM: 0,
        liftShare: frameLiftShare,
      },
      speedMps,
      sinkMps: t < touchdownS ? sink0 * (1 - t / touchdownS) : 0,
      liftShare: frameLiftShare,
      brakeShare: post <= CAL.rolloutDelayS ? 0 : scenario.landing.brakeShare * Math.min(1, brakingT / 2),
      wheel: frameWheels(perWheel, contactIds, progress),
      flags: [...summary.flags],
    })

    if (stopped) break
  }

  const last = frames.at(-1)
  if (last && summary.stopDistM > scenario.landing.runwayM) last.phase = 'overrun'
  return frames
}

function frameWheels(perWheel: Record<string, PerWheelSummary>, contactIds: Set<string>, progress: number): Record<string, PerWheelFrame> {
  return Object.fromEntries(
    Object.entries(perWheel).map(([id, w]) => [
      id,
      {
        loadKN: contactIds.has(id) ? w.peakLoadKN : 0,
        scrubMm: w.scrubMm * progress,
        brakeMJ: w.brakeMJ * progress,
        beadC: w.beadPeakC * progress,
        contact: contactIds.has(id),
      },
    ]),
  )
}

function wheelWeight(t: Tire, attitude: Attitude, landing: Landing) {
  const sideSign = t.gear === 'right' ? 1 : t.gear === 'left' ? -1 : 0
  const downSign = Math.sign(attitude.rollDeg) || 1
  const rollSkew = Math.min(0.45, Math.abs(attitude.rollDeg) / 8 * 0.45)
  const windSkew = Math.min(0.2, landing.crosswindKt / 120)
  return Math.max(0.1, 1 + sideSign * downSign * (rollSkew + windSkew))
}

type RolloutProfile = {
  brakeAccel: number
  brakeS: number
  delayS: number
  liftDelayS: number
  flareFloatS: number
  touchdownXM: number
  stopDistM: number
  stopMarginM: number
}

function rolloutProfile(l: Landing, attitude: Attitude, track: Track, tires: Tire[]): RolloutProfile {
  const v0 = scenarioSpeedMps(l)
  const brakeAccel = rolloutDecelMps2(l) * trackGripFactor(track, l) * fleetGripFactor(tires)
  const liftDelayS = liftShare(attitude) * LIFT_DELAY_MAX_S
  const flareFloatM = Math.max(0, attitude.pitchDeg - 4) * FLARE_FLOAT_PER_DEG_M
  const flareFloatS = flareFloatM / Math.max(v0, 1)
  const delayS = CAL.rolloutDelayS + liftDelayS
  const brakeS = v0 / brakeAccel
  const stopDistM = flareFloatM + v0 * delayS + v0 ** 2 / (2 * brakeAccel)
  return { brakeAccel, brakeS, delayS, liftDelayS, flareFloatS, touchdownXM: flareFloatM, stopDistM, stopMarginM: l.runwayM - stopDistM }
}

function adjustedFlags(flags: readonly string[], profile: RolloutProfile, attitude: Attitude, selected: Tire, track: Track, landing: Landing) {
  const out = flags.filter((f) => !/^(Overrun|Tight)/i.test(f))
  if (profile.stopMarginM < 0) out.unshift(`Overrun — the stop needs ${Math.round(profile.stopDistM)} m and the runway is ${Math.round(profile.stopDistM + profile.stopMarginM)} m`)
  else if (profile.stopMarginM < CAL.marginM) out.unshift(`Tight — only ${Math.round(profile.stopMarginM)} m of runway left after the stop`)
  if (attitude.pitchDeg > TAILSTRIKE_PITCH_DEG) out.push(`Tailstrike risk — pitch ${attitude.pitchDeg.toFixed(1)}° exceeds ${TAILSTRIKE_PITCH_DEG}°`)
  for (const flag of trackConditionFlags(track, landing)) out.push(flag)
  for (const flag of wheelCondition(selected).flags) out.push(flag)
  return out
}

function statusFor(baseStatus: SimResult['status'], flags: string[], profile: RolloutProfile, attitude: Attitude) {
  if (!flags.length) return 'ok'
  return baseStatus === 'action' || profile.stopMarginM < 0 || attitude.pitchDeg > TAILSTRIKE_PITCH_DEG ? 'action' : 'watch'
}

function touchdownTires(tires: Tire[], attitude: Attitude) {
  const mains = tires.filter((t) => t.gear !== 'nose')
  if (Math.abs(attitude.rollDeg) < 0.5) return mains.map((t) => t.id)
  const gear = attitude.rollDeg > 0 ? 'right' : 'left'
  return mains.filter((t) => t.gear === gear).map((t) => t.id)
}

function contactSet(t: number, touchdownS: number, tires: Tire[], first: Set<string>, absRollDeg: number) {
  if (t < touchdownS) return new Set<string>()
  const mains = tires.filter((x) => x.gear !== 'nose').map((x) => x.id)
  if (absRollDeg >= 0.5 && t < touchdownS + SPINUP_S) return first
  return new Set(mains)
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
  return Math.min(0.9, Math.max(0, attitude.liftShare))
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
