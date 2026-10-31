"""B0 (driving-force threshold), B0-T (temperature ratio) and B60meV
(thermodynamic-competition margin) baselines.

All three are fixed, fit-free rules over explicitly supplied numbers. No energy
threshold, temperature-ratio threshold or competition-margin threshold has been
frozen in the protocol, so each must be passed in a config; nothing here has a
default. None of them reads labels, calls the compute service or looks anything
up. B0 and B60meV take reaction energies the caller already obtained through
logged compute requests; B0-T takes the temperatures carried on each ``Item``.

B0-T ranks items by ``T_dwell / T_melt(higher)``, both in kelvin: the furnace
setpoint over the higher of the two precursor melting points. The ratio itself
needs no fitted value; only the decision threshold comes from config. It
replaces an earlier Tammann-fraction rule. Reason for the swap (reviewer-sourced,
UNVERIFIED, not checked against the dataset's own documentation): the dataset's
firing temperature is reportedly set by Tammann's rule, which would make a rule
that compares the furnace temperature with a Tammann temperature circular.

B60meV is a margin feature, a marker of the thermodynamic-control regime, and
not a validated rule for whether a pair reacts. Its margin is the driving force
of the best (most negative) reaction minus that of the best competing reaction.
Szymanski et al., Science Advances 10(27), 2024, DOI 10.1126/sciadv.adp3309,
report from an in situ study of 37 reactant pairs (ternary metal oxides) that
the FIRST product to form can be predicted when its driving force exceeds that
of every competing phase by at least 60 meV/atom (0.060 eV/atom), and that 15%
of possible Materials Project reactions fall in that regime. That 15% is a
Materials Project statistic, not a rate for this dataset, and the study says
which product forms first, not whether a pair reacts. The label "B60meV" names
that literature regime; the threshold actually used comes from config and is
recorded on every result. The selectivity metrics (primary and secondary
competition) of McDermott et al., ACS Central Science 9(10), 2023, DOI
10.1021/acscentsci.3c01051, frame the same idea; this module does not compute
them.

Outputs are decisions or features, not ``Prediction`` objects, and
``to_predictions`` fails closed: the shared schema says only ``score.py`` builds
Predictions from verifier-accepted artifacts, and turning a margin or ratio into
``p_react`` and a decision into a four-class ``Category`` needs protocol
decisions (OPEN-08) that have not been made. Margins and ratios are ranking
scores in physical units, not probabilities. A missing input gives an
undetermined result with a ``missing_evidence`` review flag; it is never imputed
or dropped.
"""
from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from kiln.schemas import Item, Prediction, ReviewFlag, ReviewReason, RunConfig

KELVIN_OFFSET = 273.15  # °C to K; a unit conversion, not a tuned value

FiniteFloat = Annotated[float, Field(strict=True, allow_inf_nan=False)]
PositiveFloat = Annotated[float, Field(strict=True, allow_inf_nan=False, gt=0)]
Id = Annotated[str, Field(strict=True, min_length=1, pattern=r"^\S(?:.*\S)?$")]  # nonempty, trimmed

B60MEV_CONDITION = "B60meV"  # not a schemas.ConditionId; see PREDICTION_BLOCKERS


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


# ---------- Configuration (no defaults: unfrozen values must be supplied) ----------

class DrivingForceConfig(_Frozen):
    """B0 settings. The protocol has not frozen a threshold."""
    dE_threshold_ev_per_atom: FiniteFloat   # predict a reaction when dE_ev_per_atom <= this


class TemperatureRatioConfig(_Frozen):
    """B0-T settings. The protocol has not frozen a threshold (OPEN-08)."""
    ratio_threshold: PositiveFloat
    # predict a reaction when T_dwell(K) / T_melt_higher(K) >= this


class CompetitionMarginConfig(_Frozen):
    """B60meV settings. The protocol has not frozen a threshold.

    Szymanski et al. 2024 report 0.060 eV/atom for first-product selection; it
    is not a default here and must be supplied. A margin is nonnegative by
    construction, so a threshold must be positive to separate anything.
    """
    margin_threshold_ev_per_atom: PositiveFloat
    # the regime marker is set when margin_ev_per_atom >= this


# ---------- Inputs ----------

def _check_evidence(value: float | None, evidence: tuple[str, ...], what: str) -> None:
    if len(set(evidence)) != len(evidence):
        raise ValueError(f"{what} evidence ids must be unique")
    if value is not None and not evidence:
        raise ValueError(f"a supplied {what} needs at least one evidence id")


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
    def _check(self) -> DrivingForceInput:
        _check_evidence(self.dE_ev_per_atom, self.evidence, "reaction energy")
        return self


