"""Tyre-quality detection class labels supported by the Roboflow model."""

from enum import StrEnum


class TyreQualityClass(StrEnum):
    """YOLO prediction classes for tyre quality assessment."""

    BAD_TYRE = "bad_tyre"
    GOOD_TYRE = "good_tyre"
    TYRE_UNCLEAR_TREAD = "tyre_unclear_tread"

    @classmethod
    def values(cls) -> tuple[str, ...]:
        """Return all supported class label strings."""

        return tuple(member.value for member in cls)
