"""B0 (driving-force threshold) and B0-T (Tammann rule) baselines.

Both are fixed, fit-free rules over explicitly supplied numbers. No energy
threshold, Tammann fraction or comparison rule has been frozen in the protocol,
so each must be passed in a config; nothing here has a default. Neither rule
reads labels, calls the compute service or looks anything up. B0 takes reaction
energies the caller already obtained through logged compute requests; B0-T takes
the melting points carried on each ``Item``.

Outputs are decisions, not ``Prediction`` objects. Turning a margin into
``p_react`` and a binary decision into a four-class ``Category`` needs protocol
decisions that have not been made. The margin is a ranking score in physical
units, not a probability. A missing input gives an undetermined decision with a
``missing_evidence`` review flag; it is never imputed or dropped.
"""
from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from kiln.schemas import Item, ReviewFlag, ReviewReason

KELVIN_OFFSET = 273.15  # °C to K; a unit conversion, not a tuned value

FiniteFloat = Annotated[float, Field(strict=True, allow_inf_nan=False)]
Id = Annotated[str, Field(strict=True, min_length=1, pattern=r"^\S(?:.*\S)?$")]  # nonempty, trimmed


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


# ---------- Configuration (no defaults: unfrozen values must be supplied) ----------

class DrivingForceConfig(_Frozen):
    """B0 settings. The protocol has not frozen a threshold."""
    dE_threshold_ev_per_atom: FiniteFloat   # predict a reaction when dE_ev_per_atom <= this


class TammannConfig(_Frozen):
    """B0-T settings. The protocol has frozen neither value."""
    tammann_fraction: Annotated[float, Field(strict=True, allow_inf_nan=False, gt=0, le=1)]
    # T_Tammann(K) = tammann_fraction * T_melt(K)
    require: Literal["either", "both"]
    # "either": furnace must reach the lower of the two Tammann temperatures;
    # "both": it must reach the higher one.


# ---------- Inputs ----------

class DrivingForceInput(_Frozen):
    """The reaction energy for one item and where it came from.

    ``dE_ev_per_atom`` has no default: an unavailable energy must be stated as
    None. ``evidence`` lists the compute request ids (or other provenance
    references) the value was taken from, and a value without evidence is
    rejected. This module cannot check that the ids exist or match the value;
    the verifier and evaluator own that check.
    """
    item_id: Id
    dE_ev_per_atom: FiniteFloat | None
    evidence: tuple[Id, ...]

    @model_validator(mode="after")
    def _check_evidence(self) -> DrivingForceInput:
        if len(set(self.evidence)) != len(self.evidence):
            raise ValueError("evidence ids must be unique")
        if self.dE_ev_per_atom is not None and not self.evidence:
            raise ValueError("a supplied reaction energy needs at least one evidence id")
        return self


# ---------- Outputs ----------

def _check_decision(margin: float | None, reacts: bool | None, flags: tuple[ReviewFlag, ...]) -> None:
    if (margin is None) != (reacts is None):
        raise ValueError("margin and reacts must both be set or both be None")
    if reacts is None and not flags:
        raise ValueError("an undetermined decision must carry a review flag")
    if margin is not None and reacts != (margin >= 0):
        raise ValueError("reacts must equal margin >= 0")


class DrivingForceDecision(_Frozen):
    """B0 result for one item.

    ``margin_ev_per_atom`` is threshold minus dE, so positive means a larger
    driving force than the threshold asks for. Ranking by it does not depend on
    the threshold. It is not a probability.
    """
    item_id: str
    condition: Literal["B0"]
    dE_ev_per_atom: float | None
    dE_threshold_ev_per_atom: float
    margin_ev_per_atom: float | None
    reacts: bool | None
    evidence: tuple[str, ...]
    review_flags: tuple[ReviewFlag, ...]

    @model_validator(mode="after")
    def _check(self) -> DrivingForceDecision:
        if (self.dE_ev_per_atom is None) != (self.margin_ev_per_atom is None):
            raise ValueError("margin_ev_per_atom must be set exactly when dE_ev_per_atom is")
        _check_decision(self.margin_ev_per_atom, self.reacts, self.review_flags)
        return self


class TammannDecision(_Frozen):
    """B0-T result for one item.

    ``margin_c`` is the furnace temperature minus the governing Tammann
    temperature (a difference, so the same in °C and K). Ranking by it depends
    on the configured fraction and rule. It is not a probability.
    """
    item_id: str
    condition: Literal["B0-T"]
    temperature_c: float
    melting_point_a_c: float | None
    melting_point_b_c: float | None
    tammann_fraction: float
    require: Literal["either", "both"]
    tammann_a_c: float | None
    tammann_b_c: float | None
    governing_tammann_c: float | None
    margin_c: float | None
    reacts: bool | None
    review_flags: tuple[ReviewFlag, ...]

    @model_validator(mode="after")
    def _check(self) -> TammannDecision:
        if (self.governing_tammann_c is None) != (self.margin_c is None):
            raise ValueError("margin_c must be set exactly when governing_tammann_c is")
        _check_decision(self.margin_c, self.reacts, self.review_flags)
        return self


# ---------- Rules ----------

def _expect(value: object, cls: type, name: str) -> None:
    if not isinstance(value, cls):
        raise TypeError(f"{name} must be a {cls.__name__}, got {type(value).__name__}")


def _read_items(items: Iterable[Item]) -> list[Item]:
    """Read ``items`` exactly once, so a generator is validated and decided in full."""
    read = list(items)
    if not read:
        raise ValueError("at least one item is required")
    seen: set[str] = set()
    for item in read:
        _expect(item, Item, "item")
        if item.item_id in seen:
            raise ValueError(f"duplicate item_id: {item.item_id!r}")
        seen.add(item.item_id)
    return read