class CompetitionMarginInput(_Frozen):
    """The two reaction energies B60meV needs for one item, each with its evidence.

    ``dE_best_ev_per_atom`` is the most negative reaction energy among the
    candidate reactions of the pair, and ``dE_competing_ev_per_atom`` the most
    negative among the others, both in eV/atom. Neither has a default: an
    unavailable energy must be stated as None. As for ``DrivingForceInput``,
    each supplied value needs at least one evidence id (compute request ids), and
    this module cannot check that the ids exist or match the values. Because the
    best reaction is the most negative, a best energy above the competing one is
    rejected as a wiring error rather than read as a negative margin.
    """
    item_id: Id
    dE_best_ev_per_atom: FiniteFloat | None
    best_evidence: tuple[Id, ...]
    dE_competing_ev_per_atom: FiniteFloat | None
    competing_evidence: tuple[Id, ...]

    @model_validator(mode="after")
    def _check(self) -> CompetitionMarginInput:
        _check_evidence(self.dE_best_ev_per_atom, self.best_evidence, "best reaction energy")
        _check_evidence(self.dE_competing_ev_per_atom, self.competing_evidence, "competing reaction energy")
        best, competing = self.dE_best_ev_per_atom, self.dE_competing_ev_per_atom
        if best is not None and competing is not None and best > competing:
            raise ValueError(
                f"dE_best_ev_per_atom ({best}) must not exceed dE_competing_ev_per_atom ({competing}): "
                "the best reaction is the most negative one"
            )
        return self


# ---------- Outputs ----------

def _check_undetermined(determined: bool, flags: tuple[ReviewFlag, ...]) -> None:
    if not determined and not flags:
        raise ValueError("an undetermined result must carry a review flag")


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
        if (self.margin_ev_per_atom is None) != (self.reacts is None):
            raise ValueError("margin and reacts must both be set or both be None")
        _check_undetermined(self.reacts is not None, self.review_flags)
        if self.margin_ev_per_atom is not None and self.reacts != (self.margin_ev_per_atom >= 0):
            raise ValueError("reacts must equal margin >= 0")
        return self


class TemperatureRatioDecision(_Frozen):
    """B0-T result for one item.

    ``ratio`` is ``(temperature_c + 273.15) / (melting_point_higher_c + 273.15)``,
    the furnace setpoint over the higher melting point, both in kelvin. It is
    the ranking score and does not depend on the threshold. It is not a
    probability. It is set only when both melting points are known, because a
    missing one could be the higher.
    """
    item_id: str
    condition: Literal["B0-T"]
    temperature_c: float
    melting_point_a_c: float | None
    melting_point_b_c: float | None
    melting_point_higher_c: float | None
    ratio: float | None
    ratio_threshold: float
    reacts: bool | None
    review_flags: tuple[ReviewFlag, ...]

    @model_validator(mode="after")
    def _check(self) -> TemperatureRatioDecision:
        a, b = self.melting_point_a_c, self.melting_point_b_c
        for name, value in (("temperature_c", self.temperature_c), ("melting_point_a_c", a), ("melting_point_b_c", b)):
            if value is not None:
                _absolute_c(value, name)
        expected_higher = None if a is None or b is None else max(a, b)
        if self.melting_point_higher_c != expected_higher:
            raise ValueError("melting_point_higher_c must be the larger melting point, set only when both are known")
        expected_ratio = None if expected_higher is None else _ratio(self.temperature_c, expected_higher)
        if self.ratio != expected_ratio:
            raise ValueError("ratio must be T_dwell(K) / T_melt_higher(K), set only when both melting points are known")
        if (self.ratio is None) != (self.reacts is None):
            raise ValueError("ratio and reacts must both be set or both be None")
        _check_undetermined(self.reacts is not None, self.review_flags)
        if self.ratio is not None and self.reacts != (self.ratio >= self.ratio_threshold):
            raise ValueError("reacts must equal ratio >= ratio_threshold")
        return self


