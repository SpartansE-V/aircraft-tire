import { Bars, Gauge, HUE, RowBars, Sparkline } from './charts'
import { FLEET_TIRES, type Tire } from './data'
import { Card, Field, Mini, Open } from './ui'

// The tire cards, lifted out of Tyres.tsx so both routes render the same code: /tyres arranges them
// around the 3D tire, /simulate-landing stacks them in the column beside the aircraft. One home for
// the JSX means the two pages cannot drift apart.

const avg = (xs: number[]) => Math.round(xs.reduce((a, b) => a + b, 0) / xs.length)

export function IdentityCard({ tire }: { tire: Tire }) {
  return (
    <Card title="Identity" mock tag="OCR · 3D laser">
      <div className="space-y-2">
        <Field k="Serial (molded)" v={tire.serial} mono />
        <Field k="OCR confidence" v={`${(tire.ocrConfidence * 100).toFixed(0)} %`} warn={tire.ocrConfidence < 0.85} />
        <Field k="Retread stamps" v={`R${tire.retreads} / 3 max`} warn={tire.retreads >= 3} />
        <Field k="Part / size" v={`${tire.partNo} · ${tire.size}`} />
        <Field k="Model type" v={tire.modelType.replaceAll('_', ' ').toUpperCase()} />
        <Field
          k="Scan status"
          v={tire.scanStatus.toUpperCase()}
          warn={tire.scanStatus !== 'healthy'}
        />
        <Field k="Flight-log join" v={tire.joinKey.toUpperCase()} warn={tire.joinKey === 'inferred'} />
      </div>
      <Open>Black rubber and vulcanization hairs cap OCR confidence — the serial is the only true key</Open>
    </Card>
  )
}

export function PressureCard({ tire }: { tire: Tire }) {
  const psiDev = ((tire.psi - tire.psiTarget) / tire.psiTarget) * 100
  return (
    <Card title="Tire pressure" mock tag="TPMS · ACARS">
      <Gauge
        value={tire.psi}
        min={Math.round(tire.psiTarget * 0.8)}
        max={Math.round(tire.psiTarget * 1.1)}
        target={tire.psiTarget}
        unit="psi"
        label={`target ${tire.psiTarget}`}
        color={Math.abs(psiDev) > 5 ? HUE.crit : HUE.primary}
      />
      <div className="mt-2 text-[10px] uppercase tracking-widest text-[var(--ink-3)]">14-day trend · dashed = service min</div>
      <Sparkline values={tire.psiTrend} unit=" psi" limit={Math.round(tire.psiTarget * 0.95)} />
      <div className="mt-2 space-y-2">
        <Field k="Loss rate" v={`${tire.leakPctPerDay} %/day`} warn={tire.leakPctPerDay > 0.7} />
        <Field k="ACARS downlink" v={tire.acarsOk ? `OK · ${tire.acarsLast} ago` : `STALE · ${tire.acarsLast}`} warn={!tire.acarsOk} />
      </div>
      <Open>Fitment gaps and layover downlink drops mean a silent sensor reads exactly like a healthy tire</Open>
    </Card>
  )
}

export function TouchdownCard({ tire }: { tire: Tire }) {
  return (
    <Card title="Touchdown / braking" mock tag="FOQA · per-flight rollup">
      <div className="mb-1 flex justify-between text-[10px] uppercase tracking-widest text-[var(--ink-3)]">
        <span>Peak vertical G · last 10</span>
        <span style={{ color: 'var(--crit)' }}>▲ &gt; 1.8 G</span>
      </div>
      <Bars
        values={tire.landings.map((l) => l.peakG)}
        labels={tire.landings.map((l) => `${l.flt} ${l.rwy} · ${l.sinkFpm} fpm · brake ${l.brakePsi} psi`)}
        unit=" G"
        limit={1.8}
      />
      <div className="mt-3 grid grid-cols-3 gap-2">
        <Mini label="Avg sink" value={`${avg(tire.landings.map((l) => l.sinkFpm))} fpm`} />
        <Mini label="Peak G" value={`${Math.max(...tire.landings.map((l) => l.peakG))}`} />
        <Mini label="Max brake" value={`${Math.max(...tire.landings.map((l) => l.brakePsi))} psi`} />
      </div>
      <Open>The high-rate stream collapses to one row per flight — peaks kept, waveform dropped</Open>
    </Card>
  )
}

