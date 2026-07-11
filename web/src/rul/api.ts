// Typed client for the RUL service (POST /api/v1/rul/*). The types mirror app/domain/schemas.py
// one-for-one — if the pydantic contract moves, these move with it. JSON is snake_case on the wire
// and stays snake_case here: the payloads are small, flat, and read straight into the SVG marks, so a
// camelCase conversion layer would only add a place for the two shapes to drift apart.

import { useQuery, type UseQueryResult } from '@tanstack/react-query'

// Same-origin by default: dev goes through the Vite proxy (see vite.config.ts), prod through the
// static host's /api reverse-proxy. Point VITE_API_BASE at an absolute origin to bypass both.
const API_BASE = import.meta.env.VITE_API_BASE ?? ''

export type WheelPosition = 'nlg_l' | 'nlg_r' | 'mlg_l_inbd' | 'mlg_l_outbd' | 'mlg_r_inbd' | 'mlg_r_outbd'
export type RulStatusValue = 'healthy' | 'monitor' | 'schedule' | 'replace_now'
export type RulSeverity = 'info' | 'warning' | 'critical'

export type InspectionReading = {
  cycles_since_install: number
  measured_groove_mm: number
}

export type RulPredictionRequest = {
  position: WheelPosition
  current_cycles: number
  landings_per_day: number
  readings: InspectionReading[]
  as_of_date?: string // ISO YYYY-MM-DD
}

export type RulQuantiles = { p10: number; median: number; p90: number; mean: number }

export type WearToLimitDates = {
  earliest_credible_p10: string
  median: string
  p90: string
}

export type RulStatus = {
  status: RulStatusValue
  severity: RulSeverity
  headline: string
  recommended_action: string
}

export type RulPredictionResponse = {
  prediction_id: string
  position: WheelPosition
  rul_landings: RulQuantiles
  wear_to_limit_dates: WearToLimitDates
  p_cross_before_next_check: number
  landings_per_day: number
  readings_used: number
  low_confidence: boolean
  status: RulStatus
  wear_limit_mm: number
  model_version: string
  disclaimer: string
}

export type PriorityWheel = {
  rank: number
  tail_number: string
  position: WheelPosition
  station: string
  priority: number
  p_cross_before_next_check: number
  rul_median_landings: number
  rul_p10_landings: number
  earliest_credible_date: string
  low_confidence: boolean
  reason: string
  action: string
}

export type FleetWorklistResponse = {
  as_of_date: string
  wheels: PriorityWheel[]
  disclaimer: string
}

export type WheelStatusResponse = {
  tail_number: string
  position: WheelPosition
  status: RulStatusValue
  severity: RulSeverity
  headline: string
  explanation: string
  recommended_action: string
  rul_median_landings: number
  rul_p10_landings: number
  earliest_credible_date: string
  p_cross_before_next_check: number
  pressure_pct: number | null
  pressure_action: string
  station: string
  spares_on_hand: number
  utilization_landings_per_day: number
  low_confidence: boolean
  as_of_date: string
  disclaimer: string
}

/** Carries the backend's structured error so callers can branch on 503 (fleet offline) vs 404. */
export class ApiError extends Error {
  readonly status: number
  readonly code?: string
  constructor(message: string, status: number, code?: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: { 'Content-Type': 'application/json', ...init?.headers },
    })
  } catch {
    // Network/DNS/CORS failure never reaches the backend, so there is no structured body to read.
    throw new ApiError('Cannot reach the RUL service. Is the API running?', 0, 'NETWORK')
  }
  if (!res.ok) {
    // Every backend error is ErrorResponse: { error: { code, message, ... } }. Fall back to the raw
    // text if a proxy returned a non-JSON 5xx, so the user never sees "Request failed with status 500".
    const body = (await res.json().catch(() => null)) as { error?: { code?: string; message?: string } } | null
    throw new ApiError(body?.error?.message ?? `Request failed (${res.status}).`, res.status, body?.error?.code)
  }
  return res.json() as Promise<T>
}

export function predictRul(req: RulPredictionRequest): Promise<RulPredictionResponse> {
  return request<RulPredictionResponse>('/api/v1/rul/predict', { method: 'POST', body: JSON.stringify(req) })
}

export function fetchWorklist(opts: { topN?: number; station?: string } = {}): Promise<FleetWorklistResponse> {
  const q = new URLSearchParams({ top_n: String(opts.topN ?? 10) })
  if (opts.station) q.set('station', opts.station)
  return request<FleetWorklistResponse>(`/api/v1/rul/fleet/worklist?${q}`)
}

export function fetchWheelStatus(tail: string, position: WheelPosition): Promise<WheelStatusResponse> {
  const q = new URLSearchParams({ tail, position })
  return request<WheelStatusResponse>(`/api/v1/rul/wheel/status?${q}`)
}

// --- React Query hooks. Predictions and statuses are pure functions of their inputs, so they cache
// by input and a re-selected wheel is an instant cache hit rather than a refetch. ---

export function useRulPrediction(req: RulPredictionRequest | null): UseQueryResult<RulPredictionResponse, ApiError> {
  return useQuery({
    queryKey: ['rul-predict', req],
    queryFn: () => predictRul(req as RulPredictionRequest),
    enabled: req !== null,
    staleTime: 5 * 60_000,
    retry: false,
  })
}

export function useWorklist(topN: number, station: string | null): UseQueryResult<FleetWorklistResponse, ApiError> {
  return useQuery({
    queryKey: ['rul-worklist', topN, station],
    queryFn: () => fetchWorklist({ topN, station: station ?? undefined }),
    // A fleet-offline (503) or absent dataset will not fix itself on retry — surface it immediately.
    retry: (count, err) => err.status >= 500 && err.status !== 503 && count < 2,
    staleTime: 60_000,
  })
}

export function useWheelStatus(
  tail: string | null,
  position: WheelPosition | null,
): UseQueryResult<WheelStatusResponse, ApiError> {
  return useQuery({
    queryKey: ['rul-wheel', tail, position],
    queryFn: () => fetchWheelStatus(tail as string, position as WheelPosition),
    enabled: tail !== null && position !== null,
    retry: (count, err) => err.status >= 500 && err.status !== 503 && count < 2,
    staleTime: 60_000,
  })
}
