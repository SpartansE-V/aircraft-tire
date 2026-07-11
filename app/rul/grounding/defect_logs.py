"""Free-text defect-log extraction.

Mines historical free-text removal/defect log lines into the structured tire schema — the
"leverage underused inspection records" wedge. Rule-based/regex here (deterministic, no API); for
messier real logs a VLM/LLM extractor plugs in behind the same ``extract_defect_log`` signature.
The join key that binds a log line to a tire is the **serial** (+ tail + position).
"""

from __future__ import annotations

import re

import numpy as np

# text alias -> canonical position code (longest aliases match first)
POSITION_ALIASES = {
    "mlg l inbd": "mlg_l_inbd",
    "mlg l outbd": "mlg_l_outbd",
    "mlg r inbd": "mlg_r_inbd",
    "mlg r outbd": "mlg_r_outbd",
    "main l inbd": "mlg_l_inbd",
    "main l outbd": "mlg_l_outbd",
    "main r inbd": "mlg_r_inbd",
    "main r outbd": "mlg_r_outbd",
    "l inbd": "mlg_l_inbd",
    "l outbd": "mlg_l_outbd",
    "r inbd": "mlg_r_inbd",
    "r outbd": "mlg_r_outbd",
    "nlg l": "nlg_l",
    "nlg r": "nlg_r",
    "nose l": "nlg_l",
    "nose r": "nlg_r",
}
_ALIASES_SORTED = sorted(POSITION_ALIASES, key=len, reverse=True)

_POS_DISPLAY = {
    "nlg_l": "NLG L",
    "nlg_r": "NLG R",
    "mlg_l_inbd": "MLG L INBD",
    "mlg_l_outbd": "MLG L OUTBD",
    "mlg_r_inbd": "MLG R INBD",
    "mlg_r_outbd": "MLG R OUTBD",
}

_REASON_MATCH = [
    (("worn", "wear to limit", "tread limit", "tread worn"), "worn_to_limit"),
    (("cord", "cut"), "cut"),
    (("bulge", "separation"), "bulge"),
    (("fod", "foreign object", "debris"), "fod"),
]
_REASON_RENDER = {
    "worn_to_limit": ["WORN TO LIMIT", "worn to limit", "tread worn to limit", "WORN OUT TO LIMIT"],
    "cut": ["CUT TO CORD", "cut - cord exposed", "CORD EXPOSED CUT", "cut to cord"],
    "bulge": ["SIDEWALL BULGE", "bulge separation", "BULGE - SEPARATION", "sidewall bulge"],
    "fod": ["FOD DAMAGE", "foreign object damage", "FOD DAMAGE FOUND", "fod - debris"],
}


def _normalize(line: str) -> str:
    norm = re.sub(r"[^a-z0-9/\-\s]", " ", line.lower())
    return re.sub(r"\s+", " ", norm).strip()


def _match_position(norm: str) -> str | None:
    for alias in _ALIASES_SORTED:
        if alias in norm:
            return POSITION_ALIASES[alias]
    return None


def _match_reason(norm: str) -> str | None:
    for keywords, reason in _REASON_MATCH:
        if any(k in norm for k in keywords):
            return reason
    return None


def extract_defect_log(line: str) -> dict:
    """Parse a free-text defect-log line into structured fields (None where not found)."""
    norm = _normalize(line)
    m_date = re.search(r"\d{4}-\d{2}-\d{2}", line)
    m_tail = re.search(r"vn[-\s]?a?\s?(\d{3})", norm)
    m_ser = re.search(r"s\s?/?\s?n[:\s]*([a-z0-9]{6,})", norm)
    m_cyc = re.search(r"(\d{2,4})\s*c(?:yc(?:les)?)?\b", norm)
    m_rr = re.search(r"\br(\d)\b", norm)
    return {
        "date": m_date.group(0) if m_date else None,
        "tail": f"VN-A{m_tail.group(1)}" if m_tail else None,
        "position_code": _match_position(norm),
        "serial": m_ser.group(1).upper() if m_ser else None,
        "removal_reason": _match_reason(norm),
        "cycles": int(m_cyc.group(1)) if m_cyc else None,
        "retread_level": int(m_rr.group(1)) if m_rr else None,
        "raw": line,
    }


def render_defect_log_line(
    *,
    date: str,
    tail: str,
    position_code: str,
    serial: str,
    removal_reason: str,
    cycles: int,
    retread_level: int,
    rng: np.random.Generator,
) -> str:
    """Render a realistic, noisy free-text log line from structured fields (for the extraction demo)."""
    pos_u = _POS_DISPLAY[position_code]
    pos_l = pos_u.lower()
    reason = str(rng.choice(_REASON_RENDER[removal_reason]))
    serial_u, serial_l = serial.upper(), serial.lower()
    pn = "H46X18"
    templates = [
        f"{date} A/C {tail} WHEEL POS {pos_u} TIRE P/N {pn} S/N {serial_u} RMVD {reason.upper()} AT {cycles} CYC",
        f"{date} {tail} {pos_l} tyre s/n {serial_l} removed - {reason.lower()} {cycles} cycles",
        f"{date} tail {tail} {pos_u} TIRE S/N {serial_u} REMOVED, {reason.lower()}, {cycles} cyc, retread R{retread_level}",
        f"{date} {tail} pos {pos_u} sn {serial_u} off-wing {reason.lower()} @ {cycles}c R{retread_level}",
    ]
    return str(rng.choice(templates))
