import assert from 'node:assert/strict'
import { FLEET_TIRES } from './data.ts'
import { canHydroplane, driftAngleDeg, G, hydroplaneSpeedKt, simulate } from './sim.ts'
import { LEAD_AXLE, simulateLandingRun, SPINUP_S, type Attitude } from './landingEngine.ts'

const track = {
  icao: 'KLAX',
  rwy: '25L',
  surface: 'dry',
  oatC: 21,
  env: 'coastal',
  note: 'check fixture',
  name: 'Los Angeles',
  city: 'Los Angeles',
  lengthM: 3382,
  elevFt: 125,
  headingDeg: 263,
  rwycc: 6,
} as const
const landing = {
  weightT: 200,
  sinkFpm: 240,
  gsKt: 138,
  brakeShare: 0.55,
  oatC: track.oatC,
  crosswindKt: 12,
  surface: track.surface,
  elevFt: track.elevFt,
  runwayM: track.lengthM,
}
const attitude: Attitude = { pitchDeg: 4, rollDeg: 0, crabDeg: 0, liftShare: 0 }
const selectedTireId = 'L1'
const tire = FLEET_TIRES.find((t) => t.id === selectedTireId)!
const scalar = simulate(landing, tire)
const run = simulateLandingRun({ landing, attitude, track, tires: FLEET_TIRES, selectedTireId })
const repeat = simulateLandingRun({ landing, attitude, track, tires: FLEET_TIRES, selectedTireId })

assert.ok(run.frames.length > 10, 'engine should expose a fixed-step timeline')
assert.equal(run.frames.at(-1)?.phase, 'stopped')
assert.ok(run.summary.stopDistM >= scalar.stopDistM, 'engine summary should include wheel/runway condition losses on top of scalar baseline')
assert.deepEqual(
  repeat.frames.map((f) => [f.tS, f.phase, Math.round(f.pose.xM), Math.round(f.speedMps)]),
  run.frames.map((f) => [f.tS, f.phase, Math.round(f.pose.xM), Math.round(f.speedMps)]),
  'same scenario should produce deterministic frames',
)

for (let i = 1; i < run.frames.length; i++) {
  assert.ok(run.frames[i].pose.xM >= run.frames[i - 1].pose.xM, 'runway distance must be monotonic')
  assert.ok(run.frames[i].speedMps >= 0, 'speed must never go negative')
}
assert.ok(Math.abs(run.frames.at(-1)!.pose.xM - run.summary.stopDistM) < 0.5, 'final frame should land on summary stop distance')

const levelNoWind = simulateLandingRun({ landing: { ...landing, crosswindKt: 0 }, attitude, track, tires: FLEET_TIRES, selectedTireId })
assert.ok(Math.abs(levelNoWind.summary.perWheel.L1.peakLoadKN - levelNoWind.summary.perWheel.R1.peakLoadKN) < 1e-9, 'wings-level/no-wind loads should be side-symmetric')

const banked = simulateLandingRun({ landing: { ...landing, crosswindKt: 0 }, attitude: { ...attitude, rollDeg: 8 }, track, tires: FLEET_TIRES, selectedTireId: 'R1' })
assert.ok(banked.summary.perWheel.R1.peakLoadKN > banked.summary.perWheel.L1.peakLoadKN, 'positive bank should load the right gear')
assert.ok(banked.summary.touchdownOrder.every((id) => id.startsWith('R')), 'positive bank should touch right mains first')

// --- CONSERVATION. Every other assertion in this file is a direction (`A > B`). A direction is free;
// Newton is not. A model can drop 31 % of the aeroplane and leave the nose gear at exactly zero and
// still satisfy every `A > B` above, because it drops the force *monotonically* — which is precisely
// what the old one did, green, for as long as it existed. These are the contract the load model owes.
//
// Collected rather than thrown so that all of them report at once: they tend to fail together, because
// they are usually one bug wearing several hats.
const bugs: string[] = []
const expect = (ok: boolean, msg: string) => void (ok || bugs.push(msg))


