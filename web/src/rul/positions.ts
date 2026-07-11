// The join between the two wheel models. The 3D dashboard tracks 14 wheels (six-wheel main bogies);
// the RUL service fits one prior per *canonical* position — 2 nose + 4 main (inboard/outboard on each
// side). Every physical wheel collapses onto one of those six priors, so this file owns that mapping
// plus the status→colour vocabulary the RUL views paint with.

import { HUE } from '../charts'
import type { Tire } from '../data'
import type { RulPredictionRequest, RulSeverity, RulStatusValue, WheelPosition } from './api'

// Nose fresh tread is shallower than the mains; both sit well above the 2.0 mm service limit so the
// fitted wear line always slopes down to the current reading.
const FRESH_GROOVE_MM = { nose: 10.0, main: 12.0 }
export const DEFAULT_LANDINGS_PER_DAY = 3.5

export const CANON_POSITIONS: WheelPosition[] = [
  'nlg_l',
  'nlg_r',
  'mlg_l_outbd',
  'mlg_l_inbd',
  'mlg_r_inbd',
  'mlg_r_outbd',
]

export const POSITION_LABEL: Record<WheelPosition, string> = {
  nlg_l: 'Nose L',
  nlg_r: 'Nose R',
  mlg_l_outbd: 'Main L · Outboard',
  mlg_l_inbd: 'Main L · Inboard',
  mlg_r_inbd: 'Main R · Inboard',
  mlg_r_outbd: 'Main R · Outboard',
}

export const POSITION_SHORT: Record<WheelPosition, string> = {
  nlg_l: 'N·L',
  nlg_r: 'N·R',
  mlg_l_outbd: 'L·OUT',
  mlg_l_inbd: 'L·IN',
  mlg_r_inbd: 'R·IN',
  mlg_r_outbd: 'R·OUT',
}

// Top-down gear layout for the six canonical positions (viewBox 0 0 100 100). Nose pair up top,
// the two main bogies as inboard/outboard pairs left and right of the centreline.
export const POSITION_XY: Record<WheelPosition, [number, number]> = {
  nlg_l: [44, 12],
  nlg_r: [56, 12],
  mlg_l_outbd: [20, 66],
  mlg_l_inbd: [34, 66],
  mlg_r_inbd: [66, 66],
  mlg_r_outbd: [80, 66],
}

/** Collapse a physical dashboard wheel onto its canonical RUL position. */
export function toCanonicalPosition(tire: Pick<Tire, 'id' | 'gear' | 'role'>): WheelPosition {
  if (tire.gear === 'nose') return tire.id === 'N1' ? 'nlg_l' : 'nlg_r'
  const side = tire.gear === 'left' ? 'l' : 'r'
  const rib = tire.role === 'outer' ? 'outbd' : 'inbd'
  return `mlg_${side}_${rib}` as WheelPosition
}

// --- Status & severity vocabulary. The four RUL statuses drive the label/glyph; the three severities
// drive the colour so the map and the badges read on the same green→amber→red scale as the rest of
// the dashboard. HUE hexes are for SVG marks; the --ink vars are the WCAG-safe text variants. ---

export const RUL_STATUS_META: Record<RulStatusValue, { label: string; glyph: string }> = {
  healthy: { label: 'HEALTHY', glyph: '●' },
  monitor: { label: 'MONITOR', glyph: '◆' },
  schedule: { label: 'SCHEDULE', glyph: '◆' },
  replace_now: { label: 'REPLACE', glyph: '▲' },
}

export function severityHue(severity: RulSeverity): string {
  return severity === 'critical' ? HUE.crit : severity === 'warning' ? HUE.warn : HUE.ok
}

export function severityInk(severity: RulSeverity): string {
  return severity === 'critical' ? 'var(--crit)' : severity === 'warning' ? 'var(--warn)' : 'var(--ok)'
}

/** Build a /predict request from a dashboard tire: synthesize a fresh→current wear line from its
 *  current grooves so the model has readings to fit rather than falling back to the bare prior. */
export function buildPredictionRequest(tire: Tire, landingsPerDay = DEFAULT_LANDINGS_PER_DAY): RulPredictionRequest {
  const fresh = tire.gear === 'nose' ? FRESH_GROOVE_MM.nose : FRESH_GROOVE_MM.main
  const current = Math.min(...tire.grooves)
  // measured_groove_mm must be > 0 and strictly below fresh for a declining line.
  const currentGroove = Math.min(fresh - 0.5, Math.max(0.3, current))
  const cycles = Math.max(1, Math.round(tire.cycles))
  const mid = +(fresh + (currentGroove - fresh) * 0.5).toFixed(2)
  return {
    position: toCanonicalPosition(tire),
    current_cycles: cycles,
    landings_per_day: landingsPerDay,
    readings: [
      { cycles_since_install: 0, measured_groove_mm: fresh },
      { cycles_since_install: Math.round(cycles / 2), measured_groove_mm: mid },
      { cycles_since_install: cycles, measured_groove_mm: +currentGroove.toFixed(2) },
    ],
  }
}

// --- Small formatters shared by the RUL views. ---

export function fmtLandings(n: number): string {
  return Math.round(n).toLocaleString()
}

/** "12 Aug" style — short, unambiguous, locale-aware. Input is an ISO YYYY-MM-DD from the API. */
export function fmtDate(iso: string): string {
  const d = new Date(`${iso}T00:00:00Z`)
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleDateString(undefined, { day: '2-digit', month: 'short', timeZone: 'UTC' })
}

export function fmtPct(fraction: number): string {
  return `${Math.round(fraction * 100)}%`
}
