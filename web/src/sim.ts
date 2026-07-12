// Landing-event model. Pure functions, no React — so the numbers can be checked without a browser
// (`npm run check:sim`) and later swapped for the real FOQA-fitted model behind the same shape.

export type Surface = 'dry' | 'wet' | 'contaminated'

export type Landing = {
  weightT: number // landing weight
  sinkFpm: number // vertical speed at touchdown
  gsKt: number // indicated approach speed — true speed over the ground rises with field elevation
  brakeShare: number // 0..1 — fraction of kinetic energy taken by brakes (rest: reverse thrust + drag)
  oatC: number
  surface: Surface
  elevFt: number // field elevation — thin air means a faster touchdown for the same indicated speed
  runwayM: number // landing distance available; what the stop has to fit inside
  runwayHeadingDeg: number // which way the runway points. Wind means nothing without it.

  /**
   * The wind, as an actual wind: a speed, and the direction it blows *from*, in degrees true.
   *
   * This used to be a lone `crosswindKt`, which meant the model had no headwind at all — so a 30 kt
   * wind could only ever *lengthen* the stop, through a directional-control penalty. A headwind is the
   * cheapest runway you will ever get, and this aircraft could not feel one.
   *
   * Both components now come off one vector against the runway heading, so they cannot contradict each
   * other: point the wind down the runway and it is all headwind; point it across and it is all
   * crosswind. Nothing has to be kept in sync by hand.
   */
  windKt: number
  windDirDeg: number

  /**
   * Anti-skid — the thing standing between a hard stop and a scrapped tyre.
   *
   * On, it modulates brake pressure to hold the tyre near the peak of its friction curve, and the
   * wheel will not lock however hard the pedal is pushed. Off, a brake demand the runway cannot
   * support stops the wheel dead — and a locked wheel does not roll, it *grinds*, taking one arc of
   * tread down towards the carcass.
   */
  antiskid: boolean
}

const RAD = Math.PI / 180

/** Wind straight down the runway. Positive is a headwind — free runway. Negative is a tailwind. */
export function headwindKt(l: Landing) {
  return l.windKt * Math.cos((l.windDirDeg - l.runwayHeadingDeg) * RAD)
}

/** Wind across the runway: the component that has to be crabbed out, and that scrubs the tyres. */
export function crosswindKt(l: Landing) {
  return l.windKt * Math.sin((l.windDirDeg - l.runwayHeadingDeg) * RAD)
}

// Where the gear actually is. These are measurements of a 777-300ER, not knobs — you look them up,
// you don't tune them, and they are what let the per-wheel loads come from a moment balance instead of
// a hand-fitted skew factor. Everything below that used to be guessed is now derived from these four.
export const GEAR = {
  wheelbaseM: 31.22, // nose gear to main-gear centroid
  trackM: 12.9, // between the two main-gear centrelines
  cgAheadOfMainsM: 1.56, // CG sits just forward of the mains — this alone sets the static nose share
  cgHeightM: 5.5, // CG above the ground. The lever that turns braking into nose load and side force
  // into roll transfer; nothing works without it and it is why a tall aircraft transfers so much.
  muSide: 0.6, // tyre side-force coefficient at the contact patch

  /**
   * The six-wheel truck does not land flat. The truck positioner holds it tilted in flight, so one
   * axle reaches the runway before the other two and carries the whole truck on its own until the
   * strut strokes far enough to rotate it level. That axle takes a load transient and does the
   * spin-up almost by itself — and *that* is why the six tyres on one bogie do not wear alike.
   *
   * On the 777 the truck hangs nose-up, so the AFT axle leads. The mechanism is certain; if the sign
   * turns out to be wrong against the gear spec, flip this one flag and every consequence follows.
   */
  bogieAftAxleFirst: true,
  /**
   * How far the airframe has to sink before the truck has rotated flat and the front axle reaches the
   * runway — geometrically, the height the tilt holds the front axle at (truck length × sin of tilt).
   *
   * Measured on the airframe's *total* drop (tyre squash + strut stroke), not on strut stroke alone.
   * That distinction is not pedantry: the tyre is much softer than the strut, so nearly 10 cm of the
   * first movement is rubber. Gate the truck on strut stroke and it stays tilted right through the
   * load building to 86 % of its peak, which put 6.5x a tyre's rated load on the axle that lands
   * first. It is a burst, and it is an artefact.
   */
  bogieLevelDropM: 0.12,
  // Braking drags at the contact patch, below the truck pivot, so the truck tries to rotate forward
  // and leans on its front axle. This is the counterpart to the touchdown transient, and it is why the
  // forward tyres are not simply the lucky ones.
  bogieBrakePitchPerG: 0.45,
}

// The static nose share is not a free parameter any more — it is a consequence of where the CG sits.
export const staticNoseShare = GEAR.cgAheadOfMainsM / GEAR.wheelbaseM // ≈ 0.05

