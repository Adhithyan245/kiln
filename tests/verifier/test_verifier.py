"""Verifier tests use only synthetic artifacts."""

import math

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


def test_competitor_e_hull_is_checked_against_the_cited_lookup():
    lookup = [request(tier="cached_lookup", result={"dE_ev_per_atom": -0.1,
                                                     "competitor_e_hull_ev_per_atom": 0.04})]
    good = artifact(values={"dE_ev_per_atom": -0.1, "competitor_e_hull_ev_per_atom": 0.04},
                    compute_requests=["request-1"], claims=[claim()], cost=Cost(compute_units=2))
    assert check(good, lookup, Cost(compute_units=2)) == (VerifierStatus.accepted, "Checks passed")
    bad = artifact(values={"dE_ev_per_atom": -0.1, "competitor_e_hull_ev_per_atom": 0.03},
                   compute_requests=["request-1"], cost=Cost(compute_units=2))
    assert check(bad, lookup, Cost(compute_units=2))[0] == VerifierStatus.rejected


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


@pytest.mark.parametrize("status", ["not_converged", "failed"])
@pytest.mark.parametrize("result", [{"dE_ev_per_atom": -0.08}, {"dE_ev_per_atom": None}])
def test_escalation_with_failed_refinement_keeps_cached_evidence(status, result):
    requests = escalation()
    requests[1] = requests[1].model_copy(update={"status": status, "result": result})
    target = artifact(compute_requests=["request-1", "request-2"], claims=[claim()],
                      cost=Cost(compute_units=7))
    assert check(target, requests, Cost(compute_units=7)) == (VerifierStatus.accepted,
                                                              "Checks passed")


def test_value_from_failed_request_is_not_accepted():
    requests = escalation()
    requests[1] = requests[1].model_copy(update={"status": "not_converged"})
    target = artifact(values={"dE_ev_per_atom": -0.08}, compute_requests=["request-1", "request-2"],
                      cost=Cost(compute_units=7))
    status, notes = check(target, requests, Cost(compute_units=7))
    assert status == VerifierStatus.rejected
    assert "differs from every cited compute result: dE_ev_per_atom" in notes


def test_value_supported_only_by_failed_request_is_inconclusive():
    failed = request(status="failed", result={"dE_ev_per_atom": -0.1})
    target = artifact(compute_requests=["request-1"], cost=Cost(compute_units=2))
    status, notes = check(target, [failed], Cost(compute_units=2))
    assert status == VerifierStatus.inconclusive
    assert "no usable compute result for numeric value: dE_ev_per_atom" in notes


def test_failed_request_charge_counts_towards_artifact_cost():
    requests = escalation()
    requests[1] = requests[1].model_copy(update={"status": "not_converged"})
    target = artifact(compute_requests=["request-1", "request-2"], cost=Cost(compute_units=2))
    status, notes = check(target, requests, Cost(compute_units=7))
    assert status == VerifierStatus.rejected
    assert "Artifact compute cost disagrees" in notes


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
    assert "no usable compute result for numeric value: dE_ev_per_atom" in notes


def test_missing_context_remains_inconclusive():
    target = artifact(compute_requests=["invented-request"], cost=Cost(compute_units=1000))
    status, notes = verify(target, FakeBoard(), **NO_CONTEXT)
    assert status == VerifierStatus.inconclusive
    assert "unavailable" in notes


@pytest.mark.parametrize("changes", [{"run_id": "other"}, {"item_id": "other"}])
def test_wrong_scope_request_is_rejected(changes):
    target = artifact(compute_requests=["request-1"], cost=Cost(compute_units=2))
    status, _ = check(target, [request(**changes)], Cost(compute_units=2))
    assert status == VerifierStatus.rejected


def test_cumulative_request_charges_cannot_exceed_reported_cost():
    target = artifact(compute_requests=["request-1"])
    status, _ = check(target, [request()])
    assert status == VerifierStatus.rejected


@pytest.mark.parametrize(("cost", "note"), [
    (Cost(tool_calls=13), "Tool-call budget exceeded"),
    (Cost(tokens_in=20000, tokens_out=20001), "Token budget exceeded"),
    (Cost(compute_units=10.1), "Compute budget exceeded"),
])
def test_cumulative_item_limits_are_enforced(cost, note):
    # The log matches the item's compute units, so only the limit is broken.
    log = [request(compute_units=cost.compute_units)] if cost.compute_units else []
    status, notes = check(artifact(values={}), log, cost)
    assert (status, notes) == (VerifierStatus.rejected, note)


def test_budget_limit_is_inclusive():
    cost = Cost(tool_calls=12, tokens_in=40000, compute_units=10)
    log = [request(compute_units=10)]
    assert check(artifact(values={}), log, cost) == (VerifierStatus.accepted, "Checks passed")


def thermo_log():
    # A cached lookup and a relaxation that did not converge; both are charged.
    return [request(tier="cached_lookup", status="cached", compute_units=1.0),
            request(request_id="request-2", tier="bounded_relaxation", status="not_converged",
                    result={}, compute_units=3.0, gpu_seconds=12.5)]


def thermo_artifact(**changes):
    data = dict(compute_requests=["request-1", "request-2"], claims=[claim()],
                cost=Cost(compute_units=4.0))
    data.update(changes)
    return artifact(**data)


def test_item_compute_cost_equal_to_log_total_is_accepted():
    status, notes = check(thermo_artifact(), thermo_log(), Cost(compute_units=4.0))
    assert (status, notes) == (VerifierStatus.accepted, "Checks passed")


