"""Tests for tread-status equation and circle/flatten crack → 3D conversion."""

from __future__ import annotations

import math

from app.tire_rul.scan_annotations import (
    SCAN_GROUPS,
    TREAD_COUNT,
    crack_from_circle,
    crack_from_flatten,
    extract_cracks,
    status_from_treads_and_cracks,
    write_group_annotations,
)
from app.tire_rul.scan_annotations import MOCK_TYRES_DIR


def test_status_equation():
    assert status_from_treads_and_cracks(["5-6mm", "4-5mm", "5-6mm", "4-5mm"], has_cracks=False) == "healthy"
    assert status_from_treads_and_cracks(["5-6mm", "3-4mm", "5-6mm", "4-5mm"], has_cracks=False) == "warning"
    assert status_from_treads_and_cracks(["5-6mm", "2-3mm", "5-6mm", "4-5mm"], has_cracks=False) == "error"
    assert status_from_treads_and_cracks(["5-6mm", "4-5mm"], has_cracks=True) == "error"
    # Cracks win over otherwise-healthy treads.
    assert status_from_treads_and_cracks(["5-6mm", "5-6mm"], has_cracks=True) == "error"
    # Worn band wins even without cracks.
    assert status_from_treads_and_cracks(["1-2mm", "5-6mm"], has_cracks=False) == "error"


def test_tread_counts():
    assert TREAD_COUNT["radial"] == 6
    assert TREAD_COUNT["type_vii"] == 4
    assert TREAD_COUNT["type_iii"] == 4


def test_circle_crack_uses_wheel_radius_and_lateral_pct():
    # Wheel centred at origin-ish; crack to the right of centre-line → +lateral_pct.
    ann = {"id": 1, "category": "crack", "center": {"x": 700.0, "y": 500.0, "width": 40, "height": 40}}
    d = crack_from_circle(ann, wheel_cx=500.0, wheel_cy=500.0, radius=200.0)
    assert d["wave"] is True
    assert d["category"] == "crack"
    assert d["lateral_pct"] == 100.0  # (700-500)/200 * 100
    assert abs(d["angle_rad"] - math.atan2(200.0, 0.0)) < 1e-6
    assert len(d["at"]) == 3 and d["r"] > 0


def test_flatten_crack_uses_perimeter():
    ann = {"id": 2, "category": "crack", "center": {"x": 1050.0, "y": 110.0, "width": 50, "height": 20}}
    d = crack_from_flatten(ann, width=2100.0, height=220.0, side="left")
    assert abs(d["angle_rad"] - math.pi) < 1e-6  # halfway around
    assert d["source"] == "flatten-left"
    assert d["wave"] is True


def test_extract_and_write_all_groups():
    for group_id in SCAN_GROUPS:
        left = extract_cracks(group_id, "left")
        right = extract_cracks(group_id, "right")
        assert left, f"{group_id} left should include circle cracks"
        assert all(d["category"] == "crack" for d in left)
        assert all(d["category"] == "crack" for d in right)
        packs = write_group_annotations(group_id)
        assert (MOCK_TYRES_DIR / group_id / "annotations_3d.json").exists()
        assert "left" in packs and "right" in packs


def test_healthy_and_warning_tires_use_shared_good_circle():
    from app.tire_rul.scan_annotations import HEALTHY_CIRCLE_URL, images_for

    for status in ("healthy", "warning"):
        imgs = images_for("1h233b", scan_status=status)  # type: ignore[arg-type]
        assert imgs["circle"]["url"] == HEALTHY_CIRCLE_URL
        assert imgs["circle"]["annotations"] == []
        assert imgs["flatten"]["url"].endswith("flatten-right.png")
        assert imgs["flatten"]["annotations"] == []

    damaged = images_for("1h233b", scan_status="error")
    assert damaged["circle"]["url"] == "/assets/mock-tyres/release/1h233b/circle.png"
    assert damaged["flatten"]["url"].endswith("flatten-left.png")
    assert any(a["category"] == "crack" for a in damaged["circle"]["annotations"])
    assert all(a["label"] is None for a in damaged["circle"]["annotations"] if a["category"] == "crack")
    assert any(a["category"] == "crack" for a in damaged["flatten"]["annotations"])


def test_2d_annotations_omit_wheel_and_healthy_tread():
    from app.tire_rul.scan_annotations import images_for

    imgs = images_for("1h233b", scan_status="error")
    cats = {a["category"] for a in imgs["circle"]["annotations"]}
    assert "wheel" not in cats
    assert "tread" not in cats
    assert "crack" in cats

    flat_cats = {a["category"] for a in imgs["flatten"]["annotations"]}
    assert "tread" not in flat_cats
    assert "wheel" not in flat_cats
    for a in imgs["flatten"]["annotations"]:
        if a["category"] == "tread-shallow":
            assert a["label"] == "shallow"
        if a["category"] == "crack":
            assert a["label"] is None

    warn = images_for("1h233b", scan_status="warning")
    assert warn["flatten"]["url"].endswith("flatten-right.png")
    assert warn["flatten"]["annotations"] == []
    assert warn["circle"]["annotations"] == []

    healthy = images_for("8fh20v", scan_status="healthy")
    assert healthy["flatten"]["url"].endswith("flatten-right.png")
    assert healthy["flatten"]["annotations"] == []
    assert healthy["circle"]["annotations"] == []
