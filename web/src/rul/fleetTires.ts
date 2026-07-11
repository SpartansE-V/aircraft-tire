/** Map fleet parquet tires into the /tyres dashboard Tire shape. */

import type { Defect, Tire, TireModelTypeId, TreadDepthBand } from '../data'
import { POSITION_LABEL } from './positions'
import type { FleetTireItem, FleetTiresResponse, WheelPosition } from './api'

const POS_META: Record<
  WheelPosition,
  { id: string; gear: Tire['gear']; role: Tire['role'] }
> = {
  nlg_l: { id: 'N1', gear: 'nose', role: 'nose' },
  nlg_r: { id: 'N2', gear: 'nose', role: 'nose' },
  mlg_l_outbd: { id: 'L1', gear: 'left', role: 'outer' },
  mlg_l_inbd: { id: 'L2', gear: 'left', role: 'inner' },
  mlg_r_inbd: { id: 'R1', gear: 'right', role: 'inner' },
  mlg_r_outbd: { id: 'R2', gear: 'right', role: 'outer' },
}

const BAND_MM: Record<TreadDepthBand, number> = {
  '1-2mm': 1.5,
  '2-3mm': 2.5,
  '3-4mm': 3.5,
  '4-5mm': 4.5,
  '5-6mm': 5.5,
}

function toDefects(item: FleetTireItem): Defect[] {
  // Healthy tires must not highlight; API already sends [] but guard anyway.
  if (item.scan_status === 'healthy') return []
  return item.defects.map((d) => ({
    kind: d.kind,
    label: d.label,
    severity: d.severity,
    zone: d.zone,
    at: [d.at[0], d.at[1], d.at[2]] as [number, number, number],
    r: d.r,
    wave: d.wave ?? d.category === 'crack',
    angle_rad: d.angle_rad ?? undefined,
    lateral_pct: d.lateral_pct ?? undefined,
    source: d.source ?? undefined,
  }))
}

/** Build dashboard tires from one aircraft's current mounted tires. */
export function fleetTiresToDashboard(fleet: FleetTiresResponse): Tire[] {
  return fleet.tires.map((item) => {
    const meta = POS_META[item.position]
    const treadDepths = item.tread_depths as TreadDepthBand[]
    const grooves = treadDepths.map((b) => BAND_MM[b])
    const psiTarget = item.gear === 'nose' ? 185 : 215
    const pressurePct = item.pressure_pct ?? 100
    const psi = +(psiTarget * (pressurePct / 100)).toFixed(1)
    return {
      id: meta.id,
      label: POSITION_LABEL[item.position],
      gear: meta.gear,
      role: meta.role,
      serial: item.serial,
      ocrConfidence: 0.92,
      retreads: item.retread_level,
      partNo: item.brand.slice(0, 3).toUpperCase(),
      size: item.tire_size,
      modelType: item.model_type as TireModelTypeId,
      scanStatus: item.scan_status,
      scanGroup: item.scan_group,
      scanSide: item.scan_side,
      treadDepths,
      images: item.images,
      psi,
      psiTarget,
      psiTrend: Array.from({ length: 14 }, (_, d) =>
        +(psiTarget * (pressurePct / 100) * (1 - 0.002 * (13 - d))).toFixed(1),
      ),
      leakPctPerDay: 0.25,
      acarsOk: true,
      acarsLast: '00:12',
      grooves,
      grooveLimit: item.wear_limit_mm,
      scanErrorMm: 0.12,
      calibratedDaysAgo: 3,
      defects: toDefects(item),
      landings: Array.from({ length: 10 }, (_, k) => ({
        flt: `${fleet.tail_number.replace('-', '')}${k + 1}`,
        rwy: fleet.home_station,
        sinkFpm: 180 + k * 12,
        peakG: +(1.2 + k * 0.03).toFixed(2),
        brakePsi: 1100 + k * 40,
      })),
      taxiKm: 4.2,
      taxiAvgKt: 14,
      lateralG: meta.role === 'outer' ? 0.32 : 0.18,
      steerPeakDeg: 36,
      payloadT: 58,
      oatC: 28,
      crosswindKt: 8,
      slipAngleRisk: 0.22,
      metar: `${fleet.home_station} 111756Z 29012KT 10SM FEW020 28/18 A2990`,
      cycles: item.time_to_event_cycles,
      flightHrs: Math.round(item.time_to_event_cycles * 1.8),
      taxiHrs: +(item.time_to_event_cycles * 0.12).toFixed(1),
      parkedHrs: 220,
      joinKey: 'linked',
      events: [],
      runways: [{ icao: fleet.home_station, code: 5, surface: 'Grooved asphalt', texture: 0.95 }],
    } satisfies Tire
  })
}

export function positionCodeOf(tire: Tire): WheelPosition | null {
  const entry = Object.entries(POS_META).find(([, v]) => v.id === tire.id)
  return (entry?.[0] as WheelPosition | undefined) ?? null
}
