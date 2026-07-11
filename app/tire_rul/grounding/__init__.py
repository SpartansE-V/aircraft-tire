"""Document-grounding layer.

Grounds the tool in the reference manuals: AMM-sourced thresholds (traceable provenance for the
values the pipeline uses), MEL/CDL dispatch-aware decisions (a finding → whether dispatch is
permitted and the rectification deadline), and free-text defect-log extraction (mine historical
records into the structured tire schema, linked by serial). Knowledge lives in
``config/knowledge.yaml``; the defect logs are synthetic free-text generated from real removals so
extraction can be validated against ground truth.
"""

from app.tire_rul.grounding.amm import grounded_thresholds, load_knowledge
from app.tire_rul.grounding.defect_logs import (
    POSITION_ALIASES,
    extract_defect_log,
    render_defect_log_line,
)
from app.tire_rul.grounding.mel import DispatchDecision, dispatch_for_wheel, system_dispatch

__all__ = [
    "DispatchDecision",
    "POSITION_ALIASES",
    "dispatch_for_wheel",
    "extract_defect_log",
    "grounded_thresholds",
    "load_knowledge",
    "render_defect_log_line",
    "system_dispatch",
]
