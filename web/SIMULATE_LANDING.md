# /simulate-landing — 3D landing simulator

Spec, and a build log. **Phases 1–2 are built** (the aircraft, the wheel picking, the two panels).
Phases 3–4 (the per-wheel model, playback, tracks) are still spec.

## The shape of the page

Two panels, side by side. Left is the aircraft, right is the tire you picked off it.

```
┌───────── controls ─┬──────────── THE AIRCRAFT ───────────┬──────── THE TIRE ────────┐
│ Pitch    ▁▂▃▄▅     │                                     │ L1 · BR73052    ▲ ACTION │
│ Roll     ▁▂▃       │        3D · fly the touchdown       │ Main L Fwd-Out           │
│ Crab     ▁▂        │        every wheel clickable        │ ┌──────────────────────┐ │
│ Lift     ▁▂▃▄      │        coloured by this landing     │ │ THIS LANDING         │ │
│ Sink     ▁▂▃▄▅▆    │                                     │ │ 148 kN · touched 1st │ │
│ Wind     ▁▂▃       │                    [CHASE][SIDE][GEAR]│ └──────────────────────┘ │
│ ─────────          │                                     │ Identity · TPMS · Tread  │
│ Track: KJFK 13R    │─────────────────────────────────────│ Defects · Utilization    │
│ ▶ FLY  ├──●─────┤  │  N1 N2 · L1 L2 L3 L4 · R1 R2 R3 R4  │ …the /tyres cards, for   │
│                    │  ← wheel strip: the small-screen    │    this wheel, scrolling │
│ Track: ☑ peak g    │    fallback + keyboard selector     │                          │
└────────────────────┴─────────────────────────────────────┴──────────────────────────┘
```

The aircraft is the subject **and** the selector. **Clicking a wheel on the plane is what picks a
tire** — that replaces the SVG gear map, which was only ever a flat stand-in for the thing we can now
draw properly. The right panel is the `/tyres` dashboard, scoped to whichever wheel is lit.

Side by side, not stacked, so the two panels answer their questions *simultaneously*: the landing is
happening on the left while its consequences for one tire update on the right. Stacked, you'd have to
scroll away from the aircraft to read the damage — which defeats the point of drawing it.

Under ~1024 px the panels stack (aircraft first) because two useful columns don't fit. Everything
below assumes the wide layout.

## Left — the aircraft

Raw three.js, same setup as `TireViewer.tsx` (WebGLRenderer + OrbitControls in one `useEffect`, no
`@react-three/fiber` — it isn't installed and this doesn't need it).

**The airframe is `public/b777.glb`** — a real Boeing 777-300ER (2.1 MB, Aeroflot livery). It is
metric, +z forward, +y up, and its origin already sits on the ground between the main bogies, so
`rotation.y = π/2` puts the nose at +x and attitude rotations pivot at the **main-gear contact
point** — which is where the physics pivots, and makes touchdown just `group.position.y ≈ 0`. Nothing
about the aircraft is authored by us; the only thing we add is the tire mapping.

**Finding the wheels.** The GLB's node names are Sketchfab noise (`Group_048_<Black>_0`), so identity
comes from the only reliable things: the black rubber material, and where the wheel sits. `mapWheels()`
collects every mesh with a `<Black>` material (there are exactly 14), reads each one's axle (fore/aft
rank), side (sign of z) and role (outer/inner by |z|), then asks `FLEET_TIRES` which tire that is.
**The data is the source of truth and the model has to match it** — if a wheel finds no tire, or the
counts disagree, it says so in the console rather than silently mis-labelling a tire.

**Wheels are the interactive layer.** Each is a named mesh with a `userData.tireId`:

- **Hover** → a tooltip: id, serial, psi.
- **Click** → `Raycaster` against the wheel meshes only (not the whole scene — cheap, and it can't
  mis-hit the fuselage) → sets `selectedId` → the deck below re-renders. Also nudges the camera to
  frame that gear leg.
- **Colour** → a status-coloured ring bolted to each wheel. The model's tires are black rubber and
  must stay black to read as rubber, so status rides on the ring, not on the tire. During a simulated
  landing the colour switches to *this landing's* load on that wheel, so a one-wheel touchdown lights
  up the one tire taking it.
