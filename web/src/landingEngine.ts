import { FLEET_TIRES, type Tire } from './data.ts'
import { CAL, rolloutDecelMps2, simulate, trueGroundSpeedMps, type Landing, type SimResult } from './sim.ts'
import type { Track } from './tracks.ts'

export type Attitude = { pitchDeg: number; rollDeg: number; crabDeg: number }

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
const MAX_ROLLOUT_S = 120

export function simulateLandingRun(scenario: LandingScenario): LandingRun {
  const tires = scenario.tires?.length ? scenario.tires : FLEET_TIRES
  const selected = tires.find((t) => t.id === scenario.selectedTireId) ?? tires[0]
  const base = simulate(scenario.landing, selected)
  const touchdownOrder = touchdownTires(tires, scenario.attitude)
  const perWheel = summarizeWheels(base, tires, scenario.attitude, scenario.landing, touchdownOrder)
  const summary = summarizeSelected(base, selected, perWheel[selected.id], touchdownOrder, perWheel)
  const frames = buildFrames(scenario, tires, summary, perWheel, touchdownOrder)

  return { frames, summary }
}

function summarizeWheels(base: SimResult, tires: Tire[], attitude: Attitude, landing: Landing, touchdownOrder: string[]): Record<string, PerWheelSummary> {
  const mains = tires.filter((t) => t.gear !== 'nose')
  const totalMainLoad = base.loadPerTireKN * mains.length
  const totalScrub = base.scrubMm * mains.length
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
      const scrubMm = active ? totalScrub * share + crabScrub : 0
      return [
        t.id,
        {
          peakLoadKN: loadKN,
          scrubMm,
          brakeMJ: active ? totalBrake * share : 0,
          beadPeakC: active ? base.beadPeakC : 0,
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
): LandingSummary {
  if (!selectedWheel || selected.gear === 'nose') return { ...base, touchdownOrder, perWheel }
  const minGroove = Math.min(...selected.grooves)
  const grooveAfter = minGroove - selectedWheel.scrubMm
  const cyclesToLimit = Math.max(0, Math.floor((minGroove - selected.grooveLimit) / selectedWheel.scrubMm))
  const selectedFlags = [...base.flags]
  if (grooveAfter < selected.grooveLimit && !selectedFlags.some((f) => /Groove/.test(f))) {
    selectedFlags.push(`Groove ${grooveAfter.toFixed(2)} mm lands under the ${selected.grooveLimit} mm limit`)
  }
  const severe = base.status === 'action' || grooveAfter < selected.grooveLimit
  return {
    ...base,
    loadPerTireKN: selectedWheel.peakLoadKN,
    scrubMm: selectedWheel.scrubMm,
    brakeEnergyMJ: selectedWheel.brakeMJ,
    grooveAfter,
    cyclesToLimit,
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
): LandingFrame[] {
  const dt = saneDt(scenario.dtS)
  const v0 = scenarioSpeedMps(scenario.landing)
  const sink0 = scenarioSinkMps(scenario.landing)
  const approachHeightM = Math.max(8, sink0 * PRE_TOUCHDOWN_S)
  const brakeAccel = rolloutDecelMps2(scenario.landing)
  const brakeS = v0 / brakeAccel
  const rolloutS = Math.min(MAX_ROLLOUT_S, CAL.rolloutDelayS + brakeS)
  const endS = Math.min(scenario.durationS ?? PRE_TOUCHDOWN_S + rolloutS, PRE_TOUCHDOWN_S + MAX_ROLLOUT_S)
  const first = new Set(touchdownOrder)
  const frames: LandingFrame[] = []

  for (let t = 0; t <= endS + dt / 2; t += dt) {
    const post = Math.max(0, t - PRE_TOUCHDOWN_S)
    const brakingT = Math.max(0, post - CAL.rolloutDelayS)
    const speedMps = t < PRE_TOUCHDOWN_S ? v0 : Math.max(0, v0 - brakeAccel * brakingT)
    const xM = t < PRE_TOUCHDOWN_S ? -v0 * (PRE_TOUCHDOWN_S - t) : Math.min(summary.stopDistM, v0 * Math.min(post, CAL.rolloutDelayS) + v0 * brakingT - 0.5 * brakeAccel * brakingT ** 2)
    const stopped = post >= rolloutS || speedMps === 0
    const overrun = xM > scenario.landing.runwayM && !stopped
    const phase = framePhase(t, post, speedMps, stopped, overrun)
    const contactIds = contactSet(t, tires, first, Math.abs(scenario.attitude.rollDeg))
    const progress = stopped ? 1 : Math.max(0, Math.min(1, post / Math.max(rolloutS, 1)))

    frames.push({
      tS: +t.toFixed(3),
      phase,
      pose: {
        pitchDeg: scenario.attitude.pitchDeg * (1 - Math.min(1, post / 4)),
        rollDeg: scenario.attitude.rollDeg * (1 - Math.min(1, post / 3)),
        crabDeg: scenario.attitude.crabDeg * (1 - Math.min(1, post / 2)),
        xM,
        yM: t < PRE_TOUCHDOWN_S ? approachHeightM * ((PRE_TOUCHDOWN_S - t) / PRE_TOUCHDOWN_S) ** 1.15 : 0,
        zM: 0,
      },
      speedMps,
      sinkMps: t < PRE_TOUCHDOWN_S ? sink0 * (1 - t / PRE_TOUCHDOWN_S) : 0,
      liftShare: t < PRE_TOUCHDOWN_S ? 0.18 : Math.max(0, 0.18 * (1 - post / 2)),
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

function touchdownTires(tires: Tire[], attitude: Attitude) {
  const mains = tires.filter((t) => t.gear !== 'nose')
  if (Math.abs(attitude.rollDeg) < 0.5) return mains.map((t) => t.id)
  const gear = attitude.rollDeg > 0 ? 'right' : 'left'
  return mains.filter((t) => t.gear === gear).map((t) => t.id)
}

function contactSet(t: number, tires: Tire[], first: Set<string>, absRollDeg: number) {
  if (t < PRE_TOUCHDOWN_S) return new Set<string>()
  const mains = tires.filter((x) => x.gear !== 'nose').map((x) => x.id)
  if (absRollDeg >= 0.5 && t < PRE_TOUCHDOWN_S + SPINUP_S) return first
  return new Set(mains)
}

function framePhase(t: number, post: number, speedMps: number, stopped: boolean, overrun: boolean): LandingPhase {
  if (overrun) return 'overrun'
  if (stopped) return 'stopped'
  if (t < PRE_TOUCHDOWN_S * 0.55) return 'approach'
  if (t < PRE_TOUCHDOWN_S) return 'flare'
  if (post < 0.15) return 'touchdown'
  if (post < SPINUP_S) return 'spinup'
  if (post < CAL.rolloutDelayS) return 'spoilers'
  if (speedMps > 0) return 'braking'
  return 'rollout'
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
