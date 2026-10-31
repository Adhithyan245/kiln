"""Tammann-temperature heuristic for precursor melting points."""

from __future__ import annotations

import math
from typing import Literal


def tammann_c(melting_point_c: float | None) -> float | None:
    """Return two-thirds of the absolute melting temperature in °C.

    Missing melting points remain unknown. Invalid temperatures are rejected.
    This calculation cannot verify that an input describes actual melting;
    callers should check its source before interpreting the result.
    """
    if melting_point_c is None:
        return None
    if isinstance(melting_point_c, bool) or not isinstance(melting_point_c, (int, float)):
        raise ValueError("melting_point_c must be a finite number or None")
    if not math.isfinite(melting_point_c) or melting_point_c <= -273.15:
        raise ValueError("melting_point_c must be finite and above absolute zero")
    return (2.0 / 3.0) * (melting_point_c + 273.15) - 273.15


def checked_tammann_c(
    melting_point_c: float | None, *, melting_verified: bool = False
) -> tuple[float | None, Literal["ok", "missing", "melting_unverified"]]:
    """Return a result only when its input is confirmed as a melting point.

    Verification must come from an independently checked source; the dataset
    column name alone does not establish it. The status can drive review flags.
    """
    value = tammann_c(melting_point_c)
    if value is None:
        return None, "missing"
    if melting_verified is not True:
        return None, "melting_unverified"
    return value, "ok"
