# Aircraft Tire Wear Severity Calculator API

A standalone FastAPI service that estimates the relative wear severity of an aircraft main-gear
or nose-gear tire from one operating cycle's conditions. It returns a severity category, estimated
wear rate and tread-life estimate, pressure guidance, and an inspection-planning recommendation.

This hackathon calculator is API-only and stateless. It has no frontend, authentication, database,
user accounts, saved history, or machine-learning runtime.

## Architecture

```text
app/
├── main.py                       # Application setup, CORS, request IDs, logging
├── config.py                     # Environment configuration
├── api/
│   ├── errors.py                 # Sanitized public error responses
│   └── routes/
│       ├── health.py             # Health endpoint
│       └── wear_severity.py      # Calculator HTTP endpoint
├── domain/schemas.py             # Strict public request/response contracts
└── services/
    ├── model_config.py           # Private model configuration
    └── wear_calculator.py        # Internal calculation service
```

The route layer validates and transports data. All calculation behavior is isolated in the service
layer, and intermediate model components are not returned or documented publicly.

## Requirements and installation

- Python 3.12 (Python 3.13 is also accepted for local development)
- [uv](https://docs.astral.sh/uv/)
- Docker, if using the container workflow

```bash
cp .env.example .env
uv sync
```

## Run locally

```bash
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Or use `make run`. The service is available at `http://localhost:8000`, with Swagger UI at
`http://localhost:8000/docs`.

## Run with Docker

```bash
docker build -t wear-severity-api .
docker run --rm -p 8000:8000 \
  -e CORS_ORIGINS=http://localhost:3000 \
  wear-severity-api
```

For local Compose execution:

```bash
docker compose up --build
```

The container runs as a non-root user and honors a platform-provided `PORT` value.

## Environment variables

| Variable | Default | Meaning |
| --- | --- | --- |
| `CORS_ORIGINS` | `http://localhost:3000` | Comma-separated allowed browser origins. Wildcards are rejected. |
| `PORT` | `8000` | Uvicorn listening port in the container or Make target. |

## API

The service exposes only these application endpoints:

- `GET /` — service metadata
- `GET /health` — liveness status
- `POST /api/v1/wear-severity/calculate` — wear-severity estimate

An optional `X-Request-ID` request header is echoed in the response. If absent, the service creates
one. Calculation IDs and request IDs are not stored.

### Input definitions

| Field | Meaning | Allowed value |
| --- | --- | --- |
| `gear` | Tire position | `main` or `nose` |
| `touchdown_speed_ms` | Touchdown speed | 58–82 m/s |
| `landing_weight_kg` | Aircraft landing weight | 50,000–73,500 kg |
| `crosswind_kt` | Crosswind component | 0–25 kt |
| `taxi_distance_km` | Taxi distance for the cycle | 0.5–8 km |
| `outside_air_temperature_c` | Outside-air temperature | 5–45 °C |
| `under_inflation_pct` | Amount below approved cold pressure | 0–10% |

Main-gear tires carry more aircraft load and use a higher baseline wear rate. Nose-gear tires carry
less load and use a lower baseline rate. Numeric inputs are strict: numeric strings, booleans,
nulls, non-finite numbers, missing fields, out-of-range values, and unknown fields are rejected.

### Request example

```bash
curl -X POST http://localhost:8000/api/v1/wear-severity/calculate \
  -H "Content-Type: application/json" \
  -d '{
    "gear": "main",
    "touchdown_speed_ms": 69,
    "landing_weight_kg": 62000,
    "crosswind_kt": 6,
    "taxi_distance_km": 2.8,
    "outside_air_temperature_c": 30,
    "under_inflation_pct": 0
  }'
```

### Response example

```json
{
  "calculation_id": "3c690c67-1932-48ae-a96b-d5865f4568cc",
  "gear": "main",
  "gear_label": "Main gear",
  "severity": {
    "index": 110,
    "level": "MODERATE",
    "label": "Moderate wear conditions"
  },
  "estimated_wear_rate_mm_per_cycle": 0.044,
  "estimated_total_tread_life_cycles": 225,
  "pressure_effect": {
    "multiplier": 1.0,
    "warning": false
  },
  "recommendation": {
    "attention": "NORMAL_MONITORING",
    "message": "Operating conditions are within the normal pilot range. Continue inspections according to the maintenance schedule."
  },
  "model_version": "pilot-1.0.0",
  "disclaimer": "This result is a physics-informed hackathon estimate. It does not replace physical inspection, aircraft maintenance manuals, or qualified engineering approval."
}
```

### Severity levels

| Index | Level | Planning meaning |
| --- | --- | --- |
| Below 90 | `LOW` | Continue routine monitoring. |
| 90–119 | `MODERATE` | Continue normal scheduled monitoring. |
| 120–169 | `HIGH` | Consider earlier tread-depth and pressure inspection. |
| 170 or above | `CRITICAL` | Prioritize qualified maintenance inspection. |

These recommendations support planning only. They never authorize skipping required maintenance,
extending tire life, or declaring an aircraft safe for flight or approved for service.

## Quality checks

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy app
uv run pytest -q
uv run python -m compileall app
```

Run all checks with `make check`.

## Known limitations and safety disclaimer

- The model covers only the documented pilot input ranges and two gear positions.
- It does not ingest tire manufacturer, aircraft model, runway surface, braking-system, weather
  history, measured tread depth, damage, or inspection data.
- Results are estimates for a hackathon demonstration and are not calibrated or validated for
  real-airline maintenance decisions.
- The service is stateless and does not trend results or retain inspection history.

This result is a physics-informed hackathon estimate. It does not replace physical inspection,
aircraft maintenance manuals, required maintenance intervals, or qualified engineering approval.
