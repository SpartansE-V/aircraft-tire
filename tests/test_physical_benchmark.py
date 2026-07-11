"""Integrity, provenance, and scope tests for public physical-test evidence."""

import json
import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.calibration.physical_benchmark import (
    PhysicalBenchmarkError,
    PhysicalTestBenchmark,
    calculate_texture_wear_regression,
    load_physical_benchmark,
)

BENCHMARK_PATH = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "model_releases"
    / "pilot-sim-2.0.0"
    / "evidence"
    / "nasa-tp-3626-ittv-table4.json"
)
BENCHMARK_SHA256 = "1c499db6c7fa0463f3a58856d6a8decb02378a9d23fdc8596482233178b0a943"


def test_nasa_table4_benchmark_is_checksum_bound_and_non_target() -> None:
    snapshot = load_physical_benchmark(
        BENCHMARK_PATH,
        expected_sha256=BENCHMARK_SHA256,
    )
    benchmark = snapshot.benchmark

    assert snapshot.sha256 == BENCHMARK_SHA256
    assert benchmark.benchmark_id == "nasa-tp-3626-ittv-table4"
    assert benchmark.calibration_claim == "NOT_SUITABLE_FOR_TARGET_CALIBRATION"
    assert benchmark.source.document_id == "NASA-TP-3626"
    assert benchmark.source.source_pdf_sha256 == (
        "7b9057f5a409031a5ac6b41c63c07001c647ce548cf3cd338d9e6ceef9e51bb2"
    )
    assert benchmark.test_configuration.tire_size == "20 x 4.4"
    assert benchmark.test_configuration.yaw_angle_deg == 8.0
    assert len(benchmark.observations) == 18
    assert sum(item.wear_rate_lbm_per_ft is not None for item in benchmark.observations) == 12


def test_published_texture_wear_relationship_is_reproducible() -> None:
    snapshot = load_physical_benchmark(
        BENCHMARK_PATH,
        expected_sha256=BENCHMARK_SHA256,
    )

    result = calculate_texture_wear_regression(snapshot)

    assert result.observation_count == 12
    assert result.slope_lbm_per_ft_per_atd_in == pytest.approx(0.0294011033882)
    assert result.intercept_lbm_per_ft == pytest.approx(0.0000187892283542)
    assert result.r_squared == pytest.approx(0.850311800134)
    assert result.rmse_lbm_per_ft == pytest.approx(0.0000482619294778)


def test_benchmark_loader_rejects_tampered_bytes(tmp_path: Path) -> None:
    tampered = tmp_path / "benchmark.json"
    shutil.copy2(BENCHMARK_PATH, tampered)
    tampered.write_text(tampered.read_text() + "\n")

    with pytest.raises(PhysicalBenchmarkError, match="checksum"):
        load_physical_benchmark(tampered, expected_sha256=BENCHMARK_SHA256)


def test_benchmark_loader_enforces_size_bound_before_parsing() -> None:
    with pytest.raises(PhysicalBenchmarkError, match="exceeds"):
        load_physical_benchmark(
            BENCHMARK_PATH,
            expected_sha256=BENCHMARK_SHA256,
            maximum_bytes=10,
        )

    with pytest.raises(PhysicalBenchmarkError, match="must be positive"):
        load_physical_benchmark(
            BENCHMARK_PATH,
            expected_sha256=BENCHMARK_SHA256,
            maximum_bytes=0,
        )


def test_benchmark_schema_rejects_target_calibration_claim() -> None:
    document = json.loads(BENCHMARK_PATH.read_bytes())
    document["calibration_claim"] = "TARGET_CALIBRATION"

    with pytest.raises(ValidationError, match="NOT_SUITABLE_FOR_TARGET_CALIBRATION"):
        PhysicalTestBenchmark.model_validate(document, strict=True)
