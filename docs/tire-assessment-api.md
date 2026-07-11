# Canonical tire-assessment API

`POST /api/v1/tire-assessments` is the primary interface for the demonstration model. One request
contains measured tire condition, bounded future operating assumptions, and forecast controls.

The representative-cycle and future results share the same inputs, preventing inconsistent results
from separate severity and simulation requests.

## Input

```json
{
  "profile_id": "pilot-main-v1",
  "current_condition": {
    "cycles_since_install": 94,
    "current_tread_depth_mm": 6.8,
    "measured_cold_pressure_psi": 190.0,
    "reference_cold_pressure_psi": 200.0,
    "tire_temperature_c": 30.0,
    "retread_count": 0,
    "known_defects": []
  },
  "horizon_cycles": 50,
  "simulation_runs": 1000,
  "random_seed": 42,
  "future_conditions": {
    "landing_weight_kg": {"minimum": 58000.0, "most_likely": 64000.0, "maximum": 70000.0},
    "touchdown_ground_speed_ms": {"minimum": 63.0, "most_likely": 69.0, "maximum": 75.0},
    "crosswind_kt": {"minimum": 0.0, "most_likely": 8.0, "maximum": 16.0},
    "touchdown_sink_rate_ms": {"minimum": 0.5, "most_likely": 1.2, "maximum": 1.9},
    "touchdown_yaw_angle_deg": {"minimum": 0.0, "most_likely": 2.0, "maximum": 5.0},
    "taxi_distance_km": {"minimum": 2.7, "most_likely": 4.2, "maximum": 5.7},
    "average_taxi_speed_kt": {"minimum": 8.0, "most_likely": 14.0, "maximum": 20.0},
    "outside_air_temperature_c": {"minimum": 19.0, "most_likely": 29.0, "maximum": 39.0},
    "brake_temperature_c": {"minimum": 100.0, "most_likely": 220.0, "maximum": 340.0},
    "heavy_braking_probability": 0.05,
    "runway_condition": "DRY"
  }
}
```

The measured pressure must stay within 10% of the caller-provided reference pressure because the
demonstration wear model is not defined beyond that domain.

## Output sections

| Field | Meaning |
|---|---|
| `representative_cycle` | Severity, wear rate, pressure effect, and guidance at every range's most-likely value |
| `current_condition` | Pressure/defect-aware monitoring status |
| `forecast` | p10/p50/p90 tread and cycles-to-threshold results plus within-horizon probability |
| `pressure_policy_comparison` | Current-pressure median compared with maintained-reference-pressure median |
| `scenario_drivers` | Heuristic labels for the largest input deviations, not causal explanations |
| `recommendation` | Inspection-planning attention; never a serviceability decision |
| `approved_limits` | Explicitly `NOT_AVAILABLE` for demonstration profiles |
| `unscheduled_removal_risk` | Explicitly `NOT_MODELED` without fleet outcome data |
| `confidence` | Explicitly `LOW` until the model is calibrated and validated |
| `assumptions` and `model_versions` | Reproducibility and model-governance metadata |

The endpoint is deterministic for the same request and `random_seed`, apart from generated UUIDs.
It does not determine airworthiness, serviceability, or dispatch eligibility.
