import { useEffect, useMemo, useRef, useState } from 'react'
import TireViewer from './TireViewer'
import AnnotatedScanImage from './AnnotatedScanImage'
import { statusOf, tireTypeById, type ScanStatus, type Status, type Tire } from './data'
import {
  DefectsCard, EventsCard, IdentityCard, PressureCard, RunwayCard, TaxiCard, TouchdownCard, TreadCard, UtilizationCard, WeatherCard,
} from './TireCards'
import { Card, Field, Header, Kpi, Open, STATUS, useTheme } from './ui'
import RemainingLifeCard from './rul/RemainingLifeCard'
import {
  ApiError,
  analyzeCircle,
  useFleetAircraft,
  useFleetTires,
  type CircleAnalysisResponse,
  type WheelPosition,
} from './rul/api'
import { fleetTiresToDashboard } from './rul/fleetTires'
import { POSITION_XY } from './rul/positions'

const SCAN_STATUS: Record<ScanStatus, { hue: string; ink: string; glyph: string; text: string }> = {
  healthy: { hue: STATUS.ok.hue, ink: STATUS.ok.ink, glyph: '●', text: 'HEALTHY' },
  warning: { hue: STATUS.watch.hue, ink: STATUS.watch.ink, glyph: '◆', text: 'WARNING' },
  error: { hue: STATUS.action.hue, ink: STATUS.action.ink, glyph: '▲', text: 'ERROR' },
}