/**
 * The oleo, as an actual strut: a gas spring in series with an orifice damper. Lumped — one equivalent
 * strut standing for both main legs, so `pistonAreaM2` and `gasVolM3` are the pair.
 *
 * The old model was `peakG = 1 + v²/(2·g·stroke)`, which is the work–energy answer for a strut applying
 * *constant* force through its whole stroke. Nothing in it stores energy, so nothing could ever come
 * back out — no rebound, no bounce, and a load history that went straight to peak and stayed there.
 * The gas spring is what gives the energy back, and the asymmetric damping is what stops it giving
 * back too much.
 */
export const OLEO = {
  strokeM: 0.55, // 777 main oleo, fully extended to fully compressed
  gasColumnM: 0.62, // gas column at full extension (V₀/A — the piston area cancels out of the curve)
  preloadKN: 1179, // P₀·A — sets the rate. Under full weight the strut settles at ~0.32 m of stroke.
  gamma: 1.35, // polytropic exponent. A touchdown is fast, so the compression is adiabatic, not slow.
  // The gas column is deliberately short, which makes the spring steeply nonlinear. A softer one (an
  // earlier cut of this had 1.2 m) needs so much damping to reach a believable peak load that the
  // damper ends up doing all the work: the strut hydraulically locks, strokes barely 2 cm past static,
  // and gives almost nothing back. A stiff spring reaches the same peak by *storing* the energy, which
  // is the only way to get any of it back out — no spring, no recoil.
  //
  // Orifice damping, force ∝ ẋ|ẋ|. Rebound is 2.3x compression: the recoil orifice is the smaller one.
  cCompressNs2M2: 3.5e5,
  cReboundNs2M2: 8.0e5,
  // A small *linear* term as well (seal friction, viscous leakage). Without it the damping vanishes as
  // ẋ → 0, so the strut rings almost undamped around its static point and never settles — the model
  // sat 7 % above the aircraft's own weight eight seconds after landing, and reported its "peak" at
  // t = 2.5 s, which was not the touchdown at all but the strut overshooting as the spoilers dumped.
  cLinearNsM: 4.0e5,
  // The tyres, as the spring they are. They sit in series *below* the strut and they are what actually
  // touches the runway, so the gear load has to come up through them — it cannot appear at full value
  // the instant the rubber kisses the tarmac. Leave them out (as this did, twice) and the damper hands
  // the aeroplane 3.5 MN at t=0 with 3 mm of stroke, which is not a landing, it is a collision.
  tyreNPerM: 2.6e7, // twelve mains, ~2.2 MN/m each: rated load at ~0.12 m of deflection
  tyreDampNsM: 2.0e4, // just enough to stop the tyre mode ringing on its own
  unsprungKg: 5000, // both bogies, wheels and brakes — the mass between the strut and the road
  // Calibration: a normal arrival (240 fpm) lands on ~1.13 G, which is what a FOQA trace reads, and
  // the hard-landing flag trips around 700 fpm. FAR 25.473's design limit descent (600 fpm) sits just
  // under it at ~1.5 G — and bounces, which is the honest answer: a landing that hard really does
  // come back off the runway. Swap these for a real gear spec and the shape holds.
}

export type OleoSample = {
  tS: number
  strokeM: number // oleo compression
  tyreM: number // tyre squash — small, but it is the first thing to move
  hM: number // how far the tyres are off the runway, if it bounced
  loadKN: number
  airborne: boolean
  /** How far the airframe has dropped from where it sat at first contact: stroke + tyre, less any
   *  bounce. This is what the aircraft in the 3D scene has to actually *do* — without it the strut
   *  compresses, recoils and bounces entirely inside the numbers while the aeroplane hangs rigid. */
  dropM: number
}
export type OleoRun = {
  peakG: number
  peakLoadKN: number // total, through both main gears
  bounces: number
  maxBounceM: number
  bottomedOut: boolean // stroke ran out — the strut is no longer absorbing, the airframe is
  samples: OleoSample[]
}

/**
 * Total force the two struts push back on the airframe with, at a given compression and rate.
 *
 * Note the `− 1`. At full extension the gas is already pressurised, but that preload is reacted
 * *inside the gear*, against its own extension stops and the weight of the bogie hanging below — the
 * airframe does not feel it. What the airframe feels is the force in *excess* of the preload, which is
 * zero at first contact and climbs as the strut strokes. Leave the `− 1` out and the aeroplane gets
 * handed a meganewton the instant the tyres kiss the runway, which flings it back into the air on
 * every single landing. (Strictly this is the tyre spring, in series and much softer, deflecting until
 * the strut breaks free. Folding it into the preload term is the cheap way to get the same start.)
 */
function strutForceN(x: number, xdot: number) {
  const remaining = OLEO.gasColumnM - Math.min(x, OLEO.strokeM)
  const compression = (OLEO.gasColumnM / Math.max(remaining, 1e-4)) ** OLEO.gamma
  const gasN = OLEO.preloadKN * 1000 * (compression - 1)
  const orificeN = (xdot >= 0 ? OLEO.cCompressNs2M2 : OLEO.cReboundNs2M2) * xdot * Math.abs(xdot)
  const viscousN = OLEO.cLinearNsM * xdot
  // A strut can push. It cannot pull the aeroplane back down onto the runway.
  return Math.max(0, gasN + orificeN + viscousN)
}

