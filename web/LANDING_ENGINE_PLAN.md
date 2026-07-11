# Implementation Plan: Full Landing Simulation Engine

## 1. Summary

Build a single deterministic landing-event engine that simulates the whole event from short final through touchdown, tire spin-up, spoiler deployment, braking, rollout, and stop. Do not use a generic rigid-body physics engine as the source of truth; keep Three.js as the renderer and build a domain engine in TypeScript that owns aircraft state, tire state, runway state, and derived summaries on one timeline.

The current app computes landing consequences from independent component-level formulas in `src/sim.ts` and renders a static aircraft attitude in `src/Aircraft.tsx`. The new engine should produce both a time series for playback and a final summary for cards, charts, flags, runway map, and per-wheel tire effects.

## 2. Requirements

1. Explicit: Propose whether an engine should simulate the entire landing instead of separate components.
2. Explicit: Produce the proposal as a Markdown plan.
3. Implied: Fit the current React + TypeScript + Vite + Three.js app without replacing the existing renderer.
4. Implied: Keep simulation math deterministic and testable outside the browser, matching the current `npm run check:sim` pattern.
5. Implied: Preserve existing landing controls and tire dashboard while changing the simulation source of truth.
6. Implied: Support playback and scrubbing because a full landing engine should expose time, not only final scalar results.
7. Implied: Produce per-wheel outputs because the product is tire-position focused.
8. Implied: Keep the implementation honest about fidelity: this is a what-if/event model, not certified flight dynamics.

## 3. Engine Recommendation

Use a custom deterministic TypeScript landing engine, not Rapier, Cannon, Ammo, Matter, or another generic physics engine.

Generic physics engines are useful for rigid-body collision, stacks, vehicles, and game feel. They do not give useful aircraft landing truth by default: tire spin-up scrub, oleo stroke, lift dump, runway friction, brake heat, bead soak, per-wheel load attribution, and FOQA-style flags would still be custom code. Adding a rigid-body engine would add tuning instability and dependency weight while leaving the hard domain model unsolved.

Use external flight-dynamics engines only if the product goal changes to aircraft handling fidelity. JSBSim, FlightGear, X-Plane, or AirSim can simulate flight dynamics, but they are too heavy for the current web what-if tire workflow and would complicate browser execution, repeatability, and deployment.

The right shape here is an event engine:

```ts
type LandingScenario = {
  landing: Landing
  attitude: Attitude
  track: Track
  tires: Tire[]
  durationS: number
  dtS: number
}

type LandingFrame = {
  tS: number
  phase: 'approach' | 'flare' | 'touchdown' | 'spinup' | 'spoilers' | 'braking' | 'rollout' | 'stopped' | 'overrun'
  pose: Attitude & { xM: number; yM: number; zM: number }
  speedMps: number
  sinkMps: number
  liftShare: number
  brakeShare: number
  wheel: Record<string, { loadKN: number; scrubMm: number; brakeMJ: number; beadC: number; contact: boolean }>
  flags: string[]
}

type LandingRun = {
  frames: LandingFrame[]
  summary: SimResult
}
```

## 4. Approach & Key Decisions

The engine should live beside the existing pure model, then gradually absorb it. Start with `src/landingEngine.ts` as the new timeline engine and keep `src/sim.ts` as the scalar physics library until the final phase. This reduces migration risk because the first engine output can reproduce today's summary numbers before adding richer time-series behavior.

`src/Aircraft.tsx` should remain a Three.js renderer. It should receive either the current static `Attitude` or a playback `LandingFrame`, then render pose, wheel contact, oleo compression, wheel status rings, and runway motion from engine output. It should not contain physics rules beyond display-specific ground-clearance compensation.

`src/SimulateLanding.tsx` should become the scenario orchestrator. It should build a `LandingScenario` from sliders, selected track, and `FLEET_TIRES`; call the engine; own playback state; and pass the selected frame and summary to `Aircraft`, `TrackMap`, cards, and charts.

## 5. Implementation Steps

### Step 1: Define the Engine Contract

Files: `src/landingEngine.ts` new, `src/sim.ts` edit, `src/Aircraft.tsx` edit only for shared type imports if needed.

Change: Add `LandingScenario`, `LandingPhase`, `LandingFrame`, `PerWheelFrame`, and `LandingRun` types. Export one placeholder function, `simulateLandingRun(scenario: LandingScenario): LandingRun`, that initially creates a one-frame run whose summary delegates to `simulate()`.

Verify: `npm run build` passes. Add `src/landingEngine.check.ts` with an assertion that the one-frame engine summary matches `simulate()` for the nominal landing.

### Step 2: Move Existing Scalar Outputs Behind the Engine

Files: `src/SimulateLanding.tsx`, `src/landingEngine.ts`, `src/sim.ts`, `package.json`.

Change: Replace direct calls to `simulate(l, tire)` in `SimulateLanding` with `simulateLandingRun(...)`. Continue rendering the same KPI values from `run.summary` so the UI is behaviorally unchanged. Add `check:landing-engine` to run the new engine self-check.

