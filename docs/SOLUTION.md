# Solution Proposal — TreadCast — Aircraft Tire RUL & Wear-Forecasting POC

> Synthesized by **Fable 5** from the multi-agent research team.

**A vendor-agnostic, software-only tire prognostics demo that turns (synthetic) historical inspection records into landings-based RUL forecasts, wear-to-limit dates with confidence bands, a prioritized wheel worklist, station-level spares planning, and safety-grounded risk alerts — all in one Streamlit app powered by a hierarchical wear-degradation model.**

## Target users

- Airline maintenance planners / Maintenance Control Center (MCC) staff who decide which wheels to pull and when
- Line maintenance & wheel-shop engineers who perform tread/pressure inspections and removals
- Spares & inventory planners at airline stations and MROs who pre-position tire/wheel assemblies
- Fleet reliability engineers who need explainable, auditable degradation analytics (POC evaluation audience)

## Core capabilities (mapped to the 5 pilot goals)

### Forecast tire Remaining Useful Life (pilot goal 1)

A random-slope hierarchical (mixed-effects) linear degradation model fits measured tread depth vs cumulative landings per tire-installation, partially pooled toward fleet priors by wheel position and aircraft type (so tires with 2-3 readings shrink to the fleet wear rate instead of failing). RUL = (current min groove depth − 2.0 mm limit) / estimated wear rate, reported in remaining landings with a P10–P90 interval; a Weibull AFT survival model (right-censoring-aware) cross-checks the RUL quantiles, and a LightGBM regressor serves as an accuracy anchor in the eval report. Tires with insufficient data explicitly display 'fleet prior — low confidence' rather than a falsely tight number.

### Predict wear-to-limit dates (pilot goal 2)

First-passage threshold crossing with Monte Carlo uncertainty: draw N=2000 (intercept, slope) samples from the fitted per-tire posterior/covariance, solve the cycle where each sampled wear line crosses the 2.0 mm limit, convert cycles to calendar dates using that tail's trailing-30-day landings/day, and render a fan chart showing the median date plus the earliest-credible (P10) date. Utilization is displayed as an explicit, slider-overridable assumption and its uncertainty is propagated into the date band.

### Prioritize wheels requiring maintenance attention (pilot goal 3)

A composite priority score — not a raw RUL sort — computed in scoring.py: P(limit crossing before the tail's next maintenance opportunity) from the survival/degradation posterior, multiplied by a consequence weight (tail utilization/AOG exposure, wheel-position criticality, spare availability at the tail's station) and boosted by recent hard-landing count and pressure-ladder status. Rendered as a color-coded, sortable worklist with a recommended action and a one-line 'why' explanation per wheel.

### Support spare inventory and maintenance planning (pilot goal 4)

Aggregate every wheel's Monte Carlo limit-crossing date distribution into a probabilistic weekly removal-demand forecast per station and tire size, compared against configurable on-hand stock. The Spares Planner screen flags projected stock-out weeks, shows expected vs P90 demand, and recommends reorder timing/pre-positioning — converting the same per-wheel model output into planner-currency (dates and stock counts) with zero extra models.

### Generate risk alerts for potential operational disruptions (pilot goal 5)

Dual alert engine. (a) Model alerts: earliest-credible wear-to-limit date enters the planning window; P(cross before next check) > 20%; per-tire wear rate accelerating > 30% vs its own baseline; projected station stock-out. (b) Deterministic, standards-grounded rules shipped day one: the Goodyear/FAA cold-pressure action ladder (95–100% reinflate, 90–95% inspect, 80–90% remove, <80% remove tire + mate, >5%/24h recurring loss) and hard-removal flags (worn to groove base, bulge, cord exposure, post-hard-landing/high-energy event). All alerts fire on the conservative lower bound, never the median.

## Approach

**Data strategy.** Physics-informed synthetic data generator (no real data exists; this is the critical path). Simulate at the landing-event grain, then aggregate to inspections: per landing, wear = BASE_WEAR[type,position] × f_load × f_severity × f_taxi × f_inflation × f_temp × per-tire LogNormal susceptibility × process noise, with rare accelerated-wear events (0.5%/landing, 3–6× multiplier). Anchor all parameters to published ranges: new main-gear tread 11–14 mm, wear limit 2.0 mm, median main-gear life 250–350 landings (nose 120–200), FOD/early-removal competing-risk hazard (~0.08%/landing) yielding 15–25% EARLY_REMOVAL, 15–25% still-mounted right-censored IN_SERVICE, and ~55–65% clean WORN labels. Sample inspections every 15–30 cycles with Normal(0, 0.25 mm) gauge noise kept separate from process noise; store true_groove_depth in a hidden ground-truth sidecar for validation only. Fleet scale: one narrowbody family (A320-class), 30 aircraft, 6 wheels each (main-gear focus + nose for contrast), 18 months of history — thousands of inspection rows, seconds to regenerate. Seeded RNG + versioned YAML config so every demo run reproduces the exact same story. Schema: fleets/aircraft/wheel_positions/tires/inspection_records/operational_cycles as flat Parquet tables (snake_case, UUID ids, UTC timestamps), denormalized enough to train fast.

