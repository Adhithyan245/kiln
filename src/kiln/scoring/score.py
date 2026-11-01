"""Scoring entry points and a configured deterministic scoring engine.

The module-level ``provisional`` and ``score`` (docs/interfaces.md steps 4 and
9) apply the fixed rule set in ``protocol/scoring_rules.json`` (protocol
OPEN-05). ``load_frozen_rules`` reads that file and fails closed unless the
rules' SHA-256 digest equals ``FROZEN_RULES_SHA256`` below, so an edited rule
file cannot be used without a reviewed code change. No threshold or weight is
defined in this module.

``ScoringEngine`` applies an explicit ``ScoringRules`` (``rules.py``) for one
run. It refuses to start unless a caller-supplied verifier returns the literal
True for the rule set's SHA-256 digest; ``frozen_engine`` binds it to
``is_frozen_digest``. Numbers come only from verifier-accepted artifact values
through the configured rules. The furnace setpoint is the only item field a
rule may read (``Feature.kind == "furnace_minus_value"``); rationales, claims
and other item fields never set a number.

``changed_prediction`` is the OPEN-17 definition: a compute request changed
the prediction when the provisional four-class category differs before and
after it.
"""
from __future__ import annotations

import json
import math
import operator
from collections.abc import Callable, Sequence
from pathlib import Path

from kiln.schemas import (
    Artifact,
    Category,
    ComputeRequest,
    ComputeStatus,
    Cost,
    Item,
    Prediction,
    ReviewFlag,
    ReviewReason,
    RunConfig,
    VerifierStatus,
)
from kiln.scoring.rules import P_REACT, EvidenceSource, Feature, Outcome, ScoringRules

# The frozen rule file and the digest of the rules it must contain (OPEN-05).
# Changing either the file's rules or this digest is a protocol change.
FROZEN_RULES_PATH = Path(__file__).resolve().parents[3] / "protocol" / "scoring_rules.json"
FROZEN_RULES_SHA256 = "4390d1a05adef5e6ed3afd4b9a796ff793a0aa936d0860c0a9fffe0a29a65e14"


class ScoringConfigurationError(RuntimeError):
    """The frozen scoring rules and required run context are not configured."""


class MissingEvidenceError(ValueError):
    """A feature has no accepted value and no configured fallback."""


class ConflictingEvidenceError(ValueError):
    """Accepted artifacts give different values for one feature source."""


_OPS: dict[str, Callable[[float, float], bool]] = {
    "lt": operator.lt, "le": operator.le, "gt": operator.gt, "ge": operator.ge,
}
_FAILED = frozenset({ComputeStatus.failed, ComputeStatus.not_converged})


def _close(a: float, b: float) -> bool:
    # Same tolerance as the verifier: charges are float tier prices.
    return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-12)


def _validate_artifacts(item: Item, accepted: Sequence[Artifact]) -> str | None:
    if not isinstance(item, Item):
        raise TypeError("item must be an Item")
    seen: set[str] = set()
    run_id: str | None = None
    first: str | None = None
    for artifact in accepted:
        if not isinstance(artifact, Artifact):
            raise TypeError("accepted must contain Artifact objects")
        if artifact.verifier != VerifierStatus.accepted:
            raise ValueError(f"artifact {artifact.artifact_id!r} is not verifier-accepted")
        if artifact.item_id != item.item_id:
            raise ValueError(f"artifact {artifact.artifact_id!r} belongs to another item")
        if artifact.artifact_id in seen:
            raise ValueError(f"duplicate artifact id: {artifact.artifact_id!r}")
        seen.add(artifact.artifact_id)
        if run_id is None:
            run_id, first = artifact.run_id, artifact.artifact_id
        elif artifact.run_id != run_id:
            raise ValueError(f"artifacts belong to different runs: {first!r} is in {run_id!r}, "
                             f"{artifact.artifact_id!r} is in {artifact.run_id!r}")
    return run_id


