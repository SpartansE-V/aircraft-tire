# TreadCast — 10-minute demo script

Seeded, reproducible walkthrough on a 30-aircraft A320-family fleet, **as of 2025-01-01**.
Run `make all && make run`, then follow the beats. All numbers below come from the committed
seed; a second run reproduces them exactly. **All data is synthetic.**

Story tail: **VN-A300** — one of the busiest tails in the fleet (~3.8 landings/day), based at
**SGN**, which holds only 3 spares of this tire size.

---

## 0 · Framing (30s)

> "Aircraft tires are the highest-frequency consumable in the fleet. Today, tire condition is
> found by manual inspection at the gate — and an unexpected worn tire means a delay, an AOG, or
> an emergency spare flown in. A narrowbody AOG runs **$10–20K per hour**. TreadCast forecasts
> every wheel's remaining life from the inspection records you already collect."

## 0b · Engineer Chat — the agentic core (2 min)

Open the landing screen, **Engineer Chat**, and hold a conversation:

1. *"What's the situation of VN-A300 mlg_r_inbd?"* → status, pressure, spares, action — one turn.
2. *"Trigger a prediction for it"* → the agent resolves **"it"** from the conversation and re-runs
   the Monte-Carlo forecast live (`run_rul_prediction`, 2000 draws).
3. *"Where is the damage area?"* → `get_damage_area` returns the **CUT at the upper center tread**
   with its bounding box — and the **annotated scan image renders inline** in the chat.
4. *"What if it flies 6 landings per day?"* → a what-if forecast under the new utilization.
5. *"Plan tonight's tire maintenance for SGN"* → the ranked station plan.

- Expand the 🔍 **trace** under any reply: the agent chose and called the tools itself — this is an
  LLM **planning and using tools**, not a scripted report.

> "An engineer never leaves this chat — situation, fresh prediction, damage location with the
> image, dispatch, spares — everything else in the demo is a tool this agent calls." (Toggle
> **OpenAI agent** if a key is set; otherwise the offline agent runs the same tools.)

## 1 · Fleet Health Overview (90s)

- KPIs up top: **68 wheels** reach the wear limit within 30 days (expected), 130 within 60, 162
  within 90 — *that is your replacement pipeline, and today you'd discover most of it at the gate.*
- **88 AOG-risk wheels** — the conservative (earliest-credible P10) count that could strand an
  aircraft if you wait.
- The grid is 30 tails × 6 wheel positions, colored by expected days-to-limit. Point at the red
  cells: "these reach the limit soonest." Note **VN-A300** has red on the main gear.

> "This is the whole fleet at a glance. Now let's see why one wheel is urgent — and one isn't yet."

## 2 · Per-Wheel Wear Curve (2 min)

Select **VN-A300 · nlg_l**.

- The wear curve shows measured tread points, the fitted degradation line, and an 80% band
  fanning to the 2.0 mm limit. The recent points **steepen** — this tire's wear rate is running
  **~31% above its own baseline** (0.092 vs 0.070 mm/landing), the signature of a sustained
  under-inflation run.
- RUL **32 landings** (median), but the **earliest-credible date is 2025-01-07 — 6 days out**.
- Switch to **VN-A300 · mlg_l_outbd**: it's essentially **at the limit now** (RUL ~2) — the
  model flagged it well before the gate would.

> "The model doesn't just say 'worn' — it shows the wear line, the acceleration, and an
> earliest-credible date you can schedule against."

## 3 · Priority Worklist (2 min)

- Ranked by **P(cross before next check) × consequence** — *not* raw RUL. Consequence blends tail
  utilization (AOG exposure), wheel-position criticality, and station spare availability.
- VN-A300's wheels rank near the top: high utilization (3.8/day) **and** zero effective slack at
  SGN. Each row carries a plain-English *why* and a recommended action.
- Contrast: a wheel with similar RUL on a low-utilization, well-stocked tail ranks **lower** —
  because the *consequence* of missing it is smaller. That's the point: prioritize risk, not just
  the smallest number.

