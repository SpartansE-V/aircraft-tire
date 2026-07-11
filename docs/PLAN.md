# Implementation Plan — TreadCast POC

> Produced by the architect agent; executed by **Opus 4.8**.

## Dependencies

- python==3.11+ — single-language single-process POC as specified; 3.11 for match/typing/perf
- pandas>=2.0 — all tidy data tables and inspection/cycle joins
- pyarrow>=14 — Parquet read/write engine for every on-disk table (no DB by design)
- numpy>=1.26 — vectorized landing-event simulation and 2000-draw Monte Carlo threshold crossing
- statsmodels>=0.14 — MixedLM headline random-slope hierarchical degradation model (trains in seconds, exposes fe/re params + cov for MC sampling)
- lifelines>=0.27 — WeibullAFTFitter censoring-aware survival engine powering P(cross before next check) and quantile cross-check
- lightgbm>=4.1 — gradient-boosted regressor baseline bake-off proving linear-wear assumption leaves little signal
- shap>=0.44 — narratable per-feature attributions for the LightGBM baseline (eval report only)
- plotly>=5.18 — interactive wear-curve fan charts, fleet grid heatmap, demand-vs-stock bars
- streamlit>=1.30 — entire 5-screen demo UI, no frontend build step
- pyyaml>=6.0 — load seeded/versioned generator + threshold config (same block feeds demo sliders)
- scipy>=1.11 — norm/multivariate_normal sampling for MC draws and any distribution quantiles (transitive via statsmodels but pin explicitly)
- pytest>=8.0 — unit tests on scoring.py pure functions and generator invariants (dev-only)
- ruff>=0.3 — lint/format for a clean single-author codebase (dev-only, optional)

## File structure

```
treadcast/
├── README.md                          # Project overview, run instructions, safety positioning footer
├── requirements.txt                   # Pinned Python deps
├── pyproject.toml                     # Package metadata + pytest/ruff config (optional but included)
├── Makefile                           # Convenience targets: setup, generate, train, run, test, all
├── config/
│   ├── generator.yaml                 # Seeded, versioned synthetic-data params (fleet scale, wear bands, noise, competing-risk rates)
│   └── thresholds.yaml                # Model/alert thresholds + demo defaults (limit=2.0mm, P-cross window, accel %, pressure ladder %)
├── src/
│   └── treadcast/
│       ├── __init__.py
│       ├── constants.py               # Enums/constants: WheelPosition, AircraftType, TireOutcome, AlertType, wear limit
│       ├── paths.py                   # Central data/artifact path resolution (data/, artifacts/)
│       ├── config.py                  # YAML loaders -> typed dataclasses (GeneratorConfig, ThresholdConfig)
│       ├── generate_data.py           # Seeded physics-informed landing-grain simulator -> Parquet tables + _ground_truth sidecar
│       ├── features.py                # Leakage-safe per-inspection feature engineering + whole-tire splitter
│       ├── train.py                   # Fit MixedLM + WeibullAFT + LightGBM; persist artifacts + eval report
│       ├── scoring.py                 # PURE FUNCTIONS: wear-curve predict, MC threshold crossing, RUL/date, priority, spares rollup, alert rules
│       ├── evaluation.py              # Whole-tire holdout metrics: MAE, alpha-lambda, prognostic horizon, asymmetric score, GT recovery
│       └── app.py                     # 5-screen Streamlit UI, imports scoring.py only
├── data/                              # Generated Parquet (gitignored) — created by generate_data.py
│   ├── fleets.parquet
│   ├── aircraft.parquet
│   ├── wheel_positions.parquet
│   ├── tires.parquet
│   ├── inspection_records.parquet
│   ├── operational_cycles.parquet
│   └── _ground_truth.parquet          # Hidden sidecar: true wear rates/depths for validation ONLY
├── artifacts/                         # Trained models + reports (gitignored)
│   ├── mixedlm.pkl
│   ├── mixedlm_covariance.pkl         # Per-tire posterior means + covariance for MC sampling
│   ├── weibull_aft.pkl
│   ├── lightgbm.txt
│   ├── shap_values.parquet
│   └── eval_report.json               # All eval metrics + WORN/IN_SERVICE/EARLY_REMOVAL mix
├── tests/
│   ├── __init__.py
│   ├── conftest.py                    # Shared fixtures: tiny seeded fleet, fitted-stub params
│   ├── test_generator.py             # Invariants: median life 250-350, monotonic wear, outcome mix, reproducibility
│   ├── test_features.py              # No leakage, whole-tire split disjoint, ratio bounds
│   ├── test_scoring.py               # MC crossing, RUL math, priority ordering, alert rules, pressure ladder
│   └── test_evaluation.py            # Metric correctness on synthetic known-answer inputs
└── docs/
    ├── demo_script.md                 # 10-minute scripted walkthrough (story wheel VN-A312 / MLG_L_INBD)
    └── ARCHITECTURE.md                # Module pipeline + scoring.py graduation-path seam explanation
```

