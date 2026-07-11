"""TreadCast — 5-screen Streamlit demo.

The UI delegates ALL computation to features.py + scoring.py (it fits nothing and reimplements
no model math). The data-assembly helpers below are plain functions so they can be unit-tested
without a Streamlit runtime; only `main()` and the cached loaders touch `st`.

Screens: Fleet Health · Per-Wheel Wear Curve · Priority Worklist · Spares Planner · Alerts Feed,
plus a synthetic-data Ground-Truth Validation panel.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import date

import numpy as np
import pandas as pd

# Absolute imports: app.py is the only module run directly via `streamlit run` (from the repo
# root, e.g. `make ui`), where relative imports have no package context.
from app.rul import paths, scoring
from app.rul.config import (
    GeneratorConfig,
    ThresholdConfig,
    get_generator_config,
    get_threshold_config,
)
from app.rul.constants import ALL_POSITIONS, PressureLadderAction
from app.rul.features import build_features
from app.rul.scoring import WheelRisk

SAFETY_FOOTER = (
    "TreadCast is **decision support** that prioritizes within existing AMM removal limits — "
    "it augments, never replaces, mandated inspections and cold-pressure checks. "
    "**All data shown is synthetic**; the method and pipeline are what transfer to real records."
)
POSITION_ORDER = [p.value for p in ALL_POSITIONS]

# Top-view schematic coordinates for each wheel (nose at top, main gear behind the wings).
POSITION_XY = {
    "nlg_l": (-0.13, 0.72),
    "nlg_r": (0.13, 0.72),
    "mlg_l_outbd": (-0.52, -0.12),
    "mlg_l_inbd": (-0.32, -0.12),
    "mlg_r_inbd": (0.32, -0.12),
    "mlg_r_outbd": (0.52, -0.12),
}


# ---------------------------------------------------------------------------
# Data-assembly layer (no Streamlit — unit-testable)
# ---------------------------------------------------------------------------
def _per_aircraft_dates(ops: pd.DataFrame) -> dict[str, np.ndarray]:
    out: dict[str, np.ndarray] = {}
    o = ops.copy()
    o["cycle_date"] = o["cycle_date"].dt.tz_convert("UTC").dt.tz_localize(None)
    for ac_id, grp in o.sort_values("cycle_date").groupby("aircraft_id"):
        out[ac_id] = grp["cycle_date"].to_numpy(dtype="datetime64[ns]")
    return out


def current_cycles_map(tables: dict[str, pd.DataFrame], as_of: date) -> dict[str, int]:
    """Landings flown by each currently-mounted tire's aircraft between install and as-of."""
    dates_by_ac = _per_aircraft_dates(tables["operational_cycles"])
    as_of_np = np.datetime64(as_of)
    out: dict[str, int] = {}
    cur = tables["tires"][tables["tires"]["is_current"]]
    for _, t in cur.iterrows():
        arr = dates_by_ac.get(t["aircraft_id"])
        if arr is None:
            out[t["tire_id"]] = int(t["time_to_event_cycles"])
            continue
        inst = np.datetime64(pd.Timestamp(t["install_date"]).tz_convert("UTC").tz_localize(None))
        lo = int(np.searchsorted(arr, inst, side="left"))
        hi = int(np.searchsorted(arr, as_of_np, side="right"))
        out[t["tire_id"]] = max(hi - lo, int(t["time_to_event_cycles"]))
    return out


def recent_hard_landings(tables: dict[str, pd.DataFrame], as_of: date, days: int = 14) -> dict[str, int]:
    ops = tables["operational_cycles"].copy()
    ops["cycle_date"] = ops["cycle_date"].dt.tz_convert("UTC").dt.tz_localize(None)
    lo = pd.Timestamp(as_of) - pd.Timedelta(days=days)
    recent = ops[(ops["cycle_date"] >= lo) & (ops["hard_landing"])]
    return recent.groupby("aircraft_id").size().to_dict()


def assemble_wheels(
    tables: dict[str, pd.DataFrame],
    feats: pd.DataFrame,
    prior: dict,
    tc: ThresholdConfig,
    as_of: date,
    util_override: float = 0.0,
) -> list[WheelRisk]:
    """Build a WheelRisk for every currently-mounted tire (all math via scoring.estimate_wheel)."""
    tires = tables["tires"]
    ac = tables["aircraft"].set_index("aircraft_id")
    stock = dict(zip(tables["station_stock"]["station_code"], tables["station_stock"]["on_hand"], strict=False))
    cur = tires[tires["is_current"]]
    cyc_map = current_cycles_map(tables, as_of)
    hard_recent = recent_hard_landings(tables, as_of, days=14)
    feats_by_tire = {tid: g for tid, g in feats.groupby("tire_id")}

    risks: list[WheelRisk] = []
    for _, t in cur.iterrows():
        tid, pos, ac_id = t["tire_id"], t["position_code"], t["aircraft_id"]
        g = feats_by_tire.get(tid)
        if g is not None:
            g = g.sort_values("cycles_since_install")
            rc = g["cycles_since_install"].to_numpy(dtype=float)
            rg = g["measured_groove_mm"].to_numpy(dtype=float)
            n = len(g)
        else:
            rc, rg, n = np.array([]), np.array([]), 0
        cur_cyc = float(cyc_map.get(tid, rc[-1] if n else 0.0))
        cpd = float(ac.loc[ac_id, "cycles_per_day"]) if util_override <= 0 else float(util_override)
        pmean, pcov, scale = scoring.prior_arrays(prior, pos)
        est = scoring.estimate_wheel(
            rc, rg, pmean, pcov, scale,
            current_cycles=cur_cyc, landings_per_day=cpd, as_of_date=as_of,
            limit_mm=tc.wear_limit_mm, mc_draws=tc.mc_draws, mc_seed=tc.mc_seed,
            next_check_cycles=tc.next_check_interval_cycles, n_readings=n,
            low_confidence_min_readings=tc.low_confidence_min_readings,
        )
        latest_press = float(g["latest_pressure_pct"].iloc[-1]) if n else None
        press_action = (
            scoring.pressure_ladder_action(latest_press, tc.pressure_bands)
            if latest_press is not None
            else PressureLadderAction.OK.value
        )
        recent_rate = float(g["recent_wear_rate"].iloc[-1]) if n and pd.notna(g["recent_wear_rate"].iloc[-1]) else abs(est.slope)
        risks.append(
            WheelRisk(
                aircraft_id=ac_id,
                tail_number=str(ac.loc[ac_id, "tail_number"]),
                position_code=pos,
                station=str(ac.loc[ac_id, "home_station"]),
                on_hand=int(stock.get(ac.loc[ac_id, "home_station"], 0)),
                cycles_per_day=cpd,
                estimate=est,
                hard_landings_recent=int(hard_recent.get(ac_id, 0)),
                pressure_pct=latest_press,
                pressure_action=press_action,
                recent_wear_rate=recent_rate,
                baseline_wear_rate=abs(pmean[1]),
            )
        )
    return risks


