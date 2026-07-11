"""Roboflow inference HTTP API tests."""

from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from app.config import RoboflowModelSettings, RoboflowSettings
from app.integrations.roboflow.controller import ImageInputError, TreadDepthController
from app.integrations.roboflow.manager import RoboflowManager


@pytest.fixture
def tyre_quality_predictions() -> list[dict[str, Any]]:
    return [
        {
            "x": 321,
            "y": 273,
            "width": 622,
            "height": 472,
            "confidence": 0.824,
            "class": "bad_tyre",
            "class_id": 0,
            "detection_id": "ea4dce18-94eb-4c4a-a358-4bb8b860d0fb",
        }
    ]


@pytest.fixture
def tread_depth_predictions() -> list[dict[str, Any]]:
    return [
        {
            "x": 2019,
            "y": 1285.5,
            "width": 4026,
            "height": 397,
            "confidence": 0.832,
            "class": "7-8 mm",
            "class_id": 6,
            "detection_id": "0d34376c-a32b-4811-9bd9-9b0c68937207",
        },
        {
            "x": 2017,
            "y": 729,
            "width": 4026,
            "height": 518,
            "confidence": 0.55,
            "class": "7-8 mm",
            "class_id": 6,
            "detection_id": "b100d76d-0d93-4de9-a7eb-e08a660da31a",
        },
    ]


@pytest.fixture
def mock_tyre_quality_controller(
    tyre_quality_predictions: list[dict[str, Any]],
) -> Generator[MagicMock, None, None]:
    controller = MagicMock()
    controller.detect = AsyncMock(return_value=tyre_quality_predictions)

    with patch(
        "app.api.routes.crack_detector._get_controller",
        return_value=controller,
    ):
        yield controller


@pytest.fixture
def mock_tread_depth_controller(
    tread_depth_predictions: list[dict[str, Any]],
) -> Generator[MagicMock, None, None]:
    controller = MagicMock(spec=TreadDepthController)
    controller.detect = AsyncMock(return_value=tread_depth_predictions)

    with patch(
        "app.api.routes.tread_depth._get_controller",
        return_value=controller,
    ):
        yield controller


@pytest.mark.asyncio
async def test_tyre_quality_detect_with_image_upload(
    client: AsyncClient,
    mock_tyre_quality_controller: MagicMock,
    tyre_quality_predictions: list[dict[str, Any]],
) -> None:
    files = {"image": ("tyre.jpg", b"fake-image-bytes", "image/jpeg")}
    response = await client.post("/api/v1/crack-detector/detect", files=files)

    assert response.status_code == 200
    assert response.json() == {"predictions": tyre_quality_predictions}
    mock_tyre_quality_controller.detect.assert_called_once()


@pytest.mark.asyncio
async def test_tread_depth_detect_with_image_url(
    client: AsyncClient,
    mock_tread_depth_controller: MagicMock,
    tread_depth_predictions: list[dict[str, Any]],
) -> None:
    response = await client.post(
        "/api/v1/tread-depth/detect",
        data={"image_url": "https://example.com/tyre.jpg"},
    )

    assert response.status_code == 200
    assert response.json() == {"predictions": tread_depth_predictions}
    mock_tread_depth_controller.detect.assert_called_once()


@pytest.mark.asyncio
async def test_tread_depth_requires_single_image_input(client: AsyncClient) -> None:
    controller = MagicMock(spec=TreadDepthController)
    controller.detect = AsyncMock(
        side_effect=ImageInputError("Either an image file or image_url is required.")
    )

    with patch(
        "app.api.routes.tread_depth._get_controller",
        return_value=controller,
    ):
        response = await client.post("/api/v1/tread-depth/detect")

    assert response.status_code == 400
    body = response.json()
    assert body["detail"]["error"]["code"] == "INVALID_IMAGE_INPUT"


def test_manager_filters_predictions_below_response_threshold() -> None:
    settings = RoboflowSettings()
    manager = RoboflowManager(
        api_url=settings.api_url,
        api_key="test-key",
        model_settings=RoboflowModelSettings(filter_confidence_threshold=0.5),
    )

    predictions = manager._filter_predictions(
        [
            {"class": "7-8 mm", "confidence": 0.832},
            {"class": "7-8 mm", "confidence": 0.485},
            {"class": "7-8 mm", "confidence": 0.55},
        ]
    )

    assert len(predictions) == 2
    assert predictions[0]["confidence"] == 0.832
    assert predictions[1]["confidence"] == 0.55


def test_manager_extracts_infer_predictions() -> None:
    raw_result = {
        "predictions": [
            {
                "x": 10,
                "y": 20,
                "width": 30,
                "height": 40,
                "confidence": 0.9,
                "class": "2-3 mm",
                "class_id": 1,
                "detection_id": "abc",
            }
        ],
        "image": {"width": 640, "height": 480},
    }

    predictions = RoboflowManager._extract_predictions(raw_result)

    assert len(predictions) == 1
    assert predictions[0]["class"] == "2-3 mm"