- **Keyboard** → a strip of the fourteen wheel ids sits under the canvas (`N1 N2 · L1..L6 · R1..R6`),
  status-coloured. It is the keyboard path, the small-screen path, and the honest fallback if the 3D
  wheels turn out to be too small to hit. The 3D is never the only way to pick a tire.

Runway: a long `PlaneGeometry` with centreline markings drawn into a `CanvasTexture` (procedural, no
image asset). Surface state changes how it *looks*, not just what it is called: wet is dark and glossy
(low roughness is the sheen), contaminated is pale and dull, dry is neither.

**Environment** (`ENV` in `tracks.ts`) — **built.** Each airport carries a climate: sky gradient, sun
colour + intensity, ambient, ground tint and fog distance. The sky is one inside-out sphere with a
vertical gradient baked into a 1×256 canvas — a sphere's UVs run pole to pole, so the gradient lands
the right way up for free. No shader, no HDRI to fetch. The sun is swung around by the runway heading,
so no two airports are lit the same way. Dark theme **dims** the world (×0.42) rather than recolouring
it: a noon sky next to a dark dashboard reads as a bug, and dusk is the honest way to keep both.

Seven climates: `tropical` (hazy, warm), `coastal` (marine layer), `overcast`, `rain`, `desert`
(sand + hard sun), `highdesert` (thin, deep blue), `snow` (pale ground, low winter sun).

Wind: arrow helpers along the runway edge, length = speed, heading = direction. It shows up twice —
as arrows, and as the nose pointing off the centreline in the crab. That second one is the whole
reason crosswind is a tire problem.

**The runway used to crawl while you orbited.** Two causes, both fixed. The camera's near plane was
0.1 against a far of 4000: depth precision is spent almost entirely near the camera, so at runway
distance there was none left and the runway and the ground fought over the depth buffer. Near is now
3 (OrbitControls never lets you closer than 5 anyway), the ground sits 0.35 m lower — a real runway
is proud of the dirt — and the runway carries a `polygonOffset` so it always wins. The markings were
also shimmering at grazing angles, which is exactly what anisotropic filtering is for: the texture now
takes `renderer.capabilities.getMaxAnisotropy()` instead of a guessed 8.

Camera presets, animating the orbit target: `CHASE` (behind, low), `SIDE` (the sink-rate view, where a
hard landing is obvious), `GEAR` (tight on the mains). Orbit/zoom stays free.

## Right — the tire

The `/tyres` content, for the selected wheel. Extracted from `Tyres.tsx` as `TireDetail({ id })` and
used by both routes — one component, two homes:

- `/tyres` — SVG gear map picks the tire, detail fills the page in its existing wide grid. Unchanged.
- `/simulate-landing` — the plane picks the tire, detail fills one column beside it.

The cards live in `TireCards.tsx` as one component each (`IdentityCard`, `PressureCard`, `TreadCard`,
`DefectsCard`, `TouchdownCard`, `UtilizationCard`, …). `/tyres` arranges them in its existing 12-column
grid; `/simulate-landing` stacks them via `<TireDetail>`. Extracting the components rather than
parameterising one layout means **`/tyres` did not change at all** — and the two pages cannot drift,
because there is only one copy of the JSX. No tabs: a column that scrolls keeps the aircraft pinned in
view, which is the entire reason for putting them side by side.

One card is **new here and only here**, and it pins to the top of the column: *This landing* — peak
load on this wheel, whether it touched first, lateral scrub from the crab, tread after the event,
cycles left. It is the join between the two panels, and the only thing on the right that changes when
you move a slider on the left.

## Controls

A narrow rail on the far left. The aircraft needs the middle.

