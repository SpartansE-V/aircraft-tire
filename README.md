# TreadCast — Aircraft Tire RUL & Wear-Forecasting POC

**Turns (synthetic) historical tire-inspection records into landings-based Remaining Useful
Life (RUL) forecasts, wear-to-limit dates with confidence bands, a prioritized wheel worklist,
station-level spares planning, and safety-grounded risk alerts — in one Streamlit app.**

> Built for the P3 pilot: *predict tire remaining life so aviation maintenance teams reduce AOG
> risk, emergency logistics, and inventory inefficiency.* See [REQUIREMENT](../REQUIREMENT.md),
> [SOLUTION](docs/SOLUTION.md), and [PLAN](docs/PLAN.md).

---

## Why this shape

Aircraft tires wear by **landing cycles, not calendar age** — so RUL is modelled as a
wear-to-limit problem on tread depth, not an age-survival problem. The headline model is a
**hierarchical (mixed-effects) wear-degradation model**: it fits tread depth vs. cumulative
landings per tire, partially pooled toward a fleet/position prior, so a tire with 2–3 readings
shrinks to the fleet wear rate instead of over-fitting. Every prediction reduces to a wear line
a maintenance engineer can read.

The safety posture is explicit: alerts fire on the **conservative earliest-credible (P10)**
bound (never the median), the deterministic **FAA/Goodyear cold-pressure ladder** ships
alongside the ML model, and nothing here extends AMM removal limits — it prioritizes *within*
them.

## Agentic AI — the Maintenance Decision Agent (core)

The decision layer is an **LLM agent** (`treadcast.agent`) that turns a natural-language request
into a grounded maintenance decision by **autonomously calling tools** over the whole pipeline —
it is the core of the product, not a bolt-on. Ask it *"what should I do about VN-A300's main gear?"*
or *"plan tonight's tire maintenance for SGN"* and it investigates:

`list_priority_wheels` · `get_wheel_status` (RUL) · `get_tire_scan` (CV) · `check_dispatch`
(MEL/CDL) · `get_amm_thresholds` · `check_spares` · `search_defect_history`

…then reasons across the results — distinguishing **wear** (schedule a swap) from **acute damage**
(no dispatch relief → AOG), citing the AMM/MEL reference, and firing on the earliest-credible date —
and returns a decision + **work-order draft**, with its full tool-call **trace** shown. Backends:
**OpenAI function-calling** (`OPENAI_API_KEY`, model via `OPENAI_AGENT_MODEL`, default
`gpt-4o-mini`) — the agentic core — with an **offline deterministic planner** that runs the same
tools so the demo works with no key.