// Conservation is an *instantaneous* property, not a property of the peaks. The mains peak at
// touchdown while the nose is still flying; the nose peaks seconds later under braking. Summing the
// per-wheel maxima therefore over-counts on purpose and proves nothing. Check the frames instead —
// every one of them, which is the stronger claim anyway.
const weightKN = landing.weightT * G
const aircraftKN = (r: typeof run) => weightKN * r.summary.peakG
const frameLoad = (f: (typeof run.frames)[number]) => Object.values(f.wheel).reduce((a, w) => a + w.loadKN, 0)

// The fourteen wheels must always react exactly what the strut is pushing with — at *every* instant,
// not just at the peak. (This used to be checked against `m·g·peakG` at the frame labelled 'touchdown'.
// That worked while the arrival was a closed-form spike, and stopped meaning anything the moment the
// strut became a real one: peak load lands wherever the gas and the damper say it does, which is tens
// of milliseconds after first contact, not on whichever 50 ms frame carries the label.)
const conserves = (r: typeof run, label: string) => {
  const leaks = r.frames.filter((f) => Math.abs(frameLoad(f) - f.gearLoadKN) > Math.max(1, f.gearLoadKN * 0.01))
  const worst = leaks[0]
  expect(
    !worst,
    worst ? `${label}: load conservation broke on ${leaks.length} frames — e.g. at t=${worst.tS}s the struts push ${worst.gearLoadKN.toFixed(0)} kN and the wheels react ${frameLoad(worst).toFixed(0)} kN` : '',
  )
}
conserves(levelNoWind, 'wings level')
conserves(banked, 'one-truck arrival') // the case that used to drop 31 % of the aeroplane on the floor

// Once it has settled onto all fourteen wheels it weighs exactly what it weighs. Nothing more.
const settled = levelNoWind.frames.filter((f) => f.phase === 'braking').at(-1)!
expect(
  Math.abs(frameLoad(settled) / weightKN - 1) < 0.03,
  `settled rollout: wheels react ${frameLoad(settled).toFixed(0)} kN of a ${weightKN.toFixed(0)} kN aircraft`,
)

// And no frame may invent load out of nothing — the leak had a mirror image, and this is it.
const worstFrame = Math.max(...levelNoWind.frames.map(frameLoad))
expect(
  worstFrame <= aircraftKN(levelNoWind) * 1.02,
  `a frame reacts ${worstFrame.toFixed(0)} kN, more than the ${aircraftKN(levelNoWind).toFixed(0)} kN the arrival demands`,
)

const noseIds = FLEET_TIRES.filter((t) => t.gear === 'nose').map((t) => t.id)
expect(
  noseIds.every((id) => levelNoWind.summary.perWheel[id].peakLoadKN > 0),
  `nose gear carries no load: ${noseIds.map((id) => `${id}=${levelNoWind.summary.perWheel[id].peakLoadKN.toFixed(0)} kN`).join(' ')} — it must pick up load once it derotates onto the runway`,
)

// 8° of bank puts one truck down first. Six wheels then have to react what twelve were sharing, so
// each sees roughly double — the page's headline scenario, and the one the spec sells. This is not a
// coefficient anyone tuned; it is division, and it should land on 2.00.
const bankedPerWheel = banked.summary.perWheel.R1.peakLoadKN
const levelPerWheel = levelNoWind.summary.perWheel.L1.peakLoadKN
expect(
  bankedPerWheel / levelPerWheel > 1.8,
  `one-truck touchdown should roughly double per-wheel load (spec says "up to 2x"): ${bankedPerWheel.toFixed(0)} kN vs ${levelPerWheel.toFixed(0)} kN wings-level = ${(bankedPerWheel / levelPerWheel).toFixed(2)}x`,
)
// The strut has to still be near its peak while only one truck is down, or the doubling is a fiction
// the summary tells that the timeline never actually lives through.
const bankedPeakS = banked.summary.oleo.samples.reduce((a, s) => (s.loadKN > a.loadKN ? s : a)).tS
expect(bankedPeakS < 0.55, `the arrival must peak while one truck is still carrying it: peak at ${bankedPeakS.toFixed(2)}s, other truck lands at 0.55s`)