/**
 * Integrate the touchdown. One degree of freedom (the strut), forward Euler at 1 ms — the impact is
 * over in half a second, so this is cheap, and 50 ms steps would step straight over the peak.
 *
 * `liftShare` is the fraction of weight the wing is still carrying, decaying to nothing as the
 * spoilers deploy. It is a *force*, not a scale factor on the answer: the strut has to arrest the
 * aircraft's downward momentum whether or not the wing is still flying, but it only has to *hold the
 * weight up* once the wing stops doing it. The old model multiplied the whole result by (1 − lift),
 * which quietly claimed a 90 %-lift arrival barely touches the gear. It does.
 */
export function oleoResponse(o: { massKg: number; vSinkMps: number; liftShare: number; spoilerS: number; durationS?: number; dtS?: number }): OleoRun {
  const dt = o.dtS ?? 0.001
  const duration = o.durationS ?? 5
  const ms = Math.max(1, o.massKg - OLEO.unsprungKg) // airframe
  const mu = OLEO.unsprungKg // bogies, wheels, brakes

  let x = 0 // strut stroke
  let tyre = 0 // tyre deflection — the runway squashing the rubber
  let vs = Math.max(0, o.vSinkMps) // airframe, down positive
  let vu = vs // unsprung: arrives with the aircraft
  let h = 0 // how far the tyres are off the runway, if it has bounced
  let airborne = false
  let peakN = 0
  let bounces = 0
  let maxBounceM = 0
  let bottomedOut = false
  const samples: OleoSample[] = []

  for (let t = 0; t <= duration + dt / 2; t += dt) {
    const lift = o.liftShare * Math.max(0, 1 - t / Math.max(o.spoilerS, 1e-3))
    const liftN = o.massKg * G * lift // the wing's share, held at the airframe
    let tyreN = 0

    if (airborne) {
      // Off the ground: only gravity and whatever the wing is still making.
      vs += ((ms * G - liftN) / ms) * dt
      vu = vs
      h -= vs * dt
      if (h <= 0) {
        h = 0
        airborne = false // and it arrives a second time, which is the whole point of modelling this
      }
    } else {
      const strutN = strutForceN(x, vs - vu)
      // The runway pushes on the tyre; the tyre pushes on the bogie; the strut pushes on the airframe.
      // Load reaches the aeroplane through the rubber, so it starts at zero and climbs — which is the
      // whole reason for carrying the unsprung mass rather than lumping it in with the airframe.
      //
      // And how MUCH rubber is under it changes as it lands. The truck comes down tilted, so for the
      // first fraction of a second only its lead axle is touching: a third of the tyres, a third of the
      // spring, and therefore a load that builds three times more slowly. Assume all twelve are down
      // from the first millisecond (as this did) and the lead axle gets charged for a stiffness that is
      // not underneath it yet — which reported 627 kN on a tyre rated to 265, i.e. a burst.
      const level = Math.min(1, (x + tyre) / GEAR.bogieLevelDropM)
      const kTyre = OLEO.tyreNPerM * ((1 - level) / 3 + level)
      tyreN = Math.max(0, kTyre * tyre + OLEO.tyreDampNsM * vu)
      vs += ((ms * G - liftN - strutN) / ms) * dt
      vu += ((mu * G + strutN - tyreN) / mu) * dt
      x += (vs - vu) * dt
      tyre += vu * dt

      if (x >= OLEO.strokeM) {
        x = OLEO.strokeM // out of stroke: past here the airframe absorbs what the gear could not
        bottomedOut = true
        if (vs > vu) vs = vu
      }
      if (x < 0) {
        x = 0
        if (vs < vu) vs = vu
      }
      if (tyre <= 0) {
        tyre = 0
        // The rubber has left the runway. If it is still going up, so has the aeroplane.
        if (vu < -0.05) {
          airborne = true
          bounces++
          vs = vu
        } else if (vu < 0) vu = 0
      }
    }

    peakN = Math.max(peakN, tyreN)
    maxBounceM = Math.max(maxBounceM, h)
    samples.push({ tS: +t.toFixed(3), strokeM: x, tyreM: tyre, hM: h, loadKN: tyreN / 1000, airborne, dropM: x + tyre - h })
  }

  // Load factor is quoted against the whole aircraft, which is what a FOQA trace would show.
  return { peakG: peakN / (o.massKg * G), peakLoadKN: peakN / 1000, bounces, maxBounceM, bottomedOut, samples }
}

/** Total main-gear load at a given time after touchdown. */
export function oleoLoadKNAt(run: OleoRun, tS: number) {
  const i = Math.round(tS / Math.max(1e-6, run.samples[1].tS - run.samples[0].tS))
  return run.samples[Math.min(Math.max(0, i), run.samples.length - 1)].loadKN
}