def _validate_inputs(
    item: Item,
    accepted: Sequence[Artifact],
    requests: Sequence[ComputeRequest],
    flags: Sequence[ReviewFlag],
) -> str | None:
    run_id = _validate_artifacts(item, accepted)
    source = "the artifacts"
    seen: set[str] = set()
    for request in requests:
        if not isinstance(request, ComputeRequest):
            raise TypeError("requests must contain ComputeRequest objects")
        if request.item_id != item.item_id:
            raise ValueError(f"request {request.request_id!r} belongs to another item")
        if request.request_id in seen:
            raise ValueError(f"duplicate request id: {request.request_id!r}")
        seen.add(request.request_id)
        if run_id is None:
            run_id, source = request.run_id, f"request {request.request_id!r}"
        elif request.run_id != run_id:
            raise ValueError(f"inputs belong to different runs: {source} in {run_id!r}, "
                             f"request {request.request_id!r} in {request.run_id!r}")
    # Every request an artifact used must be in the item's compute log, so the
    # prediction's request list and cost cannot leave one out.
    for artifact in accepted:
        for request_id in artifact.compute_requests:
            if request_id not in seen:
                raise ValueError(f"artifact {artifact.artifact_id!r} cites compute request "
                                 f"{request_id!r}, which was not supplied")
    for flag in flags:
        if not isinstance(flag, ReviewFlag):
            raise TypeError("flags must contain ReviewFlag objects")
    return run_id


def is_frozen_digest(digest: str) -> bool:
    """True only for the digest of the frozen rule set (OPEN-05)."""
    return isinstance(digest, str) and digest == FROZEN_RULES_SHA256


def load_frozen_rules(path: Path | str | None = None) -> ScoringRules:
    """The frozen rule set, read from ``protocol/scoring_rules.json``.

    The file holds the rules under ``"rules"``, their digest under
    ``"rules_sha256"``, and citations and notes that do not affect scoring.
    Fails closed if the file is missing or invalid, if the recorded digest
    does not match the rules, or if the rules are not the frozen ones.
    """
    path = FROZEN_RULES_PATH if path is None else Path(path)
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        rules = ScoringRules.model_validate_json(json.dumps(document["rules"], allow_nan=False))
        recorded = document["rules_sha256"]
    except Exception as exc:
        raise ScoringConfigurationError(f"Scoring rules at {path} are missing or invalid") from exc
    digest = rules.digest()
    if recorded != digest:
        raise ScoringConfigurationError(f"{path} records digest {recorded!r} but its rules hash to {digest}")
    if not is_frozen_digest(digest):
        raise ScoringConfigurationError(f"Scoring rules {digest} in {path} are not the frozen rules "
                                        f"({FROZEN_RULES_SHA256})")
    return rules


def frozen_engine(config: RunConfig) -> ScoringEngine:
    """A ``ScoringEngine`` for one run under the frozen rules. Fits ``Components.scorer``."""
    return ScoringEngine(load_frozen_rules(), config, verify_frozen_rules=is_frozen_digest)


def provisional(item: Item, accepted: Sequence[Artifact]) -> tuple[float, Category]:
    """``(p_react, category)`` under the frozen rules, for the before/after log.

    Needs no run context: it builds no prediction and adds no flags. Missing or
    conflicting evidence uses the rule set's fallbacks, exactly as ``score``.
    """
    accepted = tuple(accepted)
    _validate_artifacts(item, accepted)
    return _provisional(load_frozen_rules(), item, accepted)


def score(
    item: Item,
    accepted: Sequence[Artifact],
    requests: Sequence[ComputeRequest],
    flags: Sequence[ReviewFlag],
    *,
    config: RunConfig | None = None,
    cost: Cost | None = None,
    gpu_seconds_from_log: bool = False,
) -> Prediction:
    """Prediction for one item under the frozen rules. See ``ScoringEngine.score``.

    A prediction needs the run context and the item's cost, so ``config`` and
    ``cost`` are required; without them this fails closed.
    """
    _validate_inputs(item, tuple(accepted), tuple(requests), tuple(flags))
    if config is None or cost is None:
        raise ScoringConfigurationError(
            "score requires run context (config=RunConfig) and the item's cost (cost=Cost); "
            "use frozen_engine(config).score(...) or pass both")
    return frozen_engine(config).score(item, accepted, requests, flags, cost=cost,
                                       gpu_seconds_from_log=gpu_seconds_from_log)