// --- BOGIE PITCH. The six-wheel truck hangs tilted and lands on ONE axle, which carries the whole
// truck alone until the strut strokes far enough to rotate it flat. That axle takes a load transient
// and does the spin-up nearly by itself — and *this* is the reason six tyres on one bogie do not wear
// alike. The page has L1..L6 as six separate tyres with six separate wear histories; before this they
// were mechanically identical and the whole per-axle story was fiction.
const leadIds = FLEET_TIRES.filter((t) => t.gear !== 'nose' && t.axle === LEAD_AXLE).map((t) => t.id)
const trailIds = FLEET_TIRES.filter((t) => t.gear !== 'nose' && t.axle !== LEAD_AXLE).map((t) => t.id)
assert.ok(leadIds.length === 4 && trailIds.length === 8, 'a six-wheel truck has one lead axle and two behind it, per side')

// The lead axle is the only thing on the ground for the first instants of the landing.
const firstContact = levelNoWind.frames.find((f) => f.gearLoadKN > 0)!
const touching = Object.entries(firstContact.wheel).filter(([, w]) => w.contact).map(([id]) => id)
assert.ok(
  touching.length > 0 && touching.every((id) => leadIds.includes(id)),
  `only the lead axle should be down at first contact: ${touching.join(',')}`,
)

// It therefore does most of the scrubbing, because spin-up happens while it is still alone down there.
const leadScrub = leadIds.reduce((a, id) => a + levelNoWind.summary.perWheel[id].scrubMm, 0) / leadIds.length
const trailScrub = trailIds.reduce((a, id) => a + levelNoWind.summary.perWheel[id].scrubMm, 0) / trailIds.length
assert.ok(leadScrub > trailScrub * 1.15, `the axle that lands first must scrub harder: lead ${leadScrub.toFixed(4)} vs ${trailScrub.toFixed(4)} mm`)
// ...and it eats a load transient the others never see.
const leadLoad = Math.max(...leadIds.map((id) => levelNoWind.summary.perWheel[id].peakLoadKN))
const trailLoad = Math.max(...trailIds.map((id) => levelNoWind.summary.perWheel[id].peakLoadKN))
assert.ok(leadLoad > trailLoad, `the axle that lands first must see the higher peak load: ${leadLoad.toFixed(0)} vs ${trailLoad.toFixed(0)} kN`)

// But the forward axle is not simply the lucky one: braking drags at the contact patch, below the truck
// pivot, so the truck pitches forward onto its nose. Punished on arrival, punished on the brakes.
const fwdIds = FLEET_TIRES.filter((t) => t.gear !== 'nose' && t.axle === 0).map((t) => t.id)
const heavyBrake = simulateLandingRun({ landing: { ...landing, brakeShare: 1 }, attitude, track, tires: FLEET_TIRES, selectedTireId })
const lightBrake = simulateLandingRun({ landing: { ...landing, brakeShare: 0.2 }, attitude, track, tires: FLEET_TIRES, selectedTireId })
const fwdBrakeMJ = (r: typeof run) => fwdIds.reduce((a, id) => a + r.summary.perWheel[id].brakeMJ, 0)
const aftBrakeMJ = (r: typeof run) => FLEET_TIRES.filter((t) => t.axle === 2 && t.gear !== 'nose').reduce((a, t) => a + r.summary.perWheel[t.id].brakeMJ, 0)
assert.ok(
  fwdBrakeMJ(heavyBrake) / aftBrakeMJ(heavyBrake) > fwdBrakeMJ(lightBrake) / aftBrakeMJ(lightBrake),
  'harder braking should pitch the truck forward and work the front axle harder',
)

// Conservation still holds through all of it — the truck redistributing load must not create any.
conserves(heavyBrake, 'bogie pitch under heavy braking')

