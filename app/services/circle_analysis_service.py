"""Circle-scan crack analysis: overlay 2D annotations on the image and ask a VLM."""

from __future__ import annotations

import base64
import io
import json
import os
from typing import Any

from app.domain.schemas import (
    CircleAnalysisRequest,
    CircleAnalysisResponse,
    TireScanAnnotation2D,
)
from app.tire_rul.mock_tyres_assets import (
    fetch_s3_object,
    local_file,
    release_relative,
    s3_key_for,
)

CIRCLE_ANALYSIS_PROMPT = """You are an aircraft-tire inspection engineer.
The image is a circle scan of an aircraft tire. Red overlays mark detected cracks
from the vision model. Use the image AND the crack list below.
Respond with ONLY a JSON object:
{
  "condition": "SERVICEABLE" | "MONITOR" | "UNSERVICEABLE",
  "summary": "<2-3 short technical sentences on overall tire condition>",
  "crack_findings": ["<one short finding per crack>"],
  "action": "<one short recommended maintenance action>"
}
Be technical, concise, and simple. No markdown, no extra keys.

Detected annotations:
"""


class CircleAnalysisError(Exception):
    """Raised when the circle image cannot be loaded or the VLM call fails."""


def analyze_circle(request: CircleAnalysisRequest) -> CircleAnalysisResponse:
    image = _load_circle_image(request.image_url)
    annotated = _overlay_annotations(image, request.annotations)
    crack_anns = [a for a in request.annotations if a.category == "crack"]
    context = _annotation_context(request, crack_anns)

    backend = (request.backend or "auto").lower()
    if backend == "auto":
        backend = "openai" if os.environ.get("OPENAI_API_KEY") else "mock"

    if backend == "openai":
        result, backend_id = _analyze_openai(annotated, context)
    elif backend == "mock":
        result, backend_id = _analyze_mock(request, crack_anns)
    else:
        raise CircleAnalysisError(
            f"Unsupported backend '{request.backend}' (use auto | openai | mock)."
        )

    return CircleAnalysisResponse(
        condition=result["condition"],
        summary=result["summary"],
        crack_findings=result["crack_findings"],
        action=result["action"],
        crack_count=len(crack_anns),
        backend=backend_id,
        serial=request.serial,
        defect_label=request.defect_label,
    )


def _load_circle_image(image_url: str):
    from PIL import Image

    if not image_url.startswith("/assets/mock-tyres/"):
        raise CircleAnalysisError("image_url must be a /assets/mock-tyres/ path.")

    rel = release_relative(image_url.removeprefix("/assets/mock-tyres/"))
    path = local_file(rel)
    if path is not None:
        return Image.open(path).convert("RGB")

    key = s3_key_for(rel)
    if key:
        fetched = fetch_s3_object(key)
        if fetched:
            body, _ = fetched
            return Image.open(io.BytesIO(body)).convert("RGB")

    raise CircleAnalysisError(f"Circle image not found: {image_url}")


def _overlay_annotations(image, annotations: list[TireScanAnnotation2D]):
    from PIL import ImageDraw

    out = image.copy()
    draw = ImageDraw.Draw(out, "RGBA")
    for ann in annotations:
        if ann.category != "crack":
            continue
        color = (239, 68, 68, 200)
        fill = (239, 68, 68, 55)
        drew = False
        for ring in ann.segmentation:
            if len(ring) < 6:
                continue
            pts = [(ring[i], ring[i + 1]) for i in range(0, len(ring) - 1, 2)]
            if len(pts) >= 3:
                draw.polygon(pts, outline=color, fill=fill)
                drew = True
        if not drew and len(ann.bbox) >= 4:
            x, y, w, h = ann.bbox
            draw.rectangle([x, y, x + w, y + h], outline=color, width=3)
        if ann.defect_label and len(ann.bbox) >= 4:
            x, y, _, _ = ann.bbox
            draw.text((x, max(0, y - 12)), ann.defect_label, fill=color)
    return out