def wheels_dataframe(risks: list[WheelRisk], as_of: date) -> pd.DataFrame:
    rows = []
    for r in risks:
        e = r.estimate
        rows.append(
            {
                "tail_number": r.tail_number,
                "position_code": r.position_code,
                "station": r.station,
                "on_hand": r.on_hand,
                "cycles_per_day": round(r.cycles_per_day, 1),
                "rul_p10": round(e.rul_p10, 0),
                "rul_median": round(e.rul_median, 0),
                "days_to_p10": (e.date_p10 - as_of).days,
                "days_to_median": (e.date_median - as_of).days,
                "date_p10": e.date_p10,
                "date_median": e.date_median,
                "p_cross_next_check": round(e.p_cross_next_check, 3),
                "pressure_pct": None if r.pressure_pct is None else round(r.pressure_pct, 0),
                "pressure_action": r.pressure_action,
                "low_confidence": e.low_confidence,
            }
        )
    return pd.DataFrame(rows)


def wheel_detail(feats: pd.DataFrame, prior: dict, tc: ThresholdConfig, tire_id: str, current_cycles: float):
    """Posterior mean line + 80% predictive band + crossing for one wheel's wear curve."""
    g = feats[feats["tire_id"] == tire_id].sort_values("cycles_since_install")
    pos = g["position_code"].iloc[0]
    rc = g["cycles_since_install"].to_numpy(dtype=float)
    rg = g["measured_groove_mm"].to_numpy(dtype=float)
    pmean, pcov, scale = scoring.prior_arrays(prior, pos)
    mean, cov = scoring.eb_posterior(rc, rg, pmean, pcov, scale)
    xs = np.linspace(0, max(current_cycles * 1.6, rc.max() * 1.3 if len(rc) else 100), 120)
    line = mean[0] + mean[1] * xs
    var = cov[0, 0] + 2 * xs * cov[0, 1] + (xs**2) * cov[1, 1] + scale
    sd = np.sqrt(np.clip(var, 0, None))
    return {
        "readings_cycles": rc,
        "readings_groove": rg,
        "xs": xs,
        "line": line,
        "upper": line + 1.28 * sd,
        "lower": line - 1.28 * sd,
        "position": pos,
    }


# ---------------------------------------------------------------------------
# Streamlit app
# ---------------------------------------------------------------------------
def _load():
    import streamlit as st

    @st.cache_resource
    def _tables():
        t = {
            "aircraft": pd.read_parquet(paths.AIRCRAFT),
            "tires": pd.read_parquet(paths.TIRES),
            "inspection_records": pd.read_parquet(paths.INSPECTION_RECORDS),
            "operational_cycles": pd.read_parquet(paths.OPERATIONAL_CYCLES),
            "station_stock": pd.read_parquet(paths.STATION_STOCK),
            "_ground_truth": pd.read_parquet(paths.GROUND_TRUTH),
        }
        t["tire_scans"] = pd.read_parquet(paths.TIRE_SCANS) if paths.TIRE_SCANS.exists() else None
        t["defect_logs"] = pd.read_parquet(paths.DEFECT_LOGS) if paths.DEFECT_LOGS.exists() else None
        return t

    @st.cache_resource
    def _prior():
        import pickle

        with open(paths.MIXEDLM_COV, "rb") as f:
            return pickle.load(f)

    @st.cache_resource
    def _feats(_tbls_id: int):
        return build_features(_tables())

    @st.cache_data
    def _eval_report():
        if paths.EVAL_REPORT.exists():
            return json.loads(paths.EVAL_REPORT.read_text())
        return {}

    return _tables(), _prior(), _feats(1), _eval_report()


def _colour_for_days(days: int) -> str:
    if days <= 30:
        return "#d64545"
    if days <= 60:
        return "#e08a1e"
    if days <= 90:
        return "#e8c33c"
    return "#3f9d55"


