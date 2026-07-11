"""Document-grounding tests: AMM provenance, MEL/CDL dispatch, defect-log extraction."""

from __future__ import annotations

import numpy as np

from app.tire_rul.grounding import (
    dispatch_for_wheel,
    extract_defect_log,
    grounded_thresholds,
    render_defect_log_line,
    system_dispatch,
)


def test_amm_thresholds_are_sourced(threshold_config):
    rows = grounded_thresholds(threshold_config)
    names = {r["threshold"] for r in rows}
    assert {"Wear limit", "Cold-pressure ladder", "Inspection interval", "Hard-removal criteria"} <= names
    # every threshold carries an AMM reference and the wear limit matches the manual value
    assert all(r["amm_ref"].startswith("AMM") for r in rows)
    assert next(r for r in rows if r["threshold"] == "Wear limit")["match"] is True


def test_amm_drift_is_detected(threshold_config):
    from dataclasses import replace

    drifted = replace(threshold_config, wear_limit_mm=1.5)  # below the AMM 2.0 mm limit
    rows = grounded_thresholds(drifted)
    assert next(r for r in rows if r["threshold"] == "Wear limit")["match"] is False


def test_mel_worn_tire_has_no_dispatch_relief():
    d = dispatch_for_wheel(True, "worn to limit")
    assert d.dispatchable is False and d.interval_days == 0


def test_mel_serviceable_tire_dispatchable():
    d = dispatch_for_wheel(False)
    assert d.dispatchable is True


def test_mel_system_item_has_category_and_interval():
    d = system_dispatch("tpms_inop")
    assert d.dispatchable is True and d.category == "C" and d.interval_days == 10


def test_defect_log_extraction_roundtrip():
    """Render a log line from known fields, then extract it back — fields must round-trip."""
    truth = {
        "date": "2024-11-03",
        "tail": "VN-A312",
        "position_code": "mlg_l_inbd",
        "serial": "MI30E388D8",
        "removal_reason": "worn_to_limit",
        "cycles": 287,
        "retread_level": 2,
    }
    # try all template variants (choice varies by rng draw)
    for seed in range(12):
        line = render_defect_log_line(**truth, rng=np.random.default_rng(seed))
        e = extract_defect_log(line)
        assert e["tail"] == truth["tail"], line
        assert e["position_code"] == truth["position_code"], line
        assert (e["serial"] or "").upper() == truth["serial"], line
        assert e["removal_reason"] == truth["removal_reason"], line
        assert e["cycles"] == truth["cycles"], line


def test_defect_log_position_normalization():
    for text, expected in [
        ("MLG L INBD", "mlg_l_inbd"),
        ("mlg r outbd", "mlg_r_outbd"),
        ("NLG L", "nlg_l"),
        ("main r inbd", "mlg_r_inbd"),
    ]:
        e = extract_defect_log(f"2024-01-01 VN-A300 {text} S/N MI123456 worn to limit 250 cyc")
        assert e["position_code"] == expected, text


def test_defect_log_damage_reasons():
    for text, expected in [("cut to cord", "cut"), ("sidewall bulge", "bulge"), ("FOD damage", "fod")]:
        e = extract_defect_log(f"2024-01-01 VN-A305 NLG R S/N GO999999 {text} 140 cyc")
        assert e["removal_reason"] == expected, text


def test_defect_log_missing_field_returns_none():
    e = extract_defect_log("free text with no structured tire data here")
    assert e["serial"] is None and e["position_code"] is None