export function TaxiCard({ tire }: { tire: Tire }) {
  return (
    <Card title="Taxi / steering" mock tag="FDR · ADS-B">
      <div className="mb-3 grid grid-cols-3 gap-2">
        <Mini label="Taxi dist" value={`${tire.taxiKm} km`} />
        <Mini label="Avg gnd spd" value={`${tire.taxiAvgKt} kt`} />
        <Mini label="Peak steer" value={`${tire.steerPeakDeg}°`} />
      </div>
      <div className="mb-1 text-[10px] uppercase tracking-widest text-[var(--ink-3)]">Lateral load by wheel position</div>
      <RowBars
        unit=" g"
        max={0.5}
        rows={FLEET_TIRES.filter((t) => t.gear === tire.gear).map((t) => ({
          label: `${t.id}${t.role === 'outer' ? ' out' : t.role === 'inner' ? ' in' : ''}`,
          value: t.lateralG,
          color: t.id === tire.id ? HUE.primary : t.role === 'outer' ? HUE.alt : 'var(--axis)',
        }))}
      />
      <Open>Outer wheels scrub hardest in a turn — the load model has to resolve per position, not per axle</Open>
    </Card>
  )
}

export function WeatherCard({ tire }: { tire: Tire }) {
  return (
    <Card title="Weights / environment" mock tag="ACARS · METAR">
      <div className="grid grid-cols-2 gap-2">
        <Mini label="Payload" value={`${tire.payloadT} t`} />
        <Mini label="OAT" value={`${tire.oatC} °C`} bad={tire.oatC > 35} />
        <Mini label="Crosswind" value={`${tire.crosswindKt} kt`} />
        <Mini label="Slip-angle risk" value={`${(tire.slipAngleRisk * 100).toFixed(0)} %`} bad={tire.slipAngleRisk > 0.6} />
      </div>
      <div className="mt-3 border border-[var(--line)] bg-[var(--panel)] p-2 text-[11px] leading-relaxed" style={{ color: 'var(--primary)' }}>
        {tire.metar}
      </div>
      <Open>Auto-ingest METAR at every OOOI-in, or thermal and slip risk get reconstructed by hand later</Open>
    </Card>
  )
}

export function UtilizationCard({ tire }: { tire: Tire }) {
  return (
    <Card title="Utilization" mock tag="OOOI · MRO">
      <div className="grid grid-cols-2 gap-2">
        <Mini label="Cycles" value={`${tire.cycles}`} />
        <Mini label="Flight hrs" value={`${tire.flightHrs}`} />
        <Mini label="Taxi hrs" value={`${tire.taxiHrs}`} />
        <Mini label="Parked hrs" value={`${tire.parkedHrs}`} bad={tire.parkedHrs > 400} />
      </div>
      <div className="mt-3">
        <Field
          k="Serial ↔ flight-log key"
          v={tire.joinKey === 'linked' ? 'LINKED (scan)' : 'INFERRED (position)'}
          warn={tire.joinKey === 'inferred'}
        />
      </div>
      <Open>Without a hard serial↔flight join, every hour above belongs to a position, not to a tire</Open>
    </Card>
  )
}

export function EventsCard({ tire }: { tire: Tire }) {
  return (
    <Card title="Route profile · high-wear events" mock tag="Flight ops log">
      {tire.events.length === 0 ? (
        <p className="py-6 text-center text-xs text-[var(--ink-4)]">No flagged events in window</p>
      ) : (
        <ul className="space-y-2">
          {tire.events.map((e) => (
            <li key={e.date} className="flex gap-2 border-l-2 pl-2" style={{ borderColor: 'var(--warn)' }}>
              <span className="w-16 shrink-0 text-[10px] uppercase tracking-widest" style={{ color: 'var(--warn)' }}>
                {e.kind}
              </span>
              <span className="text-xs leading-snug text-[var(--ink-2)]">
                {e.note}
                <span className="ml-1 text-[var(--ink-4)]">· {e.date}</span>
              </span>
            </li>
          ))}
        </ul>
      )}
      <Open>RTOs and training circuits are thermal outliers — flag them at ingest or they dissolve into averages</Open>
    </Card>
  )
}

