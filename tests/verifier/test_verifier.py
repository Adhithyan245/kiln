"""Verifier tests use only synthetic artifacts."""

import pytest
from pydantic import ValidationError

from kiln.schemas import Artifact, Claim, ComputeRequest, Cost, RunConfig, VerifierStatus
from kiln.verifier import verify


NO_CONTEXT = dict(requests=None, config=None, item_cost=None, tool_values=None)


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


def test_context_arguments_are_required():
    with pytest.raises(TypeError):
        verify(artifact(), FakeBoard())


@pytest.mark.parametrize("text", ["", "  ", "\n"])
def test_blank_falsified_if_is_rejected(text):
    status, notes = verify(artifact(claims=[claim(falsified_if=text)]), FakeBoard(), **NO_CONTEXT)
    assert status == VerifierStatus.rejected
    assert "missing falsified_if" in notes


def test_fake_citations_and_evidence_are_rejected():
    target = artifact(cites=["fake"], claims=[claim(evidence=["fake", "values.missing"])])
    status, notes = verify(target, FakeBoard(), **NO_CONTEXT)
    assert status == VerifierStatus.rejected
    assert "Unknown or unaccepted citation: fake" in notes
    assert "unknown or unaccepted evidence: fake" in notes
    assert "unknown value reference: values.missing" in notes


def test_accepted_same_run_citation_passes_available_checks_but_is_inconclusive():
    source = artifact(artifact_id="run:kinetics:1", agent="kinetics", type="kinetics_report",
                      verifier=VerifierStatus.accepted)
    target = artifact(cites=[source.artifact_id],
                      claims=[claim(evidence=[source.artifact_id, "values.dE_ev_per_atom"])])
    status, notes = verify(target, FakeBoard([source]), **NO_CONTEXT)
    assert status == VerifierStatus.inconclusive
    assert "compute request log unavailable" in notes
    assert "cumulative item cost unavailable" in notes


@pytest.mark.parametrize("changes", [
    {"run_id": "other"}, {"item_id": "other"},
    {"verifier": VerifierStatus.pending}, {"verifier": VerifierStatus.rejected},
])
def test_citation_must_be_accepted_for_same_run_and_item(changes):
    source = artifact(artifact_id="source", verifier=VerifierStatus.accepted)
    source = source.model_copy(update=changes)
    status, _ = verify(artifact(cites=["source"]), FakeBoard([source]), **NO_CONTEXT)
    assert status == VerifierStatus.rejected


def test_self_citation_is_rejected():
    target = artifact(cites=["run:thermo:1"], verifier=VerifierStatus.accepted)
    assert verify(target, FakeBoard([target]), **NO_CONTEXT)[0] == VerifierStatus.rejected


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


def check(target, requests=(), cost=Cost(), tool_values=None, board=None):
    return verify(target, board or FakeBoard(), requests=list(requests), config=config(),
                  item_cost=cost, tool_values=tool_values)


def test_fake_request_and_over_budget_are_rejected():
    target = artifact(compute_requests=["invented-request"], cost=Cost(compute_units=1000))
    status, notes = check(target, cost=Cost(compute_units=1000))
    assert status == VerifierStatus.rejected
    assert "Unknown compute request" in notes
    assert "Compute budget exceeded" in notes


def test_mismatched_numeric_result_is_rejected():
    target = artifact(values={"dE_ev_per_atom": -0.2}, compute_requests=["request-1"],
                      cost=Cost(compute_units=2))
    status, notes = check(target, [request()], Cost(compute_units=2))
    assert status == VerifierStatus.rejected
    assert "Numeric value differs" in notes


def test_complete_valid_artifact_is_accepted():
    target = artifact(compute_requests=["request-1"], claims=[claim()],
                      cost=Cost(compute_units=2))
    status, notes = check(target, [request()], Cost(compute_units=2))
    assert (status, notes) == (VerifierStatus.accepted, "Checks passed")


def escalation():
    # Thermo escalates from the cached lookup to a refined MLIP energy and cites both.
    return [request(tier="cached_lookup", result={"dE_ev_per_atom": -0.1}),
            request(request_id="request-2", tier="bounded_relaxation",
                    result={"dE_ev_per_atom": -0.08, "dE_mlip_minus_mp_ev_per_atom": 0.02},
                    compute_units=5)]


def test_escalated_artifact_matching_one_cited_result_is_accepted():
    values = {"dE_ev_per_atom": -0.08, "dE_mlip_minus_mp_ev_per_atom": 0.02}
    target = artifact(values=values, compute_requests=["request-1", "request-2"],
                      claims=[claim()], cost=Cost(compute_units=7))
    status, notes = check(target, escalation(), Cost(compute_units=7))
    assert (status, notes) == (VerifierStatus.accepted, "Checks passed")


def test_escalated_artifact_matching_no_cited_result_is_rejected():
    target = artifact(values={"dE_ev_per_atom": -0.09}, compute_requests=["request-1", "request-2"],
                      cost=Cost(compute_units=7))
    status, notes = check(target, escalation(), Cost(compute_units=7))
    assert status == VerifierStatus.rejected
    assert "differs from every cited compute result: dE_ev_per_atom" in notes


def test_uncited_request_result_cannot_support_a_value():
    target = artifact(values={"dE_ev_per_atom": -0.08}, compute_requests=["request-1"],
                      cost=Cost(compute_units=2))
    status, _ = check(target, escalation(), Cost(compute_units=7))
    assert status == VerifierStatus.rejected