## 4 · Spares Planner (2 min)

- Per-station weekly removal demand — expected vs the conservative **P90** — against on-hand stock.
- **SGN** projects a spare **stock-out in the first planning week** (on-hand 3, demand higher);
  DAD the same week, HAN the week after.

> "Same per-wheel forecast, now in planner currency: reorder SGN **now**, two weeks before the
> stock-out — instead of chartering an emergency tire when a jet is already on the ground."

## 5 · Alerts Feed (90s)

Two columns, deliberately separate:

- **Model alerts (wear-out)** — fired on the earliest-credible **P10** date, never the median.
  You'll see VN-A300's *earliest-credible date inside the planning window* alert days ahead.
- **Deterministic rules (event-driven)** — the FAA/Goodyear cold-pressure ladder and hard-removal
  flags. Several wheels read 83–88% of service pressure → **remove** (e.g. VN-A325 · mlg_r_inbd at
  83%); one reads 106% → **remove tire and mate**.

> "The probabilistic model and the standards-grounded rules never get blended — so an auditor can
> trust each on its own terms."

## 5b · Tire Scan — the CV layer (90s)

Open **Tire Scan (CV)** (defaults to a damaged wheel, e.g. VN-A300 · mlg_r_inbd).

- One tire image, three models: **Depth** recovers tread depth (≈ 3.8 mm, Δ ~0.1 mm vs the laser
  reading), **OCR** reads the serial, and the **VLM** flags the **cut** and writes an AMM-grounded
  report: *"acute damage — requires immediate removal, not a scheduled wear replacement."*
- The punchline is the **combined status**: the time-series model alone says `SCHEDULE` (this
  tire still has tread life), but the CV damage flips it to **`REPLACE NOW`** — a different
  logistics path (immediate AOG response vs a planned overnight swap).

> "Wear and damage are different problems with different responses. The time-series model plans
> the wear; the VLM catches the FOD cut that would strand the aircraft tomorrow. The offline demo
> runs with no API; in production this VLM is Claude vision."

## 5c · Documents — grounding (90s)

Open **Documents** (three tabs).

- **AMM thresholds** — every safety number the tool uses (2.0 mm limit, the pressure ladder,
  inspection interval, removal criteria) is traceable to an AMM reference, with a drift check.
  *"Nothing here is a magic constant — it's sourced from your manual."*
- **MEL/CDL dispatch** — the worn/damaged wheels show **no dispatch relief → AOG until replaced**;
  a TPMS-inop example shows a **Cat-C, 10-day** relief. *"This is what turns a forecast into a
  dispatch decision with a deadline."*
- **Defect-log extraction** — raw **free-text** removal logs are mined into structured records
  (tail · position · serial · reason · cycles) at **100% / 98%** vs ground truth. *"Your underused
  historical logs become training data — linked to each tire by serial."*

## 6 · Validation (60s)

> "Because the data is synthetic, we can do something you can't with real data: check the model
> against ground truth."

- **Wear-rate recovery: 2.1%** median error vs the true per-tire wear rate (held-out tires).
- **α-λ accuracy 71%**, **wear-to-limit date MAE 3.8 days** at a 30-day horizon.
- The scatter shows recovered vs true wear rate hugging the diagonal.

## 7 · Close (30s)

> "Reactive today: worn tires found at the gate, emergency logistics, AOG at $10–20K/hr.
> Proactive with TreadCast: every wheel forecast, the urgent ones prioritized by real consequence,
> spares pre-positioned, and alerts that turn an AOG into a scheduled overnight swap.
> This runs on synthetic data — the method and the pipeline are what transfer to your real
> inspection records. And it augments your mandated inspections; it never replaces them."

---

### Reproducing the story

The scenario is deterministic at the committed seed (`app/tire_rul/config/generator.yaml` → `seed`). If you
change the seed, the specific tails and numbers change but every screen and behavior holds.
Exact tails/wheels referenced above (VN-A300, VN-A325, …) are valid for the committed seed.
