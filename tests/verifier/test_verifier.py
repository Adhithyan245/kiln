"""Verifier tests use only synthetic artifacts."""

import pytest
from pydantic import ValidationError

from kiln.schemas import Artifact, Claim, ComputeRequest, Cost, RunConfig, VerifierStatus
from kiln.verifier import verify


class FakeBoard:
    def __init__(self, artifacts=()):
        self.artifacts = list(artifacts)

    def accepted_artifacts(self, item_id):
        return [artifact for artifact in self.artifacts if artifact.item_id == item_id]


def artifact(**changes):
    data = dict(
        artifact_id="run:thermo:1", run_id="run", item_id="synthetic-item",
        agent="thermo", type="reaction_report", values={"dE_ev_per_atom": -0.1},
    )
    data.update(changes)
    return Artifact(**data)


def claim(**changes):
    data = dict(cause="example", statement="Example", evidence=["values.dE_ev_per_atom"],
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
    status, notes = verify(artifact(cites=[source.artifact_id], claims=[claim(evidence=[source.artifact_id, "values.dE_ev_per_atom"])]), FakeBoard([source]))
    assert status == VerifierStatus.inconclusive
    assert "compute request log unavailable" in notes
    assert "cumulative item cost unavailable" in notes


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


def request(**changes):
    data = dict(request_id="request-1", run_id="run", item_id="synthetic-item",
                agent="thermo", tier="single_point", reason="synthetic",
                inputs={}, settings={}, cache_key="synthetic",
                result={"dE_ev_per_atom": -0.1}, compute_units=2)
    data.update(changes)
    return ComputeRequest(**data)


def config(**changes):
    data = dict(run_id="run", condition="B1", seed=1, model="synthetic")
    data.update(changes)
    return RunConfig(**data)


def test_fake_request_and_over_budget_are_rejected():
    target = artifact(compute_requests=["invented-request"], cost=Cost(compute_units=1000))
    status, notes = verify(target, FakeBoard(), requests=[], config=config(),
                           item_cost=Cost(compute_units=1000))
    assert status == VerifierStatus.rejected
    assert "Unknown compute request" in notes
    assert "Compute budget exceeded" in notes


def test_mismatched_numeric_result_is_rejected():
    target = artifact(values={"dE_ev_per_atom": -0.2}, compute_requests=["request-1"])
    status, notes = verify(target, FakeBoard(), requests=[request()], config=config(),
                           item_cost=Cost(compute_units=2))
    assert status == VerifierStatus.rejected
    assert "Numeric value differs" in notes


def test_complete_valid_artifact_is_accepted():
    target = artifact(compute_requests=["request-1"], claims=[claim()],
                      cost=Cost(compute_units=2))
    status, notes = verify(target, FakeBoard(), requests=[request()], config=config(),
                           item_cost=Cost(compute_units=2))
    assert (status, notes) == (VerifierStatus.accepted, "Checks passed")


def test_missing_context_remains_inconclusive():
    target = artifact(compute_requests=["invented-request"], cost=Cost(compute_units=1000))
    status, notes = verify(target, FakeBoard())
    assert status == VerifierStatus.inconclusive
    assert "unavailable" in notes


@pytest.mark.parametrize("changes", [{"run_id": "other"}, {"item_id": "other"},
                                     {"status": "failed"}])
def test_unusable_or_wrong_scope_request_is_rejected(changes):
    target = artifact(compute_requests=["request-1"])
    status, _ = verify(target, FakeBoard(), requests=[request(**changes)], config=config(),
                       item_cost=Cost(compute_units=2))
    assert status == VerifierStatus.rejected


def test_unattributed_number_is_inconclusive():
    target = artifact(values={"tammann_a_c": 900})
    status, notes = verify(target, FakeBoard(), requests=[], config=config(), item_cost=Cost())
    assert status == VerifierStatus.inconclusive
    assert "no compute result" in notes


def test_cumulative_request_charges_cannot_exceed_reported_cost():
    target = artifact(compute_requests=["request-1"])
    status, _ = verify(target, FakeBoard(), requests=[request()], config=config(), item_cost=Cost())
    assert status == VerifierStatus.rejected


@pytest.mark.parametrize("cost", [Cost(tool_calls=13), Cost(tokens_in=20000, tokens_out=20001),
                                 Cost(compute_units=10.1)])
def test_cumulative_item_limits_are_enforced(cost):
    target = artifact(values={})
    assert verify(target, FakeBoard(), requests=[], config=config(), item_cost=cost)[0] == VerifierStatus.rejected


def test_budget_limit_is_inclusive():
    target = artifact(values={})
    cost = Cost(tool_calls=12, tokens_in=40000, compute_units=10)
    assert verify(target, FakeBoard(), requests=[], config=config(), item_cost=cost)[0] == VerifierStatus.accepted


@pytest.mark.parametrize("key", ["category", "reacted", "xrd_patterns", "refinement_results",
                                 "phase_weights", "reviewer_annotations", "reaction_category"])
def test_label_keys_are_rejected(key):
    target = artifact(values={key: "synthetic"})
    status, notes = verify(target, FakeBoard(), requests=[], config=config(), item_cost=Cost())
    assert status == VerifierStatus.rejected
    assert "Forbidden value key" in notes


def test_unitless_numeric_key_is_rejected():
    target = artifact(values={"energy": -0.1})
    status, notes = verify(target, FakeBoard(), requests=[], config=config(), item_cost=Cost())
    assert status == VerifierStatus.rejected
    assert "Undocumented numeric value key" in notes


def test_documented_but_unlisted_numeric_key_is_rejected():
    target = artifact(values={"made_up_ev_per_atom": -0.1})
    assert verify(target, FakeBoard(), requests=[], config=config(), item_cost=Cost())[0] == VerifierStatus.rejected


def test_compute_cost_must_match_cited_request_charges():
    target = artifact(compute_requests=["request-1"], cost=Cost(compute_units=1))
    status, notes = verify(target, FakeBoard(), requests=[request()], config=config(),
                           item_cost=Cost(compute_units=2))
    assert status == VerifierStatus.rejected
    assert "Artifact compute cost disagrees" in notes


def test_duplicate_request_citations_are_rejected():
    target = artifact(compute_requests=["request-1", "request-1"], cost=Cost(compute_units=4))
    status, notes = verify(target, FakeBoard(), requests=[request()], config=config(),
                           item_cost=Cost(compute_units=4))
    assert status == VerifierStatus.rejected
    assert "Duplicate cited compute request" in notes
