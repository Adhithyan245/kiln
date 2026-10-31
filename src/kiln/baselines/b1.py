"""Explicit, freeze-attested B1 logistic regression on development folds.

Inputs and outcomes are supplied by the caller; no data files are read.
"""

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from math import exp, isfinite
from numbers import Real
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class FeatureRow(BaseModel):
    """Explicit feature values for one development pair, in declared order."""

    model_config = ConfigDict(frozen=True)

    item_id: str
    precursor_a: str
    precursor_b: str
    split: Literal["dev", "heldout"]
    values: tuple[float, ...]

    @field_validator("values", mode="before")
    @classmethod
    def validate_values(cls, values: object) -> object:
        if not isinstance(values, (tuple, list)) or any(
            isinstance(value, bool) or not isinstance(value, Real) or not isfinite(value)
            for value in values
        ):
            raise ValueError("feature values must be finite real numbers")
        return values


class PrecursorFold(BaseModel):
    """Indices into the original rows; test rows contain the held-out precursor."""

    model_config = ConfigDict(frozen=True)

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
        folds.append(PrecursorFold(precursor=precursor, train_indices=train, test_indices=test))
    return tuple(folds)


# Settings describe the entire fitted model, including the optimizer. The
# verifier is responsible for attesting that these settings are frozen.
class FeatureDefinition(BaseModel):
    """Caller-defined feature and its meaning; provenance is caller-owned."""

    # model_construct() and model_copy(update=...) skip validation, so existing
    # instances are validated again whenever they are passed back in.
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True, revalidate_instances="always")
    name: str
    description: str

    @field_validator("name", "description")
    @classmethod
    def nonempty_trimmed(cls, value: str) -> str:
        if not value or value != value.strip():
            raise ValueError("feature definitions must be nonempty and trimmed")
        return value


class B1Settings(BaseModel):
    """Explicit batch-gradient logistic regression settings, with no defaults.

    The objective is mean binary cross entropy plus l2/2 times the squared
    feature weights; the intercept is never penalized. Convergence requires
    the maximum absolute gradient component to be at most tolerance.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True, revalidate_instances="always")
    features: tuple[FeatureDefinition, ...]
    learning_rate: Annotated[float, Field(gt=0, allow_inf_nan=False)]
    l2: Annotated[float, Field(ge=0, allow_inf_nan=False)]
    tolerance: Annotated[float, Field(gt=0, allow_inf_nan=False)]
    max_iterations: Annotated[int, Field(gt=0)]
    fit_intercept: bool

    @model_validator(mode="after")
    def unique_features(self):
        names = [feature.name for feature in self.features]
        if not names or len(set(names)) != len(names):
            raise ValueError("features must be nonempty and uniquely named")
        return self

    def digest(self) -> str:
        payload = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), allow_nan=False)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class FoldPrediction(BaseModel):
    """One test-row score in one fold, not an aggregated item prediction."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    precursor: str
    item_id: str
    score: float


class B1ConfigurationError(ValueError):
    """The caller did not establish the required frozen-settings boundary."""


class B1ConvergenceError(RuntimeError):
    """Optimization failed or did not meet its configured convergence rule."""


def _sigmoid(value: float) -> float:
    if value >= 0:
        return 1.0 / (1.0 + exp(-value))
    e = exp(value)
    return e / (1.0 + e)


class B1Engine:
    """Fit only after a trusted caller verifies the exact settings digest.

    This boundary cannot establish a real freeze, feature provenance, or label
    access policy. The caller supplies targets and is responsible for those
    decisions. Scores are model outputs, not calibrated probabilities.

    Settings are validated again into a private copy before the digest is
    computed, so unvalidated instances are rejected and later changes to the
    caller's object cannot alter the verified model.
    """

    def __init__(self, settings: B1Settings, *, verify_frozen_settings: Callable[[str], bool] | None = None):
        if not isinstance(settings, B1Settings):
            raise TypeError("settings must be a B1Settings")
        try:
            settings = B1Settings.model_validate(settings)
        except Exception as exc:
            raise B1ConfigurationError("B1 settings failed validation") from exc
        digest = settings.digest()
        try:
            attested = verify_frozen_settings is not None and verify_frozen_settings(digest) is True
        except Exception as exc:
            raise B1ConfigurationError("Unable to verify that B1 settings are frozen") from exc
        if not attested:
            raise B1ConfigurationError(f"B1 settings {digest} have not been verified as frozen")
        self._settings = settings
        self._digest = digest

    @property
    def settings_digest(self) -> str:
        return self._digest

    def predict_folds(self, rows: Sequence[FeatureRow], targets: Mapping[str, int]) -> tuple[FoldPrediction, ...]:
        """Fit each development fold and return its individual test scores.

        Each pair occurs once per distinct precursor. No aggregation is defined.
        Targets must be exactly one integer 0 or 1 for every supplied row.
        """
        rows = tuple(rows)
        folds = leave_one_precursor_out(tuple(f.name for f in self._settings.features), rows)
        if not isinstance(targets, Mapping):
            raise ValueError("targets must be a mapping from item id to binary integer")
        targets = dict(targets)
        if set(targets) != {row.item_id for row in rows}:
            raise ValueError("targets must match the supplied item ids exactly")
        if any(type(value) is not int or value not in (0, 1) for value in targets.values()):
            raise ValueError("targets must be binary integers 0 or 1")
        for fold in folds:
            if {targets[rows[i].item_id] for i in fold.train_indices} != {0, 1}:
                raise ValueError(f"training fold {fold.precursor!r} must contain both classes")
        predictions = []
        for fold in folds:
            weights, intercept = self._fit(tuple(rows[i] for i in fold.train_indices), targets, fold.precursor)
            for i in fold.test_indices:
                row = rows[i]
                z = intercept + sum(w * x for w, x in zip(weights, row.values, strict=True))
                if not isfinite(z):
                    raise B1ConvergenceError(f"non-finite test score for fold {fold.precursor!r}")
                predictions.append(FoldPrediction(precursor=fold.precursor, item_id=row.item_id, score=_sigmoid(z)))
        return tuple(predictions)

    def _fit(self, rows: tuple[FeatureRow, ...], targets: Mapping[str, int], precursor: str) -> tuple[list[float], float]:
        settings = self._settings
        weights = [0.0] * len(settings.features)
        intercept = 0.0
        for iteration in range(settings.max_iterations + 1):
            gradients = [settings.l2 * weight for weight in weights]
            intercept_gradient = 0.0
            for row in rows:
                z = intercept + sum(w * x for w, x in zip(weights, row.values, strict=True))
                if not isfinite(z):
                    raise B1ConvergenceError(f"non-finite optimization in fold {precursor!r}")
                error = (_sigmoid(z) - targets[row.item_id]) / len(rows)
                for j, value in enumerate(row.values):
                    gradients[j] += error * value
                if settings.fit_intercept:
                    intercept_gradient += error
            if not all(isfinite(g) for g in (*gradients, intercept_gradient)):
                raise B1ConvergenceError(f"non-finite optimization in fold {precursor!r}")
            if max(abs(g) for g in (*gradients, intercept_gradient)) <= settings.tolerance:
                return weights, intercept
            if iteration == settings.max_iterations:
                break
            weights = [w - settings.learning_rate * g for w, g in zip(weights, gradients, strict=True)]
            intercept -= settings.learning_rate * intercept_gradient
        raise B1ConvergenceError(f"training fold {precursor!r} did not converge")