def main() -> None:  # pragma: no cover - Streamlit entry point
    import plotly.graph_objects as go
    import streamlit as st

    st.set_page_config(page_title="TreadCast — Tire RUL", layout="wide", page_icon="🛬")
    cfg: GeneratorConfig = get_generator_config()
    base_tc: ThresholdConfig = get_threshold_config()
    as_of = cfg.as_of_date
    tables, prior, feats, report = _load()

    st.sidebar.title("🛬 TreadCast")
    st.sidebar.caption(f"Fleet as of **{as_of.isoformat()}** · {tables['aircraft'].shape[0]} aircraft (synthetic)")
    screen = st.sidebar.radio(
        "Screen",
        ["Engineer Chat", "Fleet Health", "Aircraft", "Per-Wheel Wear Curve", "Tire Scan (CV)", "Priority Worklist", "Spares Planner", "Alerts Feed", "Documents", "Validation"],
    )

    st.sidebar.subheader("Assumptions (live)")
    planning_window = st.sidebar.slider("Planning window (days)", 7, 90, base_tc.planning_window_days, 1)
    p_cross_thr = st.sidebar.slider("P(cross before next check) alert", 0.05, 0.5, base_tc.p_cross_threshold, 0.05)
    accel_thr = st.sidebar.slider("Wear-acceleration alert", 0.1, 1.0, base_tc.wear_accel_threshold, 0.05)
    wear_limit = st.sidebar.slider("Wear limit (mm)", 1.0, 3.0, base_tc.wear_limit_mm, 0.1)
    util_override = st.sidebar.slider("Utilization override (landings/day, 0=actual)", 0.0, 8.0, 0.0, 0.5)

    tc = replace(
        base_tc,
        planning_window_days=planning_window,
        p_cross_threshold=p_cross_thr,
        wear_accel_threshold=accel_thr,
        wear_limit_mm=wear_limit,
    )

    risks = assemble_wheels(tables, feats, prior, tc, as_of, util_override=util_override)
    wdf = wheels_dataframe(risks, as_of)
    worklist = scoring.build_worklist(risks, tc)
    stock = dict(zip(tables["station_stock"]["station_code"], tables["station_stock"]["on_hand"], strict=False))
    demand = scoring.spares_demand(risks, stock, as_of, weeks=12)
    alerts = scoring.evaluate_alerts(risks, demand, tc, as_of)

    if screen == "Engineer Chat":
        _screen_agent(st, tables, risks, tc, as_of, prior=prior, feats=feats)
    elif screen == "Fleet Health":
        _screen_fleet(st, go, wdf, as_of, tc)
    elif screen == "Aircraft":
        _screen_aircraft(st, go, tables, risks, tc, as_of)
    elif screen == "Per-Wheel Wear Curve":
        _screen_wheel(st, go, tables, feats, prior, tc, risks, as_of)
    elif screen == "Tire Scan (CV)":
        _screen_scan(st, tables, risks, tc, as_of)
    elif screen == "Priority Worklist":
        _screen_worklist(st, worklist)
    elif screen == "Spares Planner":
        _screen_spares(st, go, demand)
    elif screen == "Alerts Feed":
        _screen_alerts(st, alerts)
    elif screen == "Documents":
        _screen_documents(st, tables, risks, tc, as_of)
    else:
        _screen_validation(st, go, report, tables, feats, prior, tc)

    st.divider()
    st.caption(SAFETY_FOOTER)


_DAMAGE_BOX_COLORS = {"cut": "#d64545", "bulge": "#e08a1e", "fod": "#2b6cb0"}


def _annotated_scan(ctx, tail: str, position: str):
    """Re-render a wheel's scan with damage bounding boxes drawn on it (for inline chat display)."""
    from PIL import ImageDraw

    from app.rul.agent.tools import render_scan_image
    from app.rul.cv import locate_damage

    img, meta = render_scan_image(ctx, tail, position)
    if img is None:
        return None, meta
    regions = locate_damage(img)
    draw = ImageDraw.Draw(img)
    for r in regions:
        x0, y0, x1, y1 = r["bbox"]
        color = _DAMAGE_BOX_COLORS.get(r["type"], "#ffffff")
        draw.rectangle([x0 - 4, y0 - 4, x1 + 4, y1 + 4], outline=color, width=3)
        draw.text((x0, max(y0 - 16, 2)), r["type"].upper(), fill=color)
    return img, meta


def _screen_agent(st, tables, risks, tc, as_of, prior=None, feats=None):
    from app.rul.agent import MaintenanceAgent, ToolContext, agent_backend_available

    st.title("Engineer Chat — one place for everything")
    st.caption(
        "Chat with the maintenance agent: get a tire's **situation**, **trigger a fresh prediction**, "
        "and see **where the damage is** — no page-hopping. The agent investigates via tools "
        "(RUL · CV scan · MEL dispatch · spares · history) and shows its trace."
    )
    backend_label = st.radio(
        "Agent backend",
        ["Offline agent", "OpenAI agent", "Bedrock agent"],
        horizontal=True,
        help=(
            "OpenAI agent needs OPENAI_API_KEY (model via OPENAI_AGENT_MODEL, default gpt-4o-mini). "
            "Bedrock agent needs AWS credentials (model via BEDROCK_AGENT_MODEL, default "
            "anthropic.claude-opus-4-8; region via AWS_REGION)."
        ),
    )
    backend = "mock"
    if backend_label == "OpenAI agent":
        if agent_backend_available("openai"):
            backend = "openai"
        else:
            st.info("Set `OPENAI_API_KEY` to run the OpenAI agent — using the offline agent for now.")
    elif backend_label == "Bedrock agent":
        if agent_backend_available("bedrock"):
            backend = "bedrock"
        else:
            st.info("Configure AWS credentials (and `pip install 'anthropic[bedrock]'`) to run the Bedrock agent — using the offline agent for now.")

    ctx = ToolContext(tables=tables, risks=risks, tc=tc, as_of=as_of, prior=prior, feats=feats)

    if "agent_chat" not in st.session_state:
        st.session_state.agent_chat = []
    history = st.session_state.agent_chat

    with st.expander("💡 Example conversation", expanded=not history):
        st.markdown(
            "1. `What's the situation of VN-A300 mlg_r_inbd?`\n"
            "2. `Trigger a prediction for it`\n"
            "3. `Where is the damage area?`  *(inline annotated scan)*\n"
            "4. `What if it flies 6 landings per day?`\n"
            "5. `Plan tonight's tire maintenance for SGN`"
        )
        if st.button("Reset conversation"):
            st.session_state.agent_chat = []
            st.rerun()

    # replay the conversation
    for entry in history:
        with st.chat_message(entry["role"]):
            st.markdown(entry["content"])
            if entry["role"] == "assistant":
                for tail_pos in entry.get("damage_wheels", []):
                    img, _meta = _annotated_scan(ctx, *tail_pos)
                    if img is not None:
                        st.image(img, caption=f"Damage areas · {tail_pos[0]} {tail_pos[1]}", width=380)
                if entry.get("trace"):
                    with st.expander(f"🔍 trace — {len(entry['trace'])} tool call(s)"):
                        for i, step in enumerate(entry["trace"], 1):
                            st.markdown(f"**{i}. `{step['tool']}`** · args: `{step['args']}`")
                            st.json(step["result"], expanded=False)

    question = st.chat_input("Ask about any tire — situation, prediction, damage area, dispatch, spares…")
    if question and question.strip():
        history.append({"role": "user", "content": question})
        agent = MaintenanceAgent(ctx, backend=backend)
        msgs = [{"role": m["role"], "content": m["content"]} for m in history]
        try:
            out = agent.chat(msgs)
        except Exception as exc:
            history.append({"role": "assistant", "content": f"Agent failed: {exc}", "trace": []})
            st.rerun()
            return
        # wheels whose damage areas were fetched -> render annotated scans inline
        damage_wheels = [
            (s["result"].get("tail"), s["result"].get("position"))
            for s in out["trace"]
            if s["tool"] == "get_damage_area" and s["result"].get("regions")
        ]
        history.append(
            {
                "role": "assistant",
                "content": out["answer"] + f"\n\n*backend: {out['backend']} · {len(out['trace'])} tool call(s)*",
                "trace": out["trace"],
                "damage_wheels": [dw for dw in damage_wheels if dw[0] and dw[1]],
            }
        )
        st.rerun()