Verify: Existing UI still shows the same peak G, load, stop distance, brake temperatures, groove-after, and flags for the same slider values. `npm run check:sim`, `npm run check:landing-engine`, and `npm run build` pass.

### Step 3: Add a Fixed-Step Timeline

Files: `src/landingEngine.ts`, `src/landingEngine.check.ts`.

Change: Generate frames at a fixed `dtS`, defaulting to `0.05`. Model phases in order: `approach`, `flare`, `touchdown`, `spinup`, `spoilers`, `braking`, `rollout`, then `stopped` or `overrun`. Use deterministic formulas only; no browser time, random values, or frame-rate dependence inside the engine.

Verify: Checks assert monotonic runway distance, non-negative speed, deterministic repeat output for the same scenario, a final frame that matches `summary.stopDistM`, and an overrun frame when stopping distance exceeds runway length.

### Step 4: Add Aircraft State Over Time

Files: `src/landingEngine.ts`, `src/Aircraft.tsx`, `src/SimulateLanding.tsx`.

Change: Have each frame output aircraft `pose` with runway `xM`, lateral `zM`, height `yM`, pitch, roll, and crab. Update `Aircraft` to accept an optional frame and render that frame when playback is active; otherwise use the current static attitude. Keep the existing automatic ground-clearance compensation as renderer safety, not physics.

Verify: Scrubbing through frames moves the aircraft along the runway without sinking wheels through the ground. Static sliders still work when not playing.

### Step 5: Add Per-Wheel Load, Contact, and Scrub

Files: `src/landingEngine.ts`, `src/sim.ts`, `src/landingEngine.check.ts`, `src/Aircraft.tsx`, `src/SimulateLanding.tsx`.

Change: Compute `wheel[id]` outputs for all `FLEET_TIRES`. Roll/bank decides touchdown side and first-contact wheel group. Crab adds lateral scrub. Crosswind skews downwind load. Tire pressure deviation modifies scrub through the existing deflation penalty behavior. Use the engine's per-wheel values for wheel ring colors and selected tire cards.

Verify: Checks assert wings-level load symmetry, banked landing asymmetry, load conservation across main wheels after touchdown, higher crab producing higher lateral scrub, and under-inflation increasing selected tire scrub.

### Step 6: Add Playback Controls and Scrub UI

Files: `src/SimulateLanding.tsx`, `src/charts.tsx` if a reusable scrub chart is needed, `src/ui.tsx` only if an existing component cannot express the controls.

Change: Add play, pause, reset, and scrub state to `SimulateLanding`. Use `requestAnimationFrame` only for UI playback clock advancement; never for simulation math. Display current phase, time, runway distance, speed, and selected tire load from the active frame.

Verify: Manual test play, pause, scrub backward, change a slider, and replay. Build remains clean. Engine output does not change when browser frame rate changes.

### Step 7: Replace Component-Level Cards With Engine Outputs

Files: `src/SimulateLanding.tsx`, `src/TireCards.tsx` if adding a landing-event card, `src/TrackMap.tsx`.

Change: Drive status flags, KPI cards, load bars, tread budget, brake chart, and runway map from `LandingRun.summary` plus selected `LandingFrame`. Add a `ThisLandingCard` only if the current center cards do not clearly show selected wheel load, contact order, scrub, and tire consequence.

Verify: Track map overrun still matches summary stop distance. Selected tire values update when clicking a different wheel. Existing `/tyres` route remains unchanged unless shared card extraction is needed.

### Step 8: Retire or Re-scope Old Helpers

Files: `src/sim.ts`, `src/sim.check.ts`, `src/landingEngine.ts`, `src/landingEngine.check.ts`.

Change: Keep low-level reusable formulas in `src/sim.ts`, but make `src/landingEngine.ts` the single public source for whole-event simulation. Avoid two competing APIs that can drift. If `wheelLoads()` becomes obsolete, either move it behind the engine or keep it only as a tested helper used by the engine.

Verify: Search confirms `simulateLandingRun()` is the only whole-event API used by UI. Existing checks are either migrated or still cover helper-level formulas explicitly.

## 6. Data / Schema / Contracts

No persisted backend schema is needed. All contracts are TypeScript-only.

The main contract change is from scalar event output to a full run object:

```ts
type LandingRun = {
  frames: LandingFrame[]
  summary: SimResult & {
    touchdownOrder: string[]
    perWheel: Record<string, {
      peakLoadKN: number
      scrubMm: number
      brakeMJ: number
      beadPeakC: number
      touchedFirst: boolean
    }>
  }
}
```

Keep `Landing`, `Surface`, and `CAL` in `src/sim.ts` unless they become engine-specific. Keep `Attitude` exported from `src/Aircraft.tsx` only if it remains a view concern; otherwise move it to `src/landingEngine.ts` and import it into `Aircraft`.

## 7. Edge Cases & Failure Modes