// ponytail: these are the calibration knobs — first-order physics with fitted coefficients, not a
// gear model. Refit each against FOQA once real landings are joined to serials; the shapes hold.
export const CAL = {
  mainGearShare: 1 - staticNoseShare, // ≈ 0.95, and now derived rather than asserted
  mainWheels: 12, // 777-300ER: two six-wheel bogies
  // (`strokeM: 0.45` used to live here — the single fudged stroke that `1 + v²/(2·g·s)` divided by.
  //  It is gone. The strut has a real stroke now, and it is in OLEO where the rest of the gear is.)
  scrubK: 0.035, // mm of tread per landing at reference load + reference speed
  refGsKt: 140,
  // The 777 has carbon brakes, not steel: ~110 kg of pack at ~900 J/kg·K. The old 45_000 was a steel
  // pack, and it was half the truth — it had been fitted against a 62 t aircraft (see below), so the
  // two errors cancelled and a normal landing came out at a believable 80 °C bead. At the real weight
  // they stop cancelling and every landing blows a fuse plug. Both numbers move together or neither.
  brakeHeatSinkJK: 100_000,
  // The bead is a *second* thermal mass, not a fraction of the first. Heat has to conduct out of the
  // brake pack, through the wheel, into the bead — and that takes time. The old `beadSoak: 0.2` said
  // the bead was hottest at the moment the wheels stopped, which is backwards: the pack is being
  // blasted with cooling air right up until the aircraft parks, and only *then* does the heat soak
  // inward. Fuse plugs release on the taxiway and at the gate, ten to thirty minutes after landing —
  // never on the runway. For an app whose job is the turnaround call, that timing IS the answer.
  beadHeatSinkJK: 60_000, // wheel rim + bead: ~65 kg of aluminium
  packToBeadWPerK: 35, // conduction, pack -> wheel -> bead. Slow, and that slowness is the point.
  packCoolWPerK: 60, // pack -> air, parked. Low: a hot brake pack takes 30-60 min to come down, which
  // is precisely why brake cooling schedules exist and why a quick turn is a real constraint.
  packCoolRollingWPerK: 600, // pack -> air while it is still moving and the air is being forced over it
  beadCoolWPerK: 35, // bead -> air
  soakWindowS: 2700, // watch it for 45 minutes: long enough to see the bead peak and start falling
  fusePlugC: 180, // fusible plug releases here — tire deflates rather than bursts
  gLimit: 1.8, // FOQA hard-landing flag
  tasPctPer1000ft: 2, // thin air: true (and ground) speed climbs ~2 % per 1000 ft for the same IAS
  marginM: 300, // stop margin below this is uncomfortably tight, even though it isn't an overrun
  // Nothing decelerates at touchdown: the nose has to come down, spoilers deploy, reversers unstow,
  // brakes take hold. At 70 m/s those seconds are most of a kilometre, and leaving them out made a
  // 777 stop in 640 m — which would have made every runway in the list look roomy.
  rolloutDelayS: 5,
  // At Vref the wing is still carrying the aeroplane — it does not stop flying because the wheels
  // touched. Lift decays as the spoilers deploy, and only then does the gear take the weight. This is
  // why the strut mostly has to arrest *momentum* at touchdown, not hold up 200 tonnes.
  liftAtTouchdown: 0.9,
  spoilerDumpS: 2,
  brakeDecelBase: 0.72, // baseline wheel braking effectiveness before brake-share input
  brakeDecelGain: 0.5, // higher brake share means harder wheel braking and a shorter rollout
  crosswindDecelLossMax: 0.12, // directional-control margin: strong crosswind costs braking efficiency
  mu: { dry: 0.4, wet: 0.25, contaminated: 0.15 } as Record<Surface, number>,

  /**
   * ANTI-SKID, and what happens without it.
   *
   * `muDemand` is the friction the brakes *ask* the runway for at full pedal. If the runway cannot
   * supply it, one of two things happens, and which one is the entire difference between a hard stop
   * and a scrapped tyre:
   *
   *   - anti-skid on: it backs the pressure off and holds the tyre near the peak of its friction
   *     curve. You are µ-limited, so past a certain pedal there is nothing more to be had — but the
   *     wheel keeps turning.
   *   - anti-skid off: the wheel stops dead. And a locked wheel gives you *less* braking, not more,
   *     because sliding friction is below peak friction — so it stops you worse AND grinds a flat spot.
   */
  muDemandMax: 0.5, // friction the brakes command at 100 % pedal
  muSlideFactor: 0.7, // a sliding tyre grips less than a rolling one. Locking up is a double penalty.
  // Rubber ground off a locked tyre per MJ dissipated into its contact patch. A wheel locked for a few
  // hundred metres goes through the tread and into the carcass, which is why this is a top-3 reason
  // tyres come off aeroplanes and why anti-skid failure is a land-immediately item.
  flatSpotMmPerMJ: 0.8,
  flatSpotScrapMm: 3, // past this the tyre is scrap, not a retread candidate
  // There is only so much rubber to grind. Below the last groove there is a little more, and then
  // there is the carcass — and a tyre ground to its carcass at 60 m/s does not keep making a tidy flat
  // spot, it lets go. So the depth is capped at the rubber the tyre actually has, and past that the
  // answer stops being a number of millimetres and becomes "it burst".
  carcassMarginMm: 2,
  scrubSurface: { dry: 1, wet: 1.25, contaminated: 1.6 } as Record<Surface, number>, // slip → more scrub
  // Dynamic hydroplaning (Horne, NASA TN D-2056): above roughly 9·√psi kt the tyre stops touching the
  // runway and rides up onto a film of water. This is not a coefficient anyone fitted — it is the
  // classic result, and it is why tyre pressure is a *safety* number and not a maintenance number.
  // A 777 main at 215 psi hydroplanes above 132 kt, which is BELOW a normal touchdown speed.
  hydroplaneK: 9,
  muHydroplane: 0.05, // riding on water: the brakes have almost nothing to push against
}

