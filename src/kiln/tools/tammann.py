"""Tammann-temperature heuristic for precursor melting points."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from kiln.schemas import Item


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
    melting_point_c: float | None, *, semantics: str = "as_reported"
) -> tuple[float | None, Literal["ok", "missing", "possible_decomposition_or_dehydration"]]:
    """Keep the reported input and flag only the documented narrow caution."""
    if semantics not in ("as_reported", "possible_decomposition_or_dehydration"):
        raise ValueError("Unknown melting point semantics")
    value = tammann_c(melting_point_c)
    if value is None:
        return None, "missing"
    if semantics == "possible_decomposition_or_dehydration":
        return value, "possible_decomposition_or_dehydration"
    return value, "ok"


def item_tool_values(item: Item) -> dict[str, float | None]:
    """Recompute the per-precursor values expected by the deterministic verifier."""
    from kiln.tools.precursors import props

    values: dict[str, float | None] = {}
    for side, formula, fallback in (("a", item.precursor_a, item.melting_point_a_c),
                                    ("b", item.precursor_b, item.melting_point_b_c)):
        p = props(formula)
        melting = p.melting_point_c if p.melting_point_c is not None else fallback
        values[f"tammann_{side}_c"] = tammann_c(melting)
    return values
