import { useEffect, useState } from 'react'
import Aircraft from './Aircraft'
import { Gauge, HUE, RowBars, Sparkline } from './charts'
import { FLEET_TIRES } from './data'
import Forecast from './Forecast'
import { beadCurve, CAL, contactPatchDeg, OLEO, type Landing, type Surface } from './sim'
import { LEAD_AXLE, simulateLandingRun, type Attitude } from './landingEngine'
import { TireDetail } from './TireCards'
import TireViewer, { type Impact } from './TireViewer'
import { TRACKS, type Track } from './tracks'
import TrackMap from './TrackMap'
import { Card, Field, Header, Kpi, Mini, Mock, Open, STATUS, useTheme } from './ui'

const SURFACES: { key: Surface; label: string; rwycc: number }[] = [
  { key: 'dry', label: 'Dry', rwycc: 6 },
  { key: 'wet', label: 'Wet', rwycc: 4 },
  { key: 'contaminated', label: 'Contaminated', rwycc: 2 },
]

const HOME = TRACKS.find((t) => t.icao === 'VVTS')!

/** A landing is the aircraft's numbers plus the runway it is arriving on. */
function landingAt(track: Track, base?: Partial<Landing>): Landing {
  return {
    weightT: 200,
    sinkFpm: 240,
    gsKt: 138,
    brakeShare: 0.55,
    windKt: 14,
    windDirDeg: (track.headingDeg + 40) % 360, // off the nose and to one side: some head, some cross
    antiskid: true,
    ...base,
    // The track owns these five — picking an airport is what changes them. The heading matters now:
    // a wind is only a headwind or a crosswind *relative to the runway you are landing on*.
    oatC: track.oatC,
    surface: track.surface,
    elevFt: track.elevFt,
    runwayM: track.lengthM,
    runwayHeadingDeg: track.headingDeg,
  }
}

// liftShare is the lift still on the wing when the wheels touch. At Vref that is nearly all of it —
// the wing does not stop flying because the tyres touched, it stops when the spoilers kill it. The old
// default of 0.18 belonged to a model that used this as a multiplier on load rather than as a force.
const LEVEL: Attitude = { pitchDeg: 4, rollDeg: 0, crabDeg: 0, liftShare: 0.9 }

