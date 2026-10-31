"""Synthetic evidence tests; no experimental outcomes are used."""
import math
from datetime import datetime, timedelta, timezone

import pytest

from kiln.schemas import (
    Artifact,
    Category,
    Claim,
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
from kiln.scoring.rules import (
    CategoryRule,
    Condition,
    EvidenceSource,
    Feature,
    LinearScore,
    Outcome,
    ScoringRules,
    Term,
)
from kiln.scoring.score import (
    ConflictingEvidenceError,
    MissingEvidenceError,
    ScoringConfigurationError,
    ScoringEngine,
    provisional,
    score,
)


@pytest.fixture
def item():
    return Item(item_id="synthetic", source="alab_demo", precursor_a="A", precursor_b="B", temperature_c=500, split="dev")


@pytest.fixture
def artifact(item):
    return Artifact(artifact_id="run:thermo:1", run_id="run", item_id=item.item_id,
                    agent="thermo", type="reaction_report", values={"dE_ev_per_atom": -0.1},
                    verifier=VerifierStatus.accepted)


def test_both_entry_points_fail_closed_without_frozen_rules(item, artifact):
    # Round-trip synthetic input through the shared schema before scoring.
    accepted = [Artifact.model_validate_json(artifact.model_dump_json())]
    flags = [ReviewFlag(reason="missing_evidence", detail="synthetic missing input")]
    with pytest.raises(ScoringConfigurationError, match="frozen rules"):
        provisional(item, accepted)
    with pytest.raises(ScoringConfigurationError, match="run context"):
        score(item, accepted, [], flags)


@pytest.mark.parametrize("status", [VerifierStatus.pending, VerifierStatus.rejected, VerifierStatus.inconclusive])
def test_rejects_unaccepted_artifacts(item, artifact, status):
    artifact.verifier = status
    with pytest.raises(ValueError, match="not verifier-accepted"):
        provisional(item, [artifact])


def test_rejects_wrong_item_and_duplicate_artifacts(item, artifact):
    with pytest.raises(ValueError, match="duplicate artifact"):
        score(item, [artifact, artifact], [], [])
    artifact.item_id = "other"
    with pytest.raises(ValueError, match="another item"):
        provisional(item, [artifact])


def test_rejects_wrong_item_and_duplicate_requests(item):
    request = ComputeRequest(request_id="r", run_id="run", item_id="other", agent="thermo",
                             tier="cached_lookup", reason="synthetic", inputs={}, settings={}, cache_key="key")
    with pytest.raises(ValueError, match="another item"):
        score(item, [], [request], [])
    request.item_id = item.item_id
    with pytest.raises(ValueError, match="duplicate request"):
        score(item, [], [request, request], [])


def test_rejects_mixed_artifact_runs(item, artifact):
    other = artifact.model_copy(update={"artifact_id": "other", "run_id": "other-run"})
    with pytest.raises(ValueError, match="different runs"):
        provisional(item, [artifact, other])
    with pytest.raises(ValueError, match="different runs"):
        score(item, [artifact, other], [], [])


def test_rejects_request_from_different_run(item, artifact):
    request = ComputeRequest(request_id="r", run_id="other-run", item_id=item.item_id, agent="thermo",
                             tier="cached_lookup", reason="synthetic", inputs={}, settings={}, cache_key="key")
    with pytest.raises(ValueError, match="different runs"):
        score(item, [artifact], [request], [])


def test_rejects_mixed_request_runs_without_artifacts(item):
    request = ComputeRequest(request_id="r", run_id="run", item_id=item.item_id, agent="thermo",
                             tier="cached_lookup", reason="synthetic", inputs={}, settings={}, cache_key="key")
    other = request.model_copy(update={"request_id": "other", "run_id": "other-run"})
    with pytest.raises(ValueError, match="different runs"):
        score(item, [], [request, other], [])


def test_score_rejects_wrong_item_artifact_and_bad_flags(item, artifact):
    with pytest.raises(TypeError, match="ReviewFlag"):
        score(item, [artifact], [], ["not a flag"])
    artifact.item_id = "other"
    with pytest.raises(ValueError, match="another item"):
        score(item, [artifact], [], [])


def test_score_requires_every_cited_request(item, artifact):
    artifact.compute_requests = ["run:compute:9"]
    with pytest.raises(ValueError, match="not supplied"):
        score(item, [artifact], [], [])


def test_mixed_run_errors_name_both_runs(item, artifact):
    other = artifact.model_copy(update={"artifact_id": "other", "run_id": "other-run"})
    with pytest.raises(ValueError, match="'run:thermo:1' is in 'run'.*'other' is in 'other-run'"):
        provisional(item, [artifact, other])
    request = ComputeRequest(request_id="r", run_id="run", item_id=item.item_id, agent="thermo",
                             tier="cached_lookup", reason="synthetic", inputs={}, settings={}, cache_key="key")
    late = request.model_copy(update={"request_id": "r2", "run_id": "other-run"})
    with pytest.raises(ValueError, match="request 'r' in 'run', request 'r2' in 'other-run'"):
        score(item, [], [request, late], [])


# ---------- Configured engine, synthetic rules only ----------
# SYNTHETIC: every weight, threshold, fallback and outcome text below is an
# arbitrary test value chosen to exercise the code. None is a proposed rule.

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
HIGH = Outcome(category=Category.completely_reacted, cause="synthetic-high", fix="synthetic-fix-high")
MID = Outcome(category=Category.partially_reacted, cause="synthetic-mid", fix="synthetic-fix-mid")
LOW = Outcome(category=Category.unreacted, cause="synthetic-low", fix="synthetic-fix-low")


def synthetic_rules(link="logistic", energy_weight=2.0, intercept=0.5):
    return ScoringRules(
        features=(
            Feature(name="energy", on_multiple="require_equal", fallback=None, sources=(
                EvidenceSource(agent="thermo", artifact_type="reaction_report", value_key="dE_ev_per_atom"),
                EvidenceSource(agent="single", artifact_type="reaction_report", value_key="dE_ev_per_atom"),
            )),
            Feature(name="tammann", on_multiple="latest_created", fallback=7.0, sources=(
                EvidenceSource(agent="kinetics", artifact_type="kinetics_report", value_key="tammann_a_c"),
            )),
        ),
        p_react=LinearScore(intercept=intercept, link=link, terms=(
            Term(feature="energy", weight=energy_weight), Term(feature="tammann", weight=0.25))),
        category_rules=(
            CategoryRule(when=(Condition(subject="p_react", op="ge", threshold=0.9),), outcome=HIGH),
            CategoryRule(when=(Condition(subject="p_react", op="ge", threshold=0.5),
                               Condition(subject="tammann", op="lt", threshold=10.0)), outcome=MID),
        ),
        otherwise=LOW,
        disagreement_flag_reasons=(ReviewReason.conflict,),
        applicability_flag_reasons=(ReviewReason.outside_applicability,),
    )


def engine_for(rules, config=None):
    config = config or RunConfig(run_id="run", condition="C1", seed=3, model="synthetic-model")
    return ScoringEngine(rules, config, verify_frozen_rules=lambda digest: digest == rules.digest())


def make_artifact(seq, agent="thermo", kind="reaction_report", values=None, at=T0, **extra):
    return Artifact(artifact_id=f"run:{agent}:{seq}", run_id="run", item_id="synthetic", agent=agent,
                    type=kind, values=values if values is not None else {"dE_ev_per_atom": -0.1},
                    verifier=VerifierStatus.accepted, created_at=at, **extra)


def make_request(seq, units=1.5, gpu=2.0, status=ComputeStatus.ok):
    return ComputeRequest(request_id=f"run:compute:{seq}", run_id="run", item_id="synthetic", agent="thermo",
                          tier="cached_lookup", reason="synthetic", inputs={}, settings={},
                          cache_key=f"key{seq}", status=status, compute_units=units, gpu_seconds=gpu)


def cost_for(requests, **extra):
    return Cost(compute_units=math.fsum(r.compute_units for r in requests),
                gpu_seconds=math.fsum(r.gpu_seconds for r in requests), **extra)


def logistic(z):
    return 1 / (1 + math.exp(-z))


@pytest.fixture
def evidence():
    return [make_artifact(1, values={"dE_ev_per_atom": 0.9}, compute_requests=["run:compute:1"]),
            make_artifact(1, agent="kinetics", kind="kinetics_report", values={"tammann_a_c": 2.0}),
            make_artifact(1, agent="precursor", kind="precursor_report", values={"decomposes_at_c": 800.0})]


@pytest.mark.parametrize("verifier", [None, lambda d: False, lambda d: 1, lambda d: "True", lambda d: d])
def test_engine_fails_closed_unless_rules_are_attested(verifier):
    config = RunConfig(run_id="run", condition="C1", seed=0, model="synthetic-model")
    with pytest.raises(ScoringConfigurationError, match="not been verified as frozen"):
        ScoringEngine(synthetic_rules(), config, verify_frozen_rules=verifier)


def test_engine_wraps_verifier_errors_and_passes_the_digest():
    config = RunConfig(run_id="run", condition="C1", seed=0, model="synthetic-model")
    rules = synthetic_rules()

    def broken(digest):
        raise OSError("unreachable")
    with pytest.raises(ScoringConfigurationError, match="Unable to verify") as caught:
        ScoringEngine(rules, config, verify_frozen_rules=broken)
    assert isinstance(caught.value.__cause__, OSError)
    seen = []
    engine = ScoringEngine(rules, config, verify_frozen_rules=lambda d: seen.append(d) or True)
    assert seen == [rules.digest()] == [engine.rules_digest]
    with pytest.raises(TypeError):
        ScoringEngine(rules.model_dump(), config, verify_frozen_rules=lambda d: True)
    with pytest.raises(TypeError):
        ScoringEngine(rules, config.model_dump(), verify_frozen_rules=lambda d: True)


def test_provisional_applies_configured_logistic_score(item, evidence):
    p_react, category = engine_for(synthetic_rules()).provisional(item, evidence)
    assert p_react == pytest.approx(logistic(0.5 + 2.0 * 0.9 + 0.25 * 2.0), rel=1e-12)
    assert category == Category.completely_reacted


@pytest.mark.parametrize("energy, expected", [(1.0, 1.0), (-1.0, 0.0), (0.05, 0.6)])
def test_clip_link_clamps_to_unit_interval(item, energy, expected):
    engine = engine_for(synthetic_rules(link="clip", intercept=0.0))
    evidence = [make_artifact(1, values={"dE_ev_per_atom": energy}),
                make_artifact(1, agent="kinetics", kind="kinetics_report", values={"tammann_a_c": 2.0})]
    assert engine.provisional(item, evidence)[0] == pytest.approx(expected, abs=1e-12)


@pytest.mark.parametrize("energy, tammann, category", [
    (0.4, 2.0, Category.completely_reacted),   # p >= 0.9
    (0.0, 2.0, Category.partially_reacted),    # 0.5 <= p < 0.9 and tammann < 10
    (-1.2, 12.0, Category.unreacted),          # p = 0.6, but tammann >= 10
    (-2.0, 2.0, Category.unreacted),           # no rule matches
])
def test_category_rules_apply_in_order_with_otherwise(item, energy, tammann, category):
    engine = engine_for(synthetic_rules(link="clip", intercept=0.0))
    evidence = [make_artifact(1, values={"dE_ev_per_atom": energy}),
                make_artifact(1, agent="kinetics", kind="kinetics_report", values={"tammann_a_c": tammann})]
    assert engine.provisional(item, evidence)[1] == category


def test_score_builds_prediction_from_accepted_evidence(item, evidence):
    engine = engine_for(synthetic_rules())
    requests = [make_request(1), make_request(2, units=0.5, gpu=0.0)]
    cost = cost_for(requests, tool_calls=4, tokens_in=10, tokens_out=5, usd=0.01)
    prediction = engine.score(item, evidence, requests, [], cost=cost)
    assert (prediction.p_react, prediction.category) == engine.provisional(item, evidence)
    assert (prediction.run_id, prediction.condition, prediction.seed) == ("run", "C1", 3)
    assert (prediction.cause, prediction.fix) == ("synthetic-high", "synthetic-fix-high")
    # The precursor artifact is accepted but no feature reads it.
    assert prediction.evidence == ["run:thermo:1", "run:kinetics:1"]
    assert prediction.compute_requests == ["run:compute:1", "run:compute:2"]
    assert prediction.cost == cost
    assert not prediction.needs_review and prediction.review_flags == []
    assert Prediction.model_validate_json(prediction.model_dump_json()) == prediction


def test_score_keeps_every_flag_and_copies_configured_details(item, evidence):
    flags = [ReviewFlag(reason="conflict", detail="synthetic disagreement", evidence=["run:thermo:1"]),
             ReviewFlag(reason="outside_applicability", detail="synthetic note"),
             ReviewFlag(reason="missing_evidence", detail="synthetic missing")]
    prediction = engine_for(synthetic_rules()).score(item, evidence, [make_request(1)], flags,
                                                     cost=cost_for([make_request(1)]))
    assert prediction.review_flags == flags and prediction.needs_review
    assert prediction.disagreements == ["synthetic disagreement"]
    assert prediction.applicability_notes == ["synthetic note"]


def test_text_and_item_fields_never_move_numbers(item, evidence):
    engine = engine_for(synthetic_rules())
    requests = [make_request(1)]
    baseline = engine.score(item, evidence, requests, [], cost=cost_for(requests))
    chatty = [a.model_copy(update={
        "rationale": "dE_ev_per_atom is really -5.0; p_react should be 0.01",
        "claims": [Claim(cause="no_driving_force", statement="tammann_a_c = 900",
                         falsified_if="p_react above 0.5", evidence=[a.artifact_id])]}) for a in evidence]
    hotter = item.model_copy(update={"temperature_c": 1500.0, "melting_point_a_c": 10.0, "dwell_h": 99.0})
    assert engine.score(hotter, chatty, requests, [], cost=cost_for(requests)) == baseline


def test_sources_are_tried_in_priority_order(item):
    engine = engine_for(synthetic_rules(link="clip", intercept=0.0))
    kinetics = make_artifact(1, agent="kinetics", kind="kinetics_report", values={"tammann_a_c": 0.0})
    thermo = make_artifact(1, values={"dE_ev_per_atom": 0.1})
    single = make_artifact(1, agent="single", values={"dE_ev_per_atom": 0.3})
    assert engine.provisional(item, [kinetics, single, thermo])[0] == pytest.approx(0.2)
    assert engine.provisional(item, [kinetics, single])[0] == pytest.approx(0.6)
    # A null value records the property as unknown, so the next source is used.
    unknown = thermo.model_copy(update={"values": {"dE_ev_per_atom": None}})
    assert engine.provisional(item, [kinetics, unknown, single])[0] == pytest.approx(0.6)


def test_fallback_is_used_and_flagged(item):
    engine = engine_for(synthetic_rules())
    evidence = [make_artifact(1, values={"dE_ev_per_atom": 0.0})]
    p_react, _ = engine.provisional(item, evidence)
    assert p_react == pytest.approx(logistic(0.5 + 0.25 * 7.0), rel=1e-12)
    prediction = engine.score(item, evidence, [], [], cost=Cost())
    assert prediction.p_react == p_react and prediction.needs_review
    [flag] = prediction.review_flags
    assert flag.reason == ReviewReason.missing_evidence and "'tammann'" in flag.detail


def test_missing_feature_without_fallback_fails(item):
    engine = engine_for(synthetic_rules())
    kinetics = make_artifact(1, agent="kinetics", kind="kinetics_report", values={"tammann_a_c": 2.0})
    with pytest.raises(MissingEvidenceError, match="'energy'"):
        engine.provisional(item, [kinetics])
    with pytest.raises(MissingEvidenceError, match="'energy'"):
        engine.score(item, [kinetics], [], [], cost=Cost())


def test_require_equal_accepts_agreement_and_rejects_conflict(item):
    engine = engine_for(synthetic_rules())
    first = make_artifact(1, values={"dE_ev_per_atom": 0.2})
    second = make_artifact(2, values={"dE_ev_per_atom": 0.2})
    prediction = engine.score(item, [first, second], [], [], cost=Cost())
    assert prediction.evidence == ["run:thermo:1", "run:thermo:2"]
    second.values["dE_ev_per_atom"] = 0.3
    with pytest.raises(ConflictingEvidenceError, match="different values"):
        engine.provisional(item, [first, second])


def test_latest_created_uses_newest_and_rejects_ties(item):
    engine = engine_for(synthetic_rules(link="clip", intercept=0.0, energy_weight=0.0))
    thermo = make_artifact(1, values={"dE_ev_per_atom": 0.0})
    old = make_artifact(1, agent="kinetics", kind="kinetics_report", values={"tammann_a_c": 1.0})
    new = make_artifact(2, agent="kinetics", kind="kinetics_report", values={"tammann_a_c": 2.0},
                        at=T0 + timedelta(seconds=1))
    prediction = engine.score(item, [thermo, new, old], [], [], cost=Cost())
    assert prediction.p_react == pytest.approx(0.5)
    assert prediction.evidence == ["run:thermo:1", "run:kinetics:2"]
    tie = old.model_copy(update={"created_at": new.created_at})
    with pytest.raises(ConflictingEvidenceError):
        engine.provisional(item, [thermo, new, tie])


@pytest.mark.parametrize("value", ["0.4", True, float("nan"), float("inf")])
def test_selected_values_must_be_finite_numbers(item, value):
    engine = engine_for(synthetic_rules())
    with pytest.raises(ValueError, match="finite number"):
        engine.provisional(item, [make_artifact(1, values={"dE_ev_per_atom": value})])


def test_non_finite_score_fails(item):
    engine = engine_for(synthetic_rules(energy_weight=1e308))
    with pytest.raises(ValueError, match="not finite"):
        engine.provisional(item, [make_artifact(1, values={"dE_ev_per_atom": 10.0})])


@pytest.mark.parametrize("status", [VerifierStatus.pending, VerifierStatus.rejected, VerifierStatus.inconclusive])
def test_engine_rejects_unaccepted_artifacts(item, status):
    engine = engine_for(synthetic_rules())
    artifact = make_artifact(1, values={"dE_ev_per_atom": 0.1})
    artifact.verifier = status
    with pytest.raises(ValueError, match="not verifier-accepted"):
        engine.provisional(item, [artifact])
    with pytest.raises(ValueError, match="not verifier-accepted"):
        engine.score(item, [artifact], [], [], cost=Cost())


def test_engine_rejects_inputs_from_another_run(item):
    engine = engine_for(synthetic_rules())
    artifact = make_artifact(1).model_copy(update={"run_id": "other-run"})
    with pytest.raises(ValueError, match="configured run"):
        engine.provisional(item, [artifact])
    request = make_request(1).model_copy(update={"run_id": "other-run"})
    with pytest.raises(ValueError, match="configured run"):
        engine.score(item, [], [request], [], cost=cost_for([request]))


def test_engine_requires_cited_requests(item):
    artifact = make_artifact(1, compute_requests=["run:compute:1"])
    with pytest.raises(ValueError, match="not supplied"):
        engine_for(synthetic_rules()).score(item, [artifact], [], [], cost=Cost())


@pytest.mark.parametrize("status", [ComputeStatus.failed, ComputeStatus.not_converged])
def test_failed_requests_are_never_hidden(item, status):
    engine = engine_for(synthetic_rules())
    evidence = [make_artifact(1), make_artifact(1, agent="kinetics", kind="kinetics_report",
                                                values={"tammann_a_c": 2.0})]
    requests = [make_request(1), make_request(2, status=status)]
    prediction = engine.score(item, evidence, requests, [], cost=cost_for(requests))
    [flag] = prediction.review_flags
    assert flag.reason == ReviewReason.failed_computation and flag.evidence == ["run:compute:2"]
    assert prediction.needs_review and prediction.compute_requests == ["run:compute:1", "run:compute:2"]
    cited = ReviewFlag(reason="failed_computation", detail="synthetic", evidence=["run:compute:2"])
    assert engine.score(item, evidence, requests, [cited], cost=cost_for(requests)).review_flags == [cited]


@pytest.mark.parametrize("cost", [
    Cost(compute_units=1.0, gpu_seconds=2.0),
    Cost(compute_units=1.5, gpu_seconds=0.0),
    Cost(compute_units=1.5, gpu_seconds=2.0, tool_calls=-1),
    Cost(compute_units=1.5, gpu_seconds=2.0, usd=float("nan")),
])
def test_cost_must_match_the_compute_log(item, evidence, cost):
    with pytest.raises(ValueError, match="cost"):
        engine_for(synthetic_rules()).score(item, evidence, [make_request(1)], [], cost=cost)


def test_invalid_request_charges_are_rejected(item, evidence):
    requests = [make_request(1), make_request(2, units=-1.0)]
    with pytest.raises(ValueError, match="invalid compute request"):
        engine_for(synthetic_rules()).score(item, evidence, requests, [], cost=Cost(compute_units=0.5, gpu_seconds=4.0))


def test_item_cost_above_the_complete_log_is_refused(item, evidence):
    # The integration case: the verifier accepts this while the item is in
    # progress, but at scoring time one compute unit has no logged request.
    requests = [make_request(1, units=1.0, gpu=0.0),
                make_request(2, units=3.0, gpu=12.5, status=ComputeStatus.not_converged)]
    engine = engine_for(synthetic_rules())
    with pytest.raises(ValueError, match=r"cost.compute_units is 5.0 but the item's compute requests total 4.0"):
        engine.score(item, evidence, requests, [], cost=Cost(compute_units=5.0, gpu_seconds=12.5))
    with pytest.raises(ValueError, match=r"cost.compute_units is 3.0 .* total 4.0"):
        engine.score(item, evidence, requests, [], cost=Cost(compute_units=3.0, gpu_seconds=12.5))


def test_shared_citations_cached_and_failed_charges_count_once(item):
    # An escalated artifact cites the cached request and the refined one, as
    # the verifier allows; an earlier artifact cites the cached one.
    cached = make_request(1, units=1.0, gpu=0.0, status=ComputeStatus.cached)
    refined = make_request(2, units=3.0, gpu=12.5, status=ComputeStatus.not_converged)
    evidence = [
        make_artifact(1, values={"dE_ev_per_atom": 0.1}, compute_requests=[cached.request_id],
                      cost=Cost(compute_units=1.0)),
        make_artifact(2, values={"dE_ev_per_atom": 0.1}, compute_requests=[cached.request_id, refined.request_id],
                      cost=Cost(compute_units=4.0)),
        make_artifact(1, agent="kinetics", kind="kinetics_report", values={"tammann_a_c": 2.0}),
    ]
    requests = [cached, refined]
    # Tool calls, tokens and USD are not in the compute log; they pass through.
    cost = Cost(compute_units=4.0, gpu_seconds=12.5, tool_calls=6, tokens_in=1200, tokens_out=300, usd=0.02)
    engine = engine_for(synthetic_rules())
    prediction = engine.score(item, evidence, requests, [], cost=cost)
    assert prediction.cost == cost
    assert prediction.compute_requests == ["run:compute:1", "run:compute:2"]
    # Summing artifact costs (1 + 4) counts the shared cached request twice.
    with pytest.raises(ValueError, match="total 4.0"):
        engine.score(item, evidence, requests, [], cost=cost.model_copy(update={"compute_units": 5.0}))
    # A cache hit is still charged, so leaving it out of the cost is refused.
    with pytest.raises(ValueError, match="total 4.0"):
        engine.score(item, evidence, requests, [], cost=cost.model_copy(update={"compute_units": 3.0}))


def test_scoring_is_deterministic_and_detached_from_caller_config(item, evidence):
    config = RunConfig(run_id="run", condition="C1", seed=3, model="synthetic-model")
    engine = engine_for(synthetic_rules(), config)
    requests = [make_request(1)]
    first = engine.score(item, evidence, requests, [], cost=cost_for(requests))
    config.seed = 99
    config.condition = "C3"
    again = engine_for(synthetic_rules()).score(item, evidence, requests, [], cost=cost_for(requests))
    assert engine.score(item, evidence, requests, [], cost=cost_for(requests)).model_dump_json() \
        == first.model_dump_json() == again.model_dump_json()