def _screen_fleet(st, go, wdf, as_of, tc):
    st.title("Fleet Health Overview")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Reaching limit ≤30d", int((wdf["days_to_median"] <= 30).sum()), help="Expected (median) wear-to-limit date within 30 days — the near-term replacement pipeline.")
    c2.metric("≤60d", int((wdf["days_to_median"] <= 60).sum()))
    c3.metric("≤90d", int((wdf["days_to_median"] <= 90).sum()))
    aog = int(((wdf["days_to_p10"] <= tc.planning_window_days) | (wdf["pressure_action"].isin(["remove", "remove_tire_and_mate"]))).sum())
    c4.metric("AOG-risk wheels", aog, help="Earliest-credible (P10) date inside the planning window, or a pressure-ladder removal flag. This is the conservative safety count.")

    pivot = wdf.pivot_table(index="tail_number", columns="position_code", values="days_to_median", aggfunc="min")
    pivot = pivot.reindex(columns=[p for p in POSITION_ORDER if p in pivot.columns])
    z = pivot.to_numpy()
    fig = go.Figure(
        data=go.Heatmap(
            z=z,
            x=list(pivot.columns),
            y=list(pivot.index),
            colorscale=[[0, "#7a1f1f"], [0.12, "#d64545"], [0.25, "#e08a1e"], [0.5, "#e8c33c"], [1, "#3f9d55"]],
            zmin=0,
            zmax=120,
            colorbar=dict(title="Days to<br>limit (median)"),
            hovertemplate="%{y} · %{x}<br>%{z} days to limit (expected)<extra></extra>",
        )
    )
    fig.update_layout(height=760, margin=dict(l=10, r=10, t=30, b=10), xaxis_title="Wheel position", yaxis_title="Tail")
    st.plotly_chart(fig, width="stretch")
    st.caption("Colour = expected (median) days to the wear limit. Red wheels reach the limit soonest; the AOG-risk count above uses the conservative earliest-credible (P10) date.")


def _aircraft_schematic(go, wheels: list[dict]):
    """Top-view aircraft diagram with the 6 wheels colored by status."""
    fig = go.Figure()
    # fuselage + nose
    fig.add_shape(type="line", x0=0, y0=1.05, x1=0, y1=-0.95, line=dict(color="#9aa5b1", width=10))
    fig.add_shape(type="line", x0=0, y0=1.08, x1=-0.08, y1=0.85, line=dict(color="#9aa5b1", width=5))
    fig.add_shape(type="line", x0=0, y0=1.08, x1=0.08, y1=0.85, line=dict(color="#9aa5b1", width=5))
    # wings + tailplane
    fig.add_shape(type="line", x0=-1.15, y0=0.03, x1=1.15, y1=0.03, line=dict(color="#c3cad3", width=7))
    fig.add_shape(type="line", x0=-0.45, y0=-0.82, x1=0.45, y1=-0.82, line=dict(color="#c3cad3", width=6))
    xs, ys, colors, texts, hovers = [], [], [], [], []
    for w in wheels:
        x, y = POSITION_XY[w["position"]]
        xs.append(x)
        ys.append(y)
        colors.append(_colour_for_days(w["days"]))
        texts.append(w["position"].replace("mlg_", "M·").replace("nlg_", "N·").upper())
        hovers.append(w["hover"])
    fig.add_trace(
        go.Scatter(
            x=xs, y=ys, mode="markers+text", text=texts, textposition="middle center",
            textfont=dict(size=8, color="#111"),
            marker=dict(size=46, color=colors, line=dict(color="#333", width=2)),
            hovertext=hovers, hoverinfo="text",
        )
    )
    fig.update_xaxes(visible=False, range=[-1.35, 1.35])
    fig.update_yaxes(visible=False, range=[-1.15, 1.3])
    fig.update_layout(height=470, margin=dict(l=10, r=10, t=20, b=10), showlegend=False, plot_bgcolor="white")
    return fig


