"""Input validation and precursor-separated development folds for B1.

B1 is specified as logistic regression, but its feature set and a trusted
code-freeze verification mechanism are not yet defined. This module therefore
provides no fitting, prediction, or evaluation entry point. Callers must supply
explicit, outcome-independent features; validation cannot establish provenance
or prove that a feature does not encode an outcome.
"""

from dataclasses import dataclass
from math import isfinite
from numbers import Real
from collections.abc import Sequence


@dataclass(frozen=True)
class FeatureRow:
    """Explicit feature values for one development pair, in declared order."""

    item_id: str
    precursor_a: str
    precursor_b: str
    split: str
    values: tuple[float, ...]


@dataclass(frozen=True)
class PrecursorFold:
    """Indices into the original rows; test rows contain the held-out precursor."""

    precursor: str
    train_indices: tuple[int, ...]
    test_indices: tuple[int, ...]


def validate_features(feature_names: Sequence[str], rows: Sequence[FeatureRow]) -> None:
    """Reject ambiguous or incomplete inputs; feature provenance remains external.

    Feature names and values are supplied separately from outcomes. No feature
    set or number of features is assumed before the protocol is frozen.
    """
    if not feature_names or any(not isinstance(name, str) or not name.strip() or name != name.strip() for name in feature_names):
        raise ValueError("feature names must be nonempty, trimmed strings")
    if len(set(feature_names)) != len(feature_names):
        raise ValueError("feature names must be unique")
    if not rows:
        raise ValueError("at least one development row is required")
    seen = set()
    for row in rows:
        if not isinstance(row, FeatureRow):
            raise ValueError("rows must be FeatureRow instances")
        if any(not isinstance(value, str) or not value.strip() or value != value.strip() for value in (row.item_id, row.precursor_a, row.precursor_b)):
            raise ValueError("item and precursor identifiers must be nonempty, trimmed strings")
        if row.item_id in seen:
            raise ValueError("item identifiers must be unique")
        seen.add(row.item_id)
        if row.split != "dev":
            raise ValueError("B1 development inputs must have split 'dev'")
        if len(row.values) != len(feature_names):
            raise ValueError("each row must match the declared feature count")
        if any(isinstance(value, bool) or not isinstance(value, Real) or not isfinite(value) for value in row.values):
            raise ValueError("feature values must be finite real numbers")


def leave_one_precursor_out(feature_names: Sequence[str], rows: Sequence[FeatureRow]) -> tuple[PrecursorFold, ...]:
    """Build deterministic folds, excluding either occurrence from training.

    A pair appears in the test set of each distinct precursor it contains, so
    fold outputs must not be treated as independent item-level predictions.
    Folds without training data are rejected rather than silently omitted.
    """
    validate_features(feature_names, rows)
    precursors = sorted({p for row in rows for p in (row.precursor_a, row.precursor_b)})
    folds = []
    for precursor in precursors:
        test = tuple(i for i, row in enumerate(rows) if precursor in (row.precursor_a, row.precursor_b))
        train = tuple(i for i, row in enumerate(rows) if precursor not in (row.precursor_a, row.precursor_b))
        if not train:
            raise ValueError(f"no training rows remain for precursor {precursor!r}")
        folds.append(PrecursorFold(precursor, train, test))
    return tuple(folds)
