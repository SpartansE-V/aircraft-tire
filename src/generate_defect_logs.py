"""Generate synthetic free-text defect logs FROM real removals.

Emits noisy, varied free-text log lines for a sample of removed tires — with the true structured
fields stored alongside — so the extractor can be validated against ground truth (the same
discipline as the RUL and CV layers). WORN tires log a wear reason; EARLY_REMOVAL tires log an
acute-damage reason (cut / bulge / FOD).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from treadcast import paths
from treadcast.config import get_generator_config
from treadcast.grounding.defect_logs import render_defect_log_line

N_LOGS = 60
DAMAGE_REASONS = ["cut", "bulge", "fod"]


def generate_defect_logs(cfg=None, n: int = N_LOGS) -> pd.DataFrame:
    cfg = cfg or get_generator_config()
    rng = np.random.default_rng(cfg.seed + 555)

    tires = pd.read_parquet(paths.TIRES)
    ac = pd.read_parquet(paths.AIRCRAFT).set_index("aircraft_id")["tail_number"].to_dict()
    removed = tires[tires["outcome"].isin(["worn", "early_removal"])].copy()
    removed = removed[removed["removal_date"].notna()]
    sample = removed.sample(n=min(n, len(removed)), random_state=int(cfg.seed % (2**31)))

    rows = []
    for _, t in sample.iterrows():
        reason = "worn_to_limit" if t["outcome"] == "worn" else str(rng.choice(DAMAGE_REASONS))
        tail = ac.get(t["aircraft_id"], "VN-A000")
        date = pd.Timestamp(t["removal_date"]).date().isoformat()
        retread = int(t["retread_level"]) if "retread_level" in t and pd.notna(t["retread_level"]) else 0
        raw = render_defect_log_line(
            date=date,
            tail=tail,
            position_code=t["position_code"],
            serial=str(t["serial"]),
            removal_reason=reason,
            cycles=int(t["time_to_event_cycles"]),
            retread_level=retread,
            rng=rng,
        )
        rows.append(
            {
                "raw_text": raw,
                "true_tail": tail,
                "true_position": t["position_code"],
                "true_serial": str(t["serial"]),
                "true_reason": reason,
                "true_cycles": int(t["time_to_event_cycles"]),
                "tire_id": t["tire_id"],
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    paths.ensure_dirs()
    df = generate_defect_logs()
    df.to_parquet(paths.DEFECT_LOGS, index=False)
    print(f"Wrote {len(df)} synthetic defect-log lines to {paths.DEFECT_LOGS}")


if __name__ == "__main__":
    main()
