"""MEL / CDL dispatch decisions.

Turns a tire finding into a dispatch decision: is the aircraft dispatchable, under which MEL/CDL
item, in which rectification category, and by when. A tire worn to limit or with acute damage has
**no dispatch relief** (must be replaced) — the value of forecasting it is turning that AOG into a
*scheduled* fix rather than a gate surprise.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.rul.grounding.amm import load_knowledge


@dataclass
class DispatchDecision:
    finding: str
    dispatchable: bool
    mel_item: str
    category: str | None
    interval_days: int | None
    provisions: str
    ref: str


def dispatch_for_wheel(worn_or_damaged: bool, finding: str = "") -> DispatchDecision:
    """Dispatch decision for a wheel condition. Worn/damaged tires get no relief (AOG until fixed)."""
    if worn_or_damaged:
        k = load_knowledge()["mel"]["tire_condition"]
        return DispatchDecision(
            finding=finding or "tire worn to limit / acute damage",
            dispatchable=bool(k["dispatchable"]),
            mel_item=str(k["mel_item"]),
            category=k["category"],
            interval_days=int(k["interval_days"]),
            provisions=str(k["provisions"]),
            ref=str(k["ref"]),
        )
    return DispatchDecision(
        finding=finding or "tire serviceable",
        dispatchable=True,
        mel_item="—",
        category=None,
        interval_days=None,
        provisions="Serviceable within AMM limits — no MEL item required.",
        ref="AMM 32-45",
    )


def system_dispatch(item_key: str) -> DispatchDecision:
    """Dispatch relief for a wheel/tire SYSTEM item (e.g. TPMS or wheel-speed sensor inoperative)."""
    mel = load_knowledge()["mel"]
    if item_key not in mel:
        raise KeyError(f"Unknown MEL item '{item_key}' (have: {sorted(mel)})")
    k = mel[item_key]
    return DispatchDecision(
        finding=item_key.replace("_", " "),
        dispatchable=bool(k["dispatchable"]),
        mel_item=str(k["mel_item"]),
        category=k.get("category"),
        interval_days=k.get("interval_days"),
        provisions=str(k["provisions"]),
        ref=str(k["ref"]),
    )
