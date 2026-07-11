# Canonical tire-assessment API

`POST /api/v1/tire-assessments` is the primary interface for the demonstration model. One request
contains measured tire condition, bounded future operating assumptions, and forecast controls.

The representative-cycle and future results share the same inputs, preventing inconsistent results
from separate severity and simulation requests. The caller must declare the intended use. The
current `pilot-sim-2.0.0` release permits `SCENARIO_PLANNING` only; it is not calibrated, validated,
or authorized for maintenance or dispatch decisions.

The endpoint is intentionally generic and accepts no aircraft or tire identity. It rejects a
target-specific release because this public contract cannot establish controlled applicability.
Target identity remains internal to evidence promotion and validation workflows.

## Input

```json
{
  "intended_use": "SCENARIO_PLANNING",
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

`intended_use` is required and accepts one of:

- `SCENARIO_PLANNING`
- `MAINTENANCE_PLANNING`
- `DISPATCH_SUPPORT`

The measured pressure must stay within 10% of the caller-provided reference pressure because the
demonstration wear model is not defined beyond that domain. A deficit greater than 10% is invalid
input. A deficit exactly at 10% is inside the request schema but causes the assessment to be
withheld for qualified inspection. `reference_cold_pressure_psi` is a caller-provided scenario
assumption, not an approved servicing pressure for a particular installation.

The active release applies a narrower modeled envelope after request-schema validation. Every
future distribution's `minimum` and `maximum` must remain inside this envelope:

| Input | `pilot-sim-2.0.0` modeled range |
|---|---|
| Current tread depth | At or below the selected profile's 10.9 mm initial depth; at or below the 1.0 mm planning threshold is withheld |
| Pressure relationship | Measured pressure must not exceed the scenario reference; deficit must be 0–10% |
| Landing weight | 50,000–73,500 kg |
| Touchdown ground speed | 58–82 m/s |
| Crosswind | 0–25 kt |
| Touchdown sink rate | 0–4 m/s |
| Touchdown yaw angle | 0–15 degrees |
| Taxi distance | 0.5–8 km |
| Average taxi speed | 0–30 kt |
| Outside-air temperature | 5–45 °C |
| Brake temperature | 0–600 °C |

An input outside this release envelope returns HTTP `422` with
`MODEL_INPUT_OUTSIDE_RELEASE_DOMAIN`; the service does not extrapolate a forecast.

## Output sections

| Field | Meaning |
|---|---|
| `governance` | Active release, requested use, permission decision, evidence statuses, and SHA-256 artifact identities |
| `representative_cycle` | Severity, wear rate, pressure effect, and guidance at every range's most-likely value |
| `current_condition` | Pressure/defect-aware monitoring status |
| `forecast` | p10/p50/p90 tread and cycles-to-threshold results plus within-horizon probability |
| `pressure_policy_comparison` | Current-pressure median compared with maintained-reference-pressure median |
| `model_factor_usage` | Explicitly states which recorded inputs are excluded from the wear forecast and used only as synthetic removal proxies |
| `scenario_drivers` | Heuristic labels for the largest input deviations, not causal explanations |
| `recommendation` | Inspection-planning attention; never a serviceability decision |
| `approved_limits` | Keeps approved limits `NOT_AVAILABLE` while exposing the profile's synthetic 1.0 mm planning threshold |
| `unscheduled_removal_risk` | Synthetic per-mode and aggregate demonstration percentages, explicitly not empirical probabilities |
| `confidence` | Explicitly `LOW` until the model is calibrated and validated |
| `assumptions` and `model_versions` | Model-version traceability and governance metadata |

For the current release, a successful scenario-planning response includes governance equivalent to:

```json
{
  "release_id": "pilot-sim-2.0.0",
  "lifecycle": "DEVELOPMENT",
  "requested_use": "SCENARIO_PLANNING",
  "requested_use_permitted": true,
  "operational_decision_authorized": false,
  "calibration_status": "NOT_PERFORMED",
  "validation_status": "NOT_PERFORMED",
  "authorization_status": "NOT_AUTHORIZED",
  "manifest_sha256": "<64 lowercase hexadecimal characters>",
  "parameters_sha256": "<64 lowercase hexadecimal characters>",
  "implementation_id": "pilot-physics-simulation-2.0.0",
  "implementation_sha256": "<64 lowercase hexadecimal characters>",
  "supporting_evidence": [
    {
      "evidence_id": "nasa-tp-3626-ittv-table4",
      "source_kind": "PHYSICAL_TEST",
      "sha256": "<64 lowercase hexadecimal characters>"
    }
  ],
  "reasons": [
    "release is restricted to declared scenario-planning use"
  ]
}
```

The hashes identify the exact loaded evidence package, typed parameter artifact, manifest-listed
calculation source files, and any declared supporting evidence. The NASA artifact is an authentic
non-target physical-test benchmark. Its manifest entry labels that limited use, and the release
schema rejects reuse of a supporting-evidence digest as calibration or holdout data. These identities
support integrity and traceability; they are not target calibration, independent validation, OEM
approval, or FAA authorization. Exact result reproduction also requires the same request, random
seed, dependencies, and runtime environment.

Internal release metadata still classifies supporting evidence applicability and permitted use.
Those controls are deliberately not repeated in the public response, but the release loader still
rejects evidence misuse or checksum drift.

Future validation is claim-scoped. The implemented offline evaluator can verify only point tread
wear-rate error. It cannot validate the endpoint's forecast intervals, cycles-to-threshold,
threshold probability, severity class, recommendation, pressure-policy comparison, or synthetic
removal percentages; those require separate holdout metrics before operational authorization is
even structurally possible.

## Demonstration limits and removal modes

`approved_limits.status` remains `NOT_AVAILABLE`. The returned
`demonstration_planning_threshold_mm` is 1.0 mm for both pilot profiles and is labeled
`SYNTHETIC_PILOT_ASSUMPTION`; it is not an AMM, CMM, ICA, OEM, or regulatory removal limit.

The removal demonstration returns percentages for FOD damage, cuts or exposed cord, bulges, tread
separation, heat damage, flat spots, contamination, sudden pressure loss, and an aggregate premature
removal result. The failure-mode selection is informed by FAA and manufacturer guidance:

- [FAA AC 20-97B](https://www.faa.gov/sites/faa.gov/files/2022-11/AC20-97B.pdf)
- [Goodyear Aviation Tire Care](https://www.goodyearaviation.com/resources/pdf/aviation-tire-care-2024.pdf)
- [Bridgestone Aircraft Tire Care and Maintenance](https://www.bridgestone.com/products/aircraft/candm/)

Those sources do not supply the numerical coefficients. The coefficients are checksum-protected
pilot assumptions. The API therefore labels every result `SYNTHETIC_DEMONSTRATION`, `LOW`
confidence, and `NOT_EMPIRICAL_FAILURE_PROBABILITY`.

For each simulation sample, the model combines normalized pressure deficit, installed-age proxy,
retread count, measured tire temperature, heavy-braking probability, brake heat, taxi exposure, and
runway exposure into a synthetic per-cycle hazard. It converts that hazard to the requested horizon
with `1 - (1 - q)^horizon_cycles`, averages results across samples, and combines modes with
`1 - product(1 - mode_probability)`. These calculations are demonstration outputs, not observed
failure rates or maintenance predictions. The aggregate additionally assumes the component modes
are independent, an unvalidated simplification used only for the demonstration.

`cycles_since_install`, `retread_count`, and `tire_temperature_c` remain excluded from the tread-wear
forecast. They are used only as uncalibrated proxies in the synthetic removal demonstration, which
is disclosed in `model_factor_usage`.

## Fail-closed responses

The endpoint returns no numeric forecast when a safety or evidence gate fails.

| HTTP status | Error code | When it is returned |
|---|---|---|
| `409` | `MODEL_NOT_AUTHORIZED_FOR_INTENDED_USE` | The active release does not permit the requested maintenance or dispatch use |
| `409` | `MODEL_TARGET_IDENTITY_UNAVAILABLE` | The generic endpoint is configured with a target-specific release it cannot safely apply |
| `409` | `CONTROLLED_OPERATIONAL_CONFIGURATION_UNAVAILABLE` | Governance permits an operational use, but the deployment has no controlled installation resolver for pressure and service limits |
| `409` | `ASSESSMENT_WITHHELD` | A known defect is present, the planning threshold has been reached, or pressure deficit is exactly 10% |
| `503` | `MODEL_EVIDENCE_UNAVAILABLE` | The release package is missing, invalid, or fails checksum/schema/semantic verification for any declared model evidence |
| `422` | `MODEL_INPUT_OUTSIDE_RELEASE_DOMAIN` | Schema-valid input is outside the active release's modeled envelope, including a pressure deficit greater than 10% |
| `422` | `INVALID_INPUT` | A required field, type, schema bound, or distribution ordering is invalid |

Example operational-use rejection:

```json
{
  "error": {
    "code": "MODEL_NOT_AUTHORIZED_FOR_INTENDED_USE",
    "message": "The active model release is not authorized for the requested maintenance or dispatch use."
  }
}
```

For the same deployed service and model release, the endpoint is deterministic for the same request
and `random_seed`, apart from generated UUIDs. It does not determine airworthiness, serviceability,
or dispatch eligibility.