export function TreadCard({ tire }: { tire: Tire }) {
  const bands = tire.treadDepths
  return (
    <Card title="Tread depth" tag={`${tire.modelType} · ${bands?.length ?? tire.grooves.length} grooves`}>
      {bands?.length ? (
        <div className="space-y-1.5">
          {bands.map((band, i) => {
            const worn = band === '1-2mm' || band === '2-3mm'
            const shallow = band === '3-4mm'
            return (
              <div key={`${band}-${i}`} className="flex items-center justify-between border border-[var(--line)] px-2 py-1.5">
                <span className="text-[10px] uppercase tracking-widest text-[var(--ink-3)]">Groove {i + 1}</span>
                <span
                  className="text-xs tabular-nums"
                  style={{ color: worn ? 'var(--crit)' : shallow ? 'var(--warn)' : 'var(--ink)' }}
                >
                  {band}
                </span>
              </div>
            )
          })}
        </div>
      ) : (
        <RowBars unit=" mm" max={10} limit={tire.grooveLimit} rows={tire.grooves.map((g, i) => ({ label: `Groove ${i + 1}`, value: g }))} />
      )}
      <div className="mt-3 grid grid-cols-2 gap-2">
        <Mini label="Scan error" value={`± ${tire.scanErrorMm} mm`} bad={tire.scanErrorMm > 0.2} />
        <Mini label="Calibrated" value={`${tire.calibratedDaysAgo} d ago`} bad={tire.calibratedDaysAgo > 30} />
      </div>
      <Open>Bands: healthy 4–6 mm · warning 3–4 mm · error 1–3 mm (or any crack)</Open>
    </Card>
  )
}

export function DefectsCard({ tire }: { tire: Tire }) {
  return (
    <Card title="Defects" mock tag="Vision model">
      {tire.defects.length === 0 ? (
        <p className="py-6 text-center text-xs text-[var(--ink-4)]">Clean — no wear or damage flags</p>
      ) : (
        <ul className="space-y-2">
          {tire.defects.map((d) => (
            <li key={d.label} className="flex items-start gap-2 border border-[var(--line)] bg-[var(--panel)] p-2">
              <span className="mt-0.5 text-xs" style={{ color: d.kind === 'damage' ? 'var(--crit)' : 'var(--warn)' }}>
                {d.kind === 'damage' ? '⚠' : '≈'}
              </span>
              <div className="min-w-0">
                <div className="text-xs text-[var(--ink)]">{d.label}</div>
                <div className="mt-0.5 text-[10px] uppercase tracking-widest text-[var(--ink-3)]">
                  {d.zone} · {d.kind === 'damage' ? 'REMOVE — AOG kit' : 'MONITOR — next check'}
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
      <Open>Wear and acute damage take different logistics paths — one schedules a swap, the other grounds the aircraft</Open>
    </Card>
  )
}

export function RunwayCard({ tire, className }: { tire: Tire; className?: string }) {
  return (
    <Card title="Runway data" tag="Airport DB" className={className}>
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
        {tire.runways.map((r) => (
          <div key={r.icao} className="border border-[var(--line)] bg-[var(--panel)] p-2">
            <div className="flex items-baseline justify-between">
              <span className="text-sm text-[var(--ink)]">{r.icao}</span>
              <span className="text-[10px] uppercase tracking-widest" style={{ color: r.code >= 5 ? 'var(--ok)' : 'var(--warn)' }}>
                RWYCC {r.code}
              </span>
            </div>
            <div className="mt-1 text-[10px] uppercase tracking-widest text-[var(--ink-3)]">{r.surface}</div>
            <div className="mt-1 text-xs tabular-nums text-[var(--ink-2)]">µ-texture {r.texture} mm</div>
          </div>
        ))}
      </div>
      <Open>Surface names differ per airport feed — normalize to one material vocabulary before they feed wear models</Open>
    </Card>
  )
}

/** The whole tire dashboard as one scrolling column — what sits beside the aircraft on /simulate-landing. */
export function TireDetail({ tire }: { tire: Tire }) {
  return (
    <div className="flex flex-col gap-3">
      <IdentityCard tire={tire} />
      <PressureCard tire={tire} />
      <TreadCard tire={tire} />
      <DefectsCard tire={tire} />
      <TouchdownCard tire={tire} />
      <UtilizationCard tire={tire} />
    </div>
  )
}
