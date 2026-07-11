"""Shared enums and physical constants for the TreadCast pipeline.

Every categorical value used across generate_data / features / train / scoring / app
is defined here so no module hardcodes magic strings. Enum ``.value`` is snake_case
(matches the naming convention used for the on-disk Parquet columns).
"""

from __future__ import annotations

import enum


class WheelPosition(str, enum.Enum):
    """The 6 wheels modelled per aircraft: 2 nose + 4 main gear (A320-class)."""

    NLG_L = "nlg_l"
    NLG_R = "nlg_r"
    MLG_L_INBD = "mlg_l_inbd"
    MLG_L_OUTBD = "mlg_l_outbd"
    MLG_R_INBD = "mlg_r_inbd"
    MLG_R_OUTBD = "mlg_r_outbd"

    @property
    def is_nose(self) -> bool:
        return self.value.startswith("nlg")

    @property
    def gear(self) -> str:
        return "nose" if self.is_nose else "main"

    @property
    def mate(self) -> WheelPosition:
        """The co-axle mate — the tire that carries extra load if this one deflates."""
        return _MATE[self]


_MATE = {
    WheelPosition.NLG_L: WheelPosition.NLG_R,
    WheelPosition.NLG_R: WheelPosition.NLG_L,
    WheelPosition.MLG_L_INBD: WheelPosition.MLG_L_OUTBD,
    WheelPosition.MLG_L_OUTBD: WheelPosition.MLG_L_INBD,
    WheelPosition.MLG_R_INBD: WheelPosition.MLG_R_OUTBD,
    WheelPosition.MLG_R_OUTBD: WheelPosition.MLG_R_INBD,
}

ALL_POSITIONS: list[WheelPosition] = list(WheelPosition)
MAIN_GEAR_POSITIONS: list[WheelPosition] = [p for p in WheelPosition if not p.is_nose]
NOSE_GEAR_POSITIONS: list[WheelPosition] = [p for p in WheelPosition if p.is_nose]


class AircraftType(str, enum.Enum):
    A320_FAMILY = "a320_family"


class TireOutcome(str, enum.Enum):
    """Terminal state of a tire installation in the historical window."""

    WORN = "worn"  # reached the serviceable wear limit -> normal removal (event observed)
    EARLY_REMOVAL = "early_removal"  # FOD / damage removed it before wear-out (competing risk)
    IN_SERVICE = "in_service"  # still mounted at horizon -> right-censored


class AlertType(str, enum.Enum):
    EARLIEST_DATE_IN_WINDOW = "earliest_date_in_window"
    P_CROSS_HIGH = "p_cross_high"
    WEAR_ACCEL = "wear_accel"
    STATION_STOCKOUT = "station_stockout"
    PRESSURE_LADDER = "pressure_ladder"
    HARD_REMOVAL = "hard_removal"


class AlertCategory(str, enum.Enum):
    """Wear-out (probabilistic model) alerts are kept SEPARATE from event-driven
    (deterministic rule) alerts — they are never blended, so accuracy claims stay honest."""

    WEAR_OUT = "wear_out"
    EVENT_DRIVEN = "event_driven"


class Severity(str, enum.Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class PressureLadderAction(str, enum.Enum):
    """Goodyear/FAA cold-pressure action ladder outcomes (see thresholds.yaml)."""

    OK = "ok"
    REINFLATE = "reinflate"
    INSPECT = "inspect"
    REMOVE = "remove"
    REMOVE_TIRE_AND_MATE = "remove_tire_and_mate"


class HardRemovalReason(str, enum.Enum):
    WORN_TO_BASE = "worn_to_base"
    BULGE = "bulge"
    CORD_EXPOSED = "cord_exposed"
    POST_HARD_LANDING = "post_hard_landing"


# --- Physical anchors (cited ranges; see config/generator.yaml comments) ---
WEAR_LIMIT_MM = 2.0  # serviceable groove-depth removal limit
NEW_TREAD_MM_MIN = 11.0  # new main-gear tread depth (low end)
NEW_TREAD_MM_MAX = 14.0  # new main-gear tread depth (high end)
GAUGE_NOISE_SD_MM = 0.25  # tread-depth gauge measurement noise (kept separate from process noise)