// A normal arrival must not be reported as bursting tyres. The lead axle runs over its rated load —
// landing transients are allowed to, and this one does by ~1.1x — but the flag is for real overloads.
assert.ok(!levelNoWind.summary.flags.some((f) => /overloaded/i.test(f)), 'a normal landing must not cry overload')

// A banked slam, though, lands the whole aeroplane on ONE truck's ONE leading axle: two tyres, for a
// moment, carrying two hundred tonnes. That really does burst tyres, and it is the single most useful
// thing this page can tell a tyre shop — and it was unreachable until the bogie pitched.
const slam = simulateLandingRun({ landing: { ...landing, sinkFpm: 720 }, attitude: { ...attitude, rollDeg: 8 }, track, tires: FLEET_TIRES, selectedTireId: 'R5' })
const worstTire = FLEET_TIRES.filter((t) => t.gear !== 'nose').reduce((a, t) => (slam.summary.perWheel[t.id].peakLoadKN > slam.summary.perWheel[a.id].peakLoadKN ? t : a))
assert.equal(worstTire.axle, LEAD_AXLE, 'the worst-loaded tyre in a slam must be on the axle that lands first')
assert.ok(slam.summary.perWheel[worstTire.id].peakLoadKN > worstTire.ratedLoadKN * 1.5, 'a banked slam must overload the leading axle')
assert.ok(slam.summary.flags.some((f) => /overloaded/i.test(f)), 'and it has to say so, by name and by multiple')
assert.equal(slam.summary.status, 'action', 'an overloaded tyre is actionable')
conserves(slam, 'banked slam onto one axle')

// --- SPIN-UP AND THE CONTACT PATCH. The tyre arrives at 140 kt not turning at all, and is dragged up
// to speed by friction. Until it gets there the tread is *sliding*, and that slide is where the rubber
// goes. Which arc of tread pays depends on where the wheel happened to have stopped last time.
const frameOf = (r: typeof run, phase: string) => r.frames.find((f) => f.phase === phase)!
const td = frameOf(levelNoWind, 'touchdown')
assert.ok(td.wheel.L5.slipMps > 60, `at touchdown the tread is sliding at nearly the full groundspeed: ${td.wheel.L5.slipMps.toFixed(0)} m/s`)
const rolling = levelNoWind.frames.find((f) => f.tS > td.tS + 1)!
assert.ok(rolling.wheel.L5.slipMps < 0.5, `once it is up to speed it rolls, and rolling costs nothing: ${rolling.wheel.L5.slipMps.toFixed(1)} m/s`)
// Slip has to fall monotonically as the wheel spins up — a tyre cannot start sliding again by itself.
const slips = levelNoWind.frames.filter((f) => f.tS >= td.tS && f.tS < td.tS + SPINUP_S).map((f) => f.wheel.L5.slipMps)
assert.ok(
  slips.every((s, i) => i === 0 || s <= slips[i - 1] + 1e-9),
  'slip must fall monotonically through spin-up',
)

// The contact patch runs *round* the tyre as it turns — it is a different arc of tread every instant.
const angles = levelNoWind.frames.filter((f) => f.tS >= td.tS && f.tS < td.tS + 0.4).map((f) => f.wheel.L5.contactDeg)
assert.ok(new Set(angles.map(Math.round)).size > 3, 'the contact point must move around the tyre as it spins up')
// And each tyre lands on its own arc: the clocking is arbitrary, which is the whole point.
assert.notEqual(levelNoWind.summary.perWheel.L5.impactDeg, levelNoWind.summary.perWheel.L1.impactDeg, 'two tyres should not land on the same arc by construction')

// The patch is longer the harder the tyre is squashed — a hard landing touches more rubber at once.
const hardHit = simulateLandingRun({ landing: { ...landing, sinkFpm: 600 }, attitude, track, tires: FLEET_TIRES, selectedTireId })
assert.ok(
  hardHit.summary.perWheel.L5.impactArcDeg > levelNoWind.summary.perWheel.L5.impactArcDeg,
  `a harder arrival should flatten the tyre onto a longer arc: ${hardHit.summary.perWheel.L5.impactArcDeg.toFixed(0)}° vs ${levelNoWind.summary.perWheel.L5.impactArcDeg.toFixed(0)}°`,
)
assert.ok(levelNoWind.summary.perWheel.L5.impactArcDeg > 20 && levelNoWind.summary.perWheel.L5.impactArcDeg < 140, 'a real contact patch is tens of degrees of the circumference, not a point and not the whole tyre')