// Real aerodynamics, for the side force an uncorrected crosswind puts into the gear.
export const AERO = {
  wingAreaM2: 427, // 777-300ER reference area
  cyBetaPerRad: 0.9, // side-force coefficient per radian of sideslip — typical big-jet value
  rhoKgM3: 1.225, // sea-level density; the elevation correction is already in the true groundspeed
}

export const G = 9.81
const MS_PER_FPM = 1 / 196.85
const MS_PER_KT = 0.5144

export type SimResult = ReturnType<typeof simulate>

export function simulate(l: Landing, tire: { grooves: number[]; grooveLimit: number; psi: number; psiTarget: number }) {
  const vSink = l.sinkFpm * MS_PER_FPM
  // Field elevation is not decoration: the same indicated speed is a faster touchdown up high, and
  // every energy term below goes with its square. This is the whole reason Denver is in the list.
  const vGround = trueGroundSpeedMps(l)
  const gsTrueKt = vGround / MS_PER_KT
  const massKg = l.weightT * 1000

  // Peak vertical g, from integrating the strut rather than assuming it applies a constant force.
  // The scalar model has no attitude slider, so it uses the nominal lift-on-touchdown; the engine
  // re-runs the same integration with whatever the crew actually left on the wing.
  const oleo = oleoResponse({ massKg, vSinkMps: vSink, liftShare: CAL.liftAtTouchdown, spoilerS: CAL.spoilerDumpS })
  const peakG = oleo.peakG
  const loadPerTireKN = (massKg * G * peakG * CAL.mainGearShare) / CAL.mainWheels / 1000

  // Spin-up scrub: the tire goes 0 → groundspeed against the runway. Loss scales with load and v².
  const refLoadKN = (massKg * G * CAL.mainGearShare) / CAL.mainWheels / 1000
  const scrubMm =
    CAL.scrubK *
    (loadPerTireKN / refLoadKN) *
    (gsTrueKt / CAL.refGsKt) ** 2 *
    CAL.scrubSurface[l.surface] *
    tirePressureScrubFactor(tire)

  // Braking: total kinetic energy is fixed by mass and speed; the surface only sets how far it takes.
  const keMJ = (0.5 * massKg * vGround ** 2) / 1e6
  const brakeEnergyMJ = (keMJ * l.brakeShare) / CAL.mainWheels
  // Roll at speed while the aircraft gets configured, then decelerate at whatever µ the surface gives
  // — and, on a wet runway, only once the tyre is slow enough to be touching it at all.
  const stopDistM = stopDistanceM(l, tire.psi)
  // What the runway has left over. Negative is an overrun, and no tire number matters after that.
  const stopMarginM = l.runwayM - stopDistM
  const vpKt = hydroplaneSpeedKt(tire.psi)
  const hydroplanes = canHydroplane(l.surface) && gsTrueKt > vpKt

  // The heat, over the next three quarters of an hour — because that is when the bead actually peaks.
  const stopS = CAL.rolloutDelayS + vGround / rolloutDecelMps2(l)
  const thermal = brakeThermal({ brakeEnergyMJ, oatC: l.oatC, brakingS: Math.max(1, stopS - CAL.rolloutDelayS), stopS })
  const brakePeakC = thermal.packPeakC
  const beadPeakC = thermal.beadPeakC

  // Locked wheels. The aircraft slides from the moment the brakes bite until it stops, and every metre
  // of that is ground off one arc of one tyre.
  const locked = wheelsLock(l)
  const slideDistM = locked ? Math.max(0, stopDistM - vGround * CAL.rolloutDelayS) : 0
  const minGroove = Math.min(...tire.grooves)

  // How much rubber there is to grind before the carcass, and how far it slides before it runs out. A
  // tyre ground to its casing at 60 m/s does not go on making a tidy flat spot — it lets go.
  const rubberMm = minGroove + CAL.carcassMarginMm
  const groundMm = flatSpotMm(loadPerTireKN, slideDistM, l)
  const burst = groundMm > rubberMm
  const flatMm = Math.min(groundMm, rubberMm)
  const burstAtM = burst ? (slideDistM * rubberMm) / groundMm : 0

  // Tread budget after this landing. A flat spot comes out of the same rubber the scrub does.
  // Floored at zero. There is no such thing as −2 mm of tread: a tyre ground past its grooves is at the
  // carcass, and the flag for that is `burst`, not a negative depth.
  const grooveAfter = Math.max(0, minGroove - scrubMm - flatMm)
  const cyclesToLimit = Math.max(0, Math.floor((minGroove - tire.grooveLimit) / scrubMm))

  const overrun = stopMarginM < 0
  const flags = [
    overrun && `Overrun — the stop needs ${Math.round(stopDistM)} m and the runway is ${l.runwayM} m`,
    !overrun && stopMarginM < CAL.marginM && `Tight — only ${Math.round(stopMarginM)} m of runway left after the stop`,
    peakG > CAL.gLimit && `Hard landing — ${peakG.toFixed(2)} G exceeds the ${CAL.gLimit} G FOQA flag`,
    hydroplanes && `Hydroplaning — at ${Math.round(tire.psi)} psi this tire rides up on water above ${Math.round(vpKt)} kt, and touchdown is ${Math.round(gsTrueKt)} kt`,
    beadPeakC > CAL.fusePlugC &&
      `Bead reaches ${Math.round(beadPeakC)} °C — fuse plug releases above ${CAL.fusePlugC} °C, and it gets there ${Math.round(thermal.beadPeakAtS / 60)} min after landing, on the taxiway or at the gate`,
    locked &&
      `Anti-skid off — ${Math.round(l.brakeShare * 100)} % brake demands µ ${(CAL.muDemandMax * l.brakeShare).toFixed(2)} and the ${l.surface} runway supplies ${(canHydroplane(l.surface) ? CAL.muHydroplane : CAL.mu[l.surface]).toFixed(2)}. The wheels lock, slide ${Math.round(slideDistM)} m, and stop the aircraft *worse* than a rolling tyre would`,
    locked && burst && `Tyre burst — the locked wheel ground through all ${rubberMm.toFixed(1)} mm of rubber on that arc after ${Math.round(burstAtM)} m of a ${Math.round(slideDistM)} m slide, and went into the carcass`,
    locked && !burst && flatMm > 0.2 && `Flat-spotted — ${flatMm.toFixed(1)} mm ground off one arc of tread while the wheel was locked${flatMm > CAL.flatSpotScrapMm ? '. The tyre is scrap' : ''}`,
    grooveAfter < tire.grooveLimit && `Groove ${grooveAfter.toFixed(2)} mm lands under the ${tire.grooveLimit} mm limit`,
    Math.abs(tire.psi - tire.psiTarget) / tire.psiTarget > 0.05 && `Tire is ${Math.round(((tire.psi - tire.psiTarget) / tire.psiTarget) * 100)} % off target psi before the event`,
  ].filter((f): f is string => typeof f === 'string')

  const severe = overrun || peakG > CAL.gLimit || hydroplanes || locked || beadPeakC > CAL.fusePlugC || grooveAfter < tire.grooveLimit
  const status = flags.length === 0 ? 'ok' : severe ? 'action' : 'watch'

  return {
    peakG, loadPerTireKN, scrubMm, keMJ, brakeEnergyMJ, brakePeakC, beadPeakC, beadPeakAtS: thermal.beadPeakAtS, thermal,
    stopDistM, stopMarginM, gsTrueKt, grooveAfter, cyclesToLimit, hydroplanes, vpKt,
    locked, slideDistM, flatSpotMm: flatMm, burst, burstAtM,
    headwindKt: headwindKt(l), crosswindKt: crosswindKt(l),
    flags, status,
  } as const
}