def _annotation_context(
    request: CircleAnalysisRequest, cracks: list[TireScanAnnotation2D]
) -> str:
    lines = [
        f"serial={request.serial or '—'}",
        f"model_type={request.model_type or '—'}",
        f"scan_status={request.scan_status or '—'}",
        f"tread_depths={request.tread_depths or []}",
        f"focus_defect={request.defect_label or 'all'}",
        f"crack_count={len(cracks)}",
    ]
    for i, ann in enumerate(cracks, 1):
        bx = ann.bbox
        cx = ann.center.get("x", 0)
        cy = ann.center.get("y", 0)
        label = ann.defect_label or "crack"
        lines.append(
            f"  {i}. {label} bbox=[{bx[0]:.0f},{bx[1]:.0f},{bx[2]:.0f},{bx[3]:.0f}] "
            f"center=({cx:.0f},{cy:.0f})"
        )
    return "\n".join(lines)


def _image_b64_png(image) -> str:
    buf = io.BytesIO()
    image.convert("RGB").save(buf, format="PNG")
    return base64.standard_b64encode(buf.getvalue()).decode()


def _parse_analysis_json(text: str) -> dict[str, Any]:
    snippet = text[text.find("{") : text.rfind("}") + 1] if "{" in text else text
    data = json.loads(snippet)
    condition = str(data.get("condition", "MONITOR")).upper()
    if condition not in ("SERVICEABLE", "MONITOR", "UNSERVICEABLE"):
        condition = "MONITOR"
    findings = data.get("crack_findings") or []
    if not isinstance(findings, list):
        findings = [str(findings)]
    return {
        "condition": condition,
        "summary": str(data.get("summary", "")).strip() or "No summary returned.",
        "crack_findings": [str(f).strip() for f in findings if str(f).strip()],
        "action": str(data.get("action", "")).strip() or "Inspect per AMM.",
    }


def _analyze_openai(image, context: str) -> tuple[dict[str, Any], str]:
    try:
        import openai
    except ImportError as exc:
        raise CircleAnalysisError("OpenAI SDK not installed (pip install openai).") from exc
    if not os.environ.get("OPENAI_API_KEY"):
        raise CircleAnalysisError("OPENAI_API_KEY is not set.")

    model = os.environ.get("OPENAI_VLM_MODEL", "gpt-4o-mini")
    client = openai.OpenAI()
    try:
        resp = client.chat.completions.create(
            model=model,
            max_tokens=350,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": CIRCLE_ANALYSIS_PROMPT + context},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{_image_b64_png(image)}"
                            },
                        },
                    ],
                }
            ],
        )
    except Exception as exc:
        raise CircleAnalysisError(f"OpenAI VLM call failed: {exc}") from exc
    raw = resp.choices[0].message.content or "{}"
    try:
        return _parse_analysis_json(raw), f"openai:{model}"
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise CircleAnalysisError(f"OpenAI returned invalid JSON: {exc}") from exc


def _analyze_mock(
    request: CircleAnalysisRequest, cracks: list[TireScanAnnotation2D]
) -> tuple[dict[str, Any], str]:
    n = len(cracks)
    if n == 0:
        return (
            {
                "condition": "SERVICEABLE",
                "summary": (
                    "Circle scan shows no crack overlays. "
                    "Tread appearance is within normal visual limits."
                ),
                "crack_findings": [],
                "action": "Continue scheduled inspection interval.",
            },
            "mock",
        )

    labels = [a.defect_label or f"crack-{i}" for i, a in enumerate(cracks, 1)]
    findings = [
        (
            f"{lab}: linear crack overlay on circle scan — "
            "treat as structural damage until AMM check clears."
        )
        for lab in labels
    ]
    focus = request.defect_label
    if focus and focus in labels:
        summary = (
            f"Focused crack {focus} plus {n - 1} other crack(s) on circle scan. "
            "Acute sidewall/tread crack indication — not normal wear."
        )
    else:
        summary = (
            f"{n} crack annotation(s) on circle scan ({', '.join(labels)}). "
            "Structural damage signature — removal criteria likely apply."
        )
    return (
        {
            "condition": "UNSERVICEABLE",
            "summary": summary,
            "crack_findings": findings,
            "action": (
                "Remove tire; verify crack depth/length vs AMM limits "
                "before return to service."
            ),
        },
        "mock",
    )