## Phases

### Phase 0 — Project Scaffold & Shared Foundations

Stand up the repo skeleton, dependency environment, config system, constants, and path resolution so every downstream module has typed config and reproducible paths. No modeling yet — just the load-bearing plumbing all 5 pipeline modules import.

- **[P0-T1]** Create the directory tree, requirements.txt (all deps from the dependency list with version pins), pyproject.toml (package name treadcast, src layout, pytest + ruff config), Makefile (setup/generate/train/run/test/all targets), and .gitignore (data/, artifacts/, __pycache__, .venv). Create empty __init__.py files. Makefile 'setup' creates a venv and pip installs requirements; 'all' runs generate -> train -> test in order.
  - *Files:* treadcast/requirements.txt, treadcast/pyproject.toml, treadcast/Makefile, treadcast/.gitignore, treadcast/src/treadcast/__init__.py, treadcast/tests/__init__.py
  - *Acceptance:* `make setup` creates a venv and installs all deps with no resolution errors on Python 3.11. `python -c "import treadcast"` succeeds. `make test` runs pytest (0 tests collected is acceptable at this stage).
- **[P0-T2]** Write constants.py with all enums/constants referenced across the pipeline: WheelPosition (NLG_L, NLG_R, MLG_L_INBD, MLG_L_OUTBD, MLG_R_INBD, MLG_R_OUTBD), AircraftType (A320_FAMILY), TireOutcome (WORN, IN_SERVICE, EARLY_REMOVAL), AlertType (EARLIEST_DATE_IN_WINDOW, P_CROSS_HIGH, WEAR_ACCEL, STATION_STOCKOUT, PRESSURE_LADDER, HARD_REMOVAL), PressureLadderAction (REINFLATE, INSPECT, REMOVE, REMOVE_TIRE_AND_MATE). Define physical constants: NEW_TREAD_MM range anchors, WEAR_LIMIT_MM = 2.0, GAUGE_NOISE_SD_MM = 0.25. Use enum.Enum with string values (snake_case) per naming conventions.
  - *Files:* treadcast/src/treadcast/constants.py
  - *Acceptance:* All enums importable; WEAR_LIMIT_MM == 2.0; each enum member has a snake_case .value; no hardcoded magic strings will be needed downstream because every categorical value has an enum here.