def _screen_aircraft(st, go, tables, risks, tc, as_of):
    st.title("Aircraft — Tires & Status")
    ac = tables["aircraft"]
    cur = tables["tires"][tables["tires"]["is_current"]][["aircraft_id", "position_code", "serial"]]
    serial_to_ac = dict(zip(cur["serial"], cur["aircraft_id"], strict=False))
    tail_of = dict(zip(ac["aircraft_id"], ac["tail_number"], strict=False))
    tails = sorted(ac["tail_number"].unique())

    query = st.text_input("🔎 Search by aircraft tail (e.g. VN-A300) or tire serial", "")
    selected_ac_id = None
    if query.strip():
        q = query.strip()
        m = ac[ac["tail_number"].str.upper() == q.upper()]
        if not m.empty:
            selected_ac_id = m["aircraft_id"].iloc[0]
        elif q in serial_to_ac:
            selected_ac_id = serial_to_ac[q]
        else:
            hit = cur[cur["serial"].str.contains(q, case=False, na=False)]
            if not hit.empty:
                selected_ac_id = hit["aircraft_id"].iloc[0]
                st.info(f"Matched tire serial **{hit['serial'].iloc[0]}** → {tail_of[selected_ac_id]}")
            else:
                st.warning("No aircraft tail or tire serial matched — choose one below.")

    default_tail = tail_of.get(selected_ac_id, tails[0])
    tail = st.selectbox("Aircraft (tail)", tails, index=tails.index(default_tail))
    selected_ac_id = ac[ac["tail_number"] == tail]["aircraft_id"].iloc[0]
    row = ac[ac["aircraft_id"] == selected_ac_id].iloc[0]

    ac_risks = [r for r in risks if r.aircraft_id == selected_ac_id]
    by_pos = {r.position_code: r for r in ac_risks}
    sub = cur[cur["aircraft_id"] == selected_ac_id]
    serial_by_pos = dict(zip(sub["position_code"], sub["serial"], strict=False))
    reports = {p: scoring.tire_status_report(r, tc, as_of) for p, r in by_pos.items()}

    st.subheader(f"{tail} · {row['aircraft_type']} · home {row['home_station']} · {row['cycles_per_day']:.1f} landings/day")

    left, right = st.columns([3, 2])
    with left:
        wheels = []
        for pos in POSITION_ORDER:
            r = by_pos.get(pos)
            if r is None:
                continue
            rep = reports[pos]
            days = (r.estimate.date_median - as_of).days
            wheels.append(
                {
                    "position": pos,
                    "days": days,
                    "hover": (
                        f"{pos}<br>{rep.status.replace('_', ' ').upper()}<br>"
                        f"RUL {r.estimate.rul_median:.0f} ldg (~{rep.rul_days:.0f}d)<br>"
                        f"serial {serial_by_pos.get(pos, '?')}"
                    ),
                }
            )
        st.plotly_chart(_aircraft_schematic(go, wheels), width="stretch")
        st.caption("Top-view schematic — each wheel colored by expected days to the wear limit. Hover for detail.")
    with right:
        need = sum(1 for rep in reports.values() if rep.status in ("replace_now", "schedule"))
        st.metric("Wheels needing action", need, help="status = replace-now or schedule")
        if ac_risks:
            soonest = min(ac_risks, key=lambda r: r.estimate.date_p10)
            st.metric(
                "Soonest wheel", soonest.position_code,
                help=f"earliest-credible limit {soonest.estimate.date_p10.isoformat()}",
            )
            st.metric("Home-station spares", int(ac_risks[0].on_hand), help=f"of this tire size at {row['home_station']}")

    st.markdown("#### Tire status reports")
    for pos in POSITION_ORDER:
        r = by_pos.get(pos)
        if r is None:
            continue
        rep = reports[pos]
        icon = {"critical": "🔴", "warning": "🟠", "info": "🟢"}.get(rep.severity, "⚪")
        with st.container(border=True):
            st.markdown(
                f"{icon} **{pos}** · serial `{serial_by_pos.get(pos, '?')}` — "
                f"**{rep.status.replace('_', ' ').upper()}**"
            )
            st.markdown(f"*{rep.headline}*")
            st.caption(rep.explanation)
            st.markdown(f"**Action:** {rep.recommended_action}")


def _screen_wheel(st, go, tables, feats, prior, tc, risks, as_of):
    st.title("Per-Wheel Wear Curve")
    risk_by_key = {f"{r.tail_number} · {r.position_code}": r for r in risks}
    # default to the most urgent wheel
    default_key = min(risk_by_key, key=lambda k: risk_by_key[k].estimate.date_p10)
    key = st.selectbox("Wheel", sorted(risk_by_key), index=sorted(risk_by_key).index(default_key))
    r = risk_by_key[key]
    e = r.estimate

    cur = tables["tires"]
    match = cur[(cur["is_current"]) & (cur["aircraft_id"] == r.aircraft_id) & (cur["position_code"] == r.position_code)]
    tid = match["tire_id"].iloc[0]
    tid_feats = feats[feats["tire_id"] == tid]

    m1, m2, m3, m4 = st.columns(4)
    conf = "⚠️ fleet prior — low confidence" if e.low_confidence else "model-tracked"
    m1.metric("RUL (landings)", f"{e.rul_median:.0f}", help=f"P10 {e.rul_p10:.0f} · P90 {e.rul_p90:.0f} · {conf}")
    m2.metric("Earliest-credible date", e.date_p10.isoformat())
    m3.metric("Median date", e.date_median.isoformat())
    m4.metric("P(cross before next check)", f"{e.p_cross_next_check:.0%}")

    if tid_feats.empty:
        st.info("This wheel has no inspection readings yet — RUL shown is the fleet prior only.")
        st.caption(
            f"Utilization {r.cycles_per_day:.1f} landings/day · station {r.station} ({r.on_hand} spares)."
        )
        return
    current_cycles = float(tid_feats["cycles_since_install"].max())
    detail = wheel_detail(feats, prior, tc, tid, current_cycles)

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=detail["xs"], y=detail["upper"], line=dict(width=0), showlegend=False, hoverinfo="skip"))
    fig.add_trace(
        go.Scatter(
            x=detail["xs"], y=detail["lower"], fill="tonexty", fillcolor="rgba(63,157,85,0.18)",
            line=dict(width=0), name="80% band", hoverinfo="skip",
        )
    )
    fig.add_trace(go.Scatter(x=detail["xs"], y=detail["line"], line=dict(color="#2b6cb0", width=2), name="Fitted wear line"))
    fig.add_trace(
        go.Scatter(
            x=detail["readings_cycles"], y=detail["readings_groove"], mode="markers",
            marker=dict(color="#1a202c", size=7), name="Measured tread",
        )
    )
    fig.add_hline(y=tc.wear_limit_mm, line=dict(color="#d64545", dash="dash"), annotation_text=f"limit {tc.wear_limit_mm:.1f} mm")
    fig.update_layout(
        height=460, margin=dict(l=10, r=10, t=30, b=10),
        xaxis_title="Cumulative landings since install", yaxis_title="Groove depth (mm)",
    )
    st.plotly_chart(fig, width="stretch")
    if e.low_confidence:
        st.warning("This wheel has too few readings — showing the fleet prior with a wide band, not a tight number.")
    st.caption(
        f"Utilization {r.cycles_per_day:.1f} landings/day · station {r.station} "
        f"({r.on_hand} spares) · latest cold pressure {r.pressure_pct}% → {r.pressure_action.replace('_',' ')}."
    )


