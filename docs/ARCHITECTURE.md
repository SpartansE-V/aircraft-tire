# Architecture

TreadCast is five decoupled Python modules in a linear pipeline. Each is independently runnable
and swappable; data flows through Parquet on disk — no database, no API, no auth.

```
 config/*.yaml  ──►  generate_data.py  ──►  data/*.parquet  ──►  features.py  ──►  feature frame
   (seeded)          physics sim           (+ _ground_truth        leakage-safe        (1 row / inspection)
                                             hidden sidecar)         per-inspection

                        feature frame  ──►  train.py  ──►  artifacts/  (mixedlm prior, weibull,
                                            fit + eval        lightgbm, eval_report.json)

     prior + live readings  ──►  scoring.py  ──►  app.py  ──►  5-screen Streamlit demo
                                (PURE brain)      (UI only,
                                                   imports scoring)
```

## Modules

| Module | Responsibility | Key output |
|---|---|---|
| `generate_data.py` | Seeded, physics-informed landing-grain wear simulator with competing-risk removals and separated gauge noise | 7 Parquet tables + hidden `_ground_truth.parquet` |
| `features.py` | Leakage-safe per-inspection features (causal, backward-looking only) + whole-tire train/test splitter | Feature frame; `split_by_tire` |
| `train.py` | Fits the headline MixedLM degradation model + Weibull AFT + LightGBM baseline; writes the compact population **prior** and the evaluation report | `mixedlm_covariance.pkl` (prior), `eval_report.json` |
| `scoring.py` | **The portable brain** — pure functions: EB posterior, MC first-passage, RUL/dates, priority, spares rollup, dual alert engine, tire status report | (imported everywhere) |
| `cv/` | **CV layer** — synthetic tire images (`images.py`) + Depth model, VLM (mock or Claude), OCR (`assess.py`) → `TireScan` | `damage_findings` feed the status report |
| `generate_scans.py` | Imaging/scanning layer — writes the `tire_scans` table (laser depth + VLM damage + OCR serial) per current tire | `tire_scans.parquet` |
| `agent/` | **Agentic core** — an LLM tool-calling agent (`core.py`) over pipeline tools (`tools.py`): RUL, CV scan, MEL dispatch, spares, defect history → grounded decision + work order | OpenAI function-calling; offline fallback |
| `grounding/` | **Document layer** — AMM provenance (`amm.py`), MEL/CDL dispatch (`mel.py`), free-text defect-log extraction (`defect_logs.py`); knowledge in `config/knowledge.yaml` | dispatch decisions + structured records |
| `generate_defect_logs.py` | Emits noisy free-text logs FROM real removals (+ ground truth) so extraction is validated | `defect_logs.parquet` |
| `app.py` | 10-screen Streamlit UI (landing = Maintenance Agent); assembles per-wheel risks and renders — delegates all math to `features`/`scoring`/`cv`/`grounding`/`agent` | the demo |

## The modelling core

Tire life is **cycle-driven**, so the target is landings-to-limit, not age. train.py fits a
statsmodels **MixedLM** (`tread_depth ~ cumulative_landings * position`, random intercept+slope
per tire) once, and distills it into a population *prior*: per-position (intercept, slope), the
random-effects covariance, and the residual scale.

`scoring.eb_posterior()` then forms an **empirical-Bayes** per-tire posterior from that prior
plus the tire's own readings. This single mechanism serves three needs at once:

- a **data-rich** tire → posterior tracks its own wear line tightly;
- a **data-poor** tire → posterior shrinks to the fleet/position prior, flagged *low confidence*
  with a wide band (never a falsely tight number);
- a **held-out** tire in evaluation → same math, no leakage.

`scoring.monte_carlo_crossing()` samples (intercept, slope) from the posterior and solves the
cycle where each wear line hits 2.0 mm — a first-passage distribution that becomes RUL
quantiles, wear-to-limit dates (via utilization), and `P(cross before next check)`.

## Safety invariants (enforced in `scoring.py`)

1. **Wear-out alerts fire on the P10** (earliest-credible) bound, never the median.
2. **Wear-out (model) alerts and event-driven (deterministic rule) alerts are never blended** —
   they return in separate lists, so accuracy claims stay honest.
3. **Priority is `P(cross) × consequence`**, not a raw RUL sort — a lower-RUL wheel on a
   low-utilization, well-stocked tail can correctly rank below a higher-RUL urgent wheel.
4. **Low-confidence tires** are labelled and suppress hard wear-out alerts.
5. The **FAA/Goodyear cold-pressure ladder** ships as deterministic day-one rules.

## The `scoring.py` graduation seam

`app.py` imports `scoring.py` for **all** computation and reimplements no model math. That seam
is the deliberate path to production: the same pure functions lift behind a FastAPI service with
a React front end and MRO-system (AMOS/TRAX) read/write integration — **without a rewrite**. The
UI, the offline evaluation, and a future API all call the identical `scoring` functions.

## Data schema (Parquet)

- `fleets`, `aircraft` (tail, home station, utilization), `wheel_positions` (6-row reference)
- `tires` — install/removal, `new_tread_mm`, `outcome` (worn / early_removal / in_service),
  `censored`, `time_to_event_cycles`, `is_current`
- `inspection_records` — `cycles_since_install`, `measured_groove_mm`, `pressure_pct` (no truth)
- `operational_cycles` — per-landing date, hard-landing flag/g, load, taxi
- `station_stock` — on-hand spares per station
- `_ground_truth` — hidden: true groove depth + per-tire true wear rate, **validation only**

All ids are UUIDs; all timestamps are UTC.