**Modeling approach.** DECISION: the headline model is a random-slope linear mixed-effects degradation model (statsmodels MixedLM) of tread_depth ~ cumulative_landings with per-tire random intercept+slope, partially pooled by wheel position and aircraft type. It trains in seconds, handles sparse/irregular readings natively, extrapolates cleanly to the limit, and every prediction reduces to a plotted wear line a maintenance engineer can read — which matters more than marginal accuracy in a stakeholder demo. Two supporting models: (1) a Weibull AFT survival model (lifelines) on cycles-to-removal with position/type/load covariates as the censoring-correct risk engine — it powers P(cross before next check) and validates the degradation model's quantiles; (2) a LightGBM + SHAP regressor on engineered features (recent wear rate, rolling slope, cycles-since-install, hard-landing counts, inflation-deviation exposure) as a bake-off baseline proving the linear-wear assumption isn't leaving signal on the table. Deep sequence models (LSTM/Transformer) and CV are explicitly rejected for this data regime. Evaluation: hold out whole tires (never random rows), report MAE on RUL-in-cycles and on wear-to-limit date, alpha-lambda accuracy (α=0.2), prognostic horizon, and an asymmetric score penalizing late (over-estimated) RUL more heavily — the dangerous direction — plus a 'ground-truth recovery' panel showing the model recovered true wear rates within ±10%.

**Wear-to-limit method.** First-passage-time Monte Carlo: (1) fit the mixed-effects model; (2) per tire, draw 2000 (intercept, slope) samples from the fitted posterior/covariance; (3) solve the crossing cycle where each sampled line hits the 2.0 mm serviceable limit; (4) convert cycles to dates via the tail's trailing-30-day landings/day utilization (planner-overridable slider, uncertainty propagated); (5) report median date + P10–P90 band as a fan chart, and surface the P10 'earliest credible replacement date' as the planning and alerting anchor. Cycles are the physics axis; calendar dates are derived only at the end — keeping the model honest while giving planners what they actually schedule against.

**Prioritization & alerting.** Priority score = P(limit crossing before next maintenance opportunity) × consequence weight, where the probability comes from the Monte Carlo crossing distribution / survival curve and the consequence weight blends tail utilization (AOG exposure), position criticality, and station spare availability; recent hard-landing and pressure-ladder events add multipliers. Alerts fire when: earliest-credible (P10) wear-to-limit date falls inside the planning window; P(cross before next check) > 20% (tunable slider); wear rate accelerates > 30% vs the tire's own baseline; projected weekly station demand exceeds on-hand stock; or any deterministic Goodyear/FAA pressure-ladder / hard-removal rule triggers. All thresholds live in one config block exposed as demo sliders. Event-driven risk (FOD, hard landings) is reported separately from wear-out RUL — never blended — so accuracy claims stay honest.

## Architecture

Five decoupled Python modules in a linear pipeline, each independently runnable and swappable: (1) generate_data.py — seeded physics-informed synthetic generator emitting tidy Parquet tables (fleets, aircraft, wheel_positions, tires, inspection_records, operational_cycles) plus a hidden _ground_truth sidecar; (2) features.py — leakage-safe per-inspection feature engineering (cycles_since_install, recent wear rate, rolling wear slope, hard-landing/inflation exposure windows, groove_remaining_ratio), split by whole tire; (3) train.py — fits MixedLM degradation model + Weibull AFT + LightGBM baseline, persists model artifacts and an evaluation report (MAE, alpha-lambda, prognostic horizon, asymmetric score, ground-truth recovery); (4) scoring.py — the portable brain: pure functions for wear-curve prediction, Monte Carlo threshold crossing, RUL and date computation, priority scoring, weekly spares-demand rollup, and alert-rule evaluation (deterministic pressure-ladder rules included); (5) app.py — a 5-screen Streamlit UI importing only scoring.py: Fleet Health Overview (KPIs + color-coded fleet grid), Per-Wheel Wear Curve (measured points, fitted line, fan chart to limit, RUL + dates), Priority Worklist (ranked table with reasons), Spares Planner (weekly demand vs stock, stock-out flags), Alerts Feed (rule-triggered cards). All data flows through Parquet on disk — no database, no API, no auth. The scoring.py seam is the deliberate graduation path: if greenlit, the same functions lift behind FastAPI with a React front end and MRO-system (AMOS/TRAX) read/write integration, without a rewrite. Positioning throughout: decision support that prioritizes within existing AMM removal limits — never extends them.

