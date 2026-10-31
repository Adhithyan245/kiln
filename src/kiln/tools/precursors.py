"""Read sourced, single-precursor properties without using outcome data."""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from pathlib import Path

DEFAULT_TABLE = Path(__file__).resolve().parents[3] / "data" / "precursor_props.csv"
_LEGACY_COLUMNS = {"formula", "decomposes_at_c", "decomposition_product", "volatile_above_c", "source"}
_COLUMNS = {
    "formula",
    "decomposes_at_c",
    "decomposition_product",
    "decomposition_source",
    "volatile_above_c",
    "volatility_source",
    "melting_point_c",
    "melting_point_source",
    "melting_point_source_url",
    "melting_point_semantics",
    "melting_point_semantics_source",
    "melting_point_semantics_note",
}


@dataclass(frozen=True)
class PrecursorProps:
    """Known properties; None means missing, not that a risk is absent."""

    formula: str
    decomposes_at_c: float | None = None
    decomposition_product: str | None = None
    volatile_above_c: float | None = None
    source: str | None = None
    melting_point_c: float | None = None
    melting_point_source: str | None = None
    melting_point_source_url: str | None = None
    melting_point_semantics: str | None = None
    melting_point_semantics_source: str | None = None
    melting_point_semantics_note: str | None = None
    decomposition_source: str | None = None
    volatility_source: str | None = None


def _optional(value: str | None) -> str | None:
    value = (value or "").strip()
    return None if not value or value.lower() == "unknown" else value


def _temperature(value: str | None, field: str) -> float | None:
    value = _optional(value)
    if value is None:
        return None
    try:
        result = float(value)
    except ValueError as exc:
        raise ValueError(f"Invalid {field}") from exc
    if not math.isfinite(result) or result <= -273.15:
        raise ValueError(f"Invalid {field}")
    return result


def props(formula: str, *, path: str | Path = DEFAULT_TABLE) -> PrecursorProps:
    """Return exact-formula properties from the CSV; unknown formulas stay unknown.

    Melting-point values retain the dataset citation and are returned with a
    narrow semantics flag for values that may represent decomposition or
    dehydration. Malformed tables, duplicates and unsourced properties fail
    explicitly. A missing file is an error rather than an empty dataset.
    """
    if not isinstance(formula, str) or not formula.strip():
        raise ValueError("formula must be a non-empty string")
    formula = formula.strip()
    found: PrecursorProps | None = None
    seen: set[str] = set()
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        columns = set(reader.fieldnames or ())
        if columns != _COLUMNS and columns != _LEGACY_COLUMNS:
            raise ValueError("Invalid precursor table columns")
        legacy_table = columns == _LEGACY_COLUMNS
        for row in reader:
            name = _optional(row.get("formula"))
            if name is None or name in seen or None in row:
                raise ValueError("Missing or duplicate precursor formula or malformed row")
            seen.add(name)
            if name != formula:
                continue
            decomposition = _temperature(row.get("decomposes_at_c"), "decomposes_at_c")
            product = _optional(row.get("decomposition_product"))
            volatility = _temperature(row.get("volatile_above_c"), "volatile_above_c")
            legacy_source = _optional(row.get("source"))
            decomposition_source = None if legacy_table else _optional(row.get("decomposition_source"))
            volatility_source = None if legacy_table else _optional(row.get("volatility_source"))
            melting = _temperature(row.get("melting_point_c"), "melting_point_c")
            melting_source = _optional(row.get("melting_point_source"))
            melting_source_url = _optional(row.get("melting_point_source_url"))
            semantics = _optional(row.get("melting_point_semantics"))
            semantics_source = _optional(row.get("melting_point_semantics_source"))
            semantics_note = _optional(row.get("melting_point_semantics_note"))
            if decomposition is not None or product is not None:
                if decomposition_source is None and legacy_source is None:
                    raise ValueError(f"Decomposition properties lack a source: {name}")
            if volatility is not None and volatility_source is None and legacy_source is None:
                raise ValueError(f"Volatility property lacks a source: {name}")
            if melting is not None and (melting_source is None or melting_source_url is None):
                raise ValueError(f"Melting point lacks a source: {name}")
            if semantics not in (None, "as_reported", "possible_decomposition_or_dehydration"):
                raise ValueError(f"Invalid melting-point semantics: {name}")
            if semantics == "possible_decomposition_or_dehydration" and semantics_source is None:
                raise ValueError(f"Melting-point semantics flag lacks a source: {name}")
            found = PrecursorProps(
                name,
                decomposition,
                product,
                volatility,
                legacy_source or decomposition_source or volatility_source,
                melting,
                melting_source,
                melting_source_url,
                semantics,
                semantics_source,
                semantics_note,
                decomposition_source,
                volatility_source,
            )
    return found if found is not None else PrecursorProps(formula)
