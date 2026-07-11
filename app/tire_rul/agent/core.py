"""Maintenance Decision Agent.

Given a natural-language request ("what should I do about VN-A300's main gear?", "plan tonight's
tire maintenance for SGN"), the agent INVESTIGATES by calling pipeline tools, reasons across the
results, and returns a grounded decision + work-order draft, exposing its tool-call trace.

Backends: ``openai`` (real LLM function-calling — the agentic core), and ``mock`` (an offline,
deterministic planner that runs the same tool sequence so the demo works with no API key).
``auto`` uses OpenAI when a key is present, else the mock.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re

from app.tire_rul.agent.tools import TOOL_SCHEMAS, ToolContext, _norm_pos, call_tool

SYSTEM_PROMPT = (
    "You are TreadCast's aircraft-tire maintenance agent, chatting with a line engineer. "
    "INVESTIGATE with the tools before answering — never guess. For a wheel's situation: "
    "get_wheel_status (+ get_tire_scan). To (re)forecast: run_rul_prediction (supports a "
    "utilization_override in landings/day). For where damage is on the tire: get_damage_area "
    "(returns tread locations + pixel boxes). For dispatch: check_dispatch; spares: check_spares; "
    "planning: list_priority_wheels; history: search_defect_history. In a conversation, resolve "
    "references like 'it' / 'that wheel' from earlier turns. Always: (1) distinguish gradual WEAR "
    "(schedule a swap) from ACUTE damage — cut/bulge/FOD (immediate removal, no MEL dispatch "
    "relief -> AOG); (2) reason from the earliest-credible date, not the median; (3) cite the "
    "AMM/MEL reference a tool returns; (4) end with a concise recommended action. Be brief."
)
_STATIONS = ["SGN", "HAN", "DAD"]


def agent_backend_available(backend: str) -> bool:
    if backend == "openai":
        return importlib.util.find_spec("openai") is not None and bool(os.environ.get("OPENAI_API_KEY"))
    if backend == "bedrock":
        try:
            # cv.assess needs the `ai` extra (PIL); without it Bedrock is simply unavailable.
            from app.tire_rul.cv.assess import _aws_credentials_present
        except ImportError:
            return False

        return importlib.util.find_spec("anthropic") is not None and _aws_credentials_present()
    return backend == "mock"


class MaintenanceAgent:
    def __init__(self, ctx: ToolContext, backend: str = "auto", model: str | None = None, max_steps: int = 6):
        self.ctx = ctx
        self.backend = backend
        self.model = model
        self.max_steps = max_steps

    def _resolve(self) -> str:
        if self.backend in ("openai", "bedrock", "mock"):
            return self.backend
        if agent_backend_available("openai"):
            return "openai"
        if agent_backend_available("bedrock"):
            return "bedrock"
        return "mock"

    def run(self, question: str) -> dict:
        """One-shot ask (kept for compatibility) — a single-turn chat."""
        return self.chat([{"role": "user", "content": question}])

    def chat(self, messages: list[dict]) -> dict:
        """Multi-turn conversation. `messages` = [{'role': 'user'|'assistant', 'content': str}, ...]
        ending with the newest user message. Follow-ups may reference earlier turns ('predict it')."""
        if not messages or messages[-1].get("role") != "user":
            raise ValueError("chat() expects a message list ending with a user message")
        backend = self._resolve()
        if backend == "openai":
            return self._chat_openai(messages)
        if backend == "bedrock":
            return self._chat_bedrock(messages)
        return self._chat_mock(messages)

    # -- real agent: OpenAI function-calling loop (full history passed through) --
    def _chat_openai(self, history: list[dict]) -> dict:
        import openai

        if not os.environ.get("OPENAI_API_KEY"):
            raise RuntimeError("The OpenAI agent needs OPENAI_API_KEY in the environment.")
        model = self.model or os.environ.get("OPENAI_AGENT_MODEL", "gpt-4o-mini")
        client = openai.OpenAI()
        messages: list = [
            {"role": "system", "content": SYSTEM_PROMPT},
            *[{"role": m["role"], "content": m["content"]} for m in history],
        ]
        trace: list = []
        for _ in range(self.max_steps):
            resp = client.chat.completions.create(
                model=model, messages=messages, tools=TOOL_SCHEMAS, tool_choice="auto", temperature=0
            )
            msg = resp.choices[0].message
            if not msg.tool_calls:
                return {"answer": msg.content or "", "trace": trace, "backend": f"openai:{model}"}
            messages.append(
                {
                    "role": "assistant",
                    "content": msg.content or "",
                    "tool_calls": [tc.model_dump() for tc in msg.tool_calls],
                }
            )
            for tc in msg.tool_calls:
                args = json.loads(tc.function.arguments or "{}")
                result = call_tool(self.ctx, tc.function.name, args)
                trace.append({"tool": tc.function.name, "args": args, "result": result})
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(result)[:4000]})
        return {"answer": "Reached the investigation step limit.", "trace": trace, "backend": f"openai:{model}"}

    # -- real agent: Claude on Amazon Bedrock (Mantle client, Messages-API tool-use loop) --
    def _chat_bedrock(self, history: list[dict]) -> dict:
        try:
            from anthropic import AnthropicBedrock
        except ImportError as exc:
            raise RuntimeError(
                "The Bedrock agent needs the Anthropic SDK with Bedrock support (pip install 'anthropic[bedrock]')."
            ) from exc
        from app.tire_rul.agent.tools import anthropic_tool_schemas

        # Bedrock model IDs carry an `anthropic.` prefix.
        model = self.model or os.environ.get("BEDROCK_AGENT_MODEL", "anthropic.claude-opus-4-8")
        region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1"
        client = AnthropicBedrock(aws_region=region)
        tools = anthropic_tool_schemas()
        messages: list = [{"role": m["role"], "content": m["content"]} for m in history]
        trace: list = []
        for _ in range(self.max_steps):
            resp = client.messages.create(
                model=model, max_tokens=2048, system=SYSTEM_PROMPT, tools=tools, messages=messages
            )
            if resp.stop_reason != "tool_use":
                answer = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
                return {"answer": answer, "trace": trace, "backend": f"bedrock:{model}"}
            messages.append({"role": "assistant", "content": resp.content})
            results = []
            for block in resp.content:
                if getattr(block, "type", None) == "tool_use":
                    args = dict(block.input or {})
                    result = call_tool(self.ctx, block.name, args)
                    trace.append({"tool": block.name, "args": args, "result": result})
                    results.append(
                        {"type": "tool_result", "tool_use_id": block.id, "content": json.dumps(result)[:4000]}
                    )
            messages.append({"role": "user", "content": results})
        return {"answer": "Reached the investigation step limit.", "trace": trace, "backend": f"bedrock:{model}"}

    # -- offline deterministic planner (same tools, intent-routed, conversation-aware) --
    @staticmethod
    def _parse_wheel(text: str) -> tuple[str | None, str | None]:
        m = re.search(r"vn[- ]?a?\s?(\d{3})", text.lower())
        return (f"VN-A{m.group(1)}" if m else None), _norm_pos(text)

    def _chat_mock(self, history: list[dict]) -> dict:
        question = history[-1]["content"]
        q = question.lower()
        trace: list = []

        def T(name, **args):
            res = call_tool(self.ctx, name, args)
            trace.append({"tool": name, "args": args, "result": res})
            return res

        # Resolve the wheel from this message, then fall back to earlier turns ("predict it").
        tail, pos = self._parse_wheel(question)
        if not (tail and pos):
            for m in reversed(history[:-1]):
                t2, p2 = self._parse_wheel(str(m.get("content", "")))
                tail = tail or t2
                pos = pos or p2
                if tail and pos:
                    break
        station = next((s for s in _STATIONS if s.lower() in q), None)

        # Intent shortcuts an engineer uses in chat — no page-hopping needed.
        if tail and pos and any(k in q for k in ("damage", "where is", "area", "region", "spot")):
            area = T("get_damage_area", tail=tail, position=pos)
            return {"answer": self._damage_answer(tail, pos, area), "trace": trace, "backend": "offline-mock"}
        mu = re.search(r"(\d+(?:\.\d+)?)\s*(?:landings?|cycles?|legs?)\s*(?:/|per)\s*day", q)
        wants_predict = any(
            k in q for k in ("predict", "forecast", "rul", "how long", "how many landings", "remaining", "what if")
        )
        if tail and pos and (wants_predict or mu):
            util = float(mu.group(1)) if mu else None
            pred = T("run_rul_prediction", tail=tail, position=pos, utilization_override=util)
            return {"answer": self._predict_answer(tail, pos, pred), "trace": trace, "backend": "offline-mock"}
        if tail and pos and any(k in q for k in ("status", "situation", "condition", "how is", "state")):
            status = T("get_wheel_status", tail=tail, position=pos)
            return {"answer": self._status_answer(tail, pos, status), "trace": trace, "backend": "offline-mock"}

        if tail and pos:
            status = T("get_wheel_status", tail=tail, position=pos)
            scan = T("get_tire_scan", tail=tail, position=pos)
            disp = T("check_dispatch", tail=tail, position=pos)
            spares = T("check_spares", station=status.get("station")) if "error" not in status else {}
            answer = self._decision(tail, pos, status, scan, disp, spares)
        elif tail:
            tail_risks = [r for r in self.ctx.risks if r.tail_number == tail]
            if not tail_risks:
                answer = f"No current wheels found for {tail}."
            else:
                worst = min(tail_risks, key=lambda r: r.estimate.date_p10)  # most urgent wheel
                status = T("get_wheel_status", tail=tail, position=worst.position_code)
                scan = T("get_tire_scan", tail=tail, position=worst.position_code)
                disp = T("check_dispatch", tail=tail, position=worst.position_code)
                spares = T("check_spares", station=status.get("station")) if "error" not in status else {}
                answer = self._decision(tail, worst.position_code, status, scan, disp, spares)
        else:
            wl = T("list_priority_wheels", top_n=8, station=station)
            answer = self._plan(station, wl)
        return {"answer": answer, "trace": trace, "backend": "offline-mock"}

    def _decision(self, tail, pos, status, scan, disp, spares) -> str:
        if "error" in status:
            return f"No current-wheel data for {tail} {pos}."
        damage = scan.get("damage_findings", []) if "error" not in scan else []
        lines = [
            f"**Decision — {tail} · {status['position']}**",
            f"- Status: **{status['status'].replace('_', ' ').upper()}** — {status['headline']}",
            f"- RUL {status['rul_median_landings']} landings; earliest-credible {status['earliest_credible_date']}; "
            f"P(cross before next check) {status['p_cross_next_check']:.0%}.",
        ]
        if damage:
            lines.append(f"- CV scan: **ACUTE DAMAGE — {', '.join(damage)}** (serial {scan.get('serial')}).")
        else:
            lines.append(
                f"- CV scan: no acute damage; tread {scan.get('laser_groove_mm', '?')} mm (serial {scan.get('serial', '?')})."
            )
        if not disp.get("dispatchable", True):
            lines.append(f"- Dispatch: **NO MEL RELIEF → AOG until replaced** (basis {disp.get('ref')}).")
        else:
            lines.append(f"- Dispatch: serviceable within limits (basis {disp.get('ref')}).")
        so = spares.get("projected_stockout_week")
        lines.append(
            f"- Spares at {status.get('station')}: {status.get('spares_on_hand')} on hand"
            + (f"; projected stock-out week of {so}." if so else ".")
        )
        urgent = bool(damage) or not disp.get("dispatchable", True)
        wo = status["recommended_action"] + (
            "  Acute/at-limit — replace before next dispatch and pre-position a spare."
            if urgent
            else "  Schedule within the planning window."
        )
        lines += ["", f"**Recommended work order:** {wo}"]
        return "\n".join(lines)

    def _status_answer(self, tail, pos, status) -> str:
        if "error" in status:
            return f"No current-wheel data for {tail} {pos}."
        conf = " _(fleet prior — low confidence)_" if status.get("low_confidence") else ""
        return "\n".join(
            [
                f"**Situation — {tail} · {status['position']}**{conf}",
                f"- Status: **{status['status'].replace('_', ' ').upper()}** — {status['headline']}",
                f"- Pressure {status['pressure_pct']}% → {str(status['pressure_action']).replace('_', ' ')} · "
                f"station {status['station']} ({status['spares_on_hand']} spares) · "
                f"{status['utilization_per_day']} landings/day.",
                f"- **Action:** {status['recommended_action']}",
            ]
        )

    def _predict_answer(self, tail, pos, pred) -> str:
        if "error" in pred:
            return f"Could not run a prediction for {tail} {pos}: {pred['error']}"
        rul, dates = pred["rul_landings"], pred["wear_to_limit_date"]
        src = (
            f"fresh Monte-Carlo run ({pred['mc_draws']} draws)"
            if pred["prediction_triggered"]
            else "latest precomputed estimate"
        )
        return "\n".join(
            [
                f"**Prediction — {tail} · {pred['position']}** ({src}, "
                f"{pred['utilization_landings_per_day']} landings/day)",
                f"- RUL: **{rul['median']} landings** (P10 {rul['p10']} · P90 {rul['p90']}).",
                f"- Wear-to-limit date: **{dates['median']}** — earliest-credible **{dates['earliest_credible_p10']}**, "
                f"latest {dates['p90']}.",
                f"- P(cross before next check): **{pred['p_cross_next_check']:.0%}**."
                + (" _(fleet prior — low confidence)_" if pred.get("low_confidence") else ""),
            ]
        )

    def _damage_answer(self, tail, pos, area) -> str:
        if "error" in area:
            return f"No scan available for {tail} {pos}: {area['error']}"
        regions = area.get("regions", [])
        if not regions:
            return (
                f"**Damage check — {tail} · {area['position']}** (serial `{area['serial']}`)\n"
                "- No acute damage regions on the latest scan — tread wear only. "
                "Wear-out stays a *scheduled* item."
            )
        lines = [f"**Damage areas — {tail} · {area['position']}** (serial `{area['serial']}`)"]
        for r in regions:
            lines.append(
                f"- **{r['type'].upper()}** at the **{r['location']}** — bbox {r['bbox']} (~{r['area_px']} px)."
            )
        lines.append(
            "Acute damage → **immediate removal, no MEL dispatch relief** — treat as AOG, not a scheduled swap."
        )
        return "\n".join(lines)

    def _plan(self, station, wl) -> str:
        wheels = wl["wheels"]
        head = f"**Maintenance plan{' — ' + station if station else ''}: top {len(wheels)} wheels by risk**"
        lines = [head]
        for w in wheels:
            lines.append(
                f"- `{w['priority']:.2f}`  {w['tail']} · {w['position']} — RUL {w['rul_median_landings']} ldg, "
                f"by {w['earliest_date']} — {w['action']}"
            )
        lines += [
            "",
            "Ranked by P(cross before next check) × consequence (utilization · position · spares). Replace any "
            "acute-damage wheels first (no dispatch relief), then schedule the wear-out wheels within the window.",
        ]
        return "\n".join(lines)


def run_agent(ctx: ToolContext, question: str, backend: str = "auto", model: str | None = None) -> dict:
    return MaintenanceAgent(ctx, backend=backend, model=model).run(question)