const crabbed = simulateLandingRun({ landing: { ...landing, crosswindKt: 0 }, attitude: { ...attitude, crabDeg: 12 }, track, tires: FLEET_TIRES, selectedTireId })
const mainIds = FLEET_TIRES.filter((t) => t.gear !== 'nose').map((t) => t.id)
const fleetScrub = (r: typeof run) => mainIds.reduce((a, id) => a + r.summary.perWheel[id].scrubMm, 0)
// Crab costs the fleet rubber overall...
assert.ok(fleetScrub(crabbed) > fleetScrub(levelNoWind), 'crab should add lateral scrub across the fleet')
// ...but it does NOT cost every tyre the same, and the old assertion (`L1 scrub goes up`) was quietly
// asserting that it did. A crab rolls load onto one truck: those tyres are pressed harder and scrub
// more, while the other is *unloaded* and scrubs slightly less. Attributing the wear evenly across the
// bogies is precisely the mistake this page exists to stop someone making.
//
// Which truck? The one the tyres are pushing away from — an aeroplane leans out of a crab exactly like
// a car leans out of a turn, onto its outer wheels. A nose-right crab therefore loads the LEFT gear.
assert.ok(crabbed.summary.perWheel.L1.peakLoadKN > crabbed.summary.perWheel.R1.peakLoadKN, 'a nose-right crab should lean the aircraft onto the left gear')
assert.ok(crabbed.summary.perWheel.R1.peakLoadKN < levelNoWind.summary.perWheel.R1.peakLoadKN, 'the other truck should be unloaded, not merely less loaded')
// Compare each truck against its own wings-level baseline rather than against each other: these are
// real tyres with real defects and real pressures, so R1 already out-scrubs L1 before anyone crabs
// anything. Comparing them directly measures the fleet's condition, not the manoeuvre.
assert.ok(crabbed.summary.perWheel.L1.scrubMm > levelNoWind.summary.perWheel.L1.scrubMm, 'the truck the crab leans onto should scrub more than it did wings-level')

// NOTE: this fixture crabs with *no* crosswind, which means the aircraft is also flying sideways
// through the air — so it carries a real aero sideslip force (~250 kN) as well as the tyre force
// (~286 kN). Laterally those add; in roll they oppose, because one acts at CG height and the other at
// the ground. The net roll transfer is therefore the small difference of two large, roughly-estimated
// numbers, and it is not worth asserting a magnitude on. The crosswind cases below are the ones where
// the physics is unambiguous, and they are the ones anybody actually flies.

const lightBraking = simulateLandingRun({ landing: { ...landing, brakeShare: 0.25 }, attitude, track, tires: FLEET_TIRES, selectedTireId })
assert.ok(lightBraking.summary.stopDistM > run.summary.stopDistM, 'engine stop distance should follow brake share')
assert.ok(lightBraking.frames.length > run.frames.length, 'timeline should show longer slowing-down with less braking')

const lifted = simulateLandingRun({ landing, attitude: { ...attitude, liftShare: 0.5 }, track, tires: FLEET_TIRES, selectedTireId })
assert.ok(lifted.summary.perWheel.L1.peakLoadKN < run.summary.perWheel.L1.peakLoadKN, 'lift remaining should reduce touchdown wheel load')
assert.ok(lifted.summary.stopDistM > run.summary.stopDistM, 'lift remaining should delay full wheel braking')

