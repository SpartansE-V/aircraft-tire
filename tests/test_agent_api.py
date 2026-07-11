"""Maintenance-agent HTTP API tests (chat, fleet worklist, wheel status).

Uses the same tiny hand-built ToolContext as test_agent.py (one urgent + one healthy wheel),
patched into the agent service, so the API layer is exercised end-to-end with the offline
deterministic agent backend — no LLM key, no full training pipeline.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any
from uuid import UUID

import pandas as pd
import pytest
from httpx import AsyncClient

import app.services.agent_service as agent_service_module
from app.rul.agent import ToolContext
from app.rul.config import get_threshold_config
from app.rul.scoring import RulEstimate, WheelRisk
from app.services.agent_service import AgentDataUnavailableError

AS_OF = date(2025, 1, 1)


def _est(rul_median: float, p10_days: int, p_cross: float) -> RulEstimate:
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
def fleet_ctx(monkeypatch: pytest.MonkeyPatch) -> ToolContext:
    risks = [
        WheelRisk(
            "acA",
            "VN-A701",
            "mlg_l_inbd",
            "SGN",
            0,
            4.0,
            _est(3, 1, 1.0),
            pressure_pct=99.0,
            pressure_action="ok",
            recent_wear_rate=0.04,
            baseline_wear_rate=0.035,
        ),
        WheelRisk(
            "acB",
            "VN-A702",
            "nlg_l",
            "HAN",
            5,
            2.0,
            _est(300, 90, 0.0),
            pressure_pct=100.0,
            pressure_action="ok",
            recent_wear_rate=0.06,
            baseline_wear_rate=0.065,
        ),
    ]
    tables = {
        "tires": pd.DataFrame(
            [
                {
                    "tire_id": "tA",
                    "aircraft_id": "acA",
                    "position_code": "mlg_l_inbd",
                    "is_current": True,
                    "serial": "MI7A1B2C",
                    "new_tread_mm": 13.0,
                },
                {
                    "tire_id": "tB",
                    "aircraft_id": "acB",
                    "position_code": "nlg_l",
                    "is_current": True,
                    "serial": "GO9D3E4F",
                    "new_tread_mm": 12.5,
                },
            ]
        ),
        "tire_scans": pd.DataFrame(
            [
                {
                    "tire_id": "tA",
                    "serial": "MI7A1B2C",
                    "laser_groove_mm": 2.4,
                    "damage_findings": ["cut"],
                    "scan_confidence": 0.95,
                },
                {
                    "tire_id": "tB",
                    "serial": "GO9D3E4F",
                    "laser_groove_mm": 8.0,
                    "damage_findings": [],
                    "scan_confidence": 0.95,
                },
            ]
        ),
        "station_stock": pd.DataFrame(
            [{"station_code": "SGN", "on_hand": 0}, {"station_code": "HAN", "on_hand": 5}]
        ),
        "defect_logs": pd.DataFrame(
            [{"raw_text": "2024-12-02 VN-A701 MLG L INBD S/N MI7A1B2C worn to limit 260 cyc"}]
        ),
    }
    ctx = ToolContext(tables=tables, risks=risks, tc=get_threshold_config(), as_of=AS_OF)
    monkeypatch.setattr(agent_service_module, "_cached_context", lambda as_of: ctx)
    return ctx


def _chat_payload(*turns: tuple[str, str], backend: str = "mock") -> dict[str, Any]:
    return {
        "messages": [{"role": role, "content": content} for role, content in turns],
        "backend": backend,
    }


# --- POST /api/v1/rul/agent/chat ---
async def test_agent_chat_grounded_decision(client: AsyncClient, fleet_ctx: ToolContext) -> None:
    payload = _chat_payload(("user", "What should I do about VN-A701 mlg l inbd?"))
    response = await client.post("/api/v1/rul/agent/chat", json=payload)

    assert response.status_code == 200
    body = response.json()
    UUID(body["chat_id"])
    assert body["backend"] == "offline-mock"
    assert body["as_of_date"] == AS_OF.isoformat()
    assert "Decision — VN-A701" in body["answer"]
    assert "Recommended work order" in body["answer"]
    assert "does not replace physical inspection" in body["disclaimer"]

    tools_called = [t["tool"] for t in body["trace"]]
    assert "get_wheel_status" in tools_called
    assert "check_dispatch" in tools_called
    for call in body["trace"]:
        assert set(call) == {"tool", "args", "result"}
        assert isinstance(call["args"], dict)
        assert isinstance(call["result"], dict)


async def test_agent_chat_resolves_reference_from_history(
    client: AsyncClient, fleet_ctx: ToolContext
) -> None:
    payload = _chat_payload(
        ("user", "How is VN-A702 nose l doing?"),
        ("assistant", "**Situation — VN-A702 · nlg_l** ..."),
        ("user", "Predict it at 5 landings per day"),
    )
    response = await client.post("/api/v1/rul/agent/chat", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert "Prediction — VN-A702" in body["answer"]
    prediction_calls = [t for t in body["trace"] if t["tool"] == "run_rul_prediction"]
    assert prediction_calls and prediction_calls[0]["args"]["utilization_override"] == 5.0


async def test_agent_chat_station_plan(client: AsyncClient, fleet_ctx: ToolContext) -> None:
    payload = _chat_payload(("user", "Plan tonight's tire maintenance for SGN"))
    response = await client.post("/api/v1/rul/agent/chat", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert "Maintenance plan" in body["answer"]
    assert body["trace"][0]["tool"] == "list_priority_wheels"


@pytest.mark.parametrize(
    "payload",
    [
        {"messages": [], "backend": "mock"},
        {"messages": [{"role": "assistant", "content": "hi"}], "backend": "mock"},
        {"messages": [{"role": "user", "content": "hi"}], "backend": "not-a-backend"},
        {"messages": [{"role": "user", "content": ""}], "backend": "mock"},
    ],
)
async def test_agent_chat_invalid_requests(
    client: AsyncClient, fleet_ctx: ToolContext, payload: dict[str, Any]
) -> None:
    response = await client.post("/api/v1/rul/agent/chat", json=payload)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_INPUT"


async def test_agent_chat_explicit_llm_backend_failure_is_502(
    client: AsyncClient, fleet_ctx: ToolContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    payload = _chat_payload(("user", "plan SGN"), backend="openai")
    response = await client.post("/api/v1/rul/agent/chat", json=payload)

    assert response.status_code == 502
    error = response.json()["error"]
    assert error["code"] == "AGENT_BACKEND_FAILED"
    assert "'openai'" in error["message"]


async def test_agent_chat_auto_falls_back_to_mock_when_llm_fails(
    client: AsyncClient, fleet_ctx: ToolContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.rul.agent.core as agent_core

    # Make 'auto' pick the OpenAI backend, then let the call itself fail (no API key).
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(agent_core, "agent_backend_available", lambda backend: backend == "openai")

    payload = _chat_payload(("user", "Plan tonight's tire maintenance for SGN"), backend="auto")
    response = await client.post("/api/v1/rul/agent/chat", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["backend"] == "offline-mock (auto fallback)"
    assert "Maintenance plan" in body["answer"]


# --- GET /api/v1/rul/fleet/worklist ---
async def test_worklist_ranks_urgent_wheel_first(
    client: AsyncClient, fleet_ctx: ToolContext
) -> None:
    response = await client.get("/api/v1/rul/fleet/worklist")

    assert response.status_code == 200
    body = response.json()
    assert body["as_of_date"] == AS_OF.isoformat()
    assert [w["tail_number"] for w in body["wheels"]] == ["VN-A701", "VN-A702"]
    urgent = body["wheels"][0]
    assert urgent["rank"] == 1
    assert urgent["position"] == "mlg_l_inbd"
    assert urgent["station"] == "SGN"
    assert 0.0 <= urgent["p_cross_before_next_check"] <= 1.0
    assert urgent["priority"] >= body["wheels"][1]["priority"]
    assert urgent["reason"] and urgent["action"]


async def test_worklist_station_filter_and_top_n(
    client: AsyncClient, fleet_ctx: ToolContext
) -> None:
    filtered = await client.get("/api/v1/rul/fleet/worklist", params={"station": "HAN"})
    assert [w["station"] for w in filtered.json()["wheels"]] == ["HAN"]
    assert filtered.json()["wheels"][0]["rank"] == 1  # rank is per returned list

    capped = await client.get("/api/v1/rul/fleet/worklist", params={"top_n": 1})
    assert len(capped.json()["wheels"]) == 1

    invalid = await client.get("/api/v1/rul/fleet/worklist", params={"top_n": 0})
    assert invalid.status_code == 422


# --- GET /api/v1/rul/wheel/status ---
async def test_wheel_status_reports_condition(client: AsyncClient, fleet_ctx: ToolContext) -> None:
    response = await client.get(
        "/api/v1/rul/wheel/status", params={"tail": "VN-A701", "position": "mlg_l_inbd"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["tail_number"] == "VN-A701"
    assert body["position"] == "mlg_l_inbd"
    assert body["status"] == "replace_now"
    assert body["severity"] == "critical"
    assert body["station"] == "SGN"
    assert body["spares_on_hand"] == 0
    assert body["headline"] and body["explanation"] and body["recommended_action"]


async def test_wheel_status_accepts_position_alias(
    client: AsyncClient, fleet_ctx: ToolContext
) -> None:
    response = await client.get(
        "/api/v1/rul/wheel/status", params={"tail": "VN-A702", "position": "nose l"}
    )

    assert response.status_code == 200
    assert response.json()["position"] == "nlg_l"


async def test_wheel_status_unknown_wheel_is_404(
    client: AsyncClient, fleet_ctx: ToolContext
) -> None:
    response = await client.get(
        "/api/v1/rul/wheel/status", params={"tail": "VN-A999", "position": "nlg_l"}
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "WHEEL_NOT_FOUND"


# --- degraded deployments (no `ai` extra / no dataset) ---
async def test_fleet_endpoints_return_503_when_dataset_unavailable(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _unavailable(as_of: date) -> ToolContext:
        raise AgentDataUnavailableError("fleet dataset not found")

    monkeypatch.setattr(agent_service_module, "_cached_context", _unavailable)

    chat = await client.post("/api/v1/rul/agent/chat", json=_chat_payload(("user", "plan SGN")))
    worklist = await client.get("/api/v1/rul/fleet/worklist")
    status = await client.get(
        "/api/v1/rul/wheel/status", params={"tail": "VN-A701", "position": "nlg_l"}
    )

    for response in (chat, worklist, status):
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "FLEET_DATA_UNAVAILABLE"