The agent lives in the **Engineer Chat** screen (the app's landing page): a **multi-turn
conversation** where a line engineer gets everything in one place — no page-hopping. Follow-ups
carry context (*"trigger a prediction for **it**"*), `run_rul_prediction` re-runs the Monte-Carlo
forecast on demand (with what-if utilization overrides like *"what if it flies 6 landings/day?"*),
and `get_damage_area` returns damage **locations** (type + tread region + pixel bbox) with the
**annotated scan image rendered inline** in the chat.

## The 5 pilot capabilities → 5 screens

| Pilot goal | Screen |
|---|---|
| Forecast tire RUL | **Per-Wheel Wear Curve** — measured tread, fitted line, MC fan chart to the 2.0 mm limit, RUL in landings & days |
| Predict wear-to-limit dates | Monte-Carlo first-passage → median + P10–P90 date band |
| Prioritize wheels needing attention | **Priority Worklist** — ranked by *P(cross before next check) × consequence*, not raw RUL |
| Support spares & maintenance planning | **Spares Planner** — weekly station demand vs on-hand stock, stock-out flags |
| Generate disruption-risk alerts | **Alerts Feed** — model (P10) alerts kept separate from deterministic pressure-ladder rules |
| (overview) | **Fleet Health** — KPIs + color-coded aircraft × wheel grid |
| Aircraft view + search by serial | **Aircraft** — search by tail/tire-serial, top-view schematic of the 6 wheels, per-tire status reports |
| Multi-modal condition (VLM + Depth + OCR) | **Tire Scan (CV)** — image → tread depth, damage (cut/bulge/FOD), serial → wear-vs-damage split |
| Manual grounding + dispatch + log mining | **Documents** — AMM-sourced thresholds, MEL/CDL dispatch decisions, free-text defect-log extraction |
| (honesty) | **Validation** — recovered vs true wear rate; only a synthetic POC can show this |

## Multi-modal: the CV layer (VLM + Depth + OCR)

Beyond the time-series RUL core, the **Tire Scan** screen runs three vision capabilities on a
tire image: a **Depth model** (recovers tread depth from groove geometry — ±0.23 mm on the
synthetic scans), a **VLM** (flags cut/bulge/FOD and writes an AMM-grounded condition report),
and **OCR** (reads the serial). The offline backend is deterministic so it runs with **no
external API** and validates against known ground truth. The production VLM is pluggable behind
`get_vlm(...)`:

- **OpenAI vision** — `get_vlm("openai")`; set `OPENAI_API_KEY` (model via `OPENAI_VLM_MODEL`,
  default `gpt-4o-mini`; honors `OPENAI_BASE_URL` for Azure/compatible endpoints). The Tire Scan
  screen has a **VLM backend** toggle to run it live.
- **Claude vision** — `get_vlm("claude")`; set `ANTHROPIC_API_KEY`.
- **Amazon Bedrock** — `get_vlm("bedrock")`; uses the standard AWS credential chain (env keys,
  `AWS_PROFILE`, `~/.aws`) via the Anthropic `AnthropicBedrockMantle` client
  (`pip install 'anthropic[bedrock]'`). Bedrock model IDs carry an `anthropic.` prefix — default
  `anthropic.claude-opus-4-8`, override via `BEDROCK_VLM_MODEL`; region via `AWS_REGION`
  (default `us-east-1`).
- **`get_vlm("auto")`** picks OpenAI → Claude → Bedrock → mock by whichever credentials are present.

The **agent** has the same backend set: `MaintenanceAgent(ctx, backend="bedrock")` runs the full
tool-calling loop on Claude via Bedrock (model via `BEDROCK_AGENT_MODEL`, default
`anthropic.claude-opus-4-8`); both Engineer Chat and Tire Scan expose Bedrock in their backend toggles.

The key output is the **wear-vs-acute-damage split** — a worn
tire is a *scheduled* swap (`SCHEDULE`), while VLM-detected acute damage forces `REPLACE NOW`
(immediate AOG logistics). See [DATA_SOURCES.md](docs/DATA_SOURCES.md) for how every real signal
(TPMS, FOQA, laser scan, AMM/MEL) maps into the system.

## Document grounding (AMM · MEL/CDL · defect logs)

The **Documents** screen grounds the tool in the reference manuals (`treadcast.grounding`):

- **AMM provenance** — every threshold (wear limit, pressure ladder, inspection interval, removal
  criteria) is traceable to an AMM reference, with a drift check against the manual value.
- **MEL/CDL dispatch** — a finding becomes a dispatch decision: a tire worn to limit or with acute
  damage has **no dispatch relief** (AOG until replaced) — forecasting it turns that AOG into a
  *scheduled* fix; wheel-system items (TPMS/wheel-speed inop) carry a Cat-C 10-day relief.
- **Defect-log extraction** — mines noisy **free-text** removal logs into structured records
  (tail · position · serial · reason · cycles), validated against ground truth (tail/position/
  serial/reason **100%**, cycles **98%** on synthetic logs generated from real removals). Rule-based
  here; a VLM/LLM plugs in behind the same `extract_defect_log` signature for messier logs.

## Quickstart

```bash
cd treadcast
make setup      # create .venv (Python 3.11) and install deps
make generate   # write synthetic Parquet tables to data/
make scans      # write the imaging/scanning layer (tire_scans) for the CV screen
make logs       # write synthetic free-text defect logs for the Documents screen
make train      # fit models, write artifacts/ + eval report
make run        # launch the Streamlit app
```

`make all` runs generate → train → test. On macOS the LightGBM baseline needs OpenMP
(`brew install libomp`); it degrades gracefully if missing (the headline MixedLM/Weibull models
do not depend on it).

## Results (whole-tire holdout, committed seed)

Trained on 770 tires, evaluated on 257 held-out tires (1,991 evaluation points):

| Metric | Value | Target |
|---|---|---|
| Wear-to-limit **date MAE** @30d horizon | **3.8 days** | ≤ 7 days |
| RUL MAE, second half of life | **8.0 landings** | — |
| α-λ accuracy (±20%, second half) | **71%** | ≥ 70% |
| Ground-truth wear-rate recovery (median abs error) | **2.1%** | ≤ 10% |
| Prognostic horizon | **43 landings** | — |
| LightGBM baseline RUL MAE | 16.5 landings | (≈ headline 17.6 — linear-wear assumption holds) |

Outcome mix of the synthetic fleet: 64% worn / 19% early-removal (FOD) / 17% in-service
(right-censored) — anchored to cited aviation ranges (main-gear median life ~280 landings,
nose ~155, new tread 11–14 mm, 2.0 mm wear limit).

## Safety positioning

TreadCast is **decision support** that prioritizes within existing AMM removal limits. It
augments — never replaces — mandated inspections and cold-pressure checks. **All data here is
synthetic**; the method and pipeline are what transfer to real inspection records.

## Out of scope (roadmap, not built)

- Computer-vision tread scoring from photos (core engine runs on tabular history alone)
- Real-data / TPMS / FDR-QAR sensor ingestion
- MRO-system integration (AMOS/TRAX/Ramco) — an architecture slide, not code
- Production concerns: auth, multi-tenancy, database, API layer (Streamlit + Parquet only)
- Deep sequence models (wrong tool for sparse, irregular inspection data)

The `scoring.py` module is a deliberate seam: the same pure functions lift behind a FastAPI
service + React front end and MRO integration without a rewrite. See
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and the 10-minute
[docs/demo_script.md](docs/demo_script.md).