## Tech stack

- Python 3.11+ (single-language, single-process POC — org-default Kotlin/Micronaut + Next.js explicitly rejected as production ceremony a DS demo cannot justify)
- pandas + pyarrow (Parquet) for all data tables
- numpy (vectorized landing-event simulation, Monte Carlo threshold crossing)
- statsmodels MixedLM — hierarchical random-slope degradation model (headline)
- lifelines WeibullAFTFitter — censoring-aware survival/risk engine
- LightGBM + SHAP — baseline bake-off model with narratable feature attributions
- Plotly — interactive wear-curve fan charts, fleet grid, demand-vs-stock charts
- Streamlit — the entire 5-screen demo UI, no frontend build
- PyYAML — seeded, versioned generator + threshold config (demo sliders read the same block)
- pytest — unit tests on scoring.py pure functions and generator invariants (median life in 250–350 band, monotonic wear)

## Key features

- Fleet Health Overview: at-a-glance KPIs (wheels critical in 30/60/90 days, AOG-risk count) over a color-coded aircraft/wheel grid
- Per-wheel wear curve with fan chart: measured tread points, fitted degradation line, P10–P90 wear-to-limit date band, RUL in landings AND days
- Composite-risk Priority Worklist: probability × consequence ranking with per-wheel plain-English justification and recommended action
- Station-level Spares Planner: probabilistic weekly removal demand vs on-hand stock with stock-out flags and reorder recommendations
- Alerts Feed combining ML alerts (lower-bound date, crossing probability, wear acceleration) with deterministic Goodyear/FAA pressure-ladder and hard-removal rules
- Ground-truth validation panel: 'model recovered true wear rates within ±10%' — honest accuracy evidence only a synthetic POC can show
- Explicit-assumption UX: utilization (landings/day), wear limit, and alert thresholds exposed as sliders; low-data tires labeled 'fleet prior — low confidence'
- Prognostics-grade evaluation report: whole-tire holdout MAE, alpha-lambda accuracy, prognostic horizon, asymmetric late-penalty score (NASA-style)
- Seeded reproducible scenario: one config regenerates the exact demo story every run
- Clean scoring.py seam so the model/scoring core lifts into FastAPI + MRO integration post-greenlight without rewrite

## Demo scenario

A scripted 10-minute walkthrough on a seeded 30-aircraft A320-family fleet, anchored on one story wheel. (1) Open Fleet Health: 'Here is your whole fleet at a glance — 7 wheels go critical within 30 days; today you'd find out at the gate.' (2) Drill into tail VN-A312, wheel MLG_L_INBD: its wear curve shows acceleration after a sustained under-inflation run; the fan chart puts the median wear-to-limit date 19 days out but the earliest-credible date just 11 days out — inside the next check interval. (3) Jump to the Priority Worklist: this wheel ranks #2 fleet-wide because its tail flies 6 cycles/day and its station holds zero spares of that size — while a lower-RUL wheel on a low-utilization tail correctly ranks below it. (4) Switch to the Spares Planner: week 3 at the SGN hub projects 5 removals of this tire size against 3 in stock — reorder now, two weeks before the stock-out. (5) Land on the Alerts Feed: the 'earliest-credible date inside planning window' alert fired 14 days ahead, alongside a deterministic 80–90% pressure-ladder removal flag on another wheel — 'this is the alert that turns an AOG into a scheduled overnight swap.' Close on the counterfactual (reactive today vs proactive with TreadCast, at $10–20K/hr narrowbody AOG cost), the ground-truth validation panel, and the explicit caveat: synthetic data proves the method and pipeline; real inspection records are the next step.

## Success metrics

