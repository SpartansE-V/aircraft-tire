"""Roboflow hosted-model defect detection.

Thin wrapper around ``inference_sdk`` that mirrors the crack-detector service:
same api_url, confidence configuration, and prediction-extraction behaviour.
``inference_sdk`` is imported lazily so the rest of the pipeline (and the
projector unit tests) can be imported without it installed.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class Detection:
    """A single 2D detection in image-pixel coordinates (box centre + size)."""

    x: float
    y: float
    width: float
    height: float
    confidence: float
    class_name: str

    @property
    def x_min(self) -> float:
        return self.x - self.width / 2.0

    @property
    def x_max(self) -> float:
        return self.x + self.width / 2.0

    @property
    def y_min(self) -> float:
        return self.y - self.height / 2.0

    @property
    def y_max(self) -> float:
        return self.y + self.height / 2.0

    def contains(self, px: float, py: float) -> bool:
        """Whether a pixel coordinate falls inside this detection box."""
        return self.x_min <= px <= self.x_max and self.y_min <= py <= self.y_max


class DetectorError(RuntimeError):
    """Raised when inference cannot run (missing key/model or upstream failure)."""


class RoboflowDetector:
    def __init__(
        self,
        *,
        api_url: str,
        api_key: str,
        model_id: str,
        model_confidence_threshold: float,
        filter_confidence_threshold: float,
    ) -> None:
        if not api_key.strip():
            raise DetectorError("Roboflow API key is not configured.")
        if not model_id.strip():
            raise DetectorError("Roboflow model id is not configured.")

        try:
            from inference_sdk import InferenceConfiguration, InferenceHTTPClient
        except ImportError as exc:  # pragma: no cover - depends on optional dep
            raise DetectorError(
                "inference-sdk is not installed; add it to run detection."
            ) from exc

        from dataclasses import replace

        self._model_id = model_id
        self._filter_threshold = filter_confidence_threshold
        self._client = InferenceHTTPClient(api_url=api_url, api_key=api_key)
        self._client.configure(
            replace(
                InferenceConfiguration.init_default(),
                confidence_threshold=model_confidence_threshold,
            )
        )

    def detect(self, image_path: str) -> list[Detection]:
        try:
            raw_result = self._client.infer(image_path, model_id=self._model_id)
        except Exception as exc:  # noqa: BLE001 - surface any upstream failure uniformly
            raise DetectorError(f"Roboflow inference failed: {exc}") from exc
        return self._to_detections(_extract_predictions(raw_result))

    def _to_detections(self, predictions: list[dict[str, Any]]) -> list[Detection]:
        detections: list[Detection] = []
        for item in predictions:
            confidence = float(item.get("confidence", 0.0))
            if confidence < self._filter_threshold:
                continue
            detections.append(
                Detection(
                    x=float(item["x"]),
                    y=float(item["y"]),
                    width=float(item["width"]),
                    height=float(item["height"]),
                    confidence=confidence,
                    class_name=str(item.get("class", "defect")),
                )
            )
        return detections


def _extract_predictions(raw_result: Any) -> list[dict[str, Any]]:
    """Collect prediction dicts from Roboflow infer response shapes."""
    if isinstance(raw_result, Mapping):
        top_level = raw_result.get("predictions")
        if isinstance(top_level, list):
            return [dict(item) for item in top_level if isinstance(item, Mapping) and "class" in item]

    nested: list[dict[str, Any]] = []

    def visit(node: Any) -> None:
        if isinstance(node, Mapping):
            if isinstance(node.get("predictions"), list):
                for item in node["predictions"]:
                    if isinstance(item, Mapping) and "class" in item:
                        nested.append(dict(item))
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for item in node:
                visit(item)

    visit(raw_result)
    return nested