// Under-inflation flexes the sidewall and drags the shoulder — more scrub, hotter carcass.
export function tirePressureScrubFactor(tire: { psi: number; psiTarget: number }) {
  return 1 + Math.max(0, (tire.psiTarget - tire.psi) / tire.psiTarget) * 2
}

/** True airspeed at touchdown: the indicated approach speed, corrected for thin air up high. */
export function trueAirspeedMps(l: Landing) {
  return l.gsKt * (1 + (CAL.tasPctPer1000ft / 100) * (l.elevFt / 1000)) * MS_PER_KT
}

/**
 * Speed over the ground — which is what the runway, the brakes and the tyres actually see.
 *
 * This used to return the true *airspeed* and call it groundspeed, which is where the missing headwind
 * was hiding in plain sight. An aircraft flies at Vref through the *air*; the ground goes past at Vref
 * minus whatever the air itself is doing. Land into 25 kt and you touch down 25 kt slower over the
 * tarmac — every energy term goes with the square of this, so it is the cheapest runway there is.
 */
export function trueGroundSpeedMps(l: Landing) {
  return Math.max(10 * MS_PER_KT, trueAirspeedMps(l) - headwindKt(l) * MS_PER_KT)
}

export function rolloutDecelMps2(l: Landing, mu = CAL.mu[l.surface]) {
  const brakeShare = Math.min(1, Math.max(0, l.brakeShare))
  // Capped at 1. A wheel cannot decelerate the aeroplane harder than µ·g however hard the pedal is
  // pushed — that is what µ *means*. The old curve ran to 1.22, which quietly bought free braking
  // above about half pedal. What actually happens past that point is anti-skid holding you at the
  // limit... or, without it, the wheel locking. Both are below.
  const brakeFactor = Math.min(1, CAL.brakeDecelBase + CAL.brakeDecelGain * brakeShare)
  const crosswindLoss = Math.min(CAL.crosswindDecelLossMax, Math.abs(crosswindKt(l)) / 300)
  // A locked wheel slides, and a sliding tyre grips less than a rolling one. Locking up does not stop
  // you faster; it stops you slower, and destroys the tyre on the way.
  const slide = wheelsLock(l) ? CAL.muSlideFactor : 1
  return Math.max(0.1, mu * G * brakeFactor * slide * (1 - crosswindLoss))
}

