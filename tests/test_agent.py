"""Maintenance Decision Agent tests — tools, the offline agent loop, and backend selection.

Uses a tiny hand-built context (two wheels: one at-limit + damaged, one healthy) so we exercise the
agent logic without running the full training pipeline.
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from treadcast.agent import (
    TOOL_FUNCS,
    TOOL_SCHEMAS,
    MaintenanceAgent,
    ToolContext,
    agent_backend_available,
    call_tool,
)
from treadcast.agent.tools import _norm_pos
from treadcast.config import get_threshold_config
from treadcast.scoring import RulEstimate, WheelRisk

AS_OF = date(2025, 1, 1)


def _est(rul_median, p10_days, p_cross):
    return RulEstimate(
        rul_p10=rul_median * 0.9,
        rul_median=rul_median,
        rul_p90=rul_median * 1.1,
        rul_mean=rul_median,
        crossing_median_cycle=rul_median,
        p_cross_next_check=p_cross,
        frac_never=0.0,
        date_p10=AS_OF + timedelta(days=p10_days),
        date_median=AS_OF + timedelta(days=p10_days + 3),
        date_p90=AS_OF + timedelta(days=p10_days + 6),
        landings_per_day=3.0,
        low_confidence=False,
        intercept=12.0,
        slope=-0.04,
    )


@pytest.fixture
def ctx():
    risks = [
        WheelRisk("acA", "VN-A701", "mlg_l_inbd", "SGN", 0, 4.0, _est(3, 1, 1.0),
                  pressure_pct=99.0, pressure_action="ok", recent_wear_rate=0.04, baseline_wear_rate=0.035),
        WheelRisk("acB", "VN-A702", "nlg_l", "HAN", 5, 2.0, _est(300, 90, 0.0),
                  pressure_pct=100.0, pressure_action="ok", recent_wear_rate=0.06, baseline_wear_rate=0.065),
    ]
    tables = {
        "tires": pd.DataFrame(
            [
                {"tire_id": "tA", "aircraft_id": "acA", "position_code": "mlg_l_inbd", "is_current": True,
                 "serial": "MI7A1B2C", "new_tread_mm": 13.0},
                {"tire_id": "tB", "aircraft_id": "acB", "position_code": "nlg_l", "is_current": True,
                 "serial": "GO9D3E4F", "new_tread_mm": 12.5},
            ]
        ),
        "tire_scans": pd.DataFrame(
            [
                {"tire_id": "tA", "serial": "MI7A1B2C", "laser_groove_mm": 2.4, "damage_findings": ["cut"], "scan_confidence": 0.95},
                {"tire_id": "tB", "serial": "GO9D3E4F", "laser_groove_mm": 8.0, "damage_findings": [], "scan_confidence": 0.95},
            ]
        ),
        "station_stock": pd.DataFrame([{"station_code": "SGN", "on_hand": 0}, {"station_code": "HAN", "on_hand": 5}]),
        "defect_logs": pd.DataFrame([{"raw_text": "2024-12-02 VN-A701 MLG L INBD S/N MI7A1B2C worn to limit 260 cyc"}]),
    }
    return ToolContext(tables=tables, risks=risks, tc=get_threshold_config(), as_of=AS_OF)


# --- tools ---
def test_tool_get_wheel_status(ctx):
    s = call_tool(ctx, "get_wheel_status", {"tail": "VN-A701", "position": "mlg_l_inbd"})
    assert s["status"] == "replace_now" and s["station"] == "SGN" and s["spares_on_hand"] == 0


def test_tool_scan_and_dispatch(ctx):
    scan = call_tool(ctx, "get_tire_scan", {"tail": "VN-A701", "position": "mlg_l_inbd"})
    assert scan["damage_findings"] == ["cut"] and scan["serial"] == "MI7A1B2C"
    disp = call_tool(ctx, "check_dispatch", {"tail": "VN-A701", "position": "mlg_l_inbd"})
    assert disp["dispatchable"] is False and disp["acute_damage"] is True


def test_tool_healthy_wheel_dispatchable(ctx):
    disp = call_tool(ctx, "check_dispatch", {"tail": "VN-A702", "position": "nlg_l"})
    assert disp["dispatchable"] is True


def test_tool_list_priority_and_spares(ctx):
    wl = call_tool(ctx, "list_priority_wheels", {"top_n": 5})
    assert wl["wheels"] and wl["wheels"][0]["tail"] == "VN-A701"  # the urgent one ranks first
    sp = call_tool(ctx, "check_spares", {"station": "SGN"})
    assert sp["on_hand"] == 0


def test_tool_defect_history(ctx):
    r = call_tool(ctx, "search_defect_history", {"query": "MI7A1B2C"})
    assert r["records"] and r["records"][0]["serial"] == "MI7A1B2C"


def test_call_tool_unknown(ctx):
    assert "error" in call_tool(ctx, "nope", {})


def test_norm_pos():
    assert _norm_pos("MLG L INBD") == "mlg_l_inbd"
    assert _norm_pos("mlg_r_outbd") == "mlg_r_outbd"
    assert _norm_pos("nonsense") is None


# --- agent (offline) ---
def test_agent_investigates_specific_wheel(ctx):
    out = MaintenanceAgent(ctx, backend="mock").run("What should I do about VN-A701 mlg_l_inbd?")
    tools = [t["tool"] for t in out["trace"]]
    assert "get_wheel_status" in tools and "get_tire_scan" in tools and "check_dispatch" in tools
    assert "AOG" in out["answer"] and "cut" in out["answer"].lower()
    assert out["backend"] == "offline-mock"


def test_agent_plans_station(ctx):
    out = MaintenanceAgent(ctx, backend="mock").run("Plan tonight's tire maintenance for SGN")
    assert any(t["tool"] == "list_priority_wheels" for t in out["trace"])
    assert "Maintenance plan" in out["answer"]


def test_agent_tail_only(ctx):
    out = MaintenanceAgent(ctx, backend="mock").run("Is VN-A702 ok to dispatch?")
    assert "VN-A702" in out["answer"]


def test_agent_backend_available(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert agent_backend_available("mock") is True
    assert agent_backend_available("openai") is False
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert agent_backend_available("openai") is True  # openai SDK installed + key


def test_tool_schemas_match_funcs():
    for schema in TOOL_SCHEMAS:
        name = schema["function"]["name"]
        assert name in TOOL_FUNCS, f"schema {name} has no implementation"
    assert len(TOOL_SCHEMAS) == len(TOOL_FUNCS)


# --- Bedrock backend ---
def test_anthropic_tool_schemas_conversion():
    from treadcast.agent.tools import anthropic_tool_schemas

    schemas = anthropic_tool_schemas()
    assert len(schemas) == len(TOOL_FUNCS)
    for s in schemas:
        assert s["name"] in TOOL_FUNCS
        assert "input_schema" in s and s["input_schema"]["type"] == "object"
        assert "function" not in s  # anthropic format, not openai


def test_agent_backend_available_bedrock(monkeypatch):
    from treadcast.cv import assess

    monkeypatch.setattr(assess, "_aws_credentials_present", lambda: True)
    assert agent_backend_available("bedrock") is True  # anthropic SDK installed + creds
    monkeypatch.setattr(assess, "_aws_credentials_present", lambda: False)
    assert agent_backend_available("bedrock") is False


def test_agent_auto_prefers_openai_then_bedrock(ctx, monkeypatch):
    from treadcast.cv import assess

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(assess, "_aws_credentials_present", lambda: True)
    agent = MaintenanceAgent(ctx, backend="auto")
    assert agent._resolve() == "bedrock"
    monkeypatch.setattr(assess, "_aws_credentials_present", lambda: False)
    assert agent._resolve() == "mock"


# --- engineer-chat tools: damage area + triggered prediction ---
def test_tool_get_damage_area_finds_regions(ctx):
    area = call_tool(ctx, "get_damage_area", {"tail": "VN-A701", "position": "mlg_l_inbd"})
    assert area["serial"] == "MI7A1B2C"
    assert area["regions"], "expected at least one damage region for the cut tire"
    r = area["regions"][0]
    assert r["type"] == "cut" and len(r["bbox"]) == 4 and "tread" in r["location"]


def test_tool_get_damage_area_clean_tire(ctx):
    area = call_tool(ctx, "get_damage_area", {"tail": "VN-A702", "position": "nlg_l"})
    assert area["regions"] == []


def test_tool_run_rul_prediction_fallback(ctx):
    """Without prior/feats in the context, prediction falls back to the precomputed estimate."""
    pred = call_tool(ctx, "run_rul_prediction", {"tail": "VN-A702", "position": "nlg_l"})
    assert pred["prediction_triggered"] is False
    assert pred["rul_landings"]["median"] == 300
    assert pred["rul_landings"]["p10"] <= pred["rul_landings"]["median"] <= pred["rul_landings"]["p90"]


def test_tool_run_rul_prediction_utilization_override(ctx):
    pred = call_tool(
        ctx, "run_rul_prediction", {"tail": "VN-A702", "position": "nlg_l", "utilization_override": 6.0}
    )
    assert pred["utilization_landings_per_day"] == 6.0


# --- multi-turn chat: context carryover ---
def test_chat_carries_wheel_context(ctx):
    agent = MaintenanceAgent(ctx, backend="mock")
    hist = [{"role": "user", "content": "What's the situation of VN-A701 mlg_l_inbd?"}]
    out1 = agent.chat(hist)
    assert "Situation" in out1["answer"]
    hist.append({"role": "assistant", "content": out1["answer"]})
    hist.append({"role": "user", "content": "Trigger a prediction for it"})
    out2 = agent.chat(hist)
    tools2 = [t["tool"] for t in out2["trace"]]
    assert tools2 == ["run_rul_prediction"]
    assert "VN-A701" in out2["answer"]  # resolved from earlier turn
    hist.append({"role": "assistant", "content": out2["answer"]})
    hist.append({"role": "user", "content": "Where is the damage area?"})
    out3 = agent.chat(hist)
    assert [t["tool"] for t in out3["trace"]] == ["get_damage_area"]
    assert "cut" in out3["answer"].lower()


def test_chat_utilization_what_if(ctx):
    agent = MaintenanceAgent(ctx, backend="mock")
    out = agent.chat(
        [
            {"role": "user", "content": "status of VN-A702 nlg_l"},
            {"role": "assistant", "content": "..."},
            {"role": "user", "content": "what if it flies 6 landings per day?"},
        ]
    )
    assert [t["tool"] for t in out["trace"]] == ["run_rul_prediction"]
    assert out["trace"][0]["args"]["utilization_override"] == 6.0


def test_chat_requires_trailing_user_message(ctx):
    agent = MaintenanceAgent(ctx, backend="mock")
    with pytest.raises(ValueError):
        agent.chat([{"role": "assistant", "content": "hi"}])