export default function SimulateLanding() {
  const [theme, setTheme] = useTheme()
  const [id, setId] = useState('L1')
  const [track, setTrack] = useState<Track>(HOME)
  const [l, setL] = useState<Landing>(landingAt(HOME))
  const [att, setAtt] = useState<Attitude>(LEVEL)
  const [frameIndex, setFrameIndex] = useState(0)
  const [playing, setPlaying] = useState(false)
  const set = <K extends keyof Landing>(k: K, v: Landing[K]) => setL((p) => ({ ...p, [k]: v }))
  // Switching airport keeps how you are flying and swaps what you are landing on.
  const goTo = (t: Track) => {
    setTrack(t)
    setL((p) => landingAt(t, p))
  }
  const setA = <K extends keyof Attitude>(k: K, v: number) => setAtt((p) => ({ ...p, [k]: v }))

  const tire = FLEET_TIRES.find((t) => t.id === id)!
  const run = simulateLandingRun({ landing: l, attitude: att, track, tires: FLEET_TIRES, selectedTireId: id })
  const r = run.summary
  const s = STATUS[r.status]
  const touchdownIndex = Math.max(0, run.frames.findIndex((f) => f.phase === 'touchdown'))
  const activeIndex = Math.min(frameIndex, run.frames.length - 1)
  const frame = run.frames[activeIndex]
  const frameCount = run.frames.length
  const frameStepS = run.frames[1]?.tS - run.frames[0]?.tS || 0.05
  const sideLoads = sideLoadRows(run.summary.perWheel)
  const strutUsedM = Math.max(...r.oleo.samples.map((x) => x.strokeM))
  // What the runway is doing to the selected tyre at this instant of the landing.
  const fw = frame.wheel[id]
  const pw = r.perWheel[id]
  const impact: Impact = {
    contactDeg: fw.contactDeg,
    arcDeg: contactPatchDeg(fw.loadKN, tire.radiusM),
    loadKN: fw.loadKN,
    peakLoadKN: pw.peakLoadKN,
    peakDeg: pw.impactDeg,
    peakArcDeg: pw.impactArcDeg,
    slipMps: fw.slipMps,
    contact: fw.contact,
    flatMm: pw.flatSpotMm,
    flatDeg: pw.flatSpotDeg,
  }
  // Peak load on each axle of the truck. The aft one lands first and takes the transient; the front
  // one is the one braking leans on. Averaging these together is exactly the mistake to avoid.
  const axleLoads = ([2, 1, 0] as const).map((axle) => ({
    label: ['Fwd axle', 'Mid axle', 'Aft axle'][axle] + (axle === LEAD_AXLE ? ' · lands first' : ''),
    value: Math.round(
      Math.max(...FLEET_TIRES.filter((t) => t.gear !== 'nose' && t.axle === axle).map((t) => r.perWheel[t.id].peakLoadKN)),
    ),
    color: axle === LEAD_AXLE ? HUE.crit : HUE.alt,
  }))

  useEffect(() => {
    setPlaying(false)
    setFrameIndex(0)
  }, [l, att, track, id])

  useEffect(() => {
    if (!playing) return
    let last = performance.now()
    let raf = requestAnimationFrame(function tick(now) {
      const frames = Math.max(1, Math.floor((now - last) / 1000 / frameStepS))
      if (frames > 0) {
        last = now
        setFrameIndex((i) => Math.min(frameCount - 1, i + frames))
      }
      raf = requestAnimationFrame(tick)
    })
    return () => cancelAnimationFrame(raf)
  }, [frameCount, frameStepS, playing])

  useEffect(() => {
    if (playing && activeIndex >= run.frames.length - 1) setPlaying(false)
  }, [activeIndex, playing, run.frames.length])

  return (
    <div className="min-h-screen p-4 font-mono text-[var(--ink-2)] lg:p-6">
      <Header status={r.status} theme={theme} onTheme={setTheme} path="/simulate-landing" mockStatus />

      <div className="grid gap-3 lg:grid-cols-12">
        {/* left: the inputs */}
        <div className="flex flex-col gap-3 lg:col-span-3">
          <Card title="Landing track" tag="Airport DB">
            <div className="grid grid-cols-2 gap-1.5">
              {TRACKS.map((t) => {
                const on = t.icao === track.icao
                return (
                  <button
                    key={t.icao}
                    onClick={() => goTo(t)}
                    aria-pressed={on}
                    title={`${t.name} · ${t.city}`}
                    className="border px-2 py-1.5 text-left transition-colors"
                    style={{ borderColor: on ? 'var(--primary)' : 'var(--line-2)', color: on ? 'var(--primary)' : 'var(--ink-3)' }}
                  >
                    <span className="block text-[11px] tracking-widest">{t.icao}</span>
                    <span className="mt-0.5 block text-[9px] uppercase tracking-widest text-[var(--ink-4)]">
                      {t.rwy} · {(t.lengthM / 1000).toFixed(1)} km
                    </span>
                  </button>
                )
              })}
            </div>

            <div className="mt-3">
              <TrackMap track={track} stopDistM={r.stopDistM} />
            </div>

            <div className="mt-3 space-y-2">
              <Field k="Airport" v={`${track.name}, ${track.city}`} />
              <Field k="Runway" v={`${track.rwy} · ${track.lengthM} m · hdg ${track.headingDeg}°`} />
              <Field k="Elevation" v={`${track.elevFt} ft`} warn={track.elevFt > 3000} />
              <Field k="Surface" v={`${track.surface.toUpperCase()} · RWYCC ${track.rwycc}`} warn={track.rwycc < 5} />
              <Field k="True gnd speed" v={`${r.gsTrueKt.toFixed(0)} kt`} warn={r.gsTrueKt - l.gsKt > 3} />
            </div>

            <p className="mt-3 border-l-2 pl-2 text-[10px] leading-relaxed text-[var(--ink-3)]" style={{ borderColor: 'var(--primary)' }}>
              {track.note}
            </p>
            <Open>Field elevation, length and surface come from the airport DB — the sliders below are the crew's</Open>
          </Card>

          <Card title="Attitude at touchdown" tag="Manual · on rails">
            <div className="space-y-3">
              <Slider label="Pitch / flare" v={att.pitchDeg} min={-2} max={12} step={0.5} unit="°" onChange={(v) => setA('pitchDeg', v)} bad={att.pitchDeg > 11} />
              <Slider label="Roll / bank" v={att.rollDeg} min={-8} max={8} step={0.5} unit="°" onChange={(v) => setA('rollDeg', v)} bad={Math.abs(att.rollDeg) > 5} />
              <Slider label="Yaw / crab" v={att.crabDeg} min={-15} max={15} step={1} unit="°" onChange={(v) => setA('crabDeg', v)} bad={Math.abs(att.crabDeg) > 10} />
              {/* Both ends of this are bad, which is what makes it worth a slider: dump the lift early
                  and the gear catches 200 t on its own (a slam); carry too much and the strut throws
                  the aircraft back into the air (a bounce), with the brakes still doing nothing. */}
              <Slider label="Lift at touchdown" v={Math.round(att.liftShare * 100)} min={50} max={100} step={5} unit=" %" onChange={(v) => setA('liftShare', v / 100)} bad={att.liftShare < 0.65} />
            </div>
            <button
              onClick={() => setAtt(LEVEL)}
              className="mt-3 border border-[var(--line-2)] px-2 py-1 text-[10px] uppercase tracking-widest text-[var(--ink-3)] transition-colors hover:text-[var(--ink)]"
            >
              Wings level
            </button>
            <Open>Roll decides which main touches first — a one-wheel arrival puts the whole load on one tire</Open>
          </Card>

          <Card title="Touchdown parameters" tag="What-if · manual">
            <div className="space-y-3">
              {/* 777-300ER: empty 168 t, max landing 251.3 t. The old 40–79 t range was a narrowbody's,
                  which put every load, energy and temperature on this page about 3x low. */}
              <Slider label="Landing weight" v={l.weightT} min={168} max={251} step={1} unit=" t" onChange={(v) => set('weightT', v)} bad={l.weightT > 245} />
              <Slider label="Sink rate" v={l.sinkFpm} min={60} max={720} step={10} unit=" fpm" onChange={(v) => set('sinkFpm', v)} bad={l.sinkFpm > 600} />
              <Slider label="Approach speed" v={l.gsKt} min={100} max={175} step={1} unit=" kt" onChange={(v) => set('gsKt', v)} />
              <Slider
                label="Energy into brakes"
                v={Math.round(l.brakeShare * 100)}
                min={20}
                max={100}
                step={5}
                unit=" %"
                onChange={(v) => set('brakeShare', v / 100)}
              />
              <Slider label="OAT" v={l.oatC} min={-20} max={48} step={1} unit=" °C" onChange={(v) => set('oatC', v)} bad={l.oatC > 35} />
              {/* A wind, not a crosswind. Both components come off this one vector against the runway
                  heading, so they cannot disagree — and a headwind is finally something the aircraft
                  can feel, which it could not for the model's entire life. */}
              <Slider label="Wind speed" v={l.windKt} min={0} max={40} step={1} unit=" kt" onChange={(v) => set('windKt', v)} bad={Math.abs(r.crosswindKt) > 25} />
              <Slider label="Wind from" v={l.windDirDeg} min={0} max={359} step={5} unit="°" onChange={(v) => set('windDirDeg', v)} />
            </div>

            <div className="mt-2 grid grid-cols-2 gap-2">
              <Mini
                label="Headwind"
                value={`${r.headwindKt >= 0 ? '' : '−'}${Math.abs(r.headwindKt).toFixed(0)} kt`}
                bad={r.headwindKt < -5}
              />
              <Mini label="Crosswind" value={`${Math.abs(r.crosswindKt).toFixed(0)} kt`} bad={Math.abs(r.crosswindKt) > 25} />
            </div>
            <p className="mt-1 text-[10px] leading-relaxed text-[var(--ink-4)]">
              Runway {track.rwy} points {track.headingDeg}°. Swing the wind onto the nose and it is all headwind — the cheapest runway there is, because
              groundspeed falls and every energy term goes with its square. Swing it across and it is all crosswind, and the gear pays instead.
            </p>

            {/* Anti-skid. The one switch on this page that decides whether a hard stop costs a tyre. */}
            <div className="mt-3">
              <div className="mb-1 text-[10px] uppercase tracking-widest text-[var(--ink-3)]">Anti-skid</div>
              <div className="grid grid-cols-2 gap-2">
                {[true, false].map((on) => (
                  <button
                    key={String(on)}
                    onClick={() => set('antiskid', on)}
                    aria-pressed={l.antiskid === on}
                    className="border px-2 py-1.5 text-[10px] uppercase tracking-widest transition-colors"
                    style={{
                      borderColor: l.antiskid === on ? (on ? 'var(--primary)' : 'var(--crit)') : 'var(--line-2)',
                      color: l.antiskid === on ? (on ? 'var(--primary)' : 'var(--crit)') : 'var(--ink-4)',
                    }}
                  >
                    {on ? 'On' : 'Failed'}
                  </button>
                ))}
              </div>
              <p className="mt-1 text-[10px] leading-relaxed text-[var(--ink-4)]">
                On, it holds the tyre at the friction peak and the wheel never locks — so past about half pedal you are µ-limited and more brake buys nothing.
                Failed, a brake demand the runway cannot supply stops the wheel dead: it stops you <b>worse</b> (sliding grips less than rolling) and grinds a
                flat spot into one arc of tread.
              </p>
            </div>

            <div className="mt-3">
              <div className="mb-1 text-[10px] uppercase tracking-widest text-[var(--ink-3)]">Runway state</div>
              <div className="grid grid-cols-3 gap-2">
                {SURFACES.map((sf) => {
                  const on = sf.key === l.surface
                  return (
                    <button
                      key={sf.key}
                      onClick={() => set('surface', sf.key)}
                      aria-pressed={on}
                      className="border px-2 py-1.5 text-[10px] uppercase tracking-widest transition-colors"
                      style={{ borderColor: on ? 'var(--primary)' : 'var(--line-2)', color: on ? 'var(--primary)' : 'var(--ink-3)' }}
                    >
                      {sf.label}
                      <span className="mt-0.5 block text-[9px] text-[var(--ink-4)]">RWYCC {sf.rwycc}</span>
                    </button>
                  )
                })}
              </div>
            </div>

            <button
              onClick={() => setL(landingAt(track))}
              className="mt-3 border border-[var(--line-2)] px-2 py-1 text-[10px] uppercase tracking-widest text-[var(--ink-3)] transition-colors hover:text-[var(--ink)]"
            >
              Reset to last actual
            </button>

            <Open>The model is first-order physics with fitted coefficients — refit every constant once serials join to FOQA</Open>
          </Card>

          {/*
            Everything above is this aircraft: measured off the tyre, or computed by physics we can check.
            What follows is a demonstration model's opinion about the next fifty cycles. Those are not the
            same kind of claim, so they do not get the same kind of card. See API_INTEGRATION.md.
          */}
          <Forecast tire={tire} landing={l} attitude={att} />
        </div>

        {/* centre: the aircraft — and the wheels on it are how you pick a tire */}
        <div className="flex flex-col gap-3 lg:col-span-6">
          <div className="relative min-h-[520px] flex-1 border border-[var(--line)] bg-[var(--panel)]">
            <Aircraft selected={id} onSelect={setId} attitude={att} frame={frame} track={track} theme={theme} />
          </div>

          <section className="border border-[var(--line)] bg-[var(--panel)]/80 p-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <div className="text-xs uppercase tracking-[0.2em] text-[var(--ink)]">Landing timeline</div>
                <div className="mt-1 text-[10px] uppercase tracking-widest text-[var(--ink-4)]">
                  {frame.phase} · {frame.tS.toFixed(2)} s · {Math.max(0, frame.pose.xM).toFixed(0)} m · {(frame.speedMps / 0.5144).toFixed(0)} kt
                </div>
              </div>
              <div className="flex gap-1">
                <button
                  onClick={() => {
                    if (activeIndex >= run.frames.length - 1) setFrameIndex(0)
                    else if (!playing && activeIndex === touchdownIndex) setFrameIndex(0)
                    setPlaying((p) => !p)
                  }}
                  className="border border-[var(--line-2)] px-2 py-1 text-[10px] uppercase tracking-widest text-[var(--ink-3)] transition-colors hover:text-[var(--ink)]"
                >
                  {playing ? 'Pause' : 'Fly'}
                </button>
                <button
                  onClick={() => {
                    setPlaying(false)
                    setFrameIndex(touchdownIndex)
                  }}
                  className="border border-[var(--line-2)] px-2 py-1 text-[10px] uppercase tracking-widest text-[var(--ink-3)] transition-colors hover:text-[var(--ink)]"
                >
                  Touchdown
                </button>
              </div>
            </div>
            <input
              type="range"
              value={activeIndex}
              min={0}
              max={run.frames.length - 1}
              step={1}
              onChange={(e) => {
                setPlaying(false)
                setFrameIndex(Number(e.target.value))
              }}
              className="mt-3 w-full accent-[var(--primary)]"
              aria-label="Landing timeline"
            />
          </section>

          {/* The verdict is about this tyre — its tread, its serial, its status. Invented, all of it. */}
          <Mock>
            <section className="border p-3" style={{ borderColor: s.ink }}>
              <div className="flex items-baseline justify-between gap-2">
                <span className="text-xs uppercase tracking-[0.2em]" style={{ color: s.ink }}>
                  {s.glyph} {s.text}
                </span>
                <span className="text-[9px] uppercase tracking-widest text-[var(--ink-4)]">
                  {tire.id} · {tire.serial}
                </span>
              </div>
              {r.flags.length === 0 ? (
                <p className="mt-2 text-xs text-[var(--ink-3)]">Within limits — no removal trigger from this event.</p>
              ) : (
                <ul className="mt-2 space-y-1">
                  {r.flags.map((f) => (
                    <li key={f} className="border-l-2 pl-2 text-xs leading-snug" style={{ borderColor: s.ink }}>
                      {f}
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </Mock>

          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Kpi label="Peak vertical" value={r.peakG.toFixed(2)} unit="G" sub={`flag > ${CAL.gLimit} G`} bad={r.peakG > CAL.gLimit} />
            <Kpi label="Load / tire" value={Math.round(r.loadPerTireKN)} unit="kN" sub={`${CAL.mainWheels} main wheels`} />
            <Kpi label="Stop distance" value={Math.round(r.stopDistM)} unit="m" sub={`µ ${CAL.mu[l.surface]} · ${l.surface}`} />
            <Kpi
              label="Runway left"
              value={Math.round(r.stopMarginM)}
              unit="m"
              sub={`of ${track.lengthM} m at ${track.icao}`}
              bad={r.stopMarginM < CAL.marginM}
            />
          </div>

          <Card title="Bead · heat soak" tag="Thermal model">
            <div className="mb-3 grid grid-cols-4 gap-2">
              <Mini label="Per brake" value={`${r.brakeEnergyMJ.toFixed(1)} MJ`} />
              <Mini label="Pack peak" value={`${Math.round(r.brakePeakC)} °C`} />
              <Mini label="Bead peak" value={`${Math.round(r.beadPeakC)} °C`} bad={r.beadPeakC > CAL.fusePlugC} />
              <Mini label="Bead peaks at" value={`+${Math.round(r.beadPeakAtS / 60)} min`} bad={r.beadPeakC > CAL.fusePlugC} />
            </div>
            <div className="mb-1 text-[10px] uppercase tracking-widest text-[var(--ink-3)]">
              Bead temp · 45 min after touchdown · dashed = fuse plug {CAL.fusePlugC} °C
            </div>
            <Sparkline values={beadCurve(r.thermal)} unit=" °C" limit={CAL.fusePlugC} />
            <Open>
              The bead peaks <b>{Math.round(r.beadPeakAtS / 60)} minutes after the aircraft stops</b>, not on the runway: the pack is being blasted with cooling
              air right up until it parks, and only then does the heat soak inward through the wheel. Fuse plugs let go on the taxiway and at the gate. This is
              the number a turnaround hangs on, and the old model had it backwards.
            </Open>
          </Card>

          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <Card title="Vertical g" tag="Simulated FOQA">
            <Gauge
              value={Number(r.peakG.toFixed(2))}
              min={1}
              max={2.6}
              target={CAL.gLimit}
              unit="G"
              label={`flag ${CAL.gLimit}`}
              color={r.peakG > CAL.gLimit ? HUE.crit : HUE.primary}
            />
            <div className="mt-3 space-y-2">
              <Field k="Sink at touchdown" v={`${l.sinkFpm} fpm`} warn={l.sinkFpm > 600} />
              <Field k="Strut stroke used" v={`${strutUsedM.toFixed(2)} of ${OLEO.strokeM} m`} warn={r.bottomedOut} />
              <Field k="Bead peaks at" v={`+${Math.round(r.beadPeakAtS / 60)} min, at the gate`} />
            </div>
            <Open>
              Peak g is <b>integrated</b>, not inferred: gas spring, orifice damper and the tyre under it, at 1 ms. It is the strut's own answer, so the
              stroke and the recoil above are the same event as this number.
            </Open>
          </Card>

          <Card title="Load by gear" tag="Crosswind roll">
            <RowBars
              unit=" kN"
              max={Math.ceil(Math.max(...sideLoads.map((row) => row.value), 1) * 1.2)}
              rows={[
                { label: 'Right mains', value: Math.round(sideLoads.find((row) => row.label === 'Right mains')?.value ?? 0), color: HUE.crit },
                { label: 'Left mains', value: Math.round(sideLoads.find((row) => row.label === 'Left mains')?.value ?? 0), color: HUE.alt },
              ]}
            />
            <Open>Crosswind rolls the load onto the downwind gear — and crabbing out the drift does not spare it, it only converts the drift into scrub</Open>
          </Card>

          <Card title="Load by axle" tag="Bogie pitch">
            <RowBars unit=" kN" max={Math.ceil(Math.max(...axleLoads.map((row) => row.value), 1) * 1.2)} rows={axleLoads} />
            <Open>
              The truck hangs nose-up and lands on its <b>aft axle</b>, which carries the whole bogie alone until the strut strokes it flat — so it takes the
              transient and does the spin-up. Then braking pitches the truck forward and the <b>front</b> axle eats the heat. Six tyres on one bogie, six
              different lives. This is why wear is attributed per position and never averaged across the truck.
            </Open>
          </Card>

          <Card title="Tread budget" mock tag="Projection">
            <div className="grid grid-cols-2 gap-2">
              <Mini label="Groove now" value={`${Math.min(...tire.grooves).toFixed(2)} mm`} />
              <Mini label="After event" value={`${r.grooveAfter.toFixed(2)} mm`} bad={r.grooveAfter < tire.grooveLimit} />
              <Mini label="Limit" value={`${tire.grooveLimit.toFixed(1)} mm`} />
              <Mini label="Cycles left" value={`${r.cyclesToLimit}`} bad={r.cyclesToLimit < 30} />
            </div>
            <div className="mt-3 space-y-2">
              <Field k="Inflation" v={`${tire.psi} / ${tire.psiTarget} psi`} warn={Math.abs(tire.psi - tire.psiTarget) / tire.psiTarget > 0.05} />
              <Field k="Retreads" v={`R${tire.retreads} / 3 max`} warn={tire.retreads >= 3} />
            </div>
            <Open>Cycles-left assumes every landing looks like this one — the real curve needs the flight-mix distribution</Open>
          </Card>
          </div>
        </div>

        {/* right: the tire you clicked on the plane — the same cards /tyres shows. All of it is the
            tyre's own condition, so all of it is invented, so all of it goes with the mock switch. */}
        <div className="flex flex-col gap-3 lg:col-span-3">
          <Mock>
            <div className="border border-[var(--line)] bg-[var(--panel)]/80 px-3 py-2">
              <div className="flex items-baseline justify-between gap-2">
                <span className="text-xs uppercase tracking-[0.2em]" style={{ color: 'var(--primary)' }}>
                  {tire.id} · {tire.label}
                </span>
                <span className="text-[9px] uppercase tracking-widest" style={{ color: s.ink }}>
                  {s.glyph} {s.text}
                </span>
              </div>
              <p className="mt-1 text-[10px] uppercase tracking-widest text-[var(--ink-4)]">Click a wheel on the aircraft to switch tire</p>
            </div>

            {/* The same 3D tyre /tyres shows — with the landing on it. Scrub the timeline and the blue
                band runs round the tread: that is the arc of rubber the runway is actually touching. */}
            <div className="relative h-[340px] border border-[var(--line)] bg-[var(--panel)]">
              <TireViewer defects={tire.defects} serial={tire.serial} theme={theme} impact={impact} compact />
            </div>

            <TireDetail tire={tire} />
          </Mock>
        </div>

      </div>

      <footer className="mt-4 flex flex-wrap justify-between gap-2 text-[10px] uppercase tracking-widest text-[var(--ink-4)]">
        <span>Simulated event · not a recorded landing</span>
        <span>Amber footnotes = open questions</span>
      </footer>
    </div>
  )
}

function Slider({
  label,
  v,
  min,
  max,
  step,
  unit,
  bad,
  onChange,
}: {
  label: string
  v: number
  min: number
  max: number
  step: number
  unit: string
  bad?: boolean
  onChange: (v: number) => void
}) {
  return (
    <label className="block">
      <span className="flex items-baseline justify-between text-xs">
        <span className="text-[var(--ink-4)]">{label}</span>
        <span className="tabular-nums" style={{ color: bad ? 'var(--warn)' : 'var(--ink-2)' }}>
          {bad && '⚠ '}
          {v}
          {unit}
        </span>
      </span>
      <input
        type="range"
        value={v}
        min={min}
        max={max}
        step={step}
        onChange={(e) => onChange(Number(e.target.value))}
        className="mt-1 w-full accent-[var(--primary)]"
      />
    </label>
  )
}

function sideLoadRows(perWheel: Record<string, { peakLoadKN: number }>) {
  const avg = (ids: string[]) => ids.reduce((sum, id) => sum + (perWheel[id]?.peakLoadKN ?? 0), 0) / Math.max(ids.length, 1)
  return [
    { label: 'Right mains', value: avg(FLEET_TIRES.filter((t) => t.gear === 'right').map((t) => t.id)) },
    { label: 'Left mains', value: avg(FLEET_TIRES.filter((t) => t.gear === 'left').map((t) => t.id)) },
  ]
}