export default function Tyres() {
  const [theme, setTheme] = useTheme()
  const aircraftQ = useFleetAircraft()
  const [tail, setTail] = useState<string | null>(null)
  const tiresQ = useFleetTires(tail)
  const [id, setId] = useState<string | null>(null)
  /** Shared 2D↔3D crack selection — Defect.label / ScanAnnotation2D.defect_label. */
  const [selectedCrack, setSelectedCrack] = useState<string | null>(null)
  const [circleAnalysis, setCircleAnalysis] = useState<CircleAnalysisResponse | null>(null)
  const [circleAnalysisLoading, setCircleAnalysisLoading] = useState(false)
  const [circleAnalysisError, setCircleAnalysisError] = useState<string | null>(null)
  const [circleChatPrompt, setCircleChatPrompt] = useState<string | null>(null)
  const analysisReqId = useRef(0)

  useEffect(() => {
    if (!tail && aircraftQ.data?.aircraft.length) {
      setTail(aircraftQ.data.aircraft[0].tail_number)
    }
  }, [aircraftQ.data, tail])

  const tires = useMemo(
    () => (tiresQ.data ? fleetTiresToDashboard(tiresQ.data) : []),
    [tiresQ.data],
  )

  useEffect(() => {
    if (!tires.length) {
      setId(null)
      return
    }
    if (!id || !tires.some((t) => t.id === id)) setId(tires[0].id)
  }, [tires, id])

  useEffect(() => {
    setSelectedCrack(null)
    setCircleAnalysis(null)
    setCircleAnalysisError(null)
    setCircleAnalysisLoading(false)
    setCircleChatPrompt(null)
  }, [id])

  const selectCrack = (label: string | null) => {
    setSelectedCrack(label)
  }

  const tire = tires.find((t) => t.id === id) ?? null

  const runCircleAnalysis = (hitLabel: string | null) => {
    if (!tire?.images?.circle) return
    const circle = tire.images.circle
    const crackCount = circle.annotations.filter((a) => a.category === 'crack').length
    const prompt = hitLabel
      ? `Analyze circle scan · focus ${hitLabel} · ${crackCount} crack overlay(s)`
      : `Analyze circle scan · ${crackCount} crack overlay(s)`
    setCircleChatPrompt(prompt)

    const reqId = ++analysisReqId.current
    setCircleAnalysisLoading(true)
    setCircleAnalysisError(null)
    setCircleAnalysis(null)
    void analyzeCircle({
      image_url: circle.url,
      annotations: circle.annotations,
      serial: tire.serial,
      model_type: tire.modelType,
      scan_status: tire.scanStatus,
      tread_depths: tire.treadDepths,
      defect_label: hitLabel,
      backend: 'auto',
    })
      .then((res) => {
        if (reqId !== analysisReqId.current) return
        setCircleAnalysis(res)
      })
      .catch((err: unknown) => {
        if (reqId !== analysisReqId.current) return
        setCircleAnalysis(null)
        setCircleAnalysisError(err instanceof ApiError ? err.message : 'Circle analysis failed.')
      })
      .finally(() => {
        if (reqId !== analysisReqId.current) return
        setCircleAnalysisLoading(false)
      })
  }

  const st: Status = tire ? statusOf(tire) : 'ok'
  const loading = aircraftQ.isLoading || (!!tail && tiresQ.isLoading)
  const err = (aircraftQ.error ?? tiresQ.error) as ApiError | null

  if (loading && !tire) {
    return (
      <div className="min-h-screen p-4 font-mono text-[var(--ink-2)] lg:p-6">
        <Header status="ok" theme={theme} onTheme={setTheme} path="/tyres" />
        <p className="mt-8 text-sm text-[var(--ink-3)]">Loading fleet tires…</p>
      </div>
    )
  }

  if (err || !tire || !tiresQ.data) {
    return (
      <div className="min-h-screen p-4 font-mono text-[var(--ink-2)] lg:p-6">
        <Header status="action" theme={theme} onTheme={setTheme} path="/tyres" />
        <Card title="Fleet data unavailable" tag="API">
          <p className="text-sm text-[var(--crit)]">
            {err?.message ?? 'No mounted tires for this aircraft.'}
          </p>
          <Open>Start the API and ensure tires.parquet has been enriched (`python -m app.tire_rul.enrich_tire_assets`).</Open>
        </Card>
      </div>
    )
  }

  const fleet = tiresQ.data
  const minGroove = Math.min(...tire.grooves)
  const psiDev = ((tire.psi - tire.psiTarget) / tire.psiTarget) * 100
  const scan = SCAN_STATUS[tire.scanStatus]
  const model = tireTypeById(tire.modelType)

  return (
    <div className="min-h-screen p-4 font-mono text-[var(--ink-2)] lg:p-6">
      <Header status={st} theme={theme} onTheme={setTheme} path="/tyres" mockStatus />

      <div className="mb-3 flex flex-wrap items-center gap-3 text-[11px] uppercase tracking-widest">
        <label className="flex items-center gap-2 text-[var(--ink-3)]">
          Aircraft
          <select
            className="border border-[var(--line-2)] bg-[var(--panel)] px-2 py-1 text-[var(--ink)]"
            value={tail ?? ''}
            onChange={(e) => setTail(e.target.value)}
          >
            {(aircraftQ.data?.aircraft ?? []).map((a) => (
              <option key={a.tail_number} value={a.tail_number}>
                {a.tail_number} · {a.home_station}
              </option>
            ))}
          </select>
        </label>
        <span className="text-[var(--ink-4)]">
          {fleet.aircraft_type.replaceAll('_', ' ')} · {fleet.home_station}
        </span>
      </div>

      <div className="grid gap-3 lg:grid-cols-12">
        <div className="flex flex-col gap-3 lg:col-span-3">
          <Card title="Wheel positions" tag="A320 · 6 wheels">
            <GearMap tires={tires} selected={id!} onSelect={setId} />
            <ScanLegend />
            <Open>Status from tread bands + cracks — healthy = all 4–6 mm (no highlight), warning = 3–4 mm, error = 1–3 mm or crack</Open>
          </Card>

          <IdentityCard tire={tire} />

          <Card title="Scan pack" tag={`${tire.scanGroup} · ${tire.scanSide}`}>
            <div className="space-y-2">
              <Field k="Condition" v={scan.text} warn={tire.scanStatus !== 'healthy'} />
              <Field k="Model type" v={model.name} />
              <Field k="Side" v={(tire.scanSide ?? '—').toUpperCase()} />
              <Field
                k="Treads"
                v={(tire.treadDepths ?? []).join(' · ') || '—'}
                warn={tire.scanStatus !== 'healthy'}
              />
            </div>
            {tire.images && (
              <div className="mt-3">
                <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,0.55fr)] items-stretch gap-2">
                  {/* Col 1: circle → frame-0 → frame-120 → frame-240 */}
                  <div className="flex flex-col gap-2">
                    <div>
                      <div className="mb-1 flex items-center justify-between text-[10px] uppercase tracking-widest text-[var(--ink-4)]">
                        <span>Circle{tire.scanStatus === 'error' ? ' · linked 3D' : ''}</span>
                      </div>
                      <div className="relative">
                        <AnnotatedScanImage
                          image={tire.images.circle}
                          alt="circle scan"
                          selectedLabel={selectedCrack}
                          onSelectCrack={selectCrack}
                        />
                        <button
                          type="button"
                          title="Ask agent to analyze circle + cracks"
                          aria-label="Ask agent to analyze circle + cracks"
                          disabled={circleAnalysisLoading}
                          onClick={(e) => {
                            e.stopPropagation()
                            runCircleAnalysis(selectedCrack)
                          }}
                          className="absolute right-1.5 top-1.5 z-10 flex h-7 w-7 items-center justify-center border border-[var(--line-2)] bg-[var(--panel)]/90 text-[var(--primary)] shadow-sm transition-colors hover:border-[var(--primary)] hover:bg-[var(--primary-soft)] disabled:opacity-50"
                        >
                          <AgentIcon busy={circleAnalysisLoading} />
                        </button>
                      </div>
                      <CircleAgentChat
                        prompt={circleChatPrompt}
                        loading={circleAnalysisLoading}
                        error={circleAnalysisError}
                        result={circleAnalysis}
                      />
                    </div>
                    {(['0°', '120°', '240°'] as const).map((label, i) => {
                      const frame = tire.images!.frames[i]
                      if (!frame) return null
                      return (
                        <div key={frame.url}>
                          <div className="mb-1 text-[10px] uppercase tracking-widest text-[var(--ink-4)]">
                            Frame · {label}
                          </div>
                          <AnnotatedScanImage image={frame} alt={`frame ${label}`} />
                        </div>
                      )
                    })}
                  </div>

                  {/* Col 2: flatten fills the same total height as the left stack */}
                  <div className="relative min-h-0">
                    <AnnotatedScanImage
                      image={tire.images.flatten}
                      alt="flatten scan"
                      rotate={90}
                      fill
                      className="absolute inset-0"
                      selectedLabel={selectedCrack}
                      onSelectCrack={selectCrack}
                    />
                    <div className="pointer-events-none absolute left-1 top-1 bg-[var(--panel)]/80 px-1.5 py-0.5 text-[10px] uppercase tracking-widest text-[var(--ink-4)]">
                      Flatten · {tire.scanSide}
                      {tire.scanStatus === 'error' ? ' · linked 3D' : ''}
                    </div>
                  </div>
                </div>
              </div>
            )}
          </Card>
        </div>

        <div className="flex flex-col gap-3 lg:col-span-6">
          <div className="relative min-h-[420px] flex-1 border border-[var(--line)] bg-[var(--panel)]">
            <TireViewer
              defects={tire.defects}
              serial={tire.serial}
              theme={theme}
              modelType={tire.modelType}
              selectedLabel={selectedCrack}
              onSelectCrack={selectCrack}
            />
          </div>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Kpi label="Inflation" value={tire.psi} unit="psi" sub={`${psiDev > 0 ? '+' : ''}${psiDev.toFixed(1)}% vs target`} bad={Math.abs(psiDev) > 5} />
            <Kpi label="Min groove" value={minGroove} unit="mm" sub={`limit ${tire.grooveLimit} mm`} bad={minGroove < tire.grooveLimit} />
            <Kpi label="Cycles" value={tire.cycles} unit="ldg" sub={`${tire.flightHrs} flt hrs`} />
            <Kpi
              label="Scan"
              value={scan.text}
              unit=""
              sub={`${model.name} · ${tire.scanSide}`}
              bad={tire.scanStatus === 'error'}
            />
          </div>
        </div>

        <div className="flex flex-col gap-3 lg:col-span-3">
          <RemainingLifeCard tire={tire} />
          <PressureCard tire={tire} />
          <TouchdownCard tire={tire} />
        </div>
      </div>

      <div className="mt-3 grid gap-3 lg:grid-cols-3">
        <TaxiCard tire={tire} />
        <WeatherCard tire={tire} />
        <UtilizationCard tire={tire} />
        <EventsCard tire={tire} />
        <TreadCard tire={tire} />
        <DefectsCard tire={tire} selectedLabel={selectedCrack} onSelect={selectCrack} />
        <RunwayCard tire={tire} className="lg:col-span-3" />
      </div>

      <footer className="mt-4 flex flex-wrap justify-between gap-2 text-[10px] uppercase tracking-widest text-[var(--ink-4)]">
        <span>Fleet parquet · mock-tyre scan packs · {fleet.tail_number}</span>
        <span>Gear mates share model_type</span>
      </footer>
    </div>
  )
}

