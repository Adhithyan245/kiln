"""Deterministic checks on artifacts using the documented board interface."""

import math
import re
from typing import Mapping, Protocol, Sequence

from kiln.schemas import Artifact, ComputeRequest, ComputeStatus, Cost, RunConfig, VerifierStatus


# Numeric value keys are the unit-bearing keys listed in docs/interfaces.md.
# Energies come from the compute service (docs/interfaces.md step 4); Tammann
# temperatures and precursor properties come from deterministic tools (step 5).
_COMPUTE_KEYS = frozenset({"dE_ev_per_atom", "dE_mlip_minus_mp_ev_per_atom"})
_TOOL_KEYS = frozenset({"tammann_a_c", "tammann_b_c", "decomposes_at_c", "volatile_above_c"})
_NUMERIC_KEYS = _COMPUTE_KEYS | _TOOL_KEYS


def _number(value: object) -> bool:
    return (isinstance(value, (float, int)) and not isinstance(value, bool)
            and math.isfinite(value))


def _forbidden_key(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", "_", key.lower()).strip("_")
    return (normalized in {"category", "reacted", "reaction_category"}
            or "xrd" in normalized or "refin" in normalized
            or "phase_weight" in normalized or "phaseweight" in normalized
            or "reviewer_annotation" in normalized)


class Board(Protocol):
    def accepted_artifacts(self, item_id: str) -> list[Artifact]: ...


def verify(
    artifact: Artifact,
    board: Board,
    *,
    requests: Sequence[ComputeRequest] | None,
    config: RunConfig | None,
    item_cost: Cost | None,
    tool_values: Mapping[str, float | str | bool | None] | None,
) -> tuple[VerifierStatus, str]:
    """Verify an artifact against the item's compute log, budget and tool outputs.

    The context arguments are required so a caller cannot omit them by
    accident; pass ``None`` only when an input is genuinely unavailable, and
    the artifact is then at best inconclusive.

    ``requests`` must be the complete compute log for this run and item, and
    ``item_cost`` the cumulative cost for the item, including this artifact.
    ``tool_values`` holds the deterministic tool outputs for the item,
    recomputed by the caller (``tammann_a_c``/``tammann_b_c`` for precursors a
    and b, ``decomposes_at_c``, ``volatile_above_c``); it must never be copied
    from the artifact under check.

    Energy keys must equal the same key in at least one cited ``ok`` or
    ``cached`` compute result, so an escalated artifact may cite both the
    cached and the refined request. Cited ``failed`` or ``not_converged``
    requests are allowed and still count towards cost, but their results
    never support a value.
    Tool keys must equal ``tool_values``; compute results never establish them,
    and ``tool_values`` never establishes an energy. A value with no source
    is inconclusive.
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

    # Check keys before inspecting values, so forbidden fields are never read.
    forbidden = {key for key in artifact.values if _forbidden_key(key)}
    for key in sorted(forbidden):
        errors.append(f"Forbidden value key: {key}")

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
        if len(set(artifact.compute_requests)) != len(artifact.compute_requests):
            errors.append("Duplicate cited compute request")
        for request_id in artifact.compute_requests:
            request = by_id.get(request_id)
            if request is None:
                errors.append(f"Unknown compute request: {request_id}")
            else:
                cited.append(request)
    # Failed and non-converged requests stay cited and charged, so an honest
    # artifact is not punished for listing them; review flags surface them.
    usable = [request for request in cited
              if request.status in (ComputeStatus.ok, ComputeStatus.cached)]

    for key in artifact.values:
        if key in forbidden:
            continue
        value = artifact.values[key]
        if isinstance(value, (float, int)) and not isinstance(value, bool):
            if key not in _NUMERIC_KEYS:
                errors.append(f"Undocumented numeric value key: {key}")
                continue
            if not math.isfinite(value):
                errors.append(f"Non-finite value: {key}")
                continue
            if key in _TOOL_KEYS:
                if tool_values is None or key not in tool_values:
                    unknown.append(f"no tool value for numeric value: {key}")
                elif not _number(tool_values[key]):
                    errors.append(f"Invalid tool value: {key}")
                elif tool_values[key] != value:
                    errors.append(f"Numeric value differs from tool value: {key}")
                continue
            sources = [request.result[key] for request in usable if key in request.result]
            if not sources:
                unknown.append(f"no usable compute result for numeric value: {key}")
            elif not all(_number(source) for source in sources):
                errors.append(f"Invalid compute result for numeric value: {key}")
            elif value not in sources:
                errors.append(f"Numeric value differs from every cited compute result: {key}")

    if requests is not None and len(cited) == len(artifact.compute_requests):
        charges = [request.compute_units for request in cited]
        if (all(math.isfinite(unit) and unit >= 0 for unit in charges)
                and math.isfinite(artifact.cost.compute_units)
                and not math.isclose(artifact.cost.compute_units, math.fsum(charges),
                                     rel_tol=1e-9, abs_tol=1e-12)):
            errors.append("Artifact compute cost disagrees with cited request charges")

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
