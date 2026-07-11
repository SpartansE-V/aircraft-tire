"""Roboflow InferenceHTTPClient wrapper for hosted-model inference."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from inference_sdk import InferenceConfiguration, InferenceHTTPClient

from app.config import RoboflowModelSettings


class RoboflowManager:
    """Run Roboflow hosted-model inference and normalize prediction payloads."""

    def __init__(
        self,
        *,
        api_url: str,
        api_key: str,
        model_settings: RoboflowModelSettings,
    ) -> None:
        self._api_key = api_key
        self._model_settings = model_settings
        self._client = InferenceHTTPClient(
            api_url=api_url,
            api_key=api_key,
        )
        self._client.configure(
            replace(
                InferenceConfiguration.init_default(),
                confidence_threshold=model_settings.model_confidence_threshold,
            )
        )

    def infer(self, image_source: str) -> list[dict[str, Any]]:
        """Run the configured YOLO model against a local path or public image URL."""

        if not self._api_key:
            raise ValueError("Roboflow API key is not configured.")
        if not self._model_settings.model_id:
            raise ValueError("Roboflow model_id is not configured.")

        raw_result = self._client.infer(
            image_source,
            model_id=self._model_settings.model_id,
        )
        predictions = self._extract_predictions(raw_result)
        return self._filter_predictions(predictions)

    def _filter_predictions(self, predictions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        threshold = self._model_settings.filter_confidence_threshold
        return [
            prediction
            for prediction in predictions
            if float(prediction.get("confidence", 0)) >= threshold
        ]

    @staticmethod
    def _extract_predictions(raw_result: Any) -> list[dict[str, Any]]:
        """Collect prediction dicts from Roboflow infer response shapes."""

        if isinstance(raw_result, Mapping):
            top_level = raw_result.get("predictions")
            if isinstance(top_level, list):
                return [
                    dict(item)
                    for item in top_level
                    if isinstance(item, Mapping) and "class" in item
                ]

        nested_predictions: list[dict[str, Any]] = []

        def visit(node: Any) -> None:
            if isinstance(node, Mapping):
                if "predictions" in node and isinstance(node["predictions"], list):
                    for item in node["predictions"]:
                        if isinstance(item, Mapping) and "class" in item:
                            nested_predictions.append(dict(item))
                for value in node.values():
                    visit(value)
            elif isinstance(node, list):
                for item in node:
                    visit(item)

        visit(raw_result)
        return nested_predictions