/**
 * Does the brake demand exceed what the runway can actually supply?
 *
 * With anti-skid, never: it backs off and holds the tyre at the friction peak. Without it, the pedal
 * commands a torque the surface cannot react, and the wheel stops turning. On a dry runway you have to
 * stamp on it; on a wet one, half pedal will do it; on standing water the tyre is aquaplaning and
 * almost any braking at all locks it.
 */
export function wheelsLock(l: Landing) {
  if (l.antiskid) return false
  const muAvailable = canHydroplane(l.surface) ? CAL.muHydroplane : CAL.mu[l.surface]
  return CAL.muDemandMax * Math.min(1, Math.max(0, l.brakeShare)) > muAvailable
}

/** The speed above which this tyre stops touching the runway. Falls with pressure — which is the
 *  entire point: a soft tyre hydroplanes sooner, and the app already knows every tyre's psi. */
export function hydroplaneSpeedKt(psi: number) {
  return CAL.hydroplaneK * Math.sqrt(Math.max(0, psi))
}

/**
 * How deep a flat spot a locked wheel grinds into one tyre.
 *
 * This is *the* mechanism, and it is worth being precise about why it is different from spin-up. At
 * touchdown the tyre also slides — hard, at the full groundspeed — but it is *accelerating*, so it
 * turns several times while it does, and the abrasion is smeared right round the circumference. That
 * is why a normal landing does not flat-spot a tyre.
 *
 * A locked wheel does not turn at all. Every metre the aeroplane slides is ground off the *same arc*.
 * All of the energy lands on one patch, and it goes through the tread and into the carcass.
 */
export function flatSpotMm(loadKN: number, slideDistM: number, l: Landing) {
  if (!wheelsLock(l)) return 0
  const muSlide = (canHydroplane(l.surface) ? CAL.muHydroplane : CAL.mu[l.surface]) * CAL.muSlideFactor
  const energyMJ = (muSlide * loadKN * 1000 * slideDistM) / 1e6
  return CAL.flatSpotMmPerMJ * energyMJ
}

/**
 * How much of the tyre's circumference is actually touching the runway, in degrees.
 *
 * Not a constant: the tyre squashes under load, and a squashed tyre touches along a longer arc. Press
 * a 200 kN tyre onto the ground and it flattens ~9 cm, which spreads the contact patch to about half a
 * metre — roughly 50° of its own circumference. Hit it at 1.8 G and the patch is longer still. This is
 * the arc that is being abraded at any instant, so it is the arc worth drawing.
 */
export function contactPatchDeg(loadKN: number, radiusM: number) {
  const kPerTyre = OLEO.tyreNPerM / CAL.mainWheels
  const deflM = Math.min(radiusM * 0.35, Math.max(0, (loadKN * 1000) / kPerTyre))
  const patchM = 2 * Math.sqrt(Math.max(0, 2 * radiusM * deflM - deflM ** 2))
  return Math.min(140, (patchM / (2 * Math.PI * radiusM)) * 360)
}

/**
 * Dynamic hydroplaning needs *standing water* — a depth the tyre cannot squeeze out of the way in
 * time. A merely damp runway does not do it, and is already paid for by its lower µ. So this is the
 * `contaminated` case (flooded, slush), not the `wet` one. Getting this wrong makes every rainy
 * landing an emergency, which is both false and the fastest way to teach someone to ignore the flag.
 */
export function canHydroplane(s: Surface) {
  return s === 'contaminated'
}

/**
 * Stop distance, with a hydroplaning phase.
 *
 * On a wet or contaminated runway a tyre above its hydroplaning speed is riding on water: µ collapses
 * to almost nothing and the brakes do essentially nothing until it slows below Vp. So the rollout is
 * two constant-µ phases, not one — which keeps it closed-form, no integration.
 *
 * `psi` is the pressure of the tyre that gives up first. One soft tyre is enough to start the slide.
 */
