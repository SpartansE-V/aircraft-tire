// Typed client for the tire-photo assessment endpoint (app/api/routes/tire_image.py).
//
// The browser posts the photo to our own /api origin (Vite proxy in dev, the static host's /api
// reverse-proxy in prod). The backend does the cross-origin S3 upload the browser can't — the AWS
// upload service sends no CORS headers, so a direct browser fetch would upload but never read the
// {imageId, key, presignedUrl} response. Wire shape stays snake_case, matching agentApi.ts.

import { ApiError } from './agentApi'

export type TireImageStatus = 'ok' | 'watch' | 'action'
export type VlmBackend = 'mock' | 'openai' | 'claude' | 'bedrock'
export type FindingKind = 'cut' | 'bulge' | 'fod'

export type TireImageFinding = {
  kind: FindingKind
  severity: 'low' | 'med' | 'high'
  detail: string
}

export type TireImageUpload = {
  image_id?: string | null
  key: string
  url?: string | null
  etag?: string | null
}

export type TireImageAssessment = {
  backend: VlmBackend
  degraded: boolean
  status: TireImageStatus
  headline: string
  summary: string
  findings: TireImageFinding[]
}

export type TireImageAssessmentResponse = {
  tire_id?: string | null
  aircraft_id?: string | null
  upload?: TireImageUpload | null
  assessment: TireImageAssessment
  assessed_at: string
  disclaimer: string
}

export { ApiError }

const ENV = import.meta.env as unknown as Record<string, string | undefined>
const API_BASE = (ENV.VITE_API_BASE ?? '').replace(/\/$/, '')

type Errorish = { error?: { message?: string }; detail?: unknown }

async function readError(res: Response): Promise<string> {
  try {
    const body = (await res.json()) as Errorish
    // Custom handlers (422 validation, gate errors) emit a top-level { error: { message } }.
    if (body.error?.message) return body.error.message
    const detail = body.detail
    // This endpoint's own 400/503 raise a plain HTTPException, which FastAPI's default handler
    // wraps as { detail: { error: { code, message } } } — the message is one level deeper.
    if (detail && typeof detail === 'object' && !Array.isArray(detail)) {
      const nested = (detail as { error?: { message?: string } }).error?.message
      if (nested) return nested
    }
    if (Array.isArray(detail)) {
      return detail.map((d) => (d as { msg?: string }).msg ?? String(d)).join('; ')
    }
    if (typeof detail === 'string') return detail
  } catch {
    // fall through to the status-only message
  }
  return `Upload failed (${res.status})`
}

export type AssessOptions = {
  tireId?: string
  aircraftId?: string
  backend?: string
}

export async function assessTireImage(file: File, opts: AssessOptions = {}): Promise<TireImageAssessmentResponse> {
  const form = new FormData()
  form.append('image', file)
  if (opts.tireId) form.append('tire_id', opts.tireId)
  if (opts.aircraftId) form.append('aircraft_id', opts.aircraftId)
  if (opts.backend) form.append('backend', opts.backend)

  // No explicit Content-Type: the browser sets multipart/form-data with the boundary. That also
  // keeps this a CORS "simple request" shape, though here we go same-origin through the proxy.
  const res = await fetch(`${API_BASE}/api/v1/tire-image/assess`, { method: 'POST', body: form })
  if (!res.ok) throw new ApiError(await readError(res), res.status)
  return (await res.json()) as TireImageAssessmentResponse
}
