"""Typed configuration loaders.

YAML config (``config/generator.yaml``, ``config/thresholds.yaml``) is parsed into
frozen dataclasses. A missing key raises a clear error naming the section, rather than
a bare ``KeyError`` deep inside a downstream module.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

from . import paths


def _req(d: dict, key: str, ctx: str) -> Any:
    if not isinstance(d, dict) or key not in d:
        raise KeyError(f"Missing required config key '{key}' in section '{ctx}'")
    return d[key]


def _pair(v: Any, ctx: str) -> tuple[float, float]:
    if not isinstance(v, (list, tuple)) or len(v) != 2:
        raise ValueError(f"Expected a [min, max] pair for '{ctx}', got {v!r}")
    return (v[0], v[1])


def _add_months(d: date, months: int) -> date:
    total = (d.month - 1) + months
    year = d.year + total // 12
    month = total % 12 + 1
    return date(year, month, min(d.day, 28))


# ---------------------------------------------------------------------------
# Generator config
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Station:
    code: str
    spare_stock: int


@dataclass(frozen=True)
class GeneratorConfig:
    version: str
    seed: int
    sim_start_date: str
    history_months: int
    n_aircraft: int
    aircraft_type: str
    cycles_per_day: tuple[float, float]
    tire_size: str
    brands: list[str]
    new_tread_mm: tuple[float, float]
    wear_limit_mm: float
    base_wear_mm_per_landing: dict[str, float]
    factors: dict[str, dict]
    susceptibility_sigma: float
    process_noise_sd: float
    accel_event_prob: float
    accel_multiplier: tuple[float, float]
    fod_hazard_per_landing: float
    hard_landing_prob: float
    hard_landing_g: tuple[float, float]
    underinflation_event_prob: float
    underinflation_run_cycles: tuple[float, float]
    underinflation_wear_multiplier: tuple[float, float]
    inspection_interval_cycles: tuple[float, float]
    gauge_noise_sd_mm: float
    gross_misread_prob: float
    gross_misread_sd_mm: float
    stations: tuple[Station, ...]
    target_outcome_mix: dict[str, list]
    sensors: dict  # additional sensor/log signals (drawn from a separate RNG stream)

    @property
    def start_date(self) -> date:
        return datetime.fromisoformat(str(self.sim_start_date)).date()

    @property
    def as_of_date(self) -> date:
        """The 'today' of the demo — end of the simulated history window."""
        return _add_months(self.start_date, self.history_months)

    @classmethod
    def from_dict(cls, d: dict) -> GeneratorConfig:
        ctx = "generator.yaml"
        fleet = _req(d, "fleet", ctx)
        tire = _req(d, "tire", ctx)
        wear = _req(d, "wear", ctx)
        insp = _req(d, "inspection", ctx)
        events = _req(d, "events", ctx)
        stations = tuple(
            Station(code=str(_req(s, "code", "stations[]")), spare_stock=int(_req(s, "spare_stock", "stations[]")))
            for s in _req(d, "stations", ctx)
        )
        return cls(
            version=str(_req(d, "version", ctx)),
            seed=int(_req(d, "seed", ctx)),
            sim_start_date=str(_req(fleet, "sim_start_date", "fleet")),
            history_months=int(_req(fleet, "history_months", "fleet")),
            n_aircraft=int(_req(fleet, "n_aircraft", "fleet")),
            aircraft_type=str(_req(fleet, "aircraft_type", "fleet")),
            cycles_per_day=_pair(_req(fleet, "cycles_per_day", "fleet"), "fleet.cycles_per_day"),
            tire_size=str(_req(tire, "tire_size", "tire")),
            brands=list(_req(tire, "brands", "tire")),
            new_tread_mm=_pair(_req(tire, "new_tread_mm", "tire"), "tire.new_tread_mm"),
            wear_limit_mm=float(_req(tire, "wear_limit_mm", "tire")),
            base_wear_mm_per_landing=dict(_req(wear, "base_wear_mm_per_landing", "wear")),
            factors=dict(_req(wear, "factors", "wear")),
            susceptibility_sigma=float(_req(wear, "susceptibility_sigma", "wear")),
            process_noise_sd=float(_req(wear, "process_noise_sd", "wear")),
            accel_event_prob=float(_req(wear, "accel_event_prob", "wear")),
            accel_multiplier=_pair(_req(wear, "accel_multiplier", "wear"), "wear.accel_multiplier"),
            fod_hazard_per_landing=float(_req(events, "fod_hazard_per_landing", "events")),
            hard_landing_prob=float(_req(events, "hard_landing_prob", "events")),
            hard_landing_g=_pair(_req(events, "hard_landing_g", "events"), "events.hard_landing_g"),
            underinflation_event_prob=float(_req(events, "underinflation_event_prob", "events")),
            underinflation_run_cycles=_pair(
                _req(events, "underinflation_run_cycles", "events"), "events.underinflation_run_cycles"
            ),
            underinflation_wear_multiplier=_pair(
                _req(events, "underinflation_wear_multiplier", "events"), "events.underinflation_wear_multiplier"
            ),
            inspection_interval_cycles=_pair(
                _req(insp, "interval_cycles", "inspection"), "inspection.interval_cycles"
            ),
            gauge_noise_sd_mm=float(_req(insp, "gauge_noise_sd_mm", "inspection")),
            gross_misread_prob=float(_req(insp, "gross_misread_prob", "inspection")),
            gross_misread_sd_mm=float(_req(insp, "gross_misread_sd_mm", "inspection")),
            stations=stations,
            target_outcome_mix=dict(_req(d, "target_outcome_mix", ctx)),
            sensors=dict(d.get("sensors", {})),
        )


# ---------------------------------------------------------------------------
# Threshold / scoring config
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class PressureBand:
    min_pct: float
    max_pct: float
    action: str


@dataclass(frozen=True)
class PriorityWeights:
    position_criticality: dict[str, float]
    utilization_weight: float
    spare_shortage_weight: float
    hard_landing_multiplier: float
    pressure_ladder_multiplier: float


@dataclass(frozen=True)
class ThresholdConfig:
    version: str
    wear_limit_mm: float
    planning_window_days: int
    p_cross_threshold: float
    wear_accel_threshold: float
    mc_draws: int
    mc_seed: int
    next_check_interval_cycles: int
    low_confidence_min_readings: int
    utilization_trailing_days: int
    default_cycles_per_day: float
    priority: PriorityWeights
    pressure_bands: tuple[PressureBand, ...]
    recurring_loss_pct_24h: float

    @classmethod
    def from_dict(cls, d: dict) -> ThresholdConfig:
        ctx = "thresholds.yaml"
        pr = _req(d, "priority", ctx)
        ladder = _req(d, "pressure_ladder", ctx)
        bands = tuple(
            PressureBand(
                min_pct=float(_req(b, "min_pct", "pressure_ladder.bands[]")),
                max_pct=float(_req(b, "max_pct", "pressure_ladder.bands[]")),
                action=str(_req(b, "action", "pressure_ladder.bands[]")),
            )
            for b in _req(ladder, "bands", "pressure_ladder")
        )
        priority = PriorityWeights(
            position_criticality=dict(_req(pr, "position_criticality", "priority")),
            utilization_weight=float(_req(pr, "utilization_weight", "priority")),
            spare_shortage_weight=float(_req(pr, "spare_shortage_weight", "priority")),
            hard_landing_multiplier=float(_req(pr, "hard_landing_multiplier", "priority")),
            pressure_ladder_multiplier=float(_req(pr, "pressure_ladder_multiplier", "priority")),
        )
        return cls(
            version=str(_req(d, "version", ctx)),
            wear_limit_mm=float(_req(d, "wear_limit_mm", ctx)),
            planning_window_days=int(_req(d, "planning_window_days", ctx)),
            p_cross_threshold=float(_req(d, "p_cross_threshold", ctx)),
            wear_accel_threshold=float(_req(d, "wear_accel_threshold", ctx)),
            mc_draws=int(_req(d, "mc_draws", ctx)),
            mc_seed=int(_req(d, "mc_seed", ctx)),
            next_check_interval_cycles=int(_req(d, "next_check_interval_cycles", ctx)),
            low_confidence_min_readings=int(_req(d, "low_confidence_min_readings", ctx)),
            utilization_trailing_days=int(_req(d, "utilization_trailing_days", ctx)),
            default_cycles_per_day=float(_req(d, "default_cycles_per_day", ctx)),
            priority=priority,
            pressure_bands=bands,
            recurring_loss_pct_24h=float(_req(ladder, "recurring_loss_pct_24h", "pressure_ladder")),
        )


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------
def load_yaml(path: Path) -> dict:
    with open(path) as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"Config file {path} did not parse to a mapping")
    return data


def get_generator_config(path: Path | None = None) -> GeneratorConfig:
    return GeneratorConfig.from_dict(load_yaml(path or paths.CONFIG_GENERATOR))


def get_threshold_config(path: Path | None = None) -> ThresholdConfig:
    return ThresholdConfig.from_dict(load_yaml(path or paths.CONFIG_THRESHOLDS))