| Control | Range | Feeds |
|---|---|---|
| Pitch / flare | −2 … +12° | Delays main contact, raises lift. Above ~11° it's a tailstrike |
| Roll / bank | −8 … +8° | **Which main touches first.** A one-wheel touchdown puts the whole load on one tire |
| Yaw / crab | −15 … +15° | Side-slip at contact → lateral scrub |
| Lift remaining | 0 … 100 % | Weight-on-wheels ramp: effective weight = `W × (1 − lift)`. Spoilers collapse it to 0 over ~2 s. Decides whether the tire carries the aircraft or the wing still does |
| Sink rate | 60 … 720 fpm | Approach slope in the scene, peak g in the model |
| Groundspeed | 100 … 175 kt | Spin-up scrub, brake energy |
| Landing weight | 40 … 79 t | Everything |
| Wind speed / dir | 0 … 40 kt, 0 … 359° | Headwind → groundspeed; crosswind → crab angle, roll onto the downwind gear |
| Brake share | 20 … 100 % | Brake energy, bead temp |
| OAT | −20 … 48 °C | Bead temp baseline |

`▶ FLY` runs the last ~6 seconds — flare, touchdown, spin-up, spoilers, braking — with a scrub bar.
Paused by default, so the sliders are live-editable without anything moving.

**Minimap** (`src/TrackMap.tsx`) — **built.** A plan view of the runway, drawn to scale and turned to
its true heading, so the tracks are comparable at a glance (Tan Son Nhat really is the stubby one) and
north really is north. The landing roll is shaded on top of it from the threshold — green with room,
amber when tight, red when the stop runs past the far end and out into the grass. It is where the stop
margin stops being a number.

**Landing tracks** (`src/tracks.ts`) — **built.** Seven real runways, and each one is a preset that
feeds the model, not a texture swap:

| | Runway | Why it is in the list |
|---|---|---|
| **VVTS** Tan Son Nhat | 25R · 3048 m · 33 ft | Shortest in the set, hottest air — least room to dump heat |
| **KLAX** Los Angeles | 25L · 3685 m · 126 ft | Long, dry, sea level — the benign case everything is measured against |
| **KJFK** New York | 04L · 3682 m · 13 ft | Wet and cold: µ drops, the rollout stretches |
| **EGLL** Heathrow | 27L · 3902 m · 83 ft | Rain — the tires spend longest hot and wet |
| **OMDB** Dubai | 12L · 4000 m · 62 ft | 43 °C ambient sits the bead near the fuse plug before the brakes do anything |
| **KDEN** Denver | 16R · 3658 m · **5434 ft** | A mile up: same IAS is a faster touchdown, and energy goes with the square |
| **PANC** Anchorage | 07R · 3535 m · 152 ft | Contaminated and freezing — µ collapses, the stop runs long |

Picking a track sets the runway length, elevation, surface and OAT; the sliders stay as the crew left
them. Two things then fall out of the model:

- **Stop margin.** `runwayM − stopDistM`. Negative is an **overrun**, and it is reachable: Denver at
  175 kt on a contaminated runway needs 3884 m and has 3658 m.
- **True groundspeed.** Field elevation raises it ~2 %/1000 ft for the same indicated speed, so
  Denver touches down at 153 kt when the slider says 138 — and brake energy, scrub and stop distance
  all follow. It is the one track where nothing looks wrong and everything costs more.

**The rollout delay.** Adding runway length exposed a bug the numbers had been hiding: the model
braked from the instant of touchdown and stopped a 777 in 640 m, which would have made every runway
in the list look roomy. Nothing decelerates at touchdown — the nose comes down, spoilers deploy,
reversers unstow. `CAL.rolloutDelayS = 5` covers it, and the dry stop is now ~1000 m. `sim.check.ts`
asserts the stop stays between 900 m and 1600 m, so it cannot silently go back.

**Conditions to track** — checkboxes over the channels (peak g, per-wheel load, bead temp, scrub,
lateral g, stop margin, touchdown order). Checked channels get a live readout during playback and are
the only ones allowed to raise flags. A filter for "what am I watching on this landing", not a
settings page.

## Model changes (`src/sim.ts`)

The existing model and its self-check stay. It grows attitude:

```ts
type Attitude = { pitchDeg: number; rollDeg: number; crabDeg: number; liftShare: number }
```

New derivations — first-order, each with a named constant in `CAL`:

- **Effective weight** — `W × (1 − liftShare)`, feeding every load number that already exists.
- **Per-wheel load** — the current model gives one number for eight identical mains. It now returns a
  `Record<TireId, number>`: roll and crab redistribute it, and an asymmetric arrival can put up to
  `2×` on a single wheel before decaying to even through derotation. **This is what the 3D colours
  read from**, so the scene and the numbers cannot drift apart.
