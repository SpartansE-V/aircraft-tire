"""Tread-depth detection class labels supported by the Roboflow model."""

from enum import StrEnum


class TreadDepthClass(StrEnum):
    """YOLO prediction classes for tread-depth assessment."""

    DEPTH_0_2_MM = "0-2 mm"
    DEPTH_2_3_MM = "2-3 mm"
    DEPTH_3_4_MM = "3-4 mm"
    DEPTH_7_8_MM = "7-8 mm"

    @classmethod
    def values(cls) -> tuple[str, ...]:
        """Return all documented class label strings."""

        return tuple(member.value for member in cls)
