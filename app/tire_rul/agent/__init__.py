"""Agentic AI layer — the Maintenance Decision Agent.

An LLM agent (OpenAI function-calling) that autonomously investigates the pipeline via tools and
returns a grounded maintenance decision. This is the core decision layer, not a decorative add-on:
it orchestrates the RUL model, the CV scan, MEL/CDL dispatch, spares, and defect history into an
actionable work order — with an offline deterministic fallback so the demo runs without a key.
"""

from app.tire_rul.agent.core import MaintenanceAgent, agent_backend_available, run_agent
from app.tire_rul.agent.tools import TOOL_FUNCS, TOOL_SCHEMAS, ToolContext, call_tool

__all__ = [
    "MaintenanceAgent",
    "TOOL_FUNCS",
    "TOOL_SCHEMAS",
    "ToolContext",
    "agent_backend_available",
    "call_tool",
    "run_agent",
]
