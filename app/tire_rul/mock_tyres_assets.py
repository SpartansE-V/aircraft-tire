"""Resolve mock-tyre image bytes: local files first, then S3 via sync manifest."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
RELEASE_DIR = REPO_ROOT / "assets" / "mock-tyres" / "release"
MANIFEST_CANDIDATES = (
    Path(__file__).resolve().parent / "config" / "mock_tyres_s3_manifest.json",
    RELEASE_DIR / "s3-manifest.json",
)


@lru_cache(maxsize=1)
def load_manifest() -> dict[str, Any]:
    for path in MANIFEST_CANDIDATES:
        if path.is_file():
            import json

            return json.loads(path.read_text(encoding="utf-8"))
    return {}


def clear_manifest_cache() -> None:
    load_manifest.cache_clear()


def release_relative(path: str) -> str:
    """Normalize URL path under /assets/mock-tyres/ to a release-relative key."""
    cleaned = path.lstrip("/")
    for prefix in ("assets/mock-tyres/release/", "release/"):
        if cleaned.startswith(prefix):
            return cleaned[len(prefix) :]
    return cleaned


def local_file(release_rel: str) -> Path | None:
    candidate = RELEASE_DIR / release_rel
    if candidate.is_file():
        return candidate
    return None


def s3_key_for(release_rel: str) -> str | None:
    objects = load_manifest().get("objects") or {}
    entry = objects.get(release_rel)
    if not isinstance(entry, dict):
        return None
    key = entry.get("key")
    return key if isinstance(key, str) and key else None


def upload_bucket() -> str | None:
    env = os.environ.get("UPLOAD_BUCKET", "").strip()
    if env:
        return env
    bucket = load_manifest().get("bucket")
    return bucket if isinstance(bucket, str) and bucket else None


def fetch_s3_object(key: str) -> tuple[bytes, str] | None:
    """Return (body, content_type) for a private upload object, or None on failure."""
    bucket = upload_bucket()
    if not bucket:
        return None
    try:
        import boto3
    except ImportError:
        return None
    try:
        client = boto3.client("s3")
        obj = client.get_object(Bucket=bucket, Key=key)
        body = obj["Body"].read()
        content_type = obj.get("ContentType") or "image/png"
        return body, str(content_type)
    except Exception:
        return None


def presigned_get_url(key: str, *, expires_in: int = 900) -> str | None:
    bucket = upload_bucket()
    if not bucket:
        return None
    try:
        import boto3
    except ImportError:
        return None
    try:
        client = boto3.client("s3")
        return client.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=expires_in,
        )
    except Exception:
        return None
