# Architecture

The repository is one Python service with a hard seam between two layers:

- **Backend (BE)** — `app/main.py`, `app/api/`, `app/domain/`, `app/services/`: a FastAPI app
  owning the HTTP surface, strict public schemas, sanitized errors, and logging. Strict-typed
  (mypy), runs on the base dependencies (`uv sync`).
- **AI** — `app/tire_rul/`: the TreadCast research pipeline (data generator, features, training,
  scoring, CV, LLM agent, document grounding, Streamlit demo). Runs on the `ai` extra
  (`uv sync --extra ai`).

```
                    BACKEND (base deps)                        AI (app/tire_rul, `ai` extra)
 ┌─────────────────────────────────────────────────┐   ┌─────────────────────────────────────┐
 │ app/api/routes/*.py      HTTP endpoints          │   │ generate_data.py  physics sim       │
 │ app/domain/schemas.py    public contracts        │   │ features.py       leakage-safe      │
 │ app/services/            business logic          │   │ train.py          fit + eval        │
 │   wear_calculator.py     physics formula         │   │ cv/, agent/, grounding/, app.py     │
 │   tire_rul_service.py  ───────────── THE SEAM ────────┼──►│ scoring.py        the pure brain    │
 └─────────────────────────────────────────────────┘   └─────────────────────────────────────┘
        POST /api/v1/tire_rul/predict ──► tire_rul_service ──► app.tire_rul.scoring.estimate_wheel()
        (inputs: config/thresholds.yaml + artifacts/mixedlm_covariance.pkl + request readings)
```

**Rule: `app/services/tire_rul_service.py` is the only backend module allowed to import `app.tire_rul`.**
Routes and domain schemas never touch the AI package; the AI package never imports the backend.
The serving path (`scoring` → `config` → `constants` → `paths`) needs only numpy + PyYAML, so
the API image ships without pandas/statsmodels/streamlit.

## Exposed API

| Method | Path | Backing |
|---|---|---|
| GET | `/health` | liveness |
| POST | `/api/v1/wear-severity/calculate` | physics formula (`wear_calculator.py`) |
| POST | `/api/v1/tire_rul/predict` | **AI**: EB posterior + Monte-Carlo first passage over the fitted MixedLM prior |

## The AI research pipeline (app/tire_rul)

Five decoupled modules in a linear pipeline; data flows through Parquet on disk.

```
 config/*.yaml  ──►  generate_data.py  ──►  data/*.parquet  ──►  features.py  ──►  feature frame
   (seeded)          physics sim           (+ _ground_truth        leakage-safe        (1 row / inspection)
                                             hidden sidecar)         per-inspection

                        feature frame  ──►  train.py  ──►  artifacts/  (mixedlm prior, weibull,
                                            fit + eval        lightgbm, eval_report.json)

     prior + live readings  ──►  scoring.py  ──►  app.py (Streamlit demo)  +  tire_rul_service.py (API)
                                (PURE brain)
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

## The `scoring.py` graduation seam — now realized

`app.py` imports `scoring.py` for **all** computation and reimplements no model math. That seam
was the deliberate path to production, and it is now live: `app/services/tire_rul_service.py` lifts
the identical pure functions behind `POST /api/v1/tire_rul/predict` — **no rewrite happened**. The
Streamlit UI, the offline evaluation, and the API all call the same `scoring` functions with
the same prior artifact and thresholds.

## Data schema (Parquet)

- `fleets`, `aircraft` (tail, home station, utilization), `wheel_positions` (6-row reference)
- `tires` — install/removal, `new_tread_mm`, `outcome` (worn / early_removal / in_service),
  `censored`, `time_to_event_cycles`, `is_current`
- `inspection_records` — `cycles_since_install`, `measured_groove_mm`, `pressure_pct` (no truth)
- `operational_cycles` — per-landing date, hard-landing flag/g, load, taxi
- `station_stock` — on-hand spares per station
- `_ground_truth` — hidden: true groove depth + per-tire true wear rate, **validation only**

All ids are UUIDs; all timestamps are UTC.
