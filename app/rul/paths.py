"""Central path resolution for data tables, model artifacts, and config files.

Project root is resolved relative to this file (``app/rul/paths.py`` -> project root),
so every module reads/writes the same locations regardless of the current working directory.
"""

from __future__ import annotations

from pathlib import Path

# app/rul/paths.py -> parents[2] == the repository root (where data/, artifacts/, config/ live)
PROJECT_ROOT = Path(__file__).resolve().parents[2]

DATA_DIR = PROJECT_ROOT / "data"
ARTIFACTS_DIR = PROJECT_ROOT / "artifacts"
CONFIG_DIR = PROJECT_ROOT / "config"

# --- Data tables (Parquet) ---
FLEETS = DATA_DIR / "fleets.parquet"
AIRCRAFT = DATA_DIR / "aircraft.parquet"
WHEEL_POSITIONS = DATA_DIR / "wheel_positions.parquet"
TIRES = DATA_DIR / "tires.parquet"
INSPECTION_RECORDS = DATA_DIR / "inspection_records.parquet"
OPERATIONAL_CYCLES = DATA_DIR / "operational_cycles.parquet"
STATION_STOCK = DATA_DIR / "station_stock.parquet"
TIRE_SCANS = DATA_DIR / "tire_scans.parquet"  # imaging/scanning records (CV layer)
SCANS_DIR = DATA_DIR / "scans"  # optional saved scan images
DEFECT_LOGS = DATA_DIR / "defect_logs.parquet"  # free-text defect logs + extraction ground truth
GROUND_TRUTH = DATA_DIR / "_ground_truth.parquet"  # hidden sidecar: validation ONLY

CORE_TABLES = [
    FLEETS,
    AIRCRAFT,
    WHEEL_POSITIONS,
    TIRES,
    INSPECTION_RECORDS,
    OPERATIONAL_CYCLES,
    STATION_STOCK,
]

# --- Model artifacts ---
MIXEDLM = ARTIFACTS_DIR / "mixedlm.pkl"
MIXEDLM_COV = ARTIFACTS_DIR / "mixedlm_covariance.pkl"  # per-tire params + cov for MC sampling
WEIBULL_AFT = ARTIFACTS_DIR / "weibull_aft.pkl"
LIGHTGBM = ARTIFACTS_DIR / "lightgbm.txt"
SHAP_VALUES = ARTIFACTS_DIR / "shap_values.parquet"
EVAL_REPORT = ARTIFACTS_DIR / "eval_report.json"

# --- Config files ---
CONFIG_GENERATOR = CONFIG_DIR / "generator.yaml"
CONFIG_THRESHOLDS = CONFIG_DIR / "thresholds.yaml"
CONFIG_KNOWLEDGE = CONFIG_DIR / "knowledge.yaml"  # AMM / MEL / CDL grounding


def ensure_dirs() -> None:
    """Create data/ and artifacts/ on demand (idempotent)."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
