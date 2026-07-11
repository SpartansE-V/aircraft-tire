// Mock telemetry. Every field here maps to a real feed (TPMS / FOQA / FDR / ACARS /
// MRO / scanner). Swap the generator for the real joins; the UI reads only this shape.
// ponytail: seeded LCG instead of a fixture file — data stays stable across renders,
// and one line changes per-wheel behaviour.

import type { AnnotatedScanImageData } from './AnnotatedScanImage'

export type Status = 'ok' | 'watch' | 'action'

/** Scan condition from linked mock-tyre annotations (crack / tread-shallow). */
export type ScanStatus = 'healthy' | 'warning' | 'error'

export type TireModelTypeId = 'radial' | 'type_vii' | 'type_iii'

export type Tire = {
  id: string
  label: string
  gear: 'nose' | 'left' | 'right'
  role: 'inner' | 'outer' | 'nose' // drives turn-load attribution
  // Identity — OCR off the molded sidewall
  serial: string
  ocrConfidence: number
  retreads: number
  partNo: string
  size: string
  // Scan pack (from tires.parquet + mock-tyres metadata)
  modelType: TireModelTypeId
  scanStatus: ScanStatus
  scanGroup?: string
  scanSide?: 'left' | 'right'
  treadDepths?: TreadDepthBand[]
  images?: {
    circle: AnnotatedScanImageData
    flatten: AnnotatedScanImageData
    frames: AnnotatedScanImageData[]
  }
  // TPMS
  psi: number
  psiTarget: number
  psiTrend: number[] // 14 days, one sample per layover downlink
  leakPctPerDay: number
  acarsOk: boolean
  acarsLast: string
  // Imaging
  grooves: number[] // mm remaining, 4 circumferential grooves
  grooveLimit: number
  scanErrorMm: number
  calibratedDaysAgo: number
  defects: Defect[]
  // FOQA — per-landing summary rolled up from the high-rate stream
  landings: Landing[]
  // FDR/ADS-B taxi
  taxiKm: number
  taxiAvgKt: number
  lateralG: number // at this wheel position
  steerPeakDeg: number
  // ACARS/METAR
  payloadT: number
  oatC: number
  crosswindKt: number
  slipAngleRisk: number // 0..1
  metar: string
  // OOOI / MRO
  cycles: number
  flightHrs: number
  taxiHrs: number
  parkedHrs: number
  joinKey: 'linked' | 'inferred' // serial ↔ flight-log join confidence
  events: { kind: string; date: string; note: string }[]
  runways: { icao: string; code: number; surface: string; texture: number }[]
}

export type Defect = {
  kind: 'wear' | 'damage' // different logistics response: monitor vs remove
  label: string
  severity: 'low' | 'med' | 'high'
  zone: string
  at: [number, number, number] // tire-local coords, for the 3D overlay
  r: number
  wave?: boolean // pulse highlight for cracks
  angle_rad?: number
  lateral_pct?: number
  source?: string
}

export type TreadDepthBand = '1-2mm' | '2-3mm' | '3-4mm' | '4-5mm' | '5-6mm'

export type Landing = {
  flt: string
  rwy: string
  sinkFpm: number
  peakG: number
  brakePsi: number
}

const lcg = (seed: number) => () => ((seed = (seed * 1103515245 + 12345) & 0x7fffffff) / 0x7fffffff)

// A 777-300ER carries six-wheel main bogies: 12 mains + 2 nose. These ids and their order are the
// join to the 3D model — Aircraft.tsx assigns them to the airframe's wheels by position (fwd->aft,
// outer->inner), so an id here that has no wheel there, or vice versa, is a bug.
const POSITIONS: [string, string, Tire['gear'], Tire['role']][] = [
  ['N1', 'Nose L', 'nose', 'nose'],
  ['N2', 'Nose R', 'nose', 'nose'],
  ['L1', 'Main L Fwd-Out', 'left', 'outer'],
  ['L2', 'Main L Fwd-In', 'left', 'inner'],
  ['L3', 'Main L Mid-Out', 'left', 'outer'],
  ['L4', 'Main L Mid-In', 'left', 'inner'],
  ['L5', 'Main L Aft-Out', 'left', 'outer'],
  ['L6', 'Main L Aft-In', 'left', 'inner'],
  ['R1', 'Main R Fwd-In', 'right', 'inner'],
  ['R2', 'Main R Fwd-Out', 'right', 'outer'],
  ['R3', 'Main R Mid-In', 'right', 'inner'],
  ['R4', 'Main R Mid-Out', 'right', 'outer'],
  ['R5', 'Main R Aft-In', 'right', 'inner'],
  ['R6', 'Main R Aft-Out', 'right', 'outer'],
]

