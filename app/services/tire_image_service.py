"""Upload a tire photo to object storage and screen it with the vision model.

The browser cannot call the AWS upload endpoint directly (it returns no CORS headers), so this
service runs server-side: it forwards the bytes to the S3-backed upload API for persistence and
runs the VLM on the same bytes. Both steps are resilient — a failed upload still returns the
assessment, and a failed cloud VLM falls back to the offline heuristic — so a single request always
yields a usable result. Heavy imports (Pillow, the CV package) are deferred to call time so the
module import stays cheap and the app boots even without the optional AI stack installed.
"""

from __future__ import annotations

import io
import logging
from datetime import UTC, datetime

import httpx

from app.config import UploadsSettings
from app.domain.tire_image_schemas import (
    ConditionStatus,
    Severity,
    TireImageAssessment,
    TireImageAssessmentResponse,
    TireImageFinding,
    TireImageUpload,
    VlmBackend,
)

logger = logging.getLogger("wear_severity_api.tire_image")

# Human labels + logistics severity for the vision model's acute-damage codes.
_FINDING_META: dict[str, tuple[Severity, str]] = {
    "cut": ("high", "Cut through tread/sidewall rubber — remove per AMM, not a wear replacement."),
    "bulge": ("high", "Sidewall bulge — carcass separation suspected; remove immediately."),
    "fod": (
        "med",
        "Foreign object / debris lodged in tread — extract and inspect the groove base.",
    ),
}

_BACKEND_LABEL: dict[str, VlmBackend] = {
    "MockVlm": "mock",
    "OpenAiVlm": "openai",
    "ClaudeVlm": "claude",
    "BedrockVlm": "bedrock",
}


class InvalidImageError(ValueError):
    """The uploaded bytes are not a decodable image."""


def assess_tire_image(
    *,
    image_bytes: bytes,
    filename: str,
    content_type: str | None,
    tire_id: str | None,
    aircraft_id: str | None,
    backend: str | None,
    settings: UploadsSettings,
) -> TireImageAssessmentResponse:
    """Persist the photo (best-effort) and return its vision assessment. Runs in a worker thread."""

    image = _open_image(image_bytes)

    upload = _upload_to_storage(
        image_bytes=image_bytes,
        filename=filename,
        content_type=content_type,
        aircraft_id=aircraft_id or tire_id,
        settings=settings,
    )

    requested = backend or settings.vlm_backend or "auto"
    assessment = _run_vlm(image, requested)

    return TireImageAssessmentResponse(
        tire_id=tire_id,
        aircraft_id=aircraft_id,
        upload=upload,
        assessment=assessment,
        assessed_at=datetime.now(UTC).isoformat(),
    )


def _open_image(image_bytes: bytes):  # type: ignore[no-untyped-def]
    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover - AI stack always present in the served image
        raise RuntimeError(
            "Image assessment needs Pillow (install the 'ai' extra: uv sync --extra ai)."
        ) from exc

    try:
        image = Image.open(io.BytesIO(image_bytes))
        image.load()
    except Exception as exc:
        raise InvalidImageError("The uploaded file is not a readable image.") from exc
    return image.convert("RGB")


def _upload_to_storage(
    *,
    image_bytes: bytes,
    filename: str,
    content_type: str | None,
    aircraft_id: str | None,
    settings: UploadsSettings,
) -> TireImageUpload | None:
    """Forward the bytes to the AWS direct-upload endpoint. Best-effort: None on any failure."""

    files = {"file": (filename, image_bytes, content_type or "application/octet-stream")}
    data = {"aircraftId": aircraft_id} if aircraft_id else {}
    try:
        with httpx.Client(timeout=settings.request_timeout_seconds) as client:
            response = client.post(settings.direct_url, files=files, data=data)
            response.raise_for_status()
            body = response.json()
        return TireImageUpload(
            image_id=body.get("imageId"),
            key=body["key"],
            url=body.get("presignedUrl"),
            etag=(body.get("etag") or "").strip('"') or None,
        )
    except Exception as exc:
        logger.warning("Tire photo upload to storage failed: %s", exc)
        return None


def _run_vlm(image, requested: str) -> TireImageAssessment:  # type: ignore[no-untyped-def]
    """Run the vision model, falling back to the offline heuristic if the cloud backend fails."""

    from app.tire_rul.cv import MockVlm, get_vlm

    degraded = False
    label: VlmBackend = "mock"
    try:
        vlm = get_vlm(requested)
        result = vlm.analyze(image)
        label = _BACKEND_LABEL.get(type(vlm).__name__, "mock")
    except Exception as exc:
        logger.warning("VLM backend %r failed (%s); using offline heuristic.", requested, exc)
        result = MockVlm().analyze(image)
        label = "mock"
        degraded = requested not in ("mock", "auto")

    damage = [d for d in result.get("damage", []) if d in _FINDING_META]
    findings = [
        TireImageFinding(kind=d, severity=_FINDING_META[d][0], detail=_FINDING_META[d][1])
        for d in damage
    ]
    status: ConditionStatus = "action" if findings else "ok"
    headline = "Acute damage detected — remove per AMM" if findings else "No acute damage detected"
    return TireImageAssessment(
        backend=label,
        degraded=degraded,
        status=status,
        headline=headline,
        summary=str(result.get("report", "")),
        findings=findings,
    )