class CompetitionMarginFeature(_Frozen):
    """B60meV result for one item: a margin feature and a regime marker.

    ``margin_ev_per_atom`` is ``dE_competing - dE_best`` (nonnegative), the
    amount by which the best reaction's driving force exceeds the best competing
    one. ``decisive`` is ``margin >= margin_threshold_ev_per_atom``: the item is
    in the regime where Szymanski et al. 2024 found the first-forming product
    predictable. It says nothing about whether the pair reacts, so there is
    deliberately no ``reacts``, ``p_react`` or category field. Neither value is
    a probability.
    """
    item_id: str
    condition: Literal["B60meV"]
    dE_best_ev_per_atom: float | None
    dE_competing_ev_per_atom: float | None
    margin_ev_per_atom: float | None
    margin_threshold_ev_per_atom: float
    decisive: bool | None
    best_evidence: tuple[str, ...]
    competing_evidence: tuple[str, ...]
    review_flags: tuple[ReviewFlag, ...]

    @model_validator(mode="after")
    def _check(self) -> CompetitionMarginFeature:
        best, competing = self.dE_best_ev_per_atom, self.dE_competing_ev_per_atom
        expected = None if best is None or competing is None else competing - best
        if self.margin_ev_per_atom != expected:
            raise ValueError("margin_ev_per_atom must be dE_competing - dE_best, set only when both are known")
        if expected is not None and expected < 0:
            raise ValueError("margin_ev_per_atom must be nonnegative: the best reaction is the most negative one")
        if (self.margin_ev_per_atom is None) != (self.decisive is None):
            raise ValueError("margin and decisive must both be set or both be None")
        _check_undetermined(self.decisive is not None, self.review_flags)
        if self.margin_ev_per_atom is not None and self.decisive != (
            self.margin_ev_per_atom >= self.margin_threshold_ev_per_atom
        ):
            raise ValueError("decisive must equal margin_ev_per_atom >= margin_threshold_ev_per_atom")
        return self


class CompetitionMarginCoverage(_Frozen):
    """How many B60meV results fall in the regime, with every item accounted for.

    ``coverage`` is ``n_decisive / n_known_margin``: the fraction decisive among
    items with a known margin, or None when no margin is known. It is not the
    evaluator's flag coverage. Items without a margin are counted in
    ``n_undetermined`` and listed by id, never dropped.
    """
    condition: Literal["B60meV"]
    margin_threshold_ev_per_atom: float
    n_items: int
    n_known_margin: int
    n_decisive: int
    n_undetermined: int
    coverage: float | None
    undetermined_item_ids: tuple[str, ...]

    @model_validator(mode="after")
    def _check(self) -> CompetitionMarginCoverage:
        if self.n_known_margin + self.n_undetermined != self.n_items:
            raise ValueError("every item must have a known margin or be undetermined")
        if len(self.undetermined_item_ids) != self.n_undetermined:
            raise ValueError("undetermined_item_ids must list every undetermined item")
        if not 0 <= self.n_decisive <= self.n_known_margin:
            raise ValueError("n_decisive must be between 0 and n_known_margin")
        expected = self.n_decisive / self.n_known_margin if self.n_known_margin else None
        if self.coverage != expected:
            raise ValueError("coverage must be n_decisive / n_known_margin, or None when no margin is known")
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


def _match_entries(items: list[Item], entries: Iterable[object], cls: type, what: str, hint: str) -> dict[str, object]:
    """Require exactly one ``cls`` entry per item and none for unknown items."""
    item_ids = {item.item_id for item in items}
    supplied: dict[str, object] = {}
    for entry in entries:
        _expect(entry, cls, what)
        item_id = entry.item_id  # type: ignore[attr-defined]
        if item_id in supplied:
            raise ValueError(f"duplicate {what} entry for {item_id!r}")
        supplied[item_id] = entry
    missing = sorted(item_ids - set(supplied))
    if missing:
        raise ValueError(f"no {what} entry for {missing}; {hint}")
    unknown = sorted(set(supplied) - item_ids)
    if unknown:
        raise ValueError(f"{what} entries for unknown items: {unknown}")
    return supplied


def _absolute_c(value: float, name: str) -> float:
    if isinstance(value, bool) or not math.isfinite(value) or value + KELVIN_OFFSET <= 0:
        raise ValueError(f"{name} must be a finite temperature above absolute zero, got {value!r}")
    return value


def _ratio(temperature_c: float, melting_point_c: float) -> float:
    """``T(K) / T_melt(K)``. The only place B0-T converts °C to K."""
    return (temperature_c + KELVIN_OFFSET) / (melting_point_c + KELVIN_OFFSET)


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
    supplied = _match_entries(
        items, energies, DrivingForceInput, "energy", "state dE_ev_per_atom=None for unavailable energies"
    )
    return [b0_driving_force(item, supplied[item.item_id], config) for item in items]  # type: ignore[arg-type]