@pytest.mark.parametrize("item_units", [5.0, 4.01])
def test_unlogged_item_compute_charge_is_rejected(item_units):
    # Charges with no logged request: e.g. a request missing from the log.
    status, notes = check(thermo_artifact(), thermo_log(), Cost(compute_units=item_units))
    assert (status, notes) == (VerifierStatus.rejected,
                               "Cumulative item compute cost exceeds compute log charges")


def test_request_missing_from_log_is_rejected():
    status, notes = check(thermo_artifact(), thermo_log()[:1], Cost(compute_units=4.0))
    assert status == VerifierStatus.rejected
    assert "Unknown compute request: request-2" in notes
    assert "Cumulative item compute cost exceeds compute log charges" in notes


def test_shared_cited_request_is_charged_once_in_item_cost():
    first = thermo_artifact(verifier=VerifierStatus.accepted)
    second = artifact(artifact_id="run:thermo:2", cites=[first.artifact_id],
                      compute_requests=["request-1"], claims=[claim()],
                      cost=Cost(compute_units=1.0))
    board = FakeBoard([first])
    # The item cost is the log total, not the sum of artifact costs.
    assert check(second, thermo_log(), Cost(compute_units=4.0), board=board) == (
        VerifierStatus.accepted, "Checks passed")
    status, notes = check(second, thermo_log(), Cost(compute_units=5.0), board=board)
    assert (status, notes) == (VerifierStatus.rejected,
                               "Cumulative item compute cost exceeds compute log charges")


@pytest.mark.parametrize(("item_units", "note"), [
    (4.0, None),
    (1.0, "Compute request charges exceed cumulative item cost"),  # failed charge dropped
    (3.0, "Compute request charges exceed cumulative item cost"),  # cache hit not charged
])
def test_uncited_cached_and_failed_requests_count_towards_item_cost(item_units, note):
    status, notes = check(kinetics(), thermo_log(), Cost(compute_units=item_units),
                          tool_values={"tammann_a_c": 600.5, "tammann_b_c": 720.0})
    if note is None:
        assert (status, notes) == (VerifierStatus.accepted, "Checks passed")
    else:
        assert (status, notes) == (VerifierStatus.rejected, note)


def test_tool_calls_and_tokens_are_not_compared_with_compute_log():
    target = thermo_artifact(cost=Cost(tool_calls=2, tokens_in=300, tokens_out=50,
                                       compute_units=4.0))
    item = Cost(tool_calls=9, tokens_in=5000, tokens_out=800, compute_units=4.0)
    assert check(target, thermo_log(), item) == (VerifierStatus.accepted, "Checks passed")


@pytest.mark.parametrize("name", ["tool_calls", "tokens_in", "tokens_out"])
def test_artifact_tool_or_token_cost_cannot_exceed_item_cost(name):
    target = thermo_artifact(cost=Cost(compute_units=4.0, **{name: 5}))
    item = Cost(compute_units=4.0, **{name: 4})
    status, notes = check(target, thermo_log(), item)
    assert (status, notes) == (VerifierStatus.rejected,
                               f"Artifact cost exceeds cumulative item cost: {name}")


def rounded_charges():
    # The item total is derived as limit - remaining() while the agent sums its own
    # charges, so the two totals for the same charges differ only by rounding.
    charges, remaining, own = [0.1, 0.2, 0.3], 10.0, 0.0
    for charge in charges:
        remaining -= charge
        own += charge
    return charges, own, 10.0 - remaining


def test_float_rounding_in_charges_is_not_a_budget_violation():
    charges, own, item_total = rounded_charges()
    assert own > item_total and math.fsum(charges) > item_total
    requests = [request(request_id=f"request-{n}", compute_units=charge)
                for n, charge in enumerate(charges, 1)]
    target = artifact(compute_requests=[r.request_id for r in requests], claims=[claim()],
                      cost=Cost(compute_units=own))
    status, notes = check(target, requests, Cost(compute_units=item_total))
    assert (status, notes) == (VerifierStatus.accepted, "Checks passed")


def test_float_rounding_at_compute_limit_is_not_a_budget_violation():
    # The agent's running sum sits a rounding error above both the log total and the limit.
    charges, own, _ = rounded_charges()
    assert own > math.fsum(charges) and own > 0.6
    requests = [request(request_id=f"request-{n}", compute_units=charge)
                for n, charge in enumerate(charges, 1)]
    status, notes = verify(artifact(values={}), FakeBoard(), requests=requests,
                           config=config(max_compute_units_per_item=0.6),
                           item_cost=Cost(compute_units=own), tool_values=None)
    assert (status, notes) == (VerifierStatus.accepted, "Checks passed")


def test_real_cost_excess_is_still_rejected():
    _, _, item_total = rounded_charges()
    target = artifact(values={}, cost=Cost(compute_units=0.61))
    status, notes = check(target, [request(compute_units=0.61)], Cost(compute_units=item_total))
    assert status == VerifierStatus.rejected
    assert "Artifact cost exceeds cumulative item cost: compute_units" in notes
    assert "Compute request charges exceed cumulative item cost" in notes
    status, notes = check(artifact(values={}), [request(compute_units=0.6)],
                          Cost(compute_units=0.61))
    assert (status, notes) == (VerifierStatus.rejected,
                               "Cumulative item compute cost exceeds compute log charges")


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