/** Top-down gear map. Colour carries status, but every wheel also shows a glyph in its tooltip. */
function GearMap({
  tires,
  selected,
  onSelect,
}: {
  tires: Tire[]
  selected: string
  onSelect: (id: string) => void
}) {
  // A320 six-wheel layout (same coords as RUL positions).
  const byId = new Map(tires.map((t) => [t.id, t]))
  const order: { id: string; pos: WheelPosition }[] = [
    { id: 'N1', pos: 'nlg_l' },
    { id: 'N2', pos: 'nlg_r' },
    { id: 'L1', pos: 'mlg_l_outbd' },
    { id: 'L2', pos: 'mlg_l_inbd' },
    { id: 'R1', pos: 'mlg_r_inbd' },
    { id: 'R2', pos: 'mlg_r_outbd' },
  ]
  return (
    <svg viewBox="0 0 100 100" className="w-full">
      <path d="M50 2 L50 92" style={{ stroke: 'var(--line-2)' }} strokeWidth="1" />
      <path d="M50 36 L14 66 M50 36 L86 66" style={{ stroke: 'var(--line-2)' }} strokeWidth="1" />
      {order.map(({ id, pos }) => {
        const t = byId.get(id)
        if (!t) return null
        const [x, y] = POSITION_XY[pos]
        const s = SCAN_STATUS[t.scanStatus]
        const on = t.id === selected
        const hue = s.hue
        return (
          <g key={t.id} onClick={() => onSelect(t.id)} className="cursor-pointer">
            <title>{`${t.id} · ${t.label} · ${s.text} · ${tireTypeById(t.modelType).name}`}</title>
            <rect
              x={x - 4}
              y={y - 6}
              width="8"
              height="12"
              rx="2"
              fill={on ? hue : `${s.hue}33`}
              style={{ stroke: on ? 'var(--ink)' : hue }}
              strokeWidth={on ? 1 : 0.6}
            />
            <text x={x} y={y + 13} textAnchor="middle" fontSize="4.5" style={{ fill: on ? 'var(--ink)' : 'var(--ink-4)' }}>
              {t.id}
            </text>
          </g>
        )
      })}
    </svg>
  )
}