- All 5 pilot capabilities visibly demonstrated on-screen in one navigable app, driven by a single model + scoring layer
- Held-out (whole-tire) MAE on RUL ≤ 15% of true remaining life at mid-life, and wear-to-limit date MAE ≤ 7 days at 30-day horizon, on noisy synthetic data
- Alpha-lambda accuracy: ≥ 70% of predictions within the ±20% band over the second half of tire life; prognostic horizon reported
- Safe-bias verified: asymmetric score shows late (over-estimated) RUL errors are rarer than early ones; zero missed limit-crossings among alerted wheels in the seeded scenario (every crossing alerted ≥ 10 cycles ahead)
- Prioritization quality: Spearman correlation ≥ 0.8 between worklist rank and true remaining-life-adjusted risk from the ground-truth sidecar
- Model recovers ground-truth per-tire wear rates within ±10% median absolute error (validation panel)
- Reproducibility: fixed seed regenerates the identical demo story; 10-minute walkthrough runs end-to-end with zero code edits
- Delivery: built by one DS/full-stack builder in ≤ 3 weeks (generator 2–3d, features+models 2–3d, scoring 1d, UI 3–4d, demo scripting + buffer 2d)

## Risks & mitigations

- **Synthetic-data credibility collapse: if wear curves or failure timing look invented, stakeholders discount every downstream number.**
  - *Mitigation:* Anchor every generator parameter to cited FAA/Goodyear/Bridgestone ranges (11–14 mm new, 2.0 mm limit, 250–350 landings main-gear median, 15–25% FOD early removals); assert these bands in generator unit tests; have a domain reviewer eyeball sample curves; state plainly in the demo that data is synthetic and the pipeline is what transfers.
- **Label leakage / too-easy learning: RUL is derived from the same equation that generates features, so the model can post unrealistically low error.**
  - *Mitigation:* Inject separated measurement noise (0.25 mm gauge error + 1% gross mis-reads) and process noise, include censored and competing-risk removals, hold out whole tires/aircraft in CV, and frame reported error explicitly as 'method demonstration on synthetic data — real accuracy TBD'.
- **Censoring handled wrong: dropping IN_SERVICE/EARLY_REMOVAL tires or treating them as failures biases RUL systematically low (or high).**
  - *Mitigation:* Carry explicit outcome/censored/time_to_event columns end-to-end; use the Weibull AFT survival model as the censoring-correct backbone; report the WORN/IN_SERVICE/EARLY_REMOVAL mix in the eval report.
- **Over-estimated RUL is the costly error — predicting more life than exists causes the exact AOG the project targets.**
  - *Mitigation:* Alert on the P10 lower bound, never the median; use an asymmetric evaluation score with heavier late-penalty; validate linearity on retired-tire curves and allow a mild two-phase wear term if residuals show end-of-life acceleration.
- **Wrong utilization assumption moves every predicted date even with a perfect wear model.**
  - *Mitigation:* Derive landings/day from trailing 30-day history per tail, display it as a visible assumption with a planner-override slider, and propagate utilization variance into the date confidence band.
- **Scope creep toward production, computer vision, or real-data ingestion blows the 3-week timeline.**
  - *Mitigation:* Hard scope line: CV tread scoring, TPMS/sensor feeds, and MRO-system integration are roadmap slides only; if the generator or model overruns its budget, ship simpler per-position linear fits rather than cutting any of the 5 screens — breadth across the 5 goals sells the pilot.
- **Safety/regulatory mispositioning: any implication the tool replaces mandated inspections or extends AMM limits is a non-starter and a liability.**
  - *Mitigation:* Position everywhere (UI footer, README, demo script) as decision support that prioritizes within existing removal limits and augments mandated cold-pressure checks; ship the deterministic FAA/Goodyear rule alerts alongside ML to show standards fluency.
- **Incumbent comparison (Bridgestone+JAL, Michelin/Safran PresSense) undercuts the pitch.**
  - *Mitigation:* Differentiate explicitly in the demo narrative: vendor-agnostic, software-only, zero hardware, works across mixed tire brands on data airlines already collect — the underused-inspection-records wedge neither OEM-locked incumbent occupies.

## Out of scope

- Computer-vision tread-depth scoring from photos (roadmap module after greenlight — core engine must run on tabular inspection history alone)
- Real data ingestion and TPMS/FDR/QAR sensor feeds (Phase 2 accuracy upside, not a demo prerequisite)
- MRO-system integration (AMOS/TRAX/Ramco read/write) — shown as an architecture slide, not built
- Production concerns: authentication, multi-tenancy, RBAC, concurrent users, database, API layer (Streamlit + Parquet only; FastAPI+React is the documented graduation path)
- Multi-fleet and cross-type model transfer — POC is one narrowbody family; nose-gear included only as contrast, not a validated model target
- Deep learning models (LSTM/Transformer) — wrong tool for sparse irregular inspection data
- Retread-shop workflow and casing lifecycle management (R-level is a feature, not a managed process)
- Any certified airworthiness decision-making or extension of AMM removal limits
- Fleet-level financial ROI modeling beyond the pitch-deck AOG/inventory benchmarks quoted in the demo narrative