export function stopDistanceM(l: Landing, psi: number, decel = rolloutDecelMps2(l)) {
  const v0 = trueGroundSpeedMps(l)
  const rollM = v0 * CAL.rolloutDelayS
  const vp = canHydroplane(l.surface) ? hydroplaneSpeedKt(psi) * MS_PER_KT : 0
  if (v0 <= vp || vp === 0) return rollM + v0 ** 2 / (2 * decel)
  // Above Vp we are aquaplaning; below it the brakes finally bite.
  const aHydro = rolloutDecelMps2(l, CAL.muHydroplane) * (decel / rolloutDecelMps2(l))
  return rollM + (v0 ** 2 - vp ** 2) / (2 * aHydro) + vp ** 2 / (2 * decel)
}

/**
 * The crab the crosswind *demands*, if you intend to track the centreline.
 *
 * Convention: crosswind comes from the left, so it drifts the aircraft right and the downwind gear is
 * the right one. This is the coupling the spec always claimed ("crosswind → crab angle") and never
 * had — without it you could dial in 35 kt of crosswind and 0° of crab and the model would accept a
 * landing that cannot physically happen.
 */
export function driftAngleDeg(l: Landing) {
  // Against the *airspeed*: the crab is how far the aircraft has to point into the air it is flying
  // through, and the air is what the wind is made of.
  const v = trueAirspeedMps(l)
  if (v < 1) return 0
  return (Math.asin(Math.min(1, Math.max(-1, (crosswindKt(l) * MS_PER_KT) / v))) * 180) / Math.PI
}

/** Side force on the airframe from the drift the pilot did NOT crab out. Fully crabbed → zero. */
export function aeroSideKN(l: Landing, crabDeg: number) {
  const v = trueAirspeedMps(l)
  const uncorrectedRad = ((driftAngleDeg(l) + crabDeg) * Math.PI) / 180
  return (0.5 * AERO.rhoKgM3 * v ** 2 * AERO.wingAreaM2 * AERO.cyBetaPerRad * uncorrectedRad) / 1000
}

export type ThermalSample = { tS: number; packC: number; beadC: number }
export type BrakeThermal = {
  packPeakC: number
  beadPeakC: number
  beadPeakAtS: number // seconds after touchdown — the number the turnaround actually hangs on
  samples: ThermalSample[]
}

/**
 * Brake pack and tyre bead, as two thermal masses with a slow conduction path between them.
 *
 * The pack takes the energy during the stop and is then cooled hard by the airflow while the aircraft
 * is still moving. The bead is heated only *through the wheel*, which is slow — so it goes on climbing
 * long after the pack has started falling, and it peaks well after the aircraft has parked. That is
 * why fuse plugs let go on the taxiway and at the gate rather than on the runway, and it is the shape
 * the old model had exactly backwards.
 */
export function brakeThermal(o: { brakeEnergyMJ: number; oatC: number; brakingS: number; stopS: number; durationS?: number }): BrakeThermal {
  const dt = 1
  const duration = o.durationS ?? CAL.soakWindowS
  const brakingS = Math.max(1, o.brakingS)
  const wattsIn = (o.brakeEnergyMJ * 1e6) / brakingS // energy arrives over the stop, not instantly

  let pack = o.oatC
  let bead = o.oatC
  let packPeakC = o.oatC
  let beadPeakC = o.oatC
  let beadPeakAtS = 0
  const samples: ThermalSample[] = []

  for (let t = 0; t <= duration; t += dt) {
    const qIn = t < brakingS ? wattsIn : 0
    // Still rolling? Then the pack is sitting in its own hurricane and dumping heat fast.
    const packCool = (t < o.stopS ? CAL.packCoolRollingWPerK : CAL.packCoolWPerK) * (pack - o.oatC)
    const conduct = CAL.packToBeadWPerK * (pack - bead)
    const beadCool = CAL.beadCoolWPerK * (bead - o.oatC)

    pack += ((qIn - packCool - conduct) / CAL.brakeHeatSinkJK) * dt
    bead += ((conduct - beadCool) / CAL.beadHeatSinkJK) * dt

    packPeakC = Math.max(packPeakC, pack)
    if (bead > beadPeakC) {
      beadPeakC = bead
      beadPeakAtS = t
    }
    if (t % 15 === 0) samples.push({ tS: t, packC: pack, beadC: bead })
  }
  return { packPeakC, beadPeakC, beadPeakAtS, samples }
}

/** Bead temperature over the 45 minutes after touchdown — for the sparkline. */
export function beadCurve(thermal: BrakeThermal, n = 24) {
  const step = Math.max(1, Math.floor(thermal.samples.length / n))
  return thermal.samples.filter((_, i) => i % step === 0).map((s) => Math.round(s.beadC))
}

// Per-wheel vertical load: crosswind rolls the aircraft onto the downwind gear.
export function wheelLoads(r: SimResult, crosswindKt: number) {
  const skew = Math.min(0.35, crosswindKt / 100)
  return { upwind: r.loadPerTireKN * (1 - skew), downwind: r.loadPerTireKN * (1 + skew) }
}