function ScanLegend() {
  return (
    <div className="mt-1 flex justify-center gap-3 text-[9px] uppercase tracking-widest">
      {(Object.keys(SCAN_STATUS) as ScanStatus[]).map((k) => (
        <span key={k} className="flex items-center gap-1" style={{ color: SCAN_STATUS[k].ink }}>
          {SCAN_STATUS[k].glyph} <span className="text-[var(--ink-4)]">{SCAN_STATUS[k].text}</span>
        </span>
      ))}
    </div>
  )
}

const CONDITION_INK: Record<CircleAnalysisResponse['condition'], string> = {
  SERVICEABLE: 'var(--ok)',
  MONITOR: 'var(--warn)',
  UNSERVICEABLE: 'var(--crit)',
}

function AgentIcon({ busy }: { busy: boolean }) {
  return (
    <svg
      viewBox="0 0 24 24"
      className={`h-4 w-4 ${busy ? 'animate-pulse' : ''}`}
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <rect x="5" y="8" width="14" height="11" rx="2" />
      <path d="M12 8V5" />
      <circle cx="12" cy="4" r="1" fill="currentColor" stroke="none" />
      <circle cx="9" cy="13" r="1" fill="currentColor" stroke="none" />
      <circle cx="15" cy="13" r="1" fill="currentColor" stroke="none" />
      <path d="M9 17h6" />
    </svg>
  )
}