def changed_prediction(before: tuple[float, Category], after: tuple[float, Category]) -> bool:
    """OPEN-17: a request changed the prediction when the provisional category differs.

    ``before`` and ``after`` are ``provisional`` results on the item's accepted
    evidence just before and just after the request's evidence was accepted. A
    change in ``p_react`` alone does not count: it is a fixed-rule score, not a
    calibrated probability, so only a change of the four-class call is a change
    of prediction. Fits ``kiln.compute.accounting.replay_changes(changed=...)``.
    """
    categories = []
    for result in (before, after):
        if not isinstance(result, tuple) or len(result) != 2:
            raise TypeError("before and after must be (p_react, category) tuples")
        categories.append(Category(result[1]))
    return categories[0] != categories[1]


def _number(artifact: Artifact, key: str) -> float:
    value = artifact.values[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"artifact {artifact.artifact_id!r} value {key!r} is not a finite number")
    return float(value)


def _select(feature: Feature, source: EvidenceSource,
            candidates: list[Artifact]) -> tuple[float, list[str]]:
    numbers = [_number(artifact, source.value_key) for artifact in candidates]
    if feature.on_multiple == "latest_created":
        latest = max(artifact.created_at for artifact in candidates)
        chosen = [(a, n) for a, n in zip(candidates, numbers, strict=True) if a.created_at == latest]
    else:
        chosen = list(zip(candidates, numbers, strict=True))
    if len({number for _, number in chosen}) > 1:
        raise ConflictingEvidenceError(
            f"feature {feature.name!r}: accepted artifacts "
            f"{[a.artifact_id for a, _ in chosen]} give different values for {source.value_key!r}")
    return chosen[0][1], [artifact.artifact_id for artifact, _ in chosen]


class _Resolved:
    """Feature values for one item, with what was used and what fell back."""

    def __init__(self) -> None:
        self.values: dict[str, float] = {}
        self.used: set[str] = set()
        self.missing: list[Feature] = []
        self.conflicts: list[tuple[Feature, ConflictingEvidenceError, list[str]]] = []


def _resolve(rules: ScoringRules, item: Item, accepted: tuple[Artifact, ...]) -> _Resolved:
    out = _Resolved()
    for feature in rules.features:
        found: tuple[float, list[str]] | None = None
        conflict: tuple[ConflictingEvidenceError, list[str]] | None = None
        for source in feature.sources:
            # A null value records the property as unknown, so it is skipped.
            candidates = [a for a in accepted if a.agent == source.agent
                          and a.type == source.artifact_type
                          and a.values.get(source.value_key) is not None]
            if candidates:
                try:
                    found = _select(feature, source, candidates)
                except ConflictingEvidenceError as exc:
                    # A conflict is not resolved by trying a lower-priority source.
                    conflict = (exc, [a.artifact_id for a in candidates])
                break
        if feature.kind == "present":
            out.values[feature.name] = 1.0 if found is not None else 0.0
            if found is not None:
                out.used.update(found[1])
            continue
        if found is not None:
            number = found[0]
            if feature.kind == "furnace_minus_value":
                number = float(item.temperature_c) - number
                if not math.isfinite(number):
                    raise ValueError(f"feature {feature.name!r} is not finite")
            out.values[feature.name] = number
            out.used.update(found[1])
            continue
        if feature.fallback is None:
            if conflict is not None:
                raise conflict[0]
            raise MissingEvidenceError(
                f"no verifier-accepted value for feature {feature.name!r} and no fallback is configured")
        out.values[feature.name] = feature.fallback
        if conflict is not None:
            out.conflicts.append((feature, conflict[0], conflict[1]))
        else:
            out.missing.append(feature)
    return out


def _linear(rules: ScoringRules, values: dict[str, float]) -> float:
    spec = rules.p_react
    parts = [spec.intercept, *(term.weight * values[term.feature] for term in spec.terms)]
    if not all(math.isfinite(part) for part in parts):
        raise ValueError("a score term is not finite")
    z = math.fsum(parts)
    if not math.isfinite(z):
        raise ValueError("the linear score is not finite")
    if spec.link == "logistic":
        return 1.0 / (1.0 + math.exp(-z)) if z >= 0 else math.exp(z) / (1.0 + math.exp(z))
    return min(1.0, max(0.0, z))


def _category(rules: ScoringRules, p_react: float, values: dict[str, float]) -> Outcome:
    subjects = {P_REACT: p_react, **values}
    for rule in rules.category_rules:
        if all(_OPS[c.op](subjects[c.subject], c.threshold) for c in rule.when):
            return rule.outcome
    return rules.otherwise


