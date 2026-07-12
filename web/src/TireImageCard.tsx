import { useEffect, useRef, useState } from 'react'
import { Card, Open, STATUS } from './ui'
import { assessTireImage, type TireImageAssessmentResponse } from './uploadApi'

// Upload a photo of the selected wheel, screen it with the backend vision model, and show the
// verdict. Identity is generic (`id` is the cache key + wire tire_id, `aircraftId` the tail/reg,
// `label` the human name) so both the Tyres gear map and the RUL worklist can reuse it. Committed
// results are cached per id so switching wheels keeps each one's last assessment; the in-progress
// file selection is scoped to the current id and resets on nav. Informational only — it does not
// mutate the wheel's telemetry-derived status.

const MAX_BYTES = 4 * 1024 * 1024 // matches the backend / AWS direct-upload cap
const BACKEND_LABEL: Record<string, string> = {
  mock: 'offline heuristic',
  openai: 'OpenAI vision',
  claude: 'Claude vision',
  bedrock: 'Claude · Bedrock',
}

export default function TireImageCard({ id, aircraftId, label }: { id: string; aircraftId: string; label: string }) {
  const [results, setResults] = useState<Record<string, TireImageAssessmentResponse>>({})
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [file, setFile] = useState<File | null>(null)
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [dragging, setDragging] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const previewRef = useRef<string | null>(null)
  // Always the currently-selected wheel, so an upload that resolves after the operator has moved on
  // touches its own wheel's cache only — never the new wheel's live selection.
  const idRef = useRef(id)
  idRef.current = id

  function setPreview(url: string | null) {
    if (previewRef.current) URL.revokeObjectURL(previewRef.current)
    previewRef.current = url
    setPreviewUrl(url)
  }

  // Reset the in-progress selection when the operator switches wheels (results stay cached).
  useEffect(() => {
    setFile(null)
    setBusy(false)
    setDragging(false)
    setPreview(null)
    if (inputRef.current) inputRef.current.value = ''
  }, [id])

  // Release the last object URL on unmount.
  useEffect(() => () => setPreview(null), [])

  const result = results[id]
  const error = errors[id]

  function pick(f: File | null | undefined) {
    if (!f) return
    if (!f.type.startsWith('image/')) {
      setErrors((e) => ({ ...e, [id]: 'Choose an image file (JPEG or PNG).' }))
      return
    }
    if (f.size > MAX_BYTES) {
      setErrors((e) => ({ ...e, [id]: 'Image exceeds the 4 MB limit — use a smaller photo.' }))
      return
    }
    setErrors((e) => dropKey(e, id))
    setFile(f)
    setPreview(URL.createObjectURL(f))
  }

  async function submit() {
    if (!file || busy) return
    const reqId = id // the wheel this upload belongs to, captured before any await
    setBusy(true)
    setErrors((e) => dropKey(e, reqId))
    try {
      const resp = await assessTireImage(file, { tireId: reqId, aircraftId })
      setResults((r) => ({ ...r, [reqId]: resp }))
      // Only clear the live picker if the operator is still on this wheel; otherwise leave the
      // wheel they've since switched to untouched.
      if (idRef.current === reqId) {
        setFile(null)
        setPreview(null)
        if (inputRef.current) inputRef.current.value = ''
      }
    } catch (err) {
      setErrors((e) => ({ ...e, [reqId]: (err as Error).message }))
    } finally {
      if (idRef.current === reqId) setBusy(false)
    }
  }

  function reset() {
    setFile(null)
    setPreview(null)
    setResults((r) => dropKey(r, id))
    setErrors((e) => dropKey(e, id))
    if (inputRef.current) inputRef.current.value = ''
  }

  return (
    <Card title="Tire photo · AI screen" tag="vision model">
      <input
        ref={inputRef}
        type="file"
        accept="image/*"
        className="hidden"
        onChange={(e) => pick(e.target.files?.[0])}
      />

      {busy ? (
        <Busy previewUrl={previewUrl} label={label} />
      ) : result ? (
        <ResultView result={result} onReplace={() => inputRef.current?.click()} onClear={reset} />
      ) : (
        <Picker
          label={label}
          file={file}
          previewUrl={previewUrl}
          dragging={dragging}
          onBrowse={() => inputRef.current?.click()}
          onDropFile={pick}
          setDragging={setDragging}
          onSubmit={submit}
          onClear={() => {
            setFile(null)
            setPreview(null)
            if (inputRef.current) inputRef.current.value = ''
          }}
        />
      )}

      {error && (
        <p className="mt-2 border border-[var(--crit)] bg-[var(--panel)] px-2 py-1.5 text-[11px]" style={{ color: 'var(--crit)' }}>
          ⚠ {error}
        </p>
      )}

      <Open>A photo screen catches acute damage a scan geometry misses — but it augments, never replaces, the mandated inspection</Open>
    </Card>
  )
}