function CircleAgentChat({
  prompt,
  loading,
  error,
  result,
}: {
  prompt: string | null
  loading: boolean
  error: string | null
  result: CircleAnalysisResponse | null
}) {
  if (!prompt) return null

  return (
    <div className="mt-2 space-y-2">
      <div className="flex justify-end">
        <div className="max-w-[92%] border border-[var(--primary-dim)] bg-[var(--primary-soft)] px-2.5 py-2 text-[11px] leading-snug text-[var(--ink)]">
          {prompt}
        </div>
      </div>

      {loading && (
        <div className="flex justify-start">
          <div className="flex items-center gap-2 border border-[var(--line)] bg-[var(--panel)] px-2.5 py-2 text-[11px] text-[var(--ink-3)]">
            <span className="inline-flex gap-1">
              <ChatDot delay="0ms" />
              <ChatDot delay="160ms" />
              <ChatDot delay="320ms" />
            </span>
            Agent analyzing circle + cracks…
          </div>
        </div>
      )}

      {error && !loading && (
        <div className="flex justify-start">
          <div className="max-w-[92%] border border-[var(--crit)] bg-[var(--panel)] px-2.5 py-2 text-[11px] text-[var(--crit)]">
            {error}
          </div>
        </div>
      )}

      {result && !loading && (
        <div className="flex justify-start">
          <div className="max-w-[92%] space-y-1.5 border border-[var(--line)] bg-[var(--panel)] px-2.5 py-2 text-[11px]">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <span className="text-[10px] uppercase tracking-widest text-[var(--ink-4)]">Agent</span>
              <span className="font-semibold" style={{ color: CONDITION_INK[result.condition] }}>
                {result.condition}
              </span>
            </div>
            <p className="leading-snug text-[var(--ink-2)]">{result.summary}</p>
            {result.crack_findings.length > 0 && (
              <ul className="space-y-0.5 text-[var(--ink-3)]">
                {result.crack_findings.map((f) => (
                  <li key={f} className="leading-snug">
                    · {f}
                  </li>
                ))}
              </ul>
            )}
            <p className="text-[var(--ink)]">
              <span className="text-[10px] uppercase tracking-widest text-[var(--ink-4)]">Action · </span>
              {result.action}
            </p>
            <div className="text-[9px] uppercase tracking-widest text-[var(--ink-4)]">
              {result.crack_count} crack{result.crack_count === 1 ? '' : 's'} · {result.backend}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function ChatDot({ delay }: { delay: string }) {
  return (
    <span
      className="h-1.5 w-1.5 animate-pulse rounded-full bg-[var(--primary)]"
      style={{ animationDelay: delay }}
    />
  )
}