def _provisional(rules: ScoringRules, item: Item, accepted: tuple[Artifact, ...]) -> tuple[float, Category]:
    values = _resolve(rules, item, accepted).values
    p_react = _linear(rules, values)
    return p_react, _category(rules, p_react, values).category


class ScoringEngine:
    """Deterministic scoring for one run under one explicit rule set.

    ``verify_frozen_rules`` receives the rules' SHA-256 digest and must return
    the literal True; otherwise, or if it raises, construction fails. The
    engine never decides that rules are frozen.

    The rules are validated again into a private plain ``ScoringRules`` before
    the digest is computed, so unvalidated instances (``model_construct``,
    ``model_copy(update=...)``) are refused before the verifier is called, a
    subclass cannot supply its own digest, and later changes to the caller's
    object cannot alter the attested rules. ``rules`` returns a copy.
    """

    def __init__(
        self,
        rules: ScoringRules,
        config: RunConfig,
        *,
        verify_frozen_rules: Callable[[str], bool] | None = None,
    ) -> None:
        if not isinstance(rules, ScoringRules):
            raise TypeError("rules must be a ScoringRules")
        if not isinstance(config, RunConfig):
            raise TypeError("config must be a RunConfig")
        config = RunConfig.model_validate(config.model_dump())
        try:
            rules = ScoringRules.model_validate(rules)
        except Exception as exc:
            raise ScoringConfigurationError("Scoring rules failed validation") from exc
        digest = ScoringRules.digest(rules)
        try:
            attested = verify_frozen_rules is not None and verify_frozen_rules(digest) is True
        except Exception as exc:
            raise ScoringConfigurationError("Unable to verify that the scoring rules are frozen") from exc
        if not attested:
            raise ScoringConfigurationError(f"Scoring rules {digest} have not been verified as frozen")
        self._rules = rules
        self._digest = digest
        self._run_id = config.run_id
        self._condition = config.condition
        self._seed = config.seed

    @property
    def rules(self) -> ScoringRules:
        """A copy of the attested rules; the engine's own snapshot stays private."""
        return self._rules.model_copy(deep=True)

    @property
    def rules_digest(self) -> str:
        return self._digest

    def _check_run(self, run_id: str | None) -> None:
        if run_id is not None and run_id != self._run_id:
            raise ValueError(f"inputs are from run {run_id!r}, not the configured run {self._run_id!r}")

    def provisional(self, item: Item, accepted: Sequence[Artifact]) -> tuple[float, Category]:
        """Score and category from accepted artifacts, for the before/after log."""
        accepted = tuple(accepted)
        self._check_run(_validate_artifacts(item, accepted))
        return _provisional(self._rules, item, accepted)

    def score(
        self,
        item: Item,
        accepted: Sequence[Artifact],
        requests: Sequence[ComputeRequest],
        flags: Sequence[ReviewFlag],
        *,
        cost: Cost,
        gpu_seconds_from_log: bool = False,
    ) -> Prediction:
        """Prediction for one item.

        ``requests`` must be the item's full compute log for this run, and
        ``cost`` its final cumulative cost: ``cost.compute_units`` and
        ``cost.gpu_seconds`` must equal the sums over ``requests``. Every
        request, cached or failed included, is charged at its tier price and
        logged (AGENTS.md rule 8), so compute units with no logged request are
        refused rather than accepted as unexplained. The verifier only checks
        that the log does not exceed the item cost, because it runs while the
        item is still in progress. Artifact costs are not summed: several
        artifacts may cite the same request. Tool calls, tokens and USD are
        not in the compute log and are taken from ``cost`` as given. Every flag
        is kept. Scoring adds a missing-evidence flag for each feature that
        used its fallback because no value was accepted, a conflict flag for
        each feature that used its fallback because accepted artifacts
        disagree, and a failed-computation flag for each failed or
        non-converged request that no failed-computation flag cites.

        ``gpu_seconds_from_log=True`` is for a ``cost`` that does not measure
        GPU time, such as ``kiln.budget.Budget.spent``. ``cost.gpu_seconds``
        must then be exactly 0.0, and the prediction's GPU-seconds are the sum
        of the measured ``gpu_seconds`` over ``requests``. A nonzero value is
        refused, not replaced; check a measured value in the default mode.
        ``cost.compute_units`` must still equal the log total, which is what
        shows the log is complete. Every other field is kept as given.
        """
        if not isinstance(gpu_seconds_from_log, bool):
            raise TypeError("gpu_seconds_from_log must be a bool")
        accepted, requests, flags = tuple(accepted), tuple(requests), tuple(flags)
        self._check_run(_validate_inputs(item, accepted, requests, flags))
        cost = _check_cost(cost, requests, gpu_seconds_from_log=gpu_seconds_from_log)
        resolved = _resolve(self._rules, item, accepted)
        values, used = resolved.values, resolved.used
        p_react = _linear(self._rules, values)
        outcome = _category(self._rules, p_react, values)

        cited = {request_id for flag in flags if flag.reason == ReviewReason.failed_computation
                 for request_id in flag.evidence}
        review_flags = [flag.model_copy(deep=True) for flag in flags]
        review_flags += [ReviewFlag(
            reason=ReviewReason.missing_evidence,
            detail=(f"No verifier-accepted value for scoring feature {feature.name!r}; "
                    f"the configured fallback {feature.fallback!r} was used."),
        ) for feature in resolved.missing]
        review_flags += [ReviewFlag(
            reason=ReviewReason.conflict,
            detail=(f"Verifier-accepted artifacts disagree on scoring feature {feature.name!r} ({error}); "
                    f"the configured fallback {feature.fallback!r} was used."),
            evidence=artifact_ids,
        ) for feature, error, artifact_ids in resolved.conflicts]
        review_flags += [ReviewFlag(
            reason=ReviewReason.failed_computation,
            detail=f"Compute request {request.request_id!r} ended with status {request.status.value!r}.",
            evidence=[request.request_id],
        ) for request in requests if request.status in _FAILED and request.request_id not in cited]

        return Prediction(
            run_id=self._run_id,
            condition=self._condition,
            seed=self._seed,
            item_id=item.item_id,
            p_react=p_react,
            category=outcome.category,
            cause=outcome.cause,
            fix=outcome.fix,
            evidence=[artifact.artifact_id for artifact in accepted if artifact.artifact_id in used],
            compute_requests=[request.request_id for request in requests],
            disagreements=[flag.detail for flag in review_flags
                           if flag.reason in self._rules.disagreement_flag_reasons],
            needs_review=bool(review_flags),
            review_flags=review_flags,
            applicability_notes=[flag.detail for flag in review_flags
                                 if flag.reason in self._rules.applicability_flag_reasons],
            cost=cost,
        )


