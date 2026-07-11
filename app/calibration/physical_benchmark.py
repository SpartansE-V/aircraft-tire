"""Checksum-bound loading and analysis of non-target physical-test benchmarks."""

import hashlib
import hmac
import math
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class PhysicalBenchmarkError(ValueError):
    """Raised when a physical benchmark is missing, unsafe, or fails integrity checks."""


class PhysicalBenchmarkIntegrityError(PhysicalBenchmarkError):
    """Raised when benchmark bytes do not match the declared digest."""


class BenchmarkSchema(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)


class BenchmarkSource(BenchmarkSchema):
    document_id: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=500)
    publication_date: date
    ntrs_record_url: str = Field(pattern=r"^https://ntrs\.nasa\.gov/")
    download_url: str = Field(pattern=r"^https://ntrs\.nasa\.gov/")
    source_pdf_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    printed_table: str = Field(min_length=1, max_length=200)
    distribution: Literal["PUBLIC"]
    copyright_determination: Literal["GOV_PUBLIC_USE_PERMITTED"]
    extraction_method: str = Field(min_length=1, max_length=500)


class BenchmarkTestConfiguration(BenchmarkSchema):
    tire_size: str = Field(min_length=1, max_length=100)
    tire_type: str = Field(min_length=1, max_length=100)
    construction: Literal["BIAS", "RADIAL"]
    ply_rating: int = Field(gt=0)
    rated_load_lbf: float = Field(gt=0, allow_inf_nan=False)
    rated_pressure_psi: float = Field(gt=0, allow_inf_nan=False)
    test_pressure_psi: float = Field(gt=0, allow_inf_nan=False)
    vertical_load_lbf: float = Field(gt=0, allow_inf_nan=False)
    yaw_angle_deg: float = Field(ge=0, le=90, allow_inf_nan=False)
    vehicle_speed_mph: float = Field(gt=0, allow_inf_nan=False)
    surface_state: Literal["DRY", "WET", "CONTAMINATED"]
    nominal_accumulated_distance_ft: float = Field(gt=0, allow_inf_nan=False)
    new_tire_per_surface: bool
    wear_measurement: str = Field(min_length=1, max_length=300)


class TextureWearObservation(BenchmarkSchema):
    test_surface: int = Field(gt=0)
    texture_modification: str = Field(min_length=1, max_length=300)
    wear_rate_lbm_per_ft: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    average_texture_depth_in: float = Field(gt=0, allow_inf_nan=False)


class PhysicalTestBenchmark(BenchmarkSchema):
    schema_version: Literal["1.0"]
    benchmark_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,127}$")
    evidence_role: Literal["NON_TARGET_PHYSICAL_TEST_BENCHMARK"]
    calibration_claim: Literal["NOT_SUITABLE_FOR_TARGET_CALIBRATION"]
    source: BenchmarkSource
    test_configuration: BenchmarkTestConfiguration
    observations: tuple[TextureWearObservation, ...] = Field(min_length=2)
    limitations: tuple[str, ...] = Field(min_length=1)

    @field_validator("observations", "limitations", mode="before")
    @classmethod
    def normalize_json_sequences(cls, value: object) -> object:
        if isinstance(value, list):
            return tuple(value)
        return value

    @model_validator(mode="after")
    def validate_observations(self) -> Self:
        surface_ids = [observation.test_surface for observation in self.observations]
        if len(set(surface_ids)) != len(surface_ids):
            raise ValueError("physical benchmark test-surface identifiers must be unique")
        measured = [
            observation
            for observation in self.observations
            if observation.wear_rate_lbm_per_ft is not None
        ]
        if len(measured) < 2:
            raise ValueError("physical benchmark requires at least two measured wear rates")
        return self


@dataclass(frozen=True)
class PhysicalBenchmarkSnapshot:
    benchmark: PhysicalTestBenchmark
    sha256: str
    byte_count: int


class TextureWearRegression(BenchmarkSchema):
    observation_count: int = Field(ge=2)
    slope_lbm_per_ft_per_atd_in: float = Field(allow_inf_nan=False)
    intercept_lbm_per_ft: float = Field(allow_inf_nan=False)
    r_squared: float = Field(ge=0, le=1, allow_inf_nan=False)
    rmse_lbm_per_ft: float = Field(ge=0, allow_inf_nan=False)


def load_physical_benchmark(
    path: Path,
    *,
    expected_sha256: str,
    maximum_bytes: int = 1_000_000,
) -> PhysicalBenchmarkSnapshot:
    """Read, hash, and parse the exact same bounded benchmark bytes."""

    if maximum_bytes < 1:
        raise PhysicalBenchmarkError("maximum_bytes must be positive")
    if path.is_symlink() or not path.is_file():
        raise PhysicalBenchmarkError("benchmark path must be a regular, non-symlink file")
    with path.open("rb") as benchmark_file:
        content = benchmark_file.read(maximum_bytes + 1)
    if len(content) > maximum_bytes:
        raise PhysicalBenchmarkError("benchmark exceeds the configured size limit")
    digest = hashlib.sha256(content).hexdigest()
    if not hmac.compare_digest(digest, expected_sha256):
        raise PhysicalBenchmarkIntegrityError("benchmark checksum does not match expected evidence")
    try:
        benchmark = PhysicalTestBenchmark.model_validate_json(content, strict=True)
    except ValueError as exc:
        raise PhysicalBenchmarkError(
            "benchmark does not satisfy the strict evidence schema"
        ) from exc
    return PhysicalBenchmarkSnapshot(
        benchmark=benchmark,
        sha256=digest,
        byte_count=len(content),
    )


def calculate_texture_wear_regression(
    snapshot: PhysicalBenchmarkSnapshot,
) -> TextureWearRegression:
    """Describe the published within-test texture relationship without target transfer."""

    measured = [
        observation
        for observation in snapshot.benchmark.observations
        if observation.wear_rate_lbm_per_ft is not None
    ]
    x_values = [observation.average_texture_depth_in for observation in measured]
    y_values = [
        observation.wear_rate_lbm_per_ft
        for observation in measured
        if observation.wear_rate_lbm_per_ft is not None
    ]
    count = len(x_values)
    x_mean = math.fsum(x_values) / count
    y_mean = math.fsum(y_values) / count
    denominator = math.fsum((value - x_mean) ** 2 for value in x_values)
    if denominator == 0:
        raise PhysicalBenchmarkError("benchmark texture depths have zero variance")
    slope = (
        math.fsum(
            (x_value - x_mean) * (y_value - y_mean)
            for x_value, y_value in zip(x_values, y_values, strict=True)
        )
        / denominator
    )
    intercept = y_mean - slope * x_mean
    predictions = [intercept + slope * value for value in x_values]
    residual_sum_squares = math.fsum(
        (actual - predicted) ** 2 for actual, predicted in zip(y_values, predictions, strict=True)
    )
    total_sum_squares = math.fsum((value - y_mean) ** 2 for value in y_values)
    if total_sum_squares == 0:
        raise PhysicalBenchmarkError("benchmark wear rates have zero variance")
    return TextureWearRegression(
        observation_count=count,
        slope_lbm_per_ft_per_atd_in=slope,
        intercept_lbm_per_ft=intercept,
        r_squared=max(0.0, min(1.0, 1 - residual_sum_squares / total_sum_squares)),
        rmse_lbm_per_ft=math.sqrt(residual_sum_squares / count),
    )
