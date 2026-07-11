"""Environment-backed application configuration."""

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

CONFIG_PATH = Path(__file__).resolve().parent / "config.yaml"
ENV_PATH = Path(__file__).resolve().parents[1] / ".env"

# The AI backends use their SDKs' standard environment-variable configuration. Load the
# application development file before the application imports those backends; existing
# deployment environment variables retain precedence.
load_dotenv(ENV_PATH)


class RoboflowModelSettings(BaseModel):
    """Per-model Roboflow inference configuration."""

    model_id: str = ""
    model_confidence_threshold: float = Field(default=0.2, ge=0.0, le=1.0)
    filter_confidence_threshold: float = Field(default=0.5, ge=0.0, le=1.0)


class RoboflowSettings(BaseModel):
    """Shared Roboflow client configuration."""

    api_url: str = "https://serverless.roboflow.com"
    api_key: str = ""
    image_fetch_timeout_seconds: int = Field(default=30, ge=1, le=300)
    max_upload_bytes: int = Field(default=10_485_760, ge=1)
    tyre_quality: RoboflowModelSettings = Field(
        default_factory=lambda: RoboflowModelSettings(model_id="tyre-quality-qccvy/1")
    )
    tread_depth: RoboflowModelSettings = Field(
        default_factory=lambda: RoboflowModelSettings(model_id="tyre_tread_depth_set/1")
    )


class Settings(BaseSettings):
    """Runtime settings loaded from config.yaml, environment variables, or a local .env file."""

    model_config = SettingsConfigDict(
        env_file=ENV_PATH,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        env_nested_delimiter="__",
    )

    cors_origins: str = Field(default="http://localhost:3000", alias="CORS_ORIGINS")
    port: int = Field(default=8000, ge=1, le=65535, alias="PORT")
    # Bake mock-tyre scan packs into tires.parquet when the API process starts
    # (same job as `python -m app.tire_rul.enrich_tire_assets`). Disable in tests.
    enrich_on_startup: bool = Field(default=True, alias="ENRICH_ON_STARTUP")
    enrich_seed: int = Field(default=20260712, ge=0, alias="ENRICH_SEED")
    roboflow: RoboflowSettings = Field(default_factory=RoboflowSettings)

    @field_validator("cors_origins")
    @classmethod
    def validate_cors_origins(cls, value: str) -> str:
        origins = [origin.strip() for origin in value.split(",") if origin.strip()]
        if not origins:
            raise ValueError("CORS_ORIGINS must contain at least one origin")
        if "*" in origins:
            raise ValueError("Wildcard CORS origins are not supported")
        return ",".join(origins)

    @property
    def allowed_origins(self) -> list[str]:
        """Return configured CORS origins as a normalized list."""

        return self.cors_origins.split(",")


def _load_yaml_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        return {}

    with CONFIG_PATH.open(encoding="utf-8") as config_file:
        loaded = yaml.safe_load(config_file)

    return loaded if isinstance(loaded, dict) else {}


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide immutable settings instance."""

    return Settings(**_load_yaml_config())