const tailstrike = simulateLandingRun({ landing, attitude: { ...attitude, pitchDeg: 12 }, track, tires: FLEET_TIRES, selectedTireId })
assert.ok(tailstrike.summary.stopDistM > run.summary.stopDistM, 'high flare pitch should float farther down the runway')
assert.ok(tailstrike.summary.flags.some((f) => /tailstrike/i.test(f)), 'high pitch should raise a tailstrike risk flag')

const deflated = FLEET_TIRES.map((t) => (t.id === selectedTireId ? { ...t, psi: t.psiTarget * 0.9 } : t))
const deflatedRun = simulateLandingRun({ landing, attitude, track, tires: deflated, selectedTireId })
assert.ok(deflatedRun.summary.perWheel.L1.scrubMm > run.summary.perWheel.L1.scrubMm, 'per-wheel underinflation should increase that wheel scrub')

const wornFleet = FLEET_TIRES.map((t) =>
  t.gear === 'nose'
    ? t
    : {
        ...t,
        grooves: [t.grooveLimit + 0.2, t.grooveLimit + 0.25, t.grooveLimit + 0.3, t.grooveLimit + 0.2],
        defects: [...t.defects, { kind: 'damage' as const, label: 'check high defect', severity: 'high' as const, zone: 'Tread', at: [0, 0, 0] as [number, number, number], r: 0.2 }],
      },
)
const wornRun = simulateLandingRun({ landing, attitude, track, tires: wornFleet, selectedTireId })
assert.ok(wornRun.summary.stopDistM > run.summary.stopDistM, 'worn/damaged fleet should reduce braking grip')
assert.ok(wornRun.summary.perWheel.L1.scrubMm > run.summary.perWheel.L1.scrubMm, 'worn/damaged selected wheel should increase scrub')
assert.ok(wornRun.summary.flags.some((f) => /defect|tread/i.test(f)), 'worn/damaged selected wheel should raise condition flags')

const lowRwyccTrack = { ...track, rwycc: 2 }
const lowRwyccRun = simulateLandingRun({ landing, attitude, track: lowRwyccTrack, tires: FLEET_TIRES, selectedTireId })
assert.ok(lowRwyccRun.summary.stopDistM > run.summary.stopDistM, 'low RWYCC track should reduce braking grip')
assert.ok(lowRwyccRun.summary.flags.some((f) => /RWYCC 2/.test(f)), 'low RWYCC should raise a runway-condition flag')

const overrun = simulateLandingRun({ landing: { ...landing, gsKt: 175, surface: 'contaminated', runwayM: 800 }, attitude, track, tires: FLEET_TIRES, selectedTireId })
assert.equal(overrun.frames.at(-1)?.phase, 'overrun', 'short contaminated runway should end as overrun')

// --- CROSSWIND → CRAB. Before this coupling you could dial 35 kt of crosswind against 0° of crab and
// the model would happily simulate a landing that cannot physically happen.
const xwind = { ...landing, crosswindKt: 30, surface: 'dry' as const }
const needed = driftAngleDeg(xwind)
assert.ok(needed > 10 && needed < 16, `30 kt of crosswind at 138 kt needs a real crab angle: got ${needed.toFixed(1)}°`)

const drifting = simulateLandingRun({ landing: xwind, attitude, track, tires: FLEET_TIRES, selectedTireId })
assert.ok(drifting.summary.flags.some((f) => /Drifting/.test(f)), 'crosswind with no crab should say the aircraft is drifting')
// ...and the drift is not free: the gear takes it as side load, onto the downwind truck.
assert.ok(drifting.summary.perWheel.R1.peakLoadKN > drifting.summary.perWheel.L1.peakLoadKN * 1.05, 'uncorrected crosswind should roll load onto the downwind gear')

// Crab it out properly and the airframe stops being pushed sideways — the drift is gone.
const crabbedIn = simulateLandingRun({ landing: xwind, attitude: { ...attitude, crabDeg: -needed }, track, tires: FLEET_TIRES, selectedTireId })
assert.ok(!crabbedIn.summary.flags.some((f) => /Drifting|Over-crabbed/.test(f)), 'a correctly crabbed landing should not flag drift')

