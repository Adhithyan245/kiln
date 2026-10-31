"""Deterministic checks on artifacts using the documented board interface."""

from typing import Protocol

from kiln.schemas import Artifact, VerifierStatus


class Board(Protocol):
    def accepted_artifacts(self, item_id: str) -> list[Artifact]: ...


def verify(artifact: Artifact, board: Board) -> tuple[VerifierStatus, str]:
    """Check references and claims; leave unavailable provenance checks inconclusive.

    The board contract does not expose compute results or cumulative budget usage,
    so passing the checks available here is not sufficient for acceptance.
    """
    errors: list[str] = []
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

    if errors:
        return VerifierStatus.rejected, "; ".join(errors)
    return (
        VerifierStatus.inconclusive,
        "Compute results and cumulative budget are unavailable through the board contract; "
        "numerical provenance and budget compliance could not be verified.",
    )