- **[P0-T3]** Write paths.py (resolve project root, data/ and artifacts/ dirs, create-if-missing helpers, named path constants for each Parquet table and each artifact) and config.py (dataclasses GeneratorConfig and ThresholdConfig with all fields; from_yaml classmethods using PyYAML; a get_generator_config()/get_threshold_config() that read from config/*.yaml). Config must include a version field and the RNG seed.
  - *Files:* treadcast/src/treadcast/paths.py, treadcast/src/treadcast/config.py
  - *Acceptance:* Loading both YAML configs returns fully-typed dataclasses with no missing fields; paths helpers create data/ and artifacts/ on demand; config exposes .seed and .version; a bad/missing YAML key raises a clear error rather than KeyError deep in a module.
- **[P0-T4]** Author config/generator.yaml and config/thresholds.yaml with all parameters anchored to cited published ranges. generator.yaml: seed, version, fleet scale (30 aircraft, A320 family, 6 wheels each, 18 months), per-(type,position) BASE_WEAR, new-tread 11-14mm, wear limit 2.0mm, target median life main-gear 250-350 / nose 120-200, competing-risk hazard ~0.08%/landing, accelerated-wear event rate 0.5%/landing at 3-6x, target outcome mix (55-65% WORN, 15-25% EARLY_REMOVAL, 15-25% IN_SERVICE), inspection interval 15-30 cycles, gauge noise 0.25mm, load/severity/taxi/inflation/temp factor ranges, per-tire LogNormal susceptibility params, station list + spare stock. thresholds.yaml: wear_limit_mm, planning_window_days, p_cross_threshold (0.20), wear_accel_threshold (0.30), MC draws (2000), pressure ladder bands (95-100/90-95/80-90/<80, >5%/24h), priority consequence weights.
  - *Files:* treadcast/config/generator.yaml, treadcast/config/thresholds.yaml
  - *Acceptance:* Both YAML files load via config.py into their dataclasses with every field populated. A comment cites the source range for each safety-relevant parameter. Changing the seed is the only edit needed to alter the scenario; changing no values reproduces the demo.

### Phase 1 — Physics-Informed Synthetic Data Generator (Critical Path)

Produce the reproducible, credibility-defensible synthetic dataset: simulate at landing-event grain, aggregate to inspections with separated gauge noise, emit tidy Parquet tables plus a hidden ground-truth sidecar, and lock invariants with tests. This is the critical path — if the data looks invented, every downstream number is discounted.

- **[P1-T1]** Implement the landing-event simulation core in generate_data.py. For each tire installation, per landing: wear_increment = BASE_WEAR[type,position] * f_load * f_severity * f_taxi * f_inflation * f_temp * per_tire_lognormal_susceptibility * process_noise, with rare accelerated-wear events (0.5%/landing, 3-6x multiplier). Track cumulative true_groove_depth starting from a sampled new-tread depth (11-14mm), decreasing monotonically (before noise) toward the 2.0mm limit. Everything driven by a single seeded numpy Generator from config. Vectorize per-tire where practical.
  - *Files:* treadcast/src/treadcast/generate_data.py
  - *Acceptance:* Running the sim for one tire produces a monotonically non-increasing true wear series; the same seed produces byte-identical arrays across two runs; median main-gear landings-to-2.0mm falls within 250-350 and nose within 120-200 across the fleet.
- **[P1-T2]** Add competing-risk / censoring logic: per landing, a FOD/early-removal hazard (~0.08%/landing) can retire a tire before wear-out (EARLY_REMOVAL); tires still mounted at the 18-month horizon are right-censored (IN_SERVICE); tires that reach the 2.0mm limit are WORN. Carry explicit outcome, censored (bool), and time_to_event (cycles) columns on the tires table. Tune hazard so the realized mix lands in target bands (55-65% WORN, 15-25% EARLY_REMOVAL, 15-25% IN_SERVICE).
  - *Files:* treadcast/src/treadcast/generate_data.py
  - *Acceptance:* Generated tires table carries outcome/censored/time_to_event for every row; realized outcome mix falls in the target bands on the seeded config; no tire is both WORN and censored.
- **[P1-T3]** Aggregate landings to inspections and emit all Parquet tables. Sample inspections every 15-30 cycles; measured tread_depth = true_groove_depth at that cycle + Normal(0, 0.25mm) gauge noise + ~1% gross mis-read, kept SEPARATE from process noise. Emit flat snake_case tables with UUID ids and UTC timestamps: fleets, aircraft, wheel_positions, tires, inspection_records (min groove per inspection + per-groove if simulated), operational_cycles (per-landing utilization, hard-landing flags, inflation-deviation events). Write true_groove_depth and per-tire true (intercept, slope) ONLY to _ground_truth.parquet. Also generate station spare-stock rows from config. Provide a main() / CLI entrypoint that writes all files to data/.
  - *Files:* treadcast/src/treadcast/generate_data.py
  - *Acceptance:* `python -m treadcast.generate_data` writes 6 core Parquet tables + _ground_truth sidecar to data/; inspection_records contains NO true_groove_depth column (only measured); all ids are UUIDs, all timestamps UTC; row counts are in the low thousands and regenerate in seconds.
- **[P1-T4]** Write generator invariant tests. Assert: median life bands (main 250-350, nose 120-200), monotonic underlying true wear, outcome-mix bands, new-tread within 11-14mm, gauge noise SD ~0.25mm on (measured - true) residuals from the sidecar, and full reproducibility (two generations with the same seed produce identical inspection_records). Use a small fleet override for speed if needed.
  - *Files:* treadcast/tests/test_generator.py, treadcast/tests/conftest.py
  - *Acceptance:* `pytest tests/test_generator.py` passes; every band-check and the reproducibility check are asserted (not just smoke-run); failing a band produces a readable assertion message naming the violated invariant.

### Phase 2 — Leakage-Safe Feature Engineering

Turn inspection history into leakage-safe per-inspection features and a whole-tire train/test splitter, so the models train fast and evaluation holds out whole tires (never random rows). No target information may leak from the ground-truth sidecar into features.

- **[P2-T1]** Implement features.py: for each inspection row, compute cycles_since_install, recent wear rate (delta depth / delta cycles vs prior reading), rolling wear slope (least-squares over trailing K readings), groove_remaining_ratio = (min_depth - 2.0) / (new_tread - 2.0), hard-landing count in trailing windows, inflation-deviation exposure in trailing windows. All features use ONLY data available up to and including that inspection's timestamp (causal / no look-ahead). Features are computed exclusively from the core Parquet tables — never from _ground_truth.parquet.
  - *Files:* treadcast/src/treadcast/features.py
  - *Acceptance:* Feature frame has one row per inspection with all named columns; a unit assertion confirms no feature references a future inspection (values for inspection i are unchanged if inspections > i are deleted); features.py imports nothing from the ground-truth sidecar.
- **[P2-T2]** Implement the whole-tire splitter: split_by_tire(df, test_frac, seed) partitions tire_ids (optionally grouped by aircraft) into disjoint train/test sets so no tire appears in both. Also emit fold assignments for whole-tire cross-validation. Return the split as boolean masks or filtered frames plus the id lists for the eval report.
  - *Files:* treadcast/src/treadcast/features.py
  - *Acceptance:* Train and test tire_id sets are disjoint (asserted in test); split is deterministic for a fixed seed; test fraction is within tolerance of the requested value.
- **[P2-T3]** Write feature tests: leakage guard (deleting later rows doesn't change earlier feature values), whole-tire split disjointness and determinism, groove_remaining_ratio bounds (~[0,1] before end-of-life, negative only past limit), and correct NaN handling for first-reading rows (no prior reading -> recent wear rate NaN/None, not a crash).
  - *Files:* treadcast/tests/test_features.py
  - *Acceptance:* `pytest tests/test_features.py` passes; leakage guard and split disjointness are explicit assertions; first-inspection edge case is covered.

### Phase 3 — Model Training & Prognostics Evaluation

Fit the headline MixedLM degradation model plus the Weibull AFT survival engine and the LightGBM baseline; persist artifacts (including per-tire posterior means + covariance for Monte Carlo); and produce the prognostics-grade evaluation report on whole-tire holdout.

- **[P3-T1]** In train.py, fit the headline model: statsmodels MixedLM of tread_depth ~ cumulative_landings with per-tire random intercept + random slope, partially pooled by wheel position and aircraft type (grouping/variance components). Extract, per tire, the fitted (intercept, slope) posterior mean and a covariance estimate suitable for MC sampling; for tires with too few readings, fall back to the fleet/position prior and TAG them low_confidence. Persist mixedlm.pkl and mixedlm_covariance.pkl (per-tire params + cov + low_confidence flag).
  - *Files:* treadcast/src/treadcast/train.py
  - *Acceptance:* Model fits on the generated data in seconds; per-tire (intercept, slope, cov, low_confidence) are persisted for every in-scope tire; tires with < N readings carry low_confidence=True and their slope equals the pooled prior slope (verified).
- **[P3-T2]** Fit the two supporting models. (1) lifelines WeibullAFTFitter on cycles-to-removal with position/type/load covariates using the outcome/censored columns (right-censoring-aware); persist weibull_aft.pkl. (2) LightGBM regressor on the Phase-2 engineered features predicting RUL-in-cycles, with SHAP values computed on the holdout; persist lightgbm.txt and shap_values.parquet. Both are supporting/bake-off models — the MixedLM remains the headline.
  - *Files:* treadcast/src/treadcast/train.py
  - *Acceptance:* WeibullAFT fits using censored rows (does not drop IN_SERVICE/EARLY_REMOVAL as failures — asserted via the mix passed in); LightGBM + SHAP artifacts persist; a quick sanity check shows recent-wear-rate is a top SHAP feature.
- **[P3-T3]** Implement evaluation.py and wire it into train.py. On whole-tire holdout compute: MAE on RUL-in-cycles and on wear-to-limit date; alpha-lambda accuracy (alpha=0.2) over the second half of tire life; prognostic horizon; an asymmetric score penalizing late (over-estimated) RUL more heavily; ground-truth recovery (compare fitted per-tire wear rate vs sidecar true rate, target within +-10% median abs error). Also report the WORN/IN_SERVICE/EARLY_REMOVAL mix. Write all of this to artifacts/eval_report.json.
  - *Files:* treadcast/src/treadcast/evaluation.py, treadcast/src/treadcast/train.py
  - *Acceptance:* `python -m treadcast.train` writes eval_report.json containing every listed metric plus the outcome mix; ground-truth wear-rate recovery median abs error is reported (target <=10%); asymmetric score confirms late errors are penalized more than early ones; holdout is whole-tire (test tires never seen in fit).
- **[P3-T4]** Add evaluation tests using known-answer synthetic inputs: feed the metric functions arrays with hand-computed expected MAE / alpha-lambda / asymmetric score and assert equality within tolerance; assert the asymmetric score is strictly larger for a late-biased prediction than an equally-sized early-biased one.
  - *Files:* treadcast/tests/test_evaluation.py
  - *Acceptance:* `pytest tests/test_evaluation.py` passes; asymmetric-penalty directionality is explicitly asserted; metric functions match hand-computed values on toy inputs.

### Phase 4 — scoring.py: The Portable Brain (Pure Functions)

Implement the deliberately decoupled scoring layer as pure functions (no I/O, no Streamlit) covering wear-curve prediction, Monte Carlo threshold crossing, RUL/date computation, composite priority scoring, weekly spares-demand rollup, and the dual alert engine including deterministic FAA/Goodyear rules. This is the graduation-path seam and the most heavily tested module.

- **[P4-T1]** Implement wear-curve + Monte Carlo first-passage functions in scoring.py: predict_wear_line(intercept, slope, cycles) and monte_carlo_crossing(intercept, slope, cov, limit_mm=2.0, n_draws=2000, seed) -> array of crossing cycles by drawing (intercept, slope) samples from the fitted covariance and solving where each sampled line hits the limit. Then rul_from_crossings(crossings, current_cycles) -> {median, p10, p90} remaining landings, and crossings_to_dates(crossings, trailing_landings_per_day, as_of_date) -> {median_date, p10_date, p90_date} propagating utilization into the band. All functions are pure (inputs -> outputs, RNG seed passed in).
  - *Files:* treadcast/src/treadcast/scoring.py
  - *Acceptance:* monte_carlo_crossing returns n_draws crossing cycles; a steeper mean slope yields an earlier median crossing (monotonicity asserted); P10 date is always on-or-before the median date; functions have no file/network I/O and take an explicit seed.
- **[P4-T2]** Implement composite priority scoring: priority_score(p_cross_before_next_check, consequence_weight) where consequence_weight blends tail utilization (AOG exposure), wheel-position criticality, and station spare availability, with recent hard-landing and pressure-ladder multipliers. p_cross_before_next_check comes from the MC crossing distribution / survival curve. Also implement a build_worklist(...) that ranks wheels and attaches a one-line plain-English 'why' + recommended action per wheel. Priority is a probability x consequence composite, NOT a raw RUL sort.
  - *Files:* treadcast/src/treadcast/scoring.py
  - *Acceptance:* Given two wheels with equal RUL, the one on a higher-utilization tail with zero station spares ranks higher (asserted); build_worklist returns rows with rank, score, reason string, and action; a low-RUL wheel on a low-utilization tail can correctly rank below a higher-RUL urgent wheel.
- **[P4-T3]** Implement weekly spares-demand rollup: spares_demand(per_wheel_crossing_dates, station, tire_size) aggregates each wheel's MC limit-crossing date distribution into a probabilistic weekly removal-demand forecast per station and tire size, returning expected and P90 demand per week; compare against configurable on-hand stock to flag projected stock-out weeks and recommend reorder timing. Reuses the same per-wheel MC output — no new model.
  - *Files:* treadcast/src/treadcast/scoring.py
  - *Acceptance:* Given wheels whose P90 crossing dates cluster in week 3 and stock=3 with 5 projected removals, the function flags a week-3 stock-out and a reorder recommendation dated before it; expected demand <= P90 demand for every week.
- **[P4-T4]** Implement the dual alert engine as pure functions. Model alerts: earliest-credible (P10) wear-to-limit date inside the planning window; P(cross before next check) > threshold (default 0.20); per-tire wear rate accelerating > threshold (default 30%) vs its own baseline; projected station stock-out. Deterministic rules (day one): Goodyear/FAA cold-pressure ladder (95-100 reinflate, 90-95 inspect, 80-90 remove, <80 remove tire + mate, >5%/24h recurring loss) and hard-removal flags (worn to groove base, bulge, cord exposure, post-hard-landing). CRITICAL: model alerts fire on the conservative lower bound (P10), never the median; event-driven risk is returned SEPARATELY from wear-out RUL alerts (never blended). All thresholds come from ThresholdConfig.
  - *Files:* treadcast/src/treadcast/scoring.py
  - *Acceptance:* Alert functions fire on P10 not median (asserted with a case where median is outside but P10 is inside the window -> alert fires); pressure-ladder function returns the correct action for each band boundary; wear-out and event-driven alerts are returned in separate collections; every threshold is read from config, none hardcoded.
- **[P4-T5]** Write comprehensive scoring tests covering every pure function: MC crossing monotonicity and seed-reproducibility, RUL quantile ordering (p10<=median<=p90), date propagation, priority ordering against RUL-only sort, spares stock-out flagging, each pressure-ladder band, P10-not-median alert firing, and wear-out vs event-driven separation. Include the low-confidence fleet-prior path.
  - *Files:* treadcast/tests/test_scoring.py
  - *Acceptance:* `pytest tests/test_scoring.py` passes with coverage of every public scoring function; the safety-critical assertions (P10 alerting, wear/event separation, priority != raw RUL) are explicit; low-confidence tires are labeled and never emit a falsely tight RUL band.

### Phase 5 — Streamlit 5-Screen Demo UI

Build the 5-screen Streamlit app that imports ONLY scoring.py (plus Parquet/artifact loading), rendering all 5 pilot capabilities on-screen with explicit-assumption sliders, low-confidence labels, the ground-truth validation panel, and the safety-positioning footer.

- **[P5-T1]** Build app.py foundation: cached loaders for Parquet tables + model artifacts, a sidebar with demo sliders bound to ThresholdConfig (utilization landings/day, wear limit, planning window, P-cross threshold, wear-accel threshold), page navigation across the 5 screens, and a persistent safety-positioning footer ('decision support that prioritizes within existing AMM removal limits — augments, never replaces, mandated inspections; data is synthetic'). App must import only scoring.py for computation (no train/features logic re-implemented in the UI).
  - *Files:* treadcast/src/treadcast/app.py
  - *Acceptance:* `streamlit run src/treadcast/app.py` launches; all 5 sliders are present and changing them re-runs scoring functions live; the safety footer is visible on every screen; app.py contains no model fitting or feature engineering — only calls into scoring.py.
- **[P5-T2]** Implement Screen 1 (Fleet Health Overview): KPIs (wheels critical in 30/60/90 days, AOG-risk count) above a color-coded aircraft x wheel-position grid (Plotly heatmap) with click-through to a selected wheel. And Screen 2 (Per-Wheel Wear Curve): measured tread points, fitted MixedLM degradation line, MC fan chart to the 2.0mm limit, RUL in landings AND days, P10-P90 wear-to-limit date band; low-data wheels display 'fleet prior — low confidence' instead of a tight number.
  - *Files:* treadcast/src/treadcast/app.py
  - *Acceptance:* Fleet grid renders with color-coded criticality and correct KPI counts; selecting a wheel opens its wear curve with measured points, fitted line, and fan chart crossing the 2.0mm limit; a known low-data wheel shows the low-confidence label and a wide band.
- **[P5-T3]** Implement Screen 3 (Priority Worklist): sortable, color-coded ranked table from scoring.build_worklist with per-wheel plain-English 'why' and recommended action. And Screen 4 (Spares Planner): per-station/tire-size weekly removal-demand chart (expected vs P90) versus on-hand stock, with stock-out weeks flagged and reorder recommendations. And Screen 5 (Alerts Feed): rule-triggered cards separating model alerts (P10 date in window, crossing probability, wear acceleration) from deterministic FAA/Goodyear pressure-ladder and hard-removal flags.
  - *Files:* treadcast/src/treadcast/app.py
  - *Acceptance:* Worklist orders wheels by composite priority (not raw RUL) with a reason per row; Spares Planner visibly flags a stock-out week with a reorder date before it; Alerts Feed shows model and deterministic alerts in visually distinct groups and no wear-out alert uses the median date.
- **[P5-T4]** Add the Ground-Truth Validation panel (its own screen or a section on Screen 1): show 'model recovered true per-tire wear rates within +-X% median absolute error' using the sidecar and eval_report.json, plus a compact prognostics scorecard (whole-tire MAE, alpha-lambda accuracy, prognostic horizon, asymmetric late-penalty score, outcome mix). This is honest-accuracy evidence only a synthetic POC can show; clearly label it validation-only.
  - *Files:* treadcast/src/treadcast/app.py
  - *Acceptance:* Validation panel reads eval_report.json and the sidecar, displays the wear-rate recovery figure and the full scorecard, and is clearly labeled as synthetic-data validation evidence (not a production accuracy claim).

### Phase 6 — Demo Scripting, Docs & End-to-End Hardening

Tune the seeded scenario to produce the scripted 10-minute story, write the demo script and architecture/README docs (with the graduation-path seam and safety positioning), and verify the whole pipeline runs end-to-end with zero code edits.

- **[P6-T1]** Tune the seed/config so the scripted demo story materializes deterministically: a story wheel (e.g. VN-A312 / MLG_L_INBD) whose curve shows post-under-inflation acceleration, median wear-to-limit ~19 days but P10 ~11 days inside the next check interval; it ranks ~#2 fleet-wide (6 cycles/day tail, zero station spares) above a lower-RUL low-utilization wheel; SGN week-3 projects 5 removals vs 3 in stock; the 'earliest-credible date inside window' alert fires ~14 days ahead alongside an 80-90% pressure-ladder removal flag on another wheel. Fix the seed once the story lands.
  - *Files:* treadcast/config/generator.yaml, treadcast/config/thresholds.yaml
  - *Acceptance:* With the committed seed, regenerating + retraining reproduces the exact story beats (the named wheel is critical, ranks ~#2, SGN week-3 stock-out fires, alert fires ~14 days ahead) with zero code edits; a second full run reproduces identical outputs.
- **[P6-T2]** Write docs/demo_script.md (the 10-minute walkthrough mapping each of the 5 screens to a story beat and closing on the reactive-vs-proactive counterfactual, ground-truth panel, and the synthetic-data caveat) and docs/ARCHITECTURE.md (the 5-module linear pipeline diagram + the scoring.py seam explaining the FastAPI+React / MRO-integration graduation path without rewrite). Write README.md (quickstart: make setup / generate / train / run; safety positioning footer; out-of-scope list: no CV, no real data, no MRO integration, no auth/DB).
  - *Files:* treadcast/docs/demo_script.md, treadcast/docs/ARCHITECTURE.md, treadcast/README.md
  - *Acceptance:* README quickstart commands, run verbatim on a clean clone, take a reader from install to a running app; demo_script.md ties each screen to a concrete on-screen number from the seeded run; ARCHITECTURE.md explicitly describes the scoring.py graduation seam and states the safety positioning.
- **[P6-T3]** End-to-end hardening: verify `make all` (generate -> train -> test) then `streamlit run` works from a clean venv on the committed seed; run the full test suite; confirm the success-metric gates from the proposal are met on the seeded run (whole-tire RUL MAE within target, wear-to-limit date MAE <=7d at 30d horizon, alpha-lambda >=70% over second half of life, zero missed limit-crossings among alerted wheels with >=10 cycle lead, worklist-vs-truth Spearman >=0.8, wear-rate recovery within +-10%). Record the observed values in eval_report.json / README. Fix any gate miss by tuning config, not by loosening the metric.
  - *Files:* treadcast/README.md, treadcast/Makefile, treadcast/tests/test_scoring.py
  - *Acceptance:* `make all` passes with all tests green on a clean environment; the app launches and shows the scripted story; every success-metric gate is met and its observed value is recorded; no code edits are required between generate, train, and demo.

## Milestones

- M0 — Foundation ready: repo scaffolded, `make setup` installs all deps on Python 3.11, config/constants/paths load as typed dataclasses (end of Phase 0).
- M1 — Credible data on disk: `python -m treadcast.generate_data` emits 6 Parquet tables + hidden ground-truth sidecar; all generator invariant tests pass (median life bands, monotonic wear, outcome mix, reproducibility) (end of Phase 1). This is the critical-path gate — nothing downstream is trustworthy until this passes.
- M2 — Leakage-safe features: per-inspection causal features + whole-tire splitter with leakage-guard and disjointness tests passing (end of Phase 2).
- M3 — Models trained + honestly evaluated: MixedLM (with per-tire cov for MC) + WeibullAFT + LightGBM persisted; eval_report.json produced on whole-tire holdout with MAE, alpha-lambda, prognostic horizon, asymmetric score, and ground-truth wear-rate recovery within +-10% (end of Phase 3).
- M4 — Portable brain complete: scoring.py pure functions (MC crossing, RUL/date, priority, spares rollup, dual alert engine with FAA/Goodyear rules) fully implemented and tested, firing on P10 not median, keeping wear-out and event-driven alerts separate (end of Phase 4). This is the graduation-path seam.
- M5 — Demo-able app: 5-screen Streamlit UI importing only scoring.py, all 5 pilot capabilities on-screen, sliders live, low-confidence labels, ground-truth validation panel, safety footer (end of Phase 5).
- M6 — Shippable POC: seeded 10-minute story reproduces with zero code edits, docs (demo script, architecture, README) complete, `make all` green on a clean env, and every proposal success-metric gate met and recorded (end of Phase 6).
