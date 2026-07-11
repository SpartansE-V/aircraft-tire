"""Canonical SHA-256 identities for frozen calibration evidence models."""

import hashlib
import json

from pydantic import BaseModel


def canonical_artifact_bytes(artifact: BaseModel) -> bytes:
    """Serialize one frozen evidence model with a single canonical JSON encoding."""

    return json.dumps(
        artifact.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def artifact_sha256(artifact: BaseModel) -> str:
    """Hash one model's canonical JSON representation."""

    return hashlib.sha256(canonical_artifact_bytes(artifact)).hexdigest()