def _screen_scan(st, tables, risks, tc, as_of):
    import zlib

    from app.rul.cv import assess_tire, get_vlm, render_tire_image, vlm_available

    st.title("Tire Scan — automated CV diagnostics")
    st.caption(
        "Depth model (tread) · VLM (damage) · OCR (serial) on a synthetic scan. On real hardware "
        "these run on laser/camera images; here the encoded ground truth lets us validate recovery."
    )
    scans = tables.get("tire_scans")
    if scans is None:
        st.warning("No scan data — run `make scans` (python -m app.rul.generate_scans) first.")
        return

    scan_by_tire = {row.tire_id: row for row in scans.itertuples()}
    cur = tables["tires"][tables["tires"]["is_current"]]
    tid_by_ac_pos = {(t.aircraft_id, t.position_code): t.tire_id for t in cur.itertuples()}
    risk_by_key = {f"{r.tail_number} · {r.position_code}": r for r in risks}

    # default to a damaged wheel so the wear-vs-damage contrast is visible on open
    default_key = next(
        (
            k
            for k, r in sorted(risk_by_key.items())
            if (tid := tid_by_ac_pos.get((r.aircraft_id, r.position_code)))
            and scan_by_tire.get(tid) is not None
            and len(scan_by_tire[tid].damage_findings) > 0
        ),
        sorted(risk_by_key)[0],
    )
    key = st.selectbox("Wheel", sorted(risk_by_key), index=sorted(risk_by_key).index(default_key))
    r = risk_by_key[key]
    tid = tid_by_ac_pos.get((r.aircraft_id, r.position_code))
    trow = cur[cur["tire_id"] == tid].iloc[0]
    scan = scan_by_tire.get(tid)
    laser = float(scan.laser_groove_mm) if scan is not None else float(trow["new_tread_mm"])
    damage = list(scan.damage_findings) if scan is not None else []
    serial = str(trow["serial"])
    new_tread = float(trow["new_tread_mm"])

    # VLM backend: offline mock by default; OpenAI / Bedrock vision when credentials are set.
    backend_label = st.radio(
        "VLM backend",
        ["Offline mock", "OpenAI vision", "Bedrock vision"],
        horizontal=True,
        help=(
            "OpenAI vision needs OPENAI_API_KEY (model via OPENAI_VLM_MODEL, default gpt-4o-mini). "
            "Bedrock vision needs AWS credentials (model via BEDROCK_VLM_MODEL, default "
            "anthropic.claude-opus-4-8; region via AWS_REGION)."
        ),
    )
    vlm = None
    backend_note = "offline deterministic mock"
    if backend_label == "OpenAI vision":
        if vlm_available("openai"):
            vlm = get_vlm("openai")
            backend_note = f"OpenAI vision · {vlm.model}"
        else:
            st.info("Set `OPENAI_API_KEY` (optionally `OPENAI_VLM_MODEL`) to enable OpenAI vision — showing the offline mock.")
    elif backend_label == "Bedrock vision":
        if vlm_available("bedrock"):
            vlm = get_vlm("bedrock")
            backend_note = f"Bedrock vision · {vlm.model} ({vlm.region})"
        else:
            st.info("Configure AWS credentials (and `pip install 'anthropic[bedrock]'`) to enable Bedrock vision — showing the offline mock.")

    seed = int(zlib.crc32(str(tid).encode()) % (2**31))
    img = render_tire_image(laser, new_tread_mm=new_tread, damage=damage, serial=serial, seed=seed)

    # Memoize per (tire, backend) so a live API call runs at most once per selection.
    cache_key = f"scan::{tid}::{backend_label}:{getattr(vlm, 'model', 'mock')}"
    if cache_key not in st.session_state:
        try:
            with st.spinner("Analyzing tire image..."):
                st.session_state[cache_key] = assess_tire(
                    img, vlm=vlm, new_tread_mm=new_tread, wear_limit_mm=tc.wear_limit_mm
                )
        except Exception as exc:  # network / API failure -> graceful fallback to mock
            st.warning(f"{backend_label} call failed ({exc}) — showing the offline mock.")
            backend_note = f"offline deterministic mock ({backend_label} failed)"
            st.session_state[cache_key] = assess_tire(
                img, vlm=None, new_tread_mm=new_tread, wear_limit_mm=tc.wear_limit_mm
            )
    result = st.session_state[cache_key]

    c1, c2 = st.columns([3, 4])
    with c1:
        st.image(img, caption=f"Synthetic scan · {serial}", width=340)
    with c2:
        m1, m2, m3 = st.columns(3)
        m1.metric("Serial (OCR)", result.serial or "—", help=f"confidence {result.serial_confidence}")
        m2.metric(
            "Tread depth (Depth model)",
            f"{result.tread_depth_mm:.1f} mm",
            help=f"encoded {laser:.1f} mm · conf {result.depth_confidence}",
        )
        m3.metric("Damage (VLM)", ", ".join(result.damage_findings) or "none", help=f"backend: {backend_note}")
        st.markdown(f"**VLM condition report:** {result.condition_report}")
        st.caption(f"VLM backend: **{backend_note}**")
        st.caption(
            f"Depth model recovered {result.tread_depth_mm:.1f} mm vs encoded {laser:.1f} mm "
            f"(Δ {abs(result.tread_depth_mm - laser):.2f} mm) — validation only."
        )

    st.markdown("#### Combined status — CV + time-series RUL")
    rep_wear = scoring.tire_status_report(r, tc, as_of)
    rep_full = scoring.tire_status_report(r, tc, as_of, damage_findings=result.damage_findings)
    cc1, cc2 = st.columns(2)
    cc1.metric("Wear-only status (time-series)", rep_wear.status.replace("_", " ").upper())
    cc2.metric("With CV damage", rep_full.status.replace("_", " ").upper())
    icon = {"critical": "🔴", "warning": "🟠", "info": "🟢"}.get(rep_full.severity, "⚪")
    st.markdown(f"{icon} **{rep_full.headline}**")
    st.markdown(f"**Action:** {rep_full.recommended_action}")
    if result.damage_findings:
        st.error(
            "Acute damage detected by the VLM → **immediate AOG response** — a different logistics "
            "path than a scheduled wear replacement."
        )