const AIRPORTS = [
  { icao: 'KSFO', code: 5, surface: 'Grooved asphalt', texture: 0.92 },
  { icao: 'KDEN', code: 5, surface: 'PCC grooved', texture: 1.04 },
  { icao: 'PANC', code: 3, surface: 'PFC overlay', texture: 0.81 },
  { icao: 'RJAA', code: 5, surface: 'PCC grooved', texture: 1.11 },
  { icao: 'KJFK', code: 4, surface: 'Grooved asphalt', texture: 0.88 },
  { icao: 'EGLL', code: 5, surface: 'PFC overlay', texture: 0.97 },
]

function makeTire(i: number, [id, label, gear, role]: (typeof POSITIONS)[number]): Tire {
  const r = lcg(i * 7919 + 13)
  const nose = gear === 'nose'
  const psiTarget = nose ? 185 : 215
  const leak = 0.18 + r() * 0.9
  const psi = psiTarget * (1 - (0.005 + r() * 0.035))
  const psiTrend = Array.from({ length: 14 }, (_, d) => +(psiTarget * (1 - leak / 100 * (13 - d)) - r() * 1.5).toFixed(1))

  const grooveLimit = 2.4
  const wear = 0.35 + r() * 0.55 + (role === 'outer' ? 0.12 : 0) // outers scrub harder in turns
  const grooves = Array.from({ length: 4 }, (_, g) => +(9.5 * (1 - wear) + (g === 0 || g === 3 ? -0.5 : 0.3) * r()).toFixed(2))

  const defects: Defect[] = []
  if (Math.min(...grooves) < grooveLimit + 1.2)
    defects.push({ kind: 'wear', label: 'Shoulder wear past 80% of allowance', severity: 'med', zone: 'Tread · outboard shoulder', at: [0.71, 0, 0.71], r: 0.45 })
  if (r() > 0.55)
    defects.push({ kind: 'damage', label: 'FOD cut, 14 mm, groove base', severity: r() > 0.6 ? 'high' : 'med', zone: 'Tread · groove 2', at: [-0.35, 0.15, 0.85], r: 0.3 })
  if (r() > 0.78)
    defects.push({ kind: 'damage', label: 'Sidewall bulge — carcass suspect', severity: 'high', zone: 'Sidewall · inboard', at: [-0.7, 0.36, 0.3], r: 0.3 })

  const landings: Landing[] = Array.from({ length: 10 }, (_, k) => ({
    flt: `AC${400 + i * 3 + k}`,
    rwy: AIRPORTS[(i + k) % AIRPORTS.length].icao,
    sinkFpm: Math.round(120 + r() * 480),
    peakG: +(1.15 + r() * 0.75).toFixed(2),
    brakePsi: Math.round(900 + r() * 1900),
  }))

  const events = [
    r() > 0.7 && { kind: 'RTO', date: '2026-06-14', note: 'Rejected takeoff @ 118 kt, KDEN 16R — thermal event' },
    r() > 0.55 && { kind: 'TRAINING', date: '2026-06-28', note: '6 touch-and-go cycles, KSFO — high cycle density' },
    r() > 0.85 && { kind: 'HARD LDG', date: '2026-07-02', note: '2.14 G, sink 612 fpm — inspection raised' },
  ].filter(Boolean) as Tire['events']

  return {
    id, label, gear, role,
    serial: `${['DL', 'MH', 'BR'][i % 3]}${String(72190 + i * 431)}`,
    ocrConfidence: +(0.71 + r() * 0.28).toFixed(2),
    retreads: Math.floor(r() * 4),
    partNo: nose ? 'APR-1830' : 'APR-2036',
    size: nose ? '40 × 14 R16' : '46 × 16 R20',
    modelType: 'radial',
    scanStatus: defects.some((d) => d.severity === 'high') ? 'error' : defects.length ? 'warning' : 'healthy',
    psi: +psi.toFixed(1),
    psiTarget,
    psiTrend,
    leakPctPerDay: +leak.toFixed(2),
    acarsOk: r() > 0.25,
    acarsLast: ['00:12', '04:38', '19:51', '2 d'][i % 4],
    grooves,
    grooveLimit,
    scanErrorMm: +(0.08 + r() * 0.22).toFixed(2),
    calibratedDaysAgo: Math.floor(r() * 60),
    defects,
    landings,
    taxiKm: +(3.2 + r() * 9).toFixed(1),
    taxiAvgKt: Math.round(11 + r() * 12),
    lateralG: +((role === 'outer' ? 0.28 : role === 'inner' ? 0.17 : 0.12) + r() * 0.12).toFixed(2),
    steerPeakDeg: Math.round(28 + r() * 42),
    payloadT: +(28 + r() * 22).toFixed(1),
    oatC: Math.round(-8 + r() * 44),
    crosswindKt: Math.round(r() * 27),
    slipAngleRisk: +r().toFixed(2),
    metar: 'KSFO 111756Z 29018G26KT 10SM FEW015 31/12 A2992',
    cycles: 180 + Math.floor(r() * 210),
    flightHrs: +(430 + r() * 380).toFixed(0),
    taxiHrs: +(38 + r() * 44).toFixed(1),
    parkedHrs: +(190 + r() * 300).toFixed(0),
    joinKey: r() > 0.3 ? 'linked' : 'inferred',
    events,
    runways: AIRPORTS.slice(0, 4).map((a) => ({ ...a })),
  }
}