// But the side load does NOT go away, and this is the honest and slightly unwelcome finding: crabbing
// converts an aerodynamic push into a tyre scrub. It still lands on the downwind truck, because the
// yawed wheels lean the aircraft the same way the wind was pushing it. There is no crab angle that
// makes a crosswind free — you only choose whether the gear pays in drift or the tread pays in rubber.
assert.ok(crabbedIn.summary.perWheel.R1.peakLoadKN > crabbedIn.summary.perWheel.L1.peakLoadKN, 'a crabbed crosswind landing still loads the downwind truck')
assert.ok(crabbedIn.summary.perWheel.R1.scrubMm > drifting.summary.perWheel.R1.scrubMm, 'crabbing trades the drift for scrub — the downwind tyre pays in rubber')

// --- HYDROPLANING. Horne: Vp ≈ 9·√psi. A main at its 215 psi target rides up on water above ~132 kt,
// which is BELOW a normal touchdown speed — so on standing water the tyres are aquaplaning on arrival
// and the brakes have nothing to push against until they slow below Vp.
assert.ok(Math.abs(hydroplaneSpeedKt(215) - 132) < 2, `Horne's number should hold: ${hydroplaneSpeedKt(215).toFixed(0)} kt at 215 psi`)
// A damp runway is NOT standing water — it must not aquaplane, only lose µ.
assert.ok(!canHydroplane('wet'), 'a merely wet runway should not hydroplane — that is what its lower µ is for')

const flooded = { ...landing, surface: 'contaminated' as const, runwayM: 4000 }
const floodedRun = simulateLandingRun({ landing: flooded, attitude, track: { ...track, surface: 'contaminated' }, tires: FLEET_TIRES, selectedTireId })
assert.ok(floodedRun.summary.flags.some((f) => /Hydroplaning/.test(f)), 'standing water at touchdown speed should flag hydroplaning')
assert.equal(floodedRun.summary.flags.filter((f) => /Hydroplaning/.test(f)).length, 1, 'hydroplaning should be said once, not twice')

// The product's entire argument, in one assertion: psi is a stop-distance number. Let one main down to
// 160 psi — still inflated, still flying — and it starts aquaplaning 18 kt earlier than the rest,
// which is worth hundreds of metres of runway that nobody would have attributed to a tyre.
const soft = FLEET_TIRES.map((t) => (t.id === 'L3' ? { ...t, psi: 160 } : t))
const softRun = simulateLandingRun({ landing: flooded, attitude, track: { ...track, surface: 'contaminated' }, tires: soft, selectedTireId })
assert.ok(softRun.summary.stopDistM > floodedRun.summary.stopDistM + 200, `one soft tyre should cost real runway: ${(softRun.summary.stopDistM - floodedRun.summary.stopDistM).toFixed(0)} m`)
assert.ok(softRun.summary.flags.some((f) => /L3 goes first/.test(f)), 'the softest tyre should be named as the one that gives up first')
// On a dry runway the same soft tyre costs nothing at all — there is no water to ride up on.
const softDry = simulateLandingRun({ landing, attitude, track, tires: soft, selectedTireId })
assert.ok(Math.abs(softDry.summary.stopDistM - run.summary.stopDistM) < 50, 'a soft tyre should not hydroplane on a dry runway')

if (bugs.length) {
  console.error(`\nlanding engine: ${bugs.length} CONSERVATION FAILURES — the per-wheel load model does not obey Newton\n`)
  for (const b of bugs) console.error(`  ✗ ${b}\n`)
  console.error('Every directional assertion above this passes — that is the point of these. See web/PHYSICS_REVIEW.md.')
  console.error('Load shares come from wheelLoadsKN(), a moment balance. If these fail, a share stopped adding up.\n')
  process.exit(1)
}

console.log('landing engine ok ·', {
  frames: run.frames.length,
  phase: run.frames.at(-1)?.phase,
  stopM: Math.round(run.summary.stopDistM),
  selectedLoadKN: Math.round(run.summary.perWheel.L1.peakLoadKN),
})