def _screen_worklist(st, worklist):
    st.title("Priority Worklist")
    st.caption("Ranked by **P(cross before next check) × consequence** (utilization, position, spares) — not raw RUL.")
    df = pd.DataFrame(
        [
            {
                "Rank": w.rank,
                "Tail": w.tail_number,
                "Position": w.position_code,
                "Priority": round(w.priority, 3),
                "P(cross)": f"{w.p_cross_next_check:.0%}",
                "RUL (median)": f"{w.rul_median:.0f}",
                "Earliest date": w.earliest_date.isoformat(),
                "Action": w.action,
                "Why": w.reason,
            }
            for w in worklist
        ]
    )

    def _row_style(row):
        rank = row["Rank"]
        colour = "#f7d5d5" if rank <= 5 else ("#fbeecd" if rank <= 15 else "white")
        return [f"background-color: {colour}"] * len(row)

    st.dataframe(df.style.apply(_row_style, axis=1), width="stretch", height=680, hide_index=True)


def _screen_spares(st, go, demand):
    st.title("Spares Planner")
    df = pd.DataFrame([d.__dict__ for d in demand])
    stations = sorted(df["station"].unique())
    st.caption("Weekly projected removal demand (expected vs conservative P90) against on-hand stock. Red weeks = projected stock-out.")
    for s in stations:
        sd = df[df["station"] == s].reset_index(drop=True)
        stock = int(sd["on_hand"].iloc[0])
        fig = go.Figure()
        fig.add_trace(go.Bar(x=sd["week_start"], y=sd["expected_demand"], name="Expected", marker_color="#7aa5d2"))
        fig.add_trace(go.Bar(x=sd["week_start"], y=sd["p90_demand"], name="P90 (conservative)", marker_color="#e08a1e"))
        fig.add_hline(y=stock, line=dict(color="#3f9d55", dash="dash"), annotation_text=f"on-hand {stock}")
        first_out = sd[sd["projected_stockout"]]
        title = f"Station {s} — stock {stock}"
        if not first_out.empty:
            wk = first_out["week_start"].iloc[0]
            title += f"  ⚠️ projected stock-out ≈ {pd.Timestamp(wk).date().isoformat()}"
        fig.update_layout(height=280, barmode="group", title=title, margin=dict(l=10, r=10, t=40, b=10))
        st.plotly_chart(fig, width="stretch")


def _screen_alerts(st, alerts):
    st.title("Alerts Feed")
    col1, col2 = st.columns(2)
    with col1:
        st.subheader(f"🔵 Model alerts — wear-out ({len(alerts.wear_out)})")
        st.caption("Probabilistic; fired on the **earliest-credible (P10)** bound, never the median.")
        if not alerts.wear_out:
            st.info("No wear-out alerts at current thresholds.")
        for a in alerts.wear_out:
            _alert_card(st, a)
    with col2:
        st.subheader(f"🟠 Deterministic rules — event-driven ({len(alerts.event_driven)})")
        st.caption("Standards-grounded FAA/Goodyear cold-pressure ladder & hard-removal flags.")
        if not alerts.event_driven:
            st.info("No deterministic-rule alerts.")
        for a in alerts.event_driven:
            _alert_card(st, a)


def _alert_card(st, a):
    icon = {"critical": "🔴", "warning": "🟠", "info": "🔵"}.get(a.severity, "⚪")
    label = f"{icon} **{a.tail_number} · {a.position_code}** — {a.alert_type.replace('_', ' ')}"
    if a.severity == "critical":
        st.error(f"{label}\n\n{a.message}")
    elif a.severity == "warning":
        st.warning(f"{label}\n\n{a.message}")
    else:
        st.info(f"{label}\n\n{a.message}")