function Picker({
  label,
  file,
  previewUrl,
  dragging,
  onBrowse,
  onDropFile,
  setDragging,
  onSubmit,
  onClear,
}: {
  label: string
  file: File | null
  previewUrl: string | null
  dragging: boolean
  onBrowse: () => void
  onDropFile: (f: File | undefined) => void
  setDragging: (v: boolean) => void
  onSubmit: () => void
  onClear: () => void
}) {
  if (file && previewUrl) {
    return (
      <div className="flex flex-col gap-2">
        <div className="flex items-center gap-3 border border-[var(--line)] bg-[var(--panel)] p-2">
          <img src={previewUrl} alt="selected tire" className="h-16 w-16 shrink-0 object-cover" />
          <div className="min-w-0">
            <div className="truncate text-xs text-[var(--ink-2)]">{file.name}</div>
            <div className="text-[10px] uppercase tracking-widest text-[var(--ink-4)]">
              {(file.size / 1024).toFixed(0)} KB · {label}
            </div>
          </div>
        </div>
        <div className="flex gap-2">
          <button
            onClick={onSubmit}
            className="flex-1 border border-[var(--primary-dim)] bg-[var(--primary-soft)] px-3 py-2 text-xs uppercase tracking-widest text-[var(--primary)] transition-opacity"
          >
            Upload &amp; assess
          </button>
          <button
            onClick={onClear}
            className="border border-[var(--line-2)] px-3 py-2 text-[10px] uppercase tracking-widest text-[var(--ink-4)] transition-colors hover:text-[var(--ink-2)]"
          >
            Clear
          </button>
        </div>
      </div>
    )
  }

  return (
    <button
      onClick={onBrowse}
      onDragOver={(e) => {
        e.preventDefault()
        setDragging(true)
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => {
        e.preventDefault()
        setDragging(false)
        onDropFile(e.dataTransfer.files?.[0])
      }}
      className="flex min-h-[96px] w-full flex-col items-center justify-center gap-1 border border-dashed px-3 py-5 text-center transition-colors"
      style={{ borderColor: dragging ? 'var(--primary)' : 'var(--line-2)', background: dragging ? 'var(--primary-soft)' : 'transparent' }}
    >
      <span className="text-lg leading-none text-[var(--ink-4)]">⊕</span>
      <span className="text-xs text-[var(--ink-3)]">Drop a photo of {label}, or click to browse</span>
      <span className="text-[10px] uppercase tracking-widest text-[var(--ink-4)]">JPEG / PNG · ≤ 4 MB</span>
    </button>
  )
}

function Busy({ previewUrl, label }: { previewUrl: string | null; label: string }) {
  return (
    <div className="flex items-center gap-3 border border-[var(--line)] bg-[var(--panel)] p-2">
      {previewUrl && <img src={previewUrl} alt="uploading tire" className="h-16 w-16 shrink-0 object-cover opacity-70" />}
      <div className="flex items-center gap-2 text-xs text-[var(--ink-3)]">
        <span className="inline-flex gap-1">
          <Dot delay="0ms" />
          <Dot delay="160ms" />
          <Dot delay="320ms" />
        </span>
        Uploading {label} &amp; running the vision model…
      </div>
    </div>
  )
}

function ResultView({
  result,
  onReplace,
  onClear,
}: {
  result: TireImageAssessmentResponse
  onReplace: () => void
  onClear: () => void
}) {
  const a = result.assessment
  const s = STATUS[a.status]
  const url = result.upload?.url ?? null
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between gap-2">
        <span className="flex items-center gap-1.5 border px-2 py-1 text-[10px] uppercase tracking-widest" style={{ borderColor: s.ink, color: s.ink }}>
          {s.glyph} {s.text}
        </span>
        <span className="text-[9px] uppercase tracking-widest text-[var(--ink-4)]">
          LLM · {BACKEND_LABEL[a.backend] ?? a.backend}
          {a.degraded && ' · fallback'}
        </span>
      </div>

      <div className="flex gap-3">
        {url && (
          <a href={url} target="_blank" rel="noreferrer" className="shrink-0" title="View stored photo">
            <img src={url} alt="assessed tire" className="h-20 w-20 object-cover border border-[var(--line)]" />
          </a>
        )}
        <div className="min-w-0">
          <div className="text-xs" style={{ color: s.ink }}>{a.headline}</div>
          <p className="mt-1 text-[11px] leading-relaxed text-[var(--ink-3)]">{a.summary}</p>
        </div>
      </div>

      {a.findings.length > 0 && (
        <ul className="flex flex-col gap-1">
          {a.findings.map((f) => (
            <li key={f.kind} className="flex items-start gap-2 border border-[var(--line)] bg-[var(--panel)] p-2">
              <span className="mt-0.5 text-xs" style={{ color: f.severity === 'high' ? 'var(--crit)' : 'var(--warn)' }}>⚠</span>
              <div className="min-w-0">
                <div className="text-[10px] uppercase tracking-widest" style={{ color: f.severity === 'high' ? 'var(--crit)' : 'var(--warn)' }}>
                  {f.kind} · {f.severity}
                </div>
                <div className="text-[11px] leading-snug text-[var(--ink-2)]">{f.detail}</div>
              </div>
            </li>
          ))}
        </ul>
      )}

      <div className="mt-1 flex items-center gap-3">
        <button
          onClick={onReplace}
          className="border border-[var(--line-2)] px-3 py-1.5 text-[10px] uppercase tracking-widest text-[var(--ink-3)] transition-colors hover:border-[var(--primary)] hover:text-[var(--primary)]"
        >
          Replace photo
        </button>
        <button
          onClick={onClear}
          className="text-[10px] uppercase tracking-widest text-[var(--ink-4)] underline-offset-2 hover:text-[var(--ink-2)] hover:underline"
        >
          Clear
        </button>
      </div>
    </div>
  )
}

function Dot({ delay }: { delay: string }) {
  return <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-[var(--primary)]" style={{ animationDelay: delay }} />
}

function dropKey<T>(obj: Record<string, T>, key: string): Record<string, T> {
  if (!(key in obj)) return obj
  const next = { ...obj }
  delete next[key]
  return next
}
