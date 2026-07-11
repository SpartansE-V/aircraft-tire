import { useState } from 'react'
import TireViewer from './TireViewer'
import { FLEET_TIRES, statusOf, type Status } from './data'
import {
  DefectsCard, EventsCard, IdentityCard, PressureCard, RunwayCard, TaxiCard, TouchdownCard, TreadCard, UtilizationCard, WeatherCard,
} from './TireCards'
import { Card, Header, Kpi, Open, STATUS, useTheme } from './ui'

export default function Tyres() {
  const [id, setId] = useState('L1')
  const [theme, setTheme] = useTheme()
  const tire = FLEET_TIRES.find((t) => t.id === id)!
  const st = statusOf(tire)
  const minGroove = Math.min(...tire.grooves)
  const psiDev = ((tire.psi - tire.psiTarget) / tire.psiTarget) * 100

  return (
    <div className="min-h-screen p-4 font-mono text-[var(--ink-2)] lg:p-6">
      <Header status={st} theme={theme} onTheme={setTheme} path="/tyres" />

      <div className="grid gap-3 lg:grid-cols-12">
        {/* left: fleet position map + tire identity */}
        <div className="flex flex-col gap-3 lg:col-span-3">
          <Card title="Wheel positions" tag="FDR · position map">
            <GearMap selected={id} onSelect={setId} />
            <Legend />
            <Open>Turn loads must attribute to inner vs outer wheels — position is the join axis</Open>
          </Card>

          <IdentityCard tire={tire} />
        </div>

        {/* centre: 3D + headline KPIs */}
        <div className="flex flex-col gap-3 lg:col-span-6">
          <div className="relative min-h-[420px] flex-1 border border-[var(--line)] bg-[var(--panel)]">
            <TireViewer defects={tire.defects} serial={tire.serial} theme={theme} />
          </div>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Kpi label="Inflation" value={tire.psi} unit="psi" sub={`${psiDev > 0 ? '+' : ''}${psiDev.toFixed(1)}% vs target`} bad={Math.abs(psiDev) > 5} />
            <Kpi label="Min groove" value={minGroove} unit="mm" sub={`limit ${tire.grooveLimit} mm`} bad={minGroove < tire.grooveLimit} />
            <Kpi label="Cycles" value={tire.cycles} unit="ldg" sub={`${tire.flightHrs} flt hrs`} />
            <Kpi label="Ambient" value={tire.oatC} unit="°C" sub={`${tire.crosswindKt} kt xwind`} bad={tire.oatC > 35} />
          </div>
        </div>

        {/* right: TPMS + touchdown */}
        <div className="flex flex-col gap-3 lg:col-span-3">
          <PressureCard tire={tire} />

          <TouchdownCard tire={tire} />
        </div>
      </div>

      {/* lower deck */}
      <div className="mt-3 grid gap-3 lg:grid-cols-3">
        <TaxiCard tire={tire} />
        <WeatherCard tire={tire} />
        <UtilizationCard tire={tire} />
        <EventsCard tire={tire} />
        <TreadCard tire={tire} />
        <DefectsCard tire={tire} />
        <RunwayCard tire={tire} className="lg:col-span-3" />
      </div>

      <footer className="mt-4 flex flex-wrap justify-between gap-2 text-[10px] uppercase tracking-widest text-[var(--ink-4)]">
        <span>Mock feeds · TPMS / FOQA / FDR / ACARS / MRO / scanner</span>
        <span>Amber footnotes = open questions</span>
      </footer>
    </div>
  )
}

/** Top-down gear map. Colour carries status, but every wheel also shows a glyph in its tooltip. */
function GearMap({ selected, onSelect }: { selected: string; onSelect: (id: string) => void }) {
  // Six-wheel main bogies: three axles (fwd / mid / aft), outer and inner on each.
  const xy: Record<string, [number, number]> = {
    N1: [44, 10], N2: [56, 10],
    L1: [22, 56], L2: [34, 56], L3: [22, 72], L4: [34, 72], L5: [22, 88], L6: [34, 88],
    R1: [66, 56], R2: [78, 56], R3: [66, 72], R4: [78, 72], R5: [66, 88], R6: [78, 88],
  }
  return (
    <svg viewBox="0 0 100 106" className="w-full">
      <path d="M50 2 L50 100" style={{ stroke: 'var(--line-2)' }} strokeWidth="1" />
      <path d="M50 40 L10 64 M50 40 L90 64" style={{ stroke: 'var(--line-2)' }} strokeWidth="1" />
      <path d="M28 72 L72 72" style={{ stroke: 'var(--line)' }} strokeWidth="1" strokeDasharray="2 2" />
      {FLEET_TIRES.map((t) => {
        const [x, y] = xy[t.id]
        const s = STATUS[statusOf(t)]
        const on = t.id === selected
        return (
          <g key={t.id} onClick={() => onSelect(t.id)} className="cursor-pointer">
            <title>{`${t.id} · ${t.label} · ${s.text} · ${t.psi} psi`}</title>
            <rect
              x={x - 4}
              y={y - 6}
              width="8"
              height="12"
              rx="2"
              fill={on ? s.hue : `${s.hue}33`}
              style={{ stroke: on ? 'var(--ink)' : s.hue }}
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

function Legend() {
  return (
    <div className="mt-1 flex justify-center gap-3 text-[9px] uppercase tracking-widest">
      {(Object.keys(STATUS) as Status[]).map((k) => (
        <span key={k} className="flex items-center gap-1" style={{ color: STATUS[k].ink }}>
          {STATUS[k].glyph} <span className="text-[var(--ink-4)]">{STATUS[k].text}</span>
        </span>
      ))}
    </div>
  )
}
