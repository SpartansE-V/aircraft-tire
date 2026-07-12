"""Public contracts for the tire-photo upload + vision-assessment endpoint."""

from typing import Literal

from pydantic import Field

from app.domain.schemas import StrictSchema

FindingKind = Literal["cut", "bulge", "fod"]
Severity = Literal["low", "med", "high"]
ConditionStatus = Literal["ok", "watch", "action"]
VlmBackend = Literal["mock", "openai", "claude", "bedrock"]


class TireImageUpload(StrictSchema):
    """Where the uploaded photo landed in object storage (from the AWS upload service)."""

    image_id: str | None = Field(default=None, description="Server-assigned upload id.")
    key: str = Field(description="S3 object key.")
    url: str | None = Field(
        default=None,
        description="Short-lived presigned GET URL for the stored image (expires; view-only).",
    )
    etag: str | None = Field(default=None, description="S3 ETag of the stored object.")


class TireImageFinding(StrictSchema):
    """One acute-damage observation from the vision model."""

    kind: FindingKind
    severity: Severity
    detail: str


class TireImageAssessment(StrictSchema):
    """The vision model's read on the photo. Informational — not a serviceability determination."""

    backend: VlmBackend = Field(description="Which vision backend produced this result.")
    degraded: bool = Field(
        default=False,
        description="True when the requested cloud VLM was unavailable and the heuristic ran.",
    )
    status: ConditionStatus = Field(description="Overall photo-derived condition signal.")
    headline: str = Field(description="One-line verdict for the status badge.")
    summary: str = Field(description="Engineer-facing condition summary from the model.")
    findings: list[TireImageFinding] = Field(
        default_factory=list, description="Acute-damage observations, if any."
    )


class TireImageAssessmentResponse(StrictSchema):
    """Combined result: where the photo was stored and what the vision model saw."""

    tire_id: str | None = Field(
        default=None, description="Wheel position this photo is for (e.g. L1)."
    )
    aircraft_id: str | None = Field(default=None, description="Aircraft registration/tail.")
    upload: TireImageUpload | None = Field(
        default=None, description="Storage metadata; null if the upload step could not complete."
    )
    assessment: TireImageAssessment
    assessed_at: str = Field(description="UTC ISO-8601 timestamp of the assessment.")
    disclaimer: str = Field(
        default=(
            "Automated photo screen only. Does not determine serviceability or replace physical "
            "inspection and approved maintenance data."
        )
    )
