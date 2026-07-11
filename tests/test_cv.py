"""CV layer tests: the Depth model recovers encoded tread depth, damage detection is exact,
and assess_tire integrates OCR + Depth + VLM into a TireScan."""

from __future__ import annotations

import numpy as np
import pytest

from app.tire_rul.cv import (
    assess_tire,
    detect_damage,
    estimate_tread_depth,
    get_vlm,
    render_tire_image,
)


@pytest.mark.parametrize("true_depth", [2.5, 4.0, 6.0, 8.0, 10.0, 12.0])
def test_depth_model_recovers_encoded_depth(true_depth):
    img = render_tire_image(true_depth, new_tread_mm=13.0, serial="MI-TEST", seed=int(true_depth * 13))
    est, conf = estimate_tread_depth(img, new_tread_mm=13.0)
    assert abs(est - true_depth) < 1.0  # recovered within 1 mm of the encoded depth
    assert 0.5 <= conf <= 1.0


def test_depth_recovery_mean_error_small():
    errs = []
    for d in np.linspace(2.5, 12.5, 12):
        img = render_tire_image(float(d), new_tread_mm=13.0, seed=int(d * 31))
        est, _ = estimate_tread_depth(img, new_tread_mm=13.0)
        errs.append(abs(est - d))
    assert np.mean(errs) < 0.6  # mean absolute recovery error


@pytest.mark.parametrize("damage", [[], ["cut"], ["bulge"], ["fod"], ["cut", "fod"]])
def test_damage_detection_matches_injected(damage):
    img = render_tire_image(6.0, damage=damage, serial="BR-9", seed=5)
    assert set(detect_damage(img)) == set(damage)


def test_clean_tire_has_no_false_damage():
    for seed in range(6):
        img = render_tire_image(7.0, damage=[], serial="GY-1", seed=seed)
        assert detect_damage(img) == []


def test_assess_tire_full_scan():
    img = render_tire_image(5.2, new_tread_mm=13.0, damage=["cut"], serial="GY-7F3A", seed=11)
    scan = assess_tire(img, new_tread_mm=13.0)
    assert scan.serial == "GY-7F3A" and scan.serial_confidence > 0.9
    assert abs(scan.tread_depth_mm - 5.2) < 1.0
    assert scan.damage_findings == ["cut"]
    assert "cut" in scan.condition_report.lower()
    assert 0.0 < scan.scan_confidence <= 1.0


def test_mock_vlm_report_distinguishes_wear_from_damage():
    clean = get_vlm("mock").analyze(render_tire_image(9.0, serial="X", seed=1))
    damaged = get_vlm("mock").analyze(render_tire_image(9.0, damage=["bulge"], serial="X", seed=1))
    assert clean["damage"] == [] and "within normal limits" in clean["report"]
    assert damaged["damage"] == ["bulge"] and "acute" in damaged["report"].lower()


def test_read_serial_via_ocr():
    from app.tire_rul.cv.assess import read_serial

    img = render_tire_image(6.0, serial="MI-ABC123", seed=2)
    serial, conf = read_serial(img)
    assert serial == "MI-ABC123" and conf > 0.9


# ---------------------------------------------------------------------------
# VLM backends (mock / OpenAI / Claude) — no API key required for these
# ---------------------------------------------------------------------------
def test_get_vlm_openai_backend():
    from app.tire_rul.cv import OpenAiVlm

    v = get_vlm("openai")
    assert isinstance(v, OpenAiVlm)
    assert v.model == "gpt-4o-mini"  # default


def test_openai_model_env_override(monkeypatch):
    from app.tire_rul.cv import OpenAiVlm

    monkeypatch.setenv("OPENAI_VLM_MODEL", "gpt-4o")
    assert OpenAiVlm().model == "gpt-4o"


def test_get_vlm_auto_falls_back_to_mock(monkeypatch):
    from app.tire_rul.cv import MockVlm, assess

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(assess, "_aws_credentials_present", lambda: False)
    assert isinstance(get_vlm("auto"), MockVlm)


def test_get_vlm_unknown_raises():
    with pytest.raises(ValueError):
        get_vlm("gemini")


def test_openai_vlm_requires_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        get_vlm("openai").analyze(render_tire_image(6.0, serial="X", seed=1))


def test_vlm_available(monkeypatch):
    from app.tire_rul.cv import vlm_available

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert vlm_available("mock") is True
    assert vlm_available("openai") is False
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert vlm_available("openai") is True  # openai SDK is installed + key present


def test_parse_vlm_json_filters_invalid_damage():
    from app.tire_rul.cv.assess import _parse_vlm_json

    out = _parse_vlm_json('prefix {"damage": ["cut", "banana", "fod"], "report": "r"} suffix')
    assert out["damage"] == ["cut", "fod"] and out["report"] == "r"


# ---------------------------------------------------------------------------
# Bedrock backend
# ---------------------------------------------------------------------------
def test_get_vlm_bedrock_backend(monkeypatch):
    from app.tire_rul.cv import BedrockVlm

    monkeypatch.delenv("AWS_REGION", raising=False)
    monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
    v = get_vlm("bedrock")
    assert isinstance(v, BedrockVlm)
    assert v.model == "anthropic.claude-opus-4-8"  # Bedrock IDs carry the anthropic. prefix
    assert v.region == "us-east-1"


def test_bedrock_model_and_region_env_override(monkeypatch):
    from app.tire_rul.cv import BedrockVlm

    monkeypatch.setenv("BEDROCK_VLM_MODEL", "anthropic.claude-haiku-4-5")
    monkeypatch.setenv("AWS_REGION", "ap-southeast-1")
    v = BedrockVlm()
    assert v.model == "anthropic.claude-haiku-4-5"
    assert v.region == "ap-southeast-1"


def test_bedrock_vlm_requires_credentials(monkeypatch):
    from app.tire_rul.cv import assess

    monkeypatch.setattr(assess, "_aws_credentials_present", lambda: False)
    with pytest.raises(RuntimeError, match="AWS credentials"):
        assess.BedrockVlm().analyze(render_tire_image(6.0, serial="X", seed=1))


def test_vlm_available_bedrock(monkeypatch):
    from app.tire_rul.cv import assess, vlm_available

    monkeypatch.setattr(assess, "_aws_credentials_present", lambda: True)
    assert vlm_available("bedrock") is True  # anthropic SDK installed + creds present
    monkeypatch.setattr(assess, "_aws_credentials_present", lambda: False)
    assert vlm_available("bedrock") is False