- **Touchdown order** — sign of roll (plus a crab term) picks left / right / both.
- **Lateral scrub** — crab at contact → side force ≈ `µ_side × load × sin(crab)`, adding a lateral
  tread-loss term on top of the existing spin-up scrub. Crab and bank interact, and the page should
  make that discoverable: a crabbed, banked arrival is the worst tire event in the model.
- **Stop margin** — `runway.lengthM − stopDistM`; negative is an overrun.
- **Geometry flags** — tailstrike pitch, sink above the gear's design limit.

Each one is one more `assert` in `sim.check.ts`. The self-check is the contract: a wings-level landing
loads both mains equally, a banked one must not.

## Files

```
DONE  public/b777.glb          the airframe (2.1 MB)
DONE  src/Aircraft.tsx         the scene: GLB, runway, wheel mapping + picking, camera presets
DONE  src/TireCards.tsx        the /tyres cards, one component each + <TireDetail> (the column)
DONE  src/Tyres.tsx            shrank 280 -> 123 lines; renders the shared cards, layout unchanged
DONE  src/SimulateLanding.tsx  controls rail | aircraft + landing readouts | tire column
DONE  src/data.ts              POSITIONS: 10 -> 14 tires (six-wheel bogies)
DONE  src/sim.ts               CAL.mainWheels: 8 -> 12
TODO  src/sim.ts               Attitude, effective weight, per-wheel load, touchdown order, scrub, margin
TODO  src/sim.check.ts         one assert per new derivation
TODO  src/tracks.ts            runway presets (data only, ~40 lines)
```

`ui.tsx`, `charts.tsx`, `Card`, `Kpi` are reused untouched. The tire cards are not rewritten — they
are moved once and then shared.

## Phases

1. ~~**The plane, static.**~~ **Done.** Real 777-300ER, orbit camera, three presets, attitude sliders
   driving the airframe, all 14 wheels clickable and status-coloured. The risky question (*can you hit
   a wheel with the mouse in a half-width panel?*) was answered by sweeping the canvas and counting
   hittable pixels: yes, comfortably, and the wheel strip covers the rest.
2. ~~**The two panels.**~~ **Done.** Cards extracted to `TireCards.tsx`, wheel-click drives the column
   on the right. Both routes render the same components. The page is useful here with no simulation at
   all — which is why it was worth stopping to look.
3. **The model.** ← *next.* Attitude → per-wheel load → wheel colours and the *This landing* card.
   Self-check green. Touchdown is a static pose; nothing animates yet.
4. **Playback, tracks, tracked conditions.** The 6-second clock, oleo compression, spin-up, runway
   swap, overrun, channel checkboxes.

Phases 1–2 ship a real page on their own. Phase 4 is the first thing to cut if it fights back.

## Not in this

- **No flight dynamics.** The aircraft is on rails: sliders set an attitude and a path; they don't fly
  it. No control surfaces, no autopilot, no stall.
- **No R3F, no physics engine, no state library.** Three.js and `useState` cover it.
- The loads and temps are first-order physics with fitted coefficients, and the page says so. A
  what-if rig, not a certification artefact.

## Open questions

- ~~**A half-width plane makes a ~12 px mainwheel.**~~ **Settled:** the default camera is `GEAR`,
  framed on the left bogie, and the camera presets are derived from the airframe's own bounding box
  rather than hard-coded metres — so they survive a model swap. Status rides on a ring around each
  wheel, which holds its colour when small; the selected wheel gets a pulsing ring drawn with
  `depthTest: false` so the wing cannot swallow it.
- **The fleet data was wrong, and the model exposed it.** `FLEET_TIRES` had 4-wheel main bogies
  (10 tires) while the aircraft it claims to be — a 777-300ER, per the header — has six-wheel bogies
  (14). The data now has 14. **The mock telemetry for the four new tires is generated, like the rest
  of it** — no one has said what a real L3/L4 should read.
- **Constants.** Every value in `CAL` is a placeholder with a plausible number and a name that says
  what would replace it. Ground truth arrives when serials join to FOQA, and not before.