def b0_temperature_ratio(item: Item, config: TemperatureRatioConfig) -> TemperatureRatioDecision:
    """B0-T: predict a reaction when ``T_dwell(K) / T_melt_higher(K)`` reaches the threshold.

    ``T_dwell`` is ``item.temperature_c`` and ``T_melt_higher`` the larger of the
    two melting points. A missing melting point leaves the decision
    undetermined, because the missing one could be the higher, so every
    determined decision has a ratio.
    """
    _expect(item, Item, "item")
    _expect(config, TemperatureRatioConfig, "config")
    temperature_c = _absolute_c(item.temperature_c, "temperature_c")
    melting = (item.melting_point_a_c, item.melting_point_b_c)
    names = ("melting_point_a_c", "melting_point_b_c")
    for name, value in zip(names, melting):
        if value is not None:
            _absolute_c(value, name)
    common = dict(
        item_id=item.item_id, condition="B0-T", temperature_c=temperature_c,
        melting_point_a_c=melting[0], melting_point_b_c=melting[1], ratio_threshold=config.ratio_threshold,
    )
    absent = [
        f"{name} ({formula})"
        for name, formula, value in zip(names, (item.precursor_a, item.precursor_b), melting)
        if value is None
    ]
    if absent:
        flag = ReviewFlag(
            reason=ReviewReason.missing_evidence,
            detail=f"Missing {', '.join(absent)}, so B0-T cannot tell which melting point is higher and cannot decide.",
        )
        return TemperatureRatioDecision(
            **common, melting_point_higher_c=None, ratio=None, reacts=None, review_flags=(flag,)
        )
    assert melting[0] is not None and melting[1] is not None
    higher = max(melting[0], melting[1])
    ratio = _ratio(temperature_c, higher)
    return TemperatureRatioDecision(
        **common, melting_point_higher_c=higher, ratio=ratio,
        reacts=ratio >= config.ratio_threshold, review_flags=(),
    )


def run_b0_t(items: Iterable[Item], config: TemperatureRatioConfig) -> list[TemperatureRatioDecision]:
    """Apply B0-T to every item, in order."""
    return [b0_temperature_ratio(item, config) for item in _read_items(items)]


def competition_margin(
    item: Item, energies: CompetitionMarginInput, config: CompetitionMarginConfig
) -> CompetitionMarginFeature:
    """B60meV: the competition margin and regime marker for one item.

    Missing energies give an undetermined feature with a ``missing_evidence``
    flag that cites whatever evidence was supplied. Furnace temperature is not
    used.
    """
    _expect(item, Item, "item")
    _expect(energies, CompetitionMarginInput, "energies")
    _expect(config, CompetitionMarginConfig, "config")
    if energies.item_id != item.item_id:
        raise ValueError(f"energies are for {energies.item_id!r}, not {item.item_id!r}")
    best, competing = energies.dE_best_ev_per_atom, energies.dE_competing_ev_per_atom
    threshold = config.margin_threshold_ev_per_atom
    common = dict(
        item_id=item.item_id, condition=B60MEV_CONDITION,
        dE_best_ev_per_atom=best, dE_competing_ev_per_atom=competing,
        margin_threshold_ev_per_atom=threshold,
        best_evidence=energies.best_evidence, competing_evidence=energies.competing_evidence,
    )
    absent = [
        name for name, value in (
            ("the best reaction energy", best), ("the best competing reaction energy", competing)
        ) if value is None
    ]
    if absent:
        flag = ReviewFlag(
            reason=ReviewReason.missing_evidence,
            detail=f"Missing {' and '.join(absent)}, so B60meV cannot compute a margin.",
            evidence=list(dict.fromkeys(energies.best_evidence + energies.competing_evidence)),
        )
        return CompetitionMarginFeature(**common, margin_ev_per_atom=None, decisive=None, review_flags=(flag,))
    assert best is not None and competing is not None
    margin = competing - best
    return CompetitionMarginFeature(**common, margin_ev_per_atom=margin, decisive=margin >= threshold, review_flags=())


def run_competition_margin(
    items: Iterable[Item], energies: Iterable[CompetitionMarginInput], config: CompetitionMarginConfig
) -> list[CompetitionMarginFeature]:
    """Apply B60meV to every item, in order. Each item needs exactly one entry
    (state unavailable energies as None); entries for unknown items are rejected."""
    items = _read_items(items)
    supplied = _match_entries(
        items, energies, CompetitionMarginInput, "competition energy",
        "state unavailable reaction energies as None",
    )
    return [competition_margin(item, supplied[item.item_id], config) for item in items]  # type: ignore[arg-type]


