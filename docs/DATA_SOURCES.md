# Data Sources → System Mapping

The real system draws on three data tiers. This maps every source signal to where it lands
in the pipeline (schema field / feature), which model consumes it, whether the current POC
already models it, and how to handle the flagged engineering challenge.

**Three architectural fits worth calling out — the design already anticipates the hard parts:**

1. **Wear vs. acute damage are separated by design.** The Defect-Detection challenge ("distinguish
   normal wear from acute physical damage — they need *different logistics responses*") is exactly
   the POC's split between **wear-out** alerts (degradation/RUL → a *scheduled* swap) and
   **event-driven** alerts (FOD/cut/bulge/pressure → an *immediate* AOG response). They are never
   blended.
2. **Inner vs. outer wheel is already a first-class dimension.** Positions are modelled as
   `MLG_L_INBD / MLG_L_OUTBD / MLG_R_INBD / MLG_R_OUTBD`, so mapped lateral turn-load can be
   allocated per position (outboard tire on the turn's outer side bears more scrub).
3. **The serial join key is the spine of the schema.** Every row keys on `tire_id`/serial +
   `aircraft_id` + `position_code`, with install/removal windows (`install_date`, `removal_date`,
   `is_current`) binding a serial to an aircraft-position over time — the "link flight logs to
   exact tire serial numbers" challenge.

Legend: ✅ modelled now · ◑ partial · ⬚ planned (new field/model)

## Tier 1 — Sensor Data (Onboard Avionics & Ground Tracking)

| Signal (source) | → Schema / feature | Model | POC | "Look into" → recommended handling |
|---|---|---|---|---|
| **Tire pressure** (TPMS / ACARS) | `inspection_records.pressure_pct`; → continuous telemetry `pressure_events` | Event-driven ladder + wear covariate (under-inflation accelerates wear) | ✅ | *ACARS reliability during layovers:* treat pressure as intermittent telemetry with explicit gap handling; keep per-flight **min & last cold pressure**; flag stale/missing transmissions as data-quality — never silently impute. |
| **Touchdown / braking** (FOQA: sink rate, G, brake pressure) | `operational_cycles.hard_landing`, `hard_landing_g`; ⬚ `brake_energy`, `sink_rate` | Wear covariate + hard-removal trigger (high-energy RTO) | ◑ | *Aggregate high-freq streams:* summarize at ingestion to the **per-flight grain** (peak G, peak brake pressure, RTO flag) — exactly the grain `operational_cycles` already uses. |
| **Taxi / steering** (FDR / ADS-B: ground speed, distance, lateral turn) | `operational_cycles.taxi_distance_m`; ⬚ `lateral_load`, `turn_scrub` | Wear covariate (per-position) | ◑ | *Map turn loads to inner vs outer:* a turn-load allocation step assigns more scrub to the outboard tire on the turn's outer side → per-position wear multiplier (the `*_INBD/*_OUTBD` split). |
| **Weights / environment** (ACARS / METAR: payload, temp, crosswind) | `operational_cycles.load_factor`; ⬚ `ambient_temp`, `crosswind` | Wear covariate (heat/slip) | ◑ | *Automate METAR:* join METAR by airport + time at ingestion → per-flight thermal & crosswind features; slip-angle risk from crosswind + taxi turn. |

## Tier 2 — Schedule & Log Data (MRO Systems)

| Signal (source) | → Schema / feature | Model | POC | "Look into" → recommended handling |
|---|---|---|---|---|
| **Utilization** (OOOI: cycles, flight/taxi hours, parking) | `tires.time_to_event_cycles`, `cycles_since_install`; `aircraft.cycles_per_day` | The RUL axis (landings) + utilization for dates | ✅ | *Reliable serial join key:* an install/removal **event log** binds serial → (aircraft, position) over time; the POC's `tires` table (install/removal dates, `is_current`) already does this — the spine of the whole join. |
| **Route profiles** (training flights, rejected takeoffs) | ⬚ `operational_cycles.high_wear_event` (proxy today = accelerated-wear events) | Wear covariate + acute thermal event | ◑ | *Consistent flagging:* a controlled vocabulary of event types (RTO, training, hard-brake) stamped at the flight-log level so extreme events are never lost. |
| **Runway data** (surface texture, condition codes) | ⬚ `operational_cycles.runway_condition` | FOD / early-removal hazard covariate | ⬚ | *Standardize definitions:* normalize to ICAO **RCC (0–6)** + a surface-material enum across the network so it's a usable model input. |

## Tier 3 — Imaging & Scanning (Automated Diagnostics → the CV models)

> **Now built in the POC** (`treadcast.cv` + the *Tire Scan* screen + the `tire_scans` table):
> Depth model recovers tread depth from the image (±0.23 mm), the VLM flags cut/bulge/FOD with an
> AMM-grounded report, and OCR reads the serial — all offline/deterministic on synthetic scans,
> with Claude vision pluggable via `get_vlm("claude")`.

| Signal (source) | → Schema / feature | Model | POC | "Look into" → recommended handling |
|---|---|---|---|---|
| **Identity / OCR** (3D laser reads molded serial + retread stamp) | `tires.serial`; ⬚ `retread_level` | **VLM/OCR** → identity + join key; enables auto-capture | ✅ serial / ⬚ OCR | *Low contrast of black rubber, vulcanization hairs:* prefer **3D depth-based OCR** over 2D; confidence threshold with human-in-loop fallback; retread stamp → `retread_level` (casing history). |
| **Tread depth** (laser scanner, groove triangulation) | `inspection_records.measured_groove_mm` (now **automated**, not manual) | **Depth model** → feeds the degradation/RUL model directly | ✅ | *Calibrate to < 0.2 mm:* POC gauge noise is 0.25 mm; a laser at < 0.2 mm **tightens RUL bands**. Add per-scanner bias correction + calibration checks; lower measurement noise → later, safer wear-to-limit dates. |
| **Defect detection** (cuts, bulges, FOD) | `damage_findings` hook → `TireOutcome.EARLY_REMOVAL` / hard-removal reasons | **VLM** → **event-driven** (acute damage), separate from wear-out | ◑ hook ready | *Distinguish wear from acute damage:* **already the core split** — wear-out → scheduled swap; acute damage → immediate AOG logistics. `scoring.tire_status_report(damage_findings=[...])` forces a REPLACE-NOW status. |

## The three model families (as the user framed them)

```
 Laser/photo ──► Depth model ──► tread depth ─┐
                                              ├──► Time-series RUL model ──► "còn bay được bao lâu"
 Sensor + log (Tier 1/2) ─────────────────────┘        (degradation + survival)     + wear-to-limit date
 Photo ──► VLM ──► damage (cut/bulge/FOD) ────────────► Event-driven alerts ──► immediate AOG response
 Photo ──► VLM/OCR ──► serial + retread ──────────────► Identity / join key
                                                        ▼
                                            Tire status report = condition + explanation + RUL
                                            Software: dashboard · search-by-serial · aircraft/tire viz
```

## Schema additions — now built

- ✅ `operational_cycles`: `brake_energy_mj`, `sink_rate_fpm`, `lateral_load_g`, `turn_direction`,
  `ambient_temp_c`, `crosswind_kt`, `runway_condition` (ICAO RCC), `high_wear_event`
- ✅ `tires`: `retread_level`
- ✅ `tire_scans` table (imaging): `serial` (OCR), `laser_groove_mm` (depth), `damage_findings` (VLM),
  `scan_confidence`, `scan_date`
- ⬚ `pressure_events` telemetry table (TPMS/ACARS): `ts`, `tire_id`, `cold_pressure_pct`, `source`

These are additive and were added via a **separate RNG stream**, so the wear physics (outcome
mix, median life, the demo story, and every headline RUL metric) is byte-identical. The sensor
signals become **leakage-safe window features** — `brake_energy_mean`, `lateral_exposure` (allocated
inner-vs-outer per position), `crosswind_mean`, `runway_roughness`, `high_wear_event_rate`,
`retread_level` — which lifted the LightGBM baseline RUL MAE from 16.5 → 15.5 landings. The
modelling core (`scoring.py`) and the existing schema keys are unchanged.

## Data-quality principles (from the "Look into" notes)

- **Never silently impute** missing telemetry — flag gaps as data-quality and let confidence widen.
- **Summarize at ingestion** to the per-flight grain; don't push raw high-frequency streams downstream.
- **Standardize vocabularies** (runway codes, event types) before they become model inputs.
- **Confidence-gate the CV outputs** (OCR serial, laser depth, VLM damage) with human-in-loop fallback.