def _absolute_c(value: float, name: str) -> float:
    if isinstance(value, bool) or not math.isfinite(value) or value + KELVIN_OFFSET <= 0:
        raise ValueError(f"{name} must be a finite temperature above absolute zero, got {value!r}")
    return value


def _tammann_c(melting_point_c: float, fraction: float) -> float:
    """Tammann temperature in °C: ``fraction`` of the melting point in kelvin."""
    return fraction * (melting_point_c + KELVIN_OFFSET) - KELVIN_OFFSET


def b0_driving_force(item: Item, energy: DrivingForceInput, config: DrivingForceConfig) -> DrivingForceDecision:
    """B0: predict a reaction when the supplied reaction energy is at or below the threshold.

    Furnace temperature is not used; the energies are the cached (0 K) values.
    """
    _expect(item, Item, "item")
    _expect(energy, DrivingForceInput, "energy")
    _expect(config, DrivingForceConfig, "config")
    if energy.item_id != item.item_id:
        raise ValueError(f"energy is for {energy.item_id!r}, not {item.item_id!r}")
    threshold = config.dE_threshold_ev_per_atom
    dE = energy.dE_ev_per_atom
    if dE is None:
        flag = ReviewFlag(
            reason=ReviewReason.missing_evidence,
            detail="No reaction energy was supplied, so B0 cannot decide.",
            evidence=list(energy.evidence),
        )
        return DrivingForceDecision(
            item_id=item.item_id, condition="B0", dE_ev_per_atom=None,
            dE_threshold_ev_per_atom=threshold, margin_ev_per_atom=None, reacts=None,
            evidence=energy.evidence, review_flags=(flag,),
        )
    return DrivingForceDecision(
        item_id=item.item_id, condition="B0", dE_ev_per_atom=dE,
        dE_threshold_ev_per_atom=threshold, margin_ev_per_atom=threshold - dE, reacts=dE <= threshold,
        evidence=energy.evidence, review_flags=(),
    )


def run_b0(
    items: Iterable[Item], energies: Iterable[DrivingForceInput], config: DrivingForceConfig
) -> list[DrivingForceDecision]:
    """Apply B0 to every item, in order. Each item needs exactly one energy entry
    (use ``dE_ev_per_atom=None`` for an unavailable energy); entries for unknown
    items are rejected."""
    items = _read_items(items)
    item_ids = {item.item_id for item in items}
    supplied: dict[str, DrivingForceInput] = {}
    for energy in energies:
        _expect(energy, DrivingForceInput, "energy")
        if energy.item_id in supplied:
            raise ValueError(f"duplicate energy entry for {energy.item_id!r}")
        supplied[energy.item_id] = energy
    missing = sorted(item_ids - set(supplied))
    if missing:
        raise ValueError(f"no energy entry for {missing}; state dE_ev_per_atom=None for unavailable energies")
    unknown = sorted(set(supplied) - item_ids)
    if unknown:
        raise ValueError(f"energy entries for unknown items: {unknown}")
    return [b0_driving_force(item, supplied[item.item_id], config) for item in items]


def b0_tammann(item: Item, config: TammannConfig) -> TammannDecision:
    """B0-T: predict a reaction when the furnace temperature reaches the governing
    Tammann temperature (the lower of the pair for "either", the higher for "both").

    Temperatures are converted to kelvin only for the Tammann fraction. A missing
    melting point leaves the decision undetermined, even when the other precursor
    alone would settle it, so every determined decision has a margin.
    """
    _expect(item, Item, "item")
    _expect(config, TammannConfig, "config")
    temperature_c = _absolute_c(item.temperature_c, "temperature_c")
    melting = (item.melting_point_a_c, item.melting_point_b_c)
    for name, value in zip(("melting_point_a_c", "melting_point_b_c"), melting):
        if value is not None:
            _absolute_c(value, name)
    tammann_a_c, tammann_b_c = (None if mp is None else _tammann_c(mp, config.tammann_fraction) for mp in melting)
    absent = [
        f"{name} ({formula})"
        for name, formula, value in zip(
            ("melting_point_a_c", "melting_point_b_c"), (item.precursor_a, item.precursor_b), melting
        )
        if value is None
    ]
    common = dict(
        item_id=item.item_id, condition="B0-T", temperature_c=temperature_c,
        melting_point_a_c=melting[0], melting_point_b_c=melting[1],
        tammann_fraction=config.tammann_fraction, require=config.require,
        tammann_a_c=tammann_a_c, tammann_b_c=tammann_b_c,
    )
    if absent:
        flag = ReviewFlag(
            reason=ReviewReason.missing_evidence,
            detail=f"Missing {', '.join(absent)}, so B0-T cannot decide.",
        )
        return TammannDecision(**common, governing_tammann_c=None, margin_c=None, reacts=None, review_flags=(flag,))
    assert tammann_a_c is not None and tammann_b_c is not None
    governing = min(tammann_a_c, tammann_b_c) if config.require == "either" else max(tammann_a_c, tammann_b_c)
    return TammannDecision(
        **common, governing_tammann_c=governing, margin_c=temperature_c - governing,
        reacts=temperature_c >= governing, review_flags=(),
    )


def run_b0_t(items: Iterable[Item], config: TammannConfig) -> list[TammannDecision]:
    """Apply B0-T to every item, in order."""
    return [b0_tammann(item, config) for item in _read_items(items)]