1. Zero or invalid timestep: Clamp or reject `dtS <= 0`; checks should cover this.
2. Empty tire list: Engine should still return aircraft-level summary, but per-wheel outputs should be empty and UI should handle no selected tire defensively.
3. Missing tire id: UI should fall back to the first available tire rather than throwing.
4. Runway overrun: Engine must keep producing frames past runway end until stopped or until a capped simulation duration is reached, and `TrackMap` should display overrun distance.
5. Infinite rollout: Add max duration and max distance guards so bad coefficients cannot hang the browser.
6. Negative speed or distance: Clamp speed at zero and assert monotonic distance in checks.
7. Bank and ground clearance: Physics should decide contact; renderer should still prevent visual clipping from bank/pitch transforms.
8. Competing formulas: Avoid separate UI calculations once engine output exists; duplicate calculations will drift.
9. Performance: A `dtS` of `0.05` over a 60-second rollout is about 1,200 frames, which is safe for React state if only the active frame is rendered and frames are stored in refs or memoized per scenario.
10. Fidelity expectations: UI copy must continue saying this is first-order fitted physics, not certification-grade flight dynamics.

## 8. Test & Verification Plan

1. Unit/self-check: `src/landingEngine.check.ts` covers deterministic output, phase order, stop distance, overrun, per-wheel symmetry, bank asymmetry, crab scrub, and pressure penalty.
2. Regression/self-check: `src/sim.check.ts` keeps covering scalar physics helpers while they remain separate.
3. Build: `npm run build` must pass after every phase.
4. Lint: `npm run lint` should not introduce new warnings beyond the existing Fast Refresh warnings in `src/charts.tsx` and `src/ui.tsx`.
5. Manual browser verification: Change pitch, roll, crab, surface, track, speed, sink, brake share, and selected tire; confirm playback and final values update from one scenario.
6. Visual verification: Banked touchdowns should show one side contacting first without wheels sinking through the runway.
7. Route verification: `/tyres` should still render existing tire cards and `/simulate-landing` should use engine output.

## 9. Requirements Coverage Map

1. Requirement 1 is covered by Sections 3 and 4: recommendation is a custom deterministic event engine, not a generic physics engine.
2. Requirement 2 is covered by this Markdown file.
3. Requirement 3 is covered by Sections 4 and 5: Three.js remains renderer, React orchestrates scenario state.
4. Requirement 4 is covered by Steps 1 through 3 and Section 8: pure TypeScript engine plus Node self-checks.
5. Requirement 5 is covered by Steps 2, 6, and 7: existing controls and cards migrate to `LandingRun` output.
6. Requirement 6 is covered by Steps 3 and 6: fixed-step timeline plus play, pause, reset, and scrub controls.
7. Requirement 7 is covered by Step 5 and the `perWheel` contract in Section 6.
8. Requirement 8 is covered by Sections 3 and 7: state fidelity boundaries clearly and avoid pretending this is certified flight dynamics.

## 10. Risks & Open Questions

1. Open question: Should playback simulate only touchdown-to-stop, or include a short stabilized approach before threshold? The recommended default is last 6 to 10 seconds before touchdown plus rollout to stop.
2. Open question: Should wind direction be added separately from crosswind speed? Current UI has `crosswindKt`; a full engine may need wind vector if crab is auto-derived.
3. Open question: Should engine output be calibrated to a specific 777-300ER landing-distance reference, or remain qualitative until real FOQA/FDR joins arrive?
4. Risk: A full timeline can look more authoritative than it is. Mitigation: keep visible copy saying coefficients are fitted placeholders.
5. Risk: Per-wheel load math can become complex quickly. Mitigation: start with conservation and monotonic assertions before adding more coefficients.
6. Risk: UI may re-render too often during playback. Mitigation: store generated frames once per scenario and update only active frame index during playback.

## Review Log

Pass 1 against requirements: Covered every explicit and implied requirement in the coverage map. Added explicit playback, per-wheel outputs, deterministic checks, and fidelity-warning requirements because a whole-event engine without these would not satisfy the product need.

Pass 2 against codebase: Re-opened `src/sim.ts` and confirmed current pure scalar functions are `simulate()`, `brakeCurve()`, and `wheelLoads()`. Re-opened `src/SimulateLanding.tsx` and confirmed it directly calls `simulate(l, tire)`, computes `loads = wheelLoads(...)`, and passes static `attitude` to `Aircraft`. Re-opened `src/Aircraft.tsx` and confirmed Three.js is already imperative and attitude-driven. Re-opened `src/data.ts` and confirmed tire ids are strings in `FLEET_TIRES`, so `Record<string, ...>` is the correct first contract. Re-opened `package.json` and confirmed there is no physics dependency and checks currently run through Node scripts.

Pass 3 against failure modes: Simplified from adding a generic physics engine to a custom event engine because generic rigid-body simulation would add risk without solving tire-domain outputs. Added guards for invalid timestep, infinite rollout, overrun, missing tire ids, negative speed, duplicated formulas, and playback performance. Ordered steps so the first engine phase reproduces existing output before adding timeline and per-wheel behavior.
