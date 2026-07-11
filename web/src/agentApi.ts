// Typed client for the maintenance-agent endpoints (app/api/routes/rul.py).
//
// We mirror the API's snake_case wire shape verbatim: this app has no case-conversion
// interceptor, and keeping the exact JSON keys avoids a translation layer that could drift
// from the Pydantic schemas in app/domain/schemas.py.

export type AgentRole = 'user' | 'assistant'
export type AgentBackend = 'auto' | 'openai' | 'bedrock' | 'mock'
export type WheelPosition = 'nlg_l' | 'nlg_r' | 'mlg_l_inbd' | 'mlg_l_outbd' | 'mlg_r_inbd' | 'mlg_r_outbd'

export type ChatMessage = { role: AgentRole; content: string }

export type AgentToolCall = {
  tool: string
  args: Record<string, unknown>
  result: Record<string, unknown>
}

export type AgentChatResponse = {
  chat_id: string
  answer: string
  trace: AgentToolCall[]
  backend: string
  as_of_date: string
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

// Empty base in dev — Vite proxies `/api` to the backend (see vite.config.ts). Set
// VITE_API_BASE at build time to aim a static prod bundle at the API origin.
const ENV = import.meta.env as unknown as Record<string, string | undefined>
const API_BASE = (ENV.VITE_API_BASE ?? '').replace(/\/$/, '')

export class ApiError extends Error {
  status: number
  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

type Errorish = { error?: { message?: string }; detail?: unknown }

// Surface the backend's human-readable message, never the bare "HTTP 500". Custom handlers
// return { error: { message } }; FastAPI validation returns { detail: [...] }.
async function readError(res: Response): Promise<string> {
  try {
    const body = (await res.json()) as Errorish
    if (body.error?.message) return body.error.message
    if (Array.isArray(body.detail)) {
      return body.detail.map((d) => (d as { msg?: string }).msg ?? String(d)).join('; ')
    }
    if (typeof body.detail === 'string') return body.detail
  } catch {
    // fall through to the status-only message
  }
  return `Request failed (${res.status})`
}

export async function postAgentChat(messages: ChatMessage[], backend: AgentBackend): Promise<AgentChatResponse> {
  const res = await fetch(`${API_BASE}/api/v1/tire_rul/agent/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ messages, backend }),
  })
  if (!res.ok) throw new ApiError(await readError(res), res.status)
  return (await res.json()) as AgentChatResponse
}

export async function getFleetWorklist(topN = 8, station?: string): Promise<FleetWorklistResponse> {
  const qs = new URLSearchParams({ top_n: String(topN) })
  if (station) qs.set('station', station)
  const res = await fetch(`${API_BASE}/api/v1/tire_rul/fleet/worklist?${qs.toString()}`)
  if (!res.ok) throw new ApiError(await readError(res), res.status)
  return (await res.json()) as FleetWorklistResponse
}
