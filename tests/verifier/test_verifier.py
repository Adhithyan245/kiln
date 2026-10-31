"""Verifier tests use only synthetic artifacts."""

import pytest
from pydantic import ValidationError

from kiln.schemas import Artifact, Claim, VerifierStatus
from kiln.verifier import verify


class FakeBoard:
    def __init__(self, artifacts=()):
        self.artifacts = list(artifacts)

    def accepted_artifacts(self, item_id):
        return [artifact for artifact in self.artifacts if artifact.item_id == item_id]


def artifact(**changes):
    data = dict(
        artifact_id="run:thermo:1", run_id="run", item_id="synthetic-item",
        agent="thermo", type="reaction_report", values={"energy": -0.1},
    )
    data.update(changes)
    return Artifact(**data)


def claim(**changes):
    data = dict(cause="example", statement="Example", evidence=["values.energy"],
                falsified_if="An independent measurement disagrees")
    data.update(changes)
    return Claim(**data)


def test_missing_falsified_if_is_rejected_by_schema():
    with pytest.raises(ValidationError):
        Claim(cause="example", statement="Example", evidence=[])


@pytest.mark.parametrize("text", ["", "  ", "\n"])
def test_blank_falsified_if_is_rejected(text):
    status, notes = verify(artifact(claims=[claim(falsified_if=text)]), FakeBoard())
    assert status == VerifierStatus.rejected
    assert "missing falsified_if" in notes


def test_fake_citations_and_evidence_are_rejected():
    status, notes = verify(artifact(cites=["fake"], claims=[claim(evidence=["fake", "values.missing"]) ]), FakeBoard())
    assert status == VerifierStatus.rejected
    assert "Unknown or unaccepted citation: fake" in notes
    assert "unknown or unaccepted evidence: fake" in notes
    assert "unknown value reference: values.missing" in notes


def test_accepted_same_run_citation_passes_available_checks_but_is_inconclusive():
    source = artifact(artifact_id="run:kinetics:1", agent="kinetics", type="kinetics_report", verifier=VerifierStatus.accepted)
    status, notes = verify(artifact(cites=[source.artifact_id], claims=[claim(evidence=[source.artifact_id, "values.energy"])]), FakeBoard([source]))
    assert status == VerifierStatus.inconclusive
    assert "numerical provenance and budget compliance" in notes


@pytest.mark.parametrize("changes", [
    {"run_id": "other"}, {"item_id": "other"},
    {"verifier": VerifierStatus.pending}, {"verifier": VerifierStatus.rejected},
])
def test_citation_must_be_accepted_for_same_run_and_item(changes):
    source = artifact(artifact_id="source", verifier=VerifierStatus.accepted).model_copy(update=changes)
    status, _ = verify(artifact(cites=["source"]), FakeBoard([source]))
    assert status == VerifierStatus.rejected


def test_self_citation_is_rejected():
    target = artifact(cites=["run:thermo:1"], verifier=VerifierStatus.accepted)
    assert verify(target, FakeBoard([target]))[0] == VerifierStatus.rejected


def test_compute_request_and_cost_cannot_establish_provenance_or_budget():
    target = artifact(compute_requests=["invented-request"], cost={"compute_units": 1000})
    status, notes = verify(target, FakeBoard())
    assert status == VerifierStatus.inconclusive
    assert "unavailable" in notes