def competition_margin_coverage(features: Iterable[CompetitionMarginFeature]) -> CompetitionMarginCoverage:
    """Fraction of items in the regime among those with a known margin.

    All features must share one threshold, since a fraction over mixed
    thresholds means nothing. Undetermined items are counted and listed.
    """
    read = list(features)
    if not read:
        raise ValueError("at least one feature is required")
    seen: set[str] = set()
    for feature in read:
        _expect(feature, CompetitionMarginFeature, "feature")
        if feature.item_id in seen:
            raise ValueError(f"duplicate feature for {feature.item_id!r}")
        seen.add(feature.item_id)
    thresholds = {feature.margin_threshold_ev_per_atom for feature in read}
    if len(thresholds) != 1:
        raise ValueError(f"features must share one margin threshold, got {sorted(thresholds)}")
    known = [feature for feature in read if feature.margin_ev_per_atom is not None]
    decisive = sum(feature.decisive is True for feature in known)
    undetermined = tuple(feature.item_id for feature in read if feature.margin_ev_per_atom is None)
    return CompetitionMarginCoverage(
        condition=B60MEV_CONDITION, margin_threshold_ev_per_atom=thresholds.pop(),
        n_items=len(read), n_known_margin=len(known), n_decisive=decisive, n_undetermined=len(undetermined),
        coverage=decisive / len(known) if known else None, undetermined_item_ids=undetermined,
    )


# ---------- Predictions (fail closed) ----------

class BaselinePredictionUnavailable(RuntimeError):
    """B0, B0-T and B60meV results cannot yet become ``Prediction`` objects."""


PREDICTION_BLOCKERS = (
    "schemas.Prediction is documented as produced only by src/kiln/scoring/score.py from "
    "verifier-accepted artifacts, but B0, B0-T and B60meV produce no artifact and the schema cannot "
    "describe one (Artifact.agent has no baseline AgentName, Artifact.type no baseline "
    "report), so a team decision on the shared schema is needed",
    "protocol OPEN-08 has not fixed the B0 and B0-T thresholds, how a margin, ratio or decision maps "
    "to p_react in [0, 1], how a binary decision maps to a four-class category, the cause and fix "
    "text, or the outcome for an undetermined decision, which the evaluator still needs (see also OPEN-23)",
    "B60meV marks the regime where the first-forming product was found predictable (Szymanski et al. "
    "2024), not whether a pair reacts, so no mapping from its margin or decisive marker to p_react or "
    "a category exists until the protocol defines one (protocol/proposals/0001 suggests a new OPEN-25), "
    "and B60meV is not a schemas.ConditionId, so no "
    "RunConfig can name it without a shared-schema change",
    "protocol OPEN-08 has not fixed how B0's cached_lookup requests are charged or which "
    "run's compute log holds them, so the prediction cost cannot be derived",
    "no trusted verifier of a frozen configuration exists yet (Gate P, OPEN-16)",
)


def to_predictions(
    decisions: Iterable[DrivingForceDecision | TemperatureRatioDecision | CompetitionMarginFeature],
    config: RunConfig,
) -> list[Prediction]:
    """Fail closed: always raises ``BaselinePredictionUnavailable`` (see
    ``PREDICTION_BLOCKERS``). Inputs are checked first so that wiring mistakes
    are reported as such. No p_react, category, cause, fix, cost or freeze
    state is chosen here.

    B60meV features cannot reach this point: their condition is not a shared
    ``ConditionId``, so no ``RunConfig`` names them, and passing them under a
    B0 or B0-T config is a type error."""
    _expect(config, RunConfig, "config")
    expected = {"B0": DrivingForceDecision, "B0-T": TemperatureRatioDecision}.get(config.condition)
    if expected is None:
        raise ValueError(
            f"run condition {config.condition!r} is not B0 or B0-T "
            f"({B60MEV_CONDITION} is not a schemas.ConditionId)"
        )
    read = list(decisions)
    if not read:
        raise ValueError("at least one decision is required")
    seen: set[str] = set()
    for decision in read:
        _expect(decision, expected, "decision")
        if decision.item_id in seen:
            raise ValueError(f"duplicate decision for {decision.item_id!r}")
        seen.add(decision.item_id)
    raise BaselinePredictionUnavailable(
        "B0, B0-T and B60meV results cannot become Predictions yet: " + "; ".join(PREDICTION_BLOCKERS) + "."
    )
