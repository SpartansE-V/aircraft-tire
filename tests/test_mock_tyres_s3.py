"""Tests for mock-tyre S3 manifest resolution."""

from __future__ import annotations

from app.tire_rul.mock_tyres_assets import (
    clear_manifest_cache,
    local_file,
    load_manifest,
    s3_key_for,
    upload_bucket,
)


def test_manifest_maps_release_paths_to_upload_keys():
    clear_manifest_cache()
    manifest = load_manifest()
    assert manifest.get("objects"), "run scripts/sync_mock_tyres_s3.py first"
    assert s3_key_for("circle.png").startswith("uploads/")
    assert s3_key_for("1h233b/flatten-left.png").endswith("flatten-left.png")
    assert upload_bucket() == manifest["bucket"]
    assert local_file("circle.png") is not None