@pytest.mark.parametrize("bad", [None, "-0.1", True, float("nan")])
def test_invalid_cited_compute_result_is_rejected(bad):
    requests = [request(), request(request_id="request-2", result={"dE_ev_per_atom": bad})]
    target = artifact(compute_requests=["request-1", "request-2"], cost=Cost(compute_units=4))
    status, notes = check(target, requests, Cost(compute_units=4))
    assert status == VerifierStatus.rejected
    assert "Invalid compute result" in notes


def kinetics(**values):
    return artifact(artifact_id="run:kinetics:1", agent="kinetics", type="kinetics_report",
                    values=values or {"tammann_a_c": 600.5, "tammann_b_c": 720},
                    claims=[claim(evidence=["values.tammann_a_c"])])


def test_kinetics_artifact_matching_tool_values_is_accepted():
    tool_values = {"tammann_a_c": 600.5, "tammann_b_c": 720.0}
    status, notes = check(kinetics(), tool_values=tool_values)
    assert (status, notes) == (VerifierStatus.accepted, "Checks passed")


def test_mismatched_tool_value_is_rejected():
    status, notes = check(kinetics(), tool_values={"tammann_a_c": 600.5, "tammann_b_c": 700.0})
    assert status == VerifierStatus.rejected
    assert "Numeric value differs from tool value: tammann_b_c" in notes


@pytest.mark.parametrize("bad", [None, "720", True, float("inf")])
def test_invalid_tool_value_is_rejected(bad):
    status, notes = check(kinetics(), tool_values={"tammann_a_c": 600.5, "tammann_b_c": bad})
    assert status == VerifierStatus.rejected
    assert "Invalid tool value: tammann_b_c" in notes


def test_tool_number_without_tool_value_is_inconclusive():
    status, notes = check(kinetics(), tool_values={"tammann_a_c": 600.5})
    assert status == VerifierStatus.inconclusive
    assert "no tool value for numeric value: tammann_b_c" in notes


def test_compute_result_cannot_establish_tool_value():
    target = artifact(values={"decomposes_at_c": 850}, compute_requests=["request-1"],
                      cost=Cost(compute_units=2))
    status, notes = check(target, [request(result={"decomposes_at_c": 850})],
                          Cost(compute_units=2))
    assert status == VerifierStatus.inconclusive
    assert "no tool value for numeric value: decomposes_at_c" in notes


def test_tool_values_cannot_establish_energy():
    status, notes = check(artifact(), tool_values={"dE_ev_per_atom": -0.1})
    assert status == VerifierStatus.inconclusive
    assert "no compute result for numeric value: dE_ev_per_atom" in notes


def test_missing_context_remains_inconclusive():
    target = artifact(compute_requests=["invented-request"], cost=Cost(compute_units=1000))
    status, notes = verify(target, FakeBoard(), **NO_CONTEXT)
    assert status == VerifierStatus.inconclusive
    assert "unavailable" in notes


@pytest.mark.parametrize("changes", [{"run_id": "other"}, {"item_id": "other"},
                                     {"status": "failed"}])
def test_unusable_or_wrong_scope_request_is_rejected(changes):
    target = artifact(compute_requests=["request-1"], cost=Cost(compute_units=2))
    status, _ = check(target, [request(**changes)], Cost(compute_units=2))
    assert status == VerifierStatus.rejected


def test_cumulative_request_charges_cannot_exceed_reported_cost():
    target = artifact(compute_requests=["request-1"])
    status, _ = check(target, [request()])
    assert status == VerifierStatus.rejected


@pytest.mark.parametrize("cost", [Cost(tool_calls=13), Cost(tokens_in=20000, tokens_out=20001),
                                 Cost(compute_units=10.1)])
def test_cumulative_item_limits_are_enforced(cost):
    assert check(artifact(values={}), cost=cost)[0] == VerifierStatus.rejected


def test_budget_limit_is_inclusive():
    cost = Cost(tool_calls=12, tokens_in=40000, compute_units=10)
    assert check(artifact(values={}), cost=cost)[0] == VerifierStatus.accepted


@pytest.mark.parametrize("key", ["category", "reacted", "xrd_patterns", "refinement_results",
                                 "phase_weights", "reviewer_annotations", "reaction_category"])
def test_label_keys_are_rejected(key):
    status, notes = check(artifact(values={key: "synthetic"}))
    assert status == VerifierStatus.rejected
    assert "Forbidden value key" in notes


def test_unitless_numeric_key_is_rejected():
    status, notes = check(artifact(values={"energy": -0.1}))
    assert status == VerifierStatus.rejected
    assert "Undocumented numeric value key" in notes


def test_documented_but_unlisted_numeric_key_is_rejected():
    assert check(artifact(values={"made_up_ev_per_atom": -0.1}))[0] == VerifierStatus.rejected


def test_compute_cost_must_match_cited_request_charges():
    target = artifact(compute_requests=["request-1"], cost=Cost(compute_units=1))
    status, notes = check(target, [request()], Cost(compute_units=2))
    assert status == VerifierStatus.rejected
    assert "Artifact compute cost disagrees" in notes


def test_duplicate_request_citations_are_rejected():
    target = artifact(compute_requests=["request-1", "request-1"], cost=Cost(compute_units=4))
    status, notes = check(target, [request()], Cost(compute_units=4))
    assert status == VerifierStatus.rejected
    assert "Duplicate cited compute request" in notes