def _screen_documents(st, tables, risks, tc, as_of):
    from app.rul.grounding import (
        dispatch_for_wheel,
        extract_defect_log,
        grounded_thresholds,
        system_dispatch,
    )

    st.title("Document grounding — AMM · MEL/CDL · defect logs")
    tab_amm, tab_mel, tab_logs = st.tabs(["AMM thresholds", "MEL/CDL dispatch", "Defect-log extraction"])

    with tab_amm:
        st.caption("Every safety threshold the pipeline uses is traceable to an AMM reference — provenance, and a drift check against the manual.")
        rows = grounded_thresholds(tc)
        df = pd.DataFrame(
            [
                {
                    "Threshold": r["threshold"],
                    "Value in use": r["config"],
                    "AMM ref": r["amm_ref"],
                    "Sourced": "✅" if r["match"] else "⚠️ drift",
                    "Manual text": r["amm_text"],
                }
                for r in rows
            ]
        )
        st.dataframe(df, hide_index=True, width="stretch")

    with tab_mel:
        st.caption("A finding → a dispatch decision. A tire worn to limit or with acute damage has **no MEL relief** — AOG until replaced. Forecasting it turns that AOG into a scheduled fix.")
        urgent = []
        for r in risks:
            rep = scoring.tire_status_report(r, tc, as_of)
            if rep.status == "replace_now":
                d = dispatch_for_wheel(True, rep.status.replace("_", " "))
                urgent.append(
                    {
                        "Tail": r.tail_number,
                        "Position": r.position_code,
                        "Dispatch": "❌ AOG — replace first" if not d.dispatchable else "✅ ok",
                        "Basis": d.ref,
                    }
                )
        st.markdown(f"**Wheels with no dispatch relief (must replace before dispatch): {len(urgent)}**")
        if urgent:
            st.dataframe(pd.DataFrame(urgent).head(25), hide_index=True, width="stretch")
        st.markdown("**Wheel/tire SYSTEM items — dispatch relief exists:**")
        for key in ["tpms_inop", "wheel_speed_sensor_inop"]:
            d = system_dispatch(key)
            st.markdown(
                f"- **{d.finding}** → {d.mel_item} · **Cat {d.category}** ({d.interval_days} days): {d.provisions}"
            )

    with tab_logs:
        st.caption("Mine historical **free-text** defect logs into structured records, linked by serial — the 'underused inspection records' wedge. Rule-based here; a VLM/LLM plugs in for messier logs.")
        logs = tables.get("defect_logs")
        if logs is None:
            st.warning("No defect logs — run `make logs` (python -m app.rul.generate_defect_logs).")
            return
        fields = {
            "tail": "true_tail",
            "position_code": "true_position",
            "serial": "true_serial",
            "removal_reason": "true_reason",
            "cycles": "true_cycles",
        }
        correct = dict.fromkeys(fields, 0)
        extracted_rows = []
        for _, row in logs.iterrows():
            e = extract_defect_log(row["raw_text"])
            for ef, tf in fields.items():
                v, tv = e[ef], row[tf]
                if ef == "serial":
                    v, tv = (v or "").upper(), str(tv).upper()
                if v == tv:
                    correct[ef] += 1
            extracted_rows.append(
                {
                    "Raw log line": row["raw_text"],
                    "Tail": e["tail"],
                    "Position": e["position_code"],
                    "Serial": e["serial"],
                    "Reason": e["removal_reason"],
                    "Cycles": e["cycles"],
                }
            )
        n = len(logs)
        cols = st.columns(len(fields))
        for c, (ef, _) in zip(cols, fields.items(), strict=False):
            c.metric(ef.replace("_code", "").replace("removal_", ""), f"{correct[ef] / n:.0%}", help=f"{correct[ef]}/{n} extracted correctly vs ground truth")
        st.dataframe(pd.DataFrame(extracted_rows).head(30), hide_index=True, width="stretch")


def _screen_validation(st, go, report, tables, feats, prior, tc):
    st.title("Ground-Truth Validation")
    st.caption("Honest accuracy evidence only a **synthetic** POC can show — validation only, not a production accuracy claim.")
    deg = report.get("degradation_model", {})
    c1, c2, c3 = st.columns(3)
    rec = deg.get("ground_truth_wear_rate_recovery_median_abs_pct")
    c1.metric("Wear-rate recovery (median abs %)", f"{rec:.1%}" if rec is not None else "—", help="Model-recovered vs true per-tire wear rate on held-out tires.")
    al = deg.get("alpha_lambda_accuracy_second_half")
    c2.metric("α-λ accuracy (2nd half)", f"{al:.0%}" if al is not None else "—")
    dm = deg.get("wear_to_limit_date_mae_days_at_30d")
    c3.metric("Wear-to-limit date MAE @30d", f"{dm:.1f} d" if dm is not None else "—")

    c4, c5, c6 = st.columns(3)
    c4.metric("RUL MAE, 2nd half (cyc)", f"{deg.get('rul_mae_cycles_second_half', float('nan')):.1f}")
    c5.metric("Prognostic horizon (cyc)", f"{deg.get('prognostic_horizon_cycles', float('nan')):.0f}")
    c6.metric("LightGBM baseline MAE (cyc)", f"{report.get('lightgbm_baseline_rul_mae_cycles', float('nan')):.1f}")

    st.write("**Outcome mix (WORN / EARLY_REMOVAL / IN_SERVICE):**", report.get("outcome_mix", {}))

    # Recovered vs true wear rate scatter for current tires (validation-only use of the sidecar).
    gt = tables["_ground_truth"]
    rate = gt[gt["inspection_id"].isna()].dropna(subset=["tire_true_wear_rate_mm_per_landing"]).set_index("tire_id")[
        "tire_true_wear_rate_mm_per_landing"
    ]
    cur = tables["tires"][tables["tires"]["is_current"]]
    xs, ys = [], []
    for _, t in cur.iterrows():
        g = feats[feats["tire_id"] == t["tire_id"]]
        if g.empty or t["tire_id"] not in rate.index:
            continue
        pmean, pcov, scale = scoring.prior_arrays(prior, t["position_code"])
        mean, _ = scoring.eb_posterior(
            g["cycles_since_install"].to_numpy(float), g["measured_groove_mm"].to_numpy(float), pmean, pcov, scale
        )
        xs.append(rate[t["tire_id"]])
        ys.append(-mean[1])
    if xs:
        lim = max(max(xs), max(ys)) * 1.1
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=xs, y=ys, mode="markers", marker=dict(color="#2b6cb0", size=6, opacity=0.6), name="tires"))
        fig.add_trace(go.Scatter(x=[0, lim], y=[0, lim], mode="lines", line=dict(color="#d64545", dash="dash"), name="ideal"))
        fig.update_layout(
            height=440, margin=dict(l=10, r=10, t=30, b=10),
            xaxis_title="True wear rate (mm/landing)", yaxis_title="Model-recovered wear rate",
            title="Recovered vs true per-tire wear rate (current fleet)",
        )
        st.plotly_chart(fig, width="stretch")


if __name__ == "__main__":  # pragma: no cover
    main()