export const FLEET_TIRES: Tire[] = POSITIONS.map((p, i) => makeTire(i, p))

export function statusOf(t: Tire): Status {
  if (t.scanStatus === 'error') return 'action'
  if (t.scanStatus === 'warning') return 'watch'
  const psiDev = Math.abs(t.psi - t.psiTarget) / t.psiTarget
  if (t.defects.some((d) => d.severity === 'high') || psiDev > 0.05 || Math.min(...t.grooves) < t.grooveLimit) return 'action'
  if (psiDev > 0.03 || Math.min(...t.grooves) < t.grooveLimit + 1.5 || t.defects.length > 0 || !t.acarsOk) return 'watch'
  return 'ok'
}

export function tireTypeById(id: TireModelTypeId) {
  return TIRE_TYPES.find((t) => t.id === id) ?? TIRE_TYPES[0]
}

export const AIRCRAFT = { reg: 'N774AC', type: 'B777-300ER', gate: 'A12', phase: 'TURNAROUND' }

// Bridgestone aircraft-tire constructions (bridgestone.com/products/aircraft/products/basicstructure).
// beadR/halfW are the modelled section proportions (OD = 1.0) — the viewer scales its rim to them.
export const TIRE_TYPES = [
  {
    id: 'radial',
    name: 'Radial',
    model: '/radial.glb',
    beadR: 0.48,
    halfW: 0.41,
    fits: 'Modern airliners',
    planes: '777 · 787 · A350 · 737 MAX · A320neo',
    note: 'Lightweight casing, high overload, low heat build-up. 6 grooves / 7 ribs.',
    fitted: true, // what this fleet flies
  },
  {
    id: 'type_vii',
    name: 'Type VII',
    model: '/type_vii.glb',
    beadR: 0.55,
    halfW: 0.29,
    fits: 'Bias jets & turboprops',
    planes: 'ATR · Dash 8 · Learjet · 737 Classic · military',
    note: 'Narrow high-pressure section, high load capacity. Center Rib: 4 grooves / 5 ribs.',
    fitted: false,
  },
  {
    id: 'type_iii',
    name: 'Type III',
    model: '/type_iii.glb',
    beadR: 0.38,
    halfW: 0.37,
    fits: 'Light general aviation',
    planes: 'C172 · Cherokee · Bonanza',
    note: 'Wide section on a small bead — low pressure, soft-field cushioning. Center Rib: 4 grooves / 5 ribs.',
    fitted: false,
  },
] as const

export type TireType = (typeof TIRE_TYPES)[number]