def _check_cost(cost: Cost, requests: tuple[ComputeRequest, ...], *, gpu_seconds_from_log: bool) -> Cost:
    """Return the prediction's cost after checking it against the complete compute log."""
    if not isinstance(cost, Cost):
        raise TypeError("cost must be a Cost")
    for name in Cost.model_fields:
        value = getattr(cost, name)
        if isinstance(value, bool) or not math.isfinite(value) or value < 0:
            raise ValueError(f"invalid cost: {name}")
    totals: dict[str, float] = {}
    for name in ("compute_units", "gpu_seconds"):
        parts = [getattr(request, name) for request in requests]
        if any(not math.isfinite(part) or part < 0 for part in parts):
            raise ValueError(f"invalid compute request {name}")
        # fsum is correctly rounded, so the total does not depend on log order.
        total = totals[name] = math.fsum(parts)
        if name == "gpu_seconds" and gpu_seconds_from_log:
            continue
        if not _close(getattr(cost, name), total):
            raise ValueError(f"cost.{name} is {getattr(cost, name)!r} but the item's compute requests total "
                             f"{total!r}; requests must be the complete compute log and every charge logged")
    if not gpu_seconds_from_log:
        return cost.model_copy()
    if cost.gpu_seconds != 0.0:
        raise ValueError(f"cost.gpu_seconds is {cost.gpu_seconds!r}, but gpu_seconds_from_log takes GPU-seconds "
                         f"only from the compute log (total {totals['gpu_seconds']!r}); a cost that measures "
                         "GPU time must be checked against the log with gpu_seconds_from_log=False")
    return cost.model_copy(update={"gpu_seconds": totals["gpu_seconds"]})
