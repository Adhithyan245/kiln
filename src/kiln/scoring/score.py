"""Fail-closed entry points for the as-yet unfrozen scoring protocol.

No scoring rules, defaults, or numerical thresholds are defined here.  A
future implementation needs an explicitly configured, frozen protocol and
run context before it can produce a Prediction.
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import NoReturn

from kiln.schemas import Artifact, Category, ComputeRequest, Item, Prediction, ReviewFlag, VerifierStatus


class ScoringConfigurationError(RuntimeError):
    """The frozen scoring rules and required run context are not configured."""


def _validate_artifacts(item: Item, accepted: Sequence[Artifact]) -> None:
    seen: set[str] = set()
    for artifact in accepted:
        if artifact.verifier != VerifierStatus.accepted:
            raise ValueError(f"artifact {artifact.artifact_id!r} is not verifier-accepted")
        if artifact.item_id != item.item_id:
            raise ValueError(f"artifact {artifact.artifact_id!r} belongs to another item")
        if artifact.artifact_id in seen:
            raise ValueError(f"duplicate artifact id: {artifact.artifact_id!r}")
        seen.add(artifact.artifact_id)


def _require_frozen_rules() -> NoReturn:
    raise ScoringConfigurationError(
        "Scoring requires explicitly configured frozen rules; score also requires "
        "defined run context, provenance and cost aggregation. No scoring "
        "configuration is supported until those contracts are fixed."
    )


def provisional(item: Item, accepted: Sequence[Artifact]) -> tuple[float, Category]:
    """Return the configured provisional score and category when rules exist."""
    _validate_artifacts(item, accepted)
    _require_frozen_rules()


def score(
    item: Item,
    accepted: Sequence[Artifact],
    requests: Sequence[ComputeRequest],
    flags: Sequence[ReviewFlag],
) -> Prediction:
    """Produce a prediction only after the scoring protocol is fixed."""
    _validate_artifacts(item, accepted)
    seen: set[str] = set()
    for request in requests:
        if request.item_id != item.item_id:
            raise ValueError(f"request {request.request_id!r} belongs to another item")
        if request.request_id in seen:
            raise ValueError(f"duplicate request id: {request.request_id!r}")
        seen.add(request.request_id)
    _require_frozen_rules()
