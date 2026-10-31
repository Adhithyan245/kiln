"""Deterministic checks on artifacts using the documented board interface."""

import math
from typing import Protocol, Sequence

from kiln.schemas import Artifact, ComputeRequest, ComputeStatus, Cost, RunConfig, VerifierStatus


class Board(Protocol):
    def accepted_artifacts(self, item_id: str) -> list[Artifact]: ...


def verify(
    artifact: Artifact,
    board: Board,
    *,
    requests: Sequence[ComputeRequest] | None = None,
    config: RunConfig | None = None,
    item_cost: Cost | None = None,
) -> tuple[VerifierStatus, str]:
    """Verify an artifact, with optional complete item request log and total cost.

    ``requests`` must be the complete compute log for this run and item, and
    ``item_cost`` the cumulative cost for the item, including this artifact.
    Without these inputs and the run config, acceptance cannot be established.
    Numerical values without a matching compute-result key are inconclusive:
    other documented tools have no result lookup in the board contract.
    """
    errors: list[str] = []
    unknown: list[str] = []
    accepted = {
        other.artifact_id
        for other in board.accepted_artifacts(artifact.item_id)
        if other.item_id == artifact.item_id
        and other.run_id == artifact.run_id
        and other.verifier == VerifierStatus.accepted
        and other.artifact_id != artifact.artifact_id
    }

    for citation in artifact.cites:
        if citation not in accepted:
            errors.append(f"Unknown or unaccepted citation: {citation}")

    for index, claim in enumerate(artifact.claims):
        if not claim.falsified_if.strip():
            errors.append(f"Claim {index}: missing falsified_if")
        for reference in claim.evidence:
            if reference.startswith("values."):
                if reference[len("values.") :] not in artifact.values:
                    errors.append(f"Claim {index}: unknown value reference: {reference}")
            elif reference not in accepted:
                errors.append(f"Claim {index}: unknown or unaccepted evidence: {reference}")

    cited: list[ComputeRequest] = []
    if requests is None:
        unknown.append("compute request log unavailable")
    else:
        by_id: dict[str, ComputeRequest] = {}
        for request in requests:
            if request.run_id != artifact.run_id or request.item_id != artifact.item_id:
                errors.append(f"Request outside run or item: {request.request_id}")
            if request.request_id in by_id:
                errors.append(f"Duplicate request ID: {request.request_id}")
            by_id[request.request_id] = request
        for request_id in artifact.compute_requests:
            request = by_id.get(request_id)
            if request is None:
                errors.append(f"Unknown compute request: {request_id}")
            else:
                cited.append(request)
                if request.status not in (ComputeStatus.ok, ComputeStatus.cached):
                    errors.append(f"Unusable compute request: {request_id}")

    for key, value in artifact.values.items():
        if isinstance(value, (float, int)) and not isinstance(value, bool):
            if not math.isfinite(value):
                errors.append(f"Non-finite value: {key}")
                continue
            sources = [request.result[key] for request in cited if key in request.result]
            if not sources:
                unknown.append(f"no compute result for numeric value: {key}")
            elif any(isinstance(source, bool) or not isinstance(source, (int, float))
                     or not math.isfinite(source) or source != value for source in sources):
                errors.append(f"Numeric value differs from compute result: {key}")

    if config is None or item_cost is None:
        unknown.append("run config or cumulative item cost unavailable")
    else:
        if config.run_id != artifact.run_id:
            errors.append("Run config does not match artifact run")
        for name in ("tool_calls", "tokens_in", "tokens_out", "compute_units"):
            total = getattr(item_cost, name)
            own = getattr(artifact.cost, name)
            if not math.isfinite(total) or not math.isfinite(own) or total < 0 or own < 0:
                errors.append(f"Invalid cost: {name}")
            elif own > total:
                errors.append(f"Artifact cost exceeds cumulative item cost: {name}")
        if item_cost.tool_calls > config.max_tool_calls_per_item:
            errors.append("Tool-call budget exceeded")
        if item_cost.tokens_in + item_cost.tokens_out > config.max_tokens_per_item:
            errors.append("Token budget exceeded")
        if item_cost.compute_units > config.max_compute_units_per_item:
            errors.append("Compute budget exceeded")
        if requests is not None:
            units = [request.compute_units for request in requests]
            if any(not math.isfinite(unit) or unit < 0 for unit in units):
                errors.append("Invalid compute request cost")
            elif sum(units) > item_cost.compute_units:
                errors.append("Compute request charges exceed cumulative item cost")

    if errors:
        return VerifierStatus.rejected, "; ".join(errors)
    if unknown:
        return VerifierStatus.inconclusive, "; ".join(unknown)
    return VerifierStatus.accepted, "Checks passed"
