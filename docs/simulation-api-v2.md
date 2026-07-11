# Tire Simulation API v2

The v2 API adds a reproducible, stateless scenario simulator while preserving the original v1
wear-severity calculator.

## Safety boundary

The available profiles are generic demonstration assumptions. They contain no controlled AMM, CMM,
ICA, aircraft-installation, or certified tire-limit data. Consequently, every simulation reports:

- certified limits as `NOT_AVAILABLE`;
- premature-removal risk as `NOT_MODELED`;
- forecast confidence as `LOW`;
- an explicit prohibition on using the result to determine serviceability or authorize dispatch.

Known defects, a reached planning threshold, or a pressure deficit of at least 10% produce a qualified
inspection recommendation. That recommendation does not determine the tire's disposition.

## Endpoints

```text
GET  /api/v2/tire-profiles
POST /api/v2/tire-simulations
```

The complete request and response contracts are available in Swagger at `/docs`.

## Example request

```json
{
  "profile_id": "pilot-main-v1",
  "current_condition": {
    "cycles_since_install": 94,
    "current_tread_depth_mm": 6.8,
    "measured_cold_pressure_psi": 190.0,
    "reference_cold_pressure_psi": 200.0,
    "tire_temperature_c": 30.0,
    "retread_count": 1,
    "known_defects": []
  },
  "horizon_cycles": 50,
  "simulation_runs": 1000,
  "random_seed": 42,
  "future_conditions": {
    "landing_weight_kg": {
      "minimum": 58000.0,
      "most_likely": 64000.0,
      "maximum": 70000.0
    },
    "touchdown_ground_speed_ms": {
      "minimum": 63.0,
      "most_likely": 69.0,
      "maximum": 76.0
    },
    "crosswind_kt": {
      "minimum": 0.0,
      "most_likely": 8.0,
      "maximum": 18.0
    },
    "touchdown_sink_rate_ms": {
      "minimum": 0.5,
      "most_likely": 1.2,
      "maximum": 2.0
    },
    "touchdown_yaw_angle_deg": {
      "minimum": 0.0,
      "most_likely": 2.0,
      "maximum": 6.0
    },
    "taxi_distance_km": {
      "minimum": 2.0,
      "most_likely": 4.2,
      "maximum": 6.0
    },
    "average_taxi_speed_kt": {
      "minimum": 8.0,
      "most_likely": 14.0,
      "maximum": 22.0
    },
    "outside_air_temperature_c": {
      "minimum": 18.0,
      "most_likely": 29.0,
      "maximum": 39.0
    },
    "brake_temperature_c": {
      "minimum": 100.0,
      "most_likely": 220.0,
      "maximum": 380.0
    },
    "heavy_braking_probability": 0.05,
    "runway_condition": "DRY"
  }
}
```

Each range is interpreted as a bounded triangular distribution. `random_seed` makes repeated and
concurrent requests reproducible.

## Response interpretation

The response provides:

- projected tread-depth distribution at the requested horizon;
- p10/p50/p90 cycles to the demonstration planning threshold;
- probability of reaching that threshold within the horizon;
- comparison between the supplied pressure condition and maintained reference pressure;
- scenario-driver labels, assumptions, confidence, and model version;
- escalation guidance when supplied condition data already warrants qualified inspection.

It intentionally does not return a failure probability for FOD, cuts, separation, heat damage, or other
premature-removal modes. Those require qualified inspection and representative fleet outcome data.
