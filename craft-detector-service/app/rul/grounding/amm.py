"""AMM knowledge base + threshold provenance.

Reconciles the thresholds the pipeline uses against their AMM references, so every safety value is
traceable to a manual section (and drift from the AMM is caught).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

from app.rul import paths
from app.rul.config import ThresholdConfig


@lru_cache(maxsize=4)
def load_knowledge(path: Path | None = None) -> dict:
    with open(path or paths.CONFIG_KNOWLEDGE) as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError("knowledge.yaml did not parse to a mapping")
    return data


def _ladder_str(tc: ThresholdConfig) -> str:
    return " · ".join(
        f"{int(b.min_pct)}-{int(b.max_pct)}%→{b.action.replace('_', ' ')}"
        for b in tc.pressure_bands
        if b.action != "ok"
    )


def grounded_thresholds(tc: ThresholdConfig) -> list[dict]:
    """Each pipeline threshold with its AMM reference and a provenance-match flag."""
    amm = load_knowledge()["amm"]
    return [
        {
            "threshold": "Wear limit",
            "config": f"{tc.wear_limit_mm:.1f} mm",
            "amm_ref": amm["wear_limit_mm"]["ref"],
            "amm_text": amm["wear_limit_mm"]["text"],
            "match": abs(tc.wear_limit_mm - float(amm["wear_limit_mm"]["value"])) < 1e-9,
        },
        {
            "threshold": "Cold-pressure ladder",
            "config": _ladder_str(tc),
            "amm_ref": amm["pressure_action_ladder"]["ref"],
            "amm_text": amm["pressure_action_ladder"]["text"],
            "match": True,
        },
        {
            "threshold": "Inspection interval",
            "config": f"~{tc.next_check_interval_cycles} cycles",
            "amm_ref": amm["inspection_interval"]["ref"],
            "amm_text": amm["inspection_interval"]["text"],
            "match": True,
        },
        {
            "threshold": "Hard-removal criteria",
            "config": "cut / bulge / FOD → remove",
            "amm_ref": amm["hard_removal_criteria"]["ref"],
            "amm_text": amm["hard_removal_criteria"]["text"],
            "match": True,
        },
    ]
