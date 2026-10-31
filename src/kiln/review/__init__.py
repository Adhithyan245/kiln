"""Review flags based on available evidence, not predictions about outcomes."""

from __future__ import annotations

import math
from collections.abc import Sequence

from kiln.schemas import Artifact, ComputeRequest, ComputeStatus, Item, ReviewFlag, ReviewReason, VerifierStatus


def flags(item: Item, accepted: Sequence[Artifact], requests: Sequence[ComputeRequest], *,
          disagreement_threshold: float | None = None) -> list[ReviewFlag]:
    """Flag observable problems; optional disagreement threshold must be protocol-set."""
    if disagreement_threshold is not None and (not math.isfinite(disagreement_threshold) or disagreement_threshold < 0):
        raise ValueError("disagreement threshold must be finite and nonnegative")
    result = []
    usable = [a for a in accepted if a.item_id == item.item_id and a.verifier == VerifierStatus.accepted]
    if not any(a.agent == "kinetics" for a in usable) or not any(a.agent == "thermo" for a in usable):
        result.append(ReviewFlag(reason=ReviewReason.missing_evidence, detail="Accepted kinetics or thermodynamic evidence is missing."))
    if any(a.agent == "precursor" and any(a.values.get(f"precursor_{side}_decomposition_known") is False
            for side in ("a", "b")) for a in usable):
        result.append(ReviewFlag(reason=ReviewReason.missing_evidence, detail="A precursor decomposition temperature is unknown."))
    for a in usable:
        if a.values.get("decomposition_conditions_unverified") is True:
            result.append(ReviewFlag(reason=ReviewReason.missing_evidence,
                detail="Decomposition re-evaluation uses literature conditions not verified for this experiment.",
                evidence=[a.artifact_id]))
        if a.values.get("outside_applicability") is True:
            result.append(ReviewFlag(reason=ReviewReason.outside_applicability,
                detail="The evidence source reports that this item is outside its applicability.", evidence=[a.artifact_id]))
        if any(a.values.get(f"melting_{side}_semantics") == "possible_decomposition_or_dehydration" for side in ("a", "b")):
            result.append(ReviewFlag(reason=ReviewReason.missing_evidence,
                detail="A reported melting point may instead represent decomposition or dehydration.", evidence=[a.artifact_id]))
    for request in requests:
        if request.item_id == item.item_id and request.status in (ComputeStatus.failed, ComputeStatus.not_converged):
            result.append(ReviewFlag(reason=ReviewReason.failed_computation,
                detail=f"{request.tier.value}: {request.status.value}", evidence=[request.request_id]))
    if disagreement_threshold is not None:
        for a in usable:
            value = a.values.get("dE_mlip_minus_mp_ev_per_atom")
            if isinstance(value, (int, float)) and not isinstance(value, bool) and abs(value) > disagreement_threshold:
                result.append(ReviewFlag(reason=ReviewReason.conflict, detail="Energy methods disagree beyond the configured threshold.", evidence=[a.artifact_id]))
    return result
