"""Tests of the frozen rule set in protocol/scoring_rules.json (OPEN-05).

Synthetic evidence only: every formula, energy and temperature below is an
arbitrary test value, not an experimental outcome, and no label is read.
"""
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from kiln.schemas import (
    Artifact,
    Category,
    Claim,
    ComputeRequest,
    ComputeStatus,
    ComputeTier,
    Cost,
    Item,
    Prediction,
    ReviewFlag,
    ReviewReason,
    RunConfig,
    VerifierStatus,
)
from kiln.scoring import score as score_module
from kiln.scoring.rules import ScoringRules
from kiln.scoring.score import (
    FROZEN_RULES_PATH,
    FROZEN_RULES_SHA256,
    ScoringConfigurationError,
    changed_prediction,
    frozen_engine,
    is_frozen_digest,
    load_frozen_rules,
    provisional,
    score,
)

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
FURNACE_C = 900.0
CONFIG = RunConfig(run_id="run", condition="C4", seed=0, model="synthetic-model")


@pytest.fixture
def item():
    return Item(item_id="synthetic", source="alab_demo", precursor_a="A", precursor_b="B",
                temperature_c=FURNACE_C, split="dev")


def thermo(dE, seq=1, at=T0, **values):
    return Artifact(artifact_id=f"run:thermo:{seq}", run_id="run", item_id="synthetic", agent="thermo",
                    type="reaction_report", values={"dE_ev_per_atom": dE, **values},
                    verifier=VerifierStatus.accepted, created_at=at)


def kinetics(tammann_a, tammann_b, seq=1, at=T0):
    return Artifact(artifact_id=f"run:kinetics:{seq}", run_id="run", item_id="synthetic", agent="kinetics",
                    type="kinetics_report", values={"tammann_a_c": tammann_a, "tammann_b_c": tammann_b},
                    verifier=VerifierStatus.accepted, created_at=at)


def precursor(dE, seq=1, at=T0):
    values = {"precursor_a_decomposition_known": True, "decomposition_conditions_unverified": True}
    if dE is not None:
        values["dE_ev_per_atom"] = dE
    return Artifact(artifact_id=f"run:precursor:{seq}", run_id="run", item_id="synthetic", agent="precursor",
                    type="precursor_report", values=values, verifier=VerifierStatus.accepted, created_at=at)


def expected_p(dE, margin_a, margin_b):
    z = -20.0 * dE + 0.005 * margin_a + 0.005 * margin_b
    return 1 / (1 + math.exp(-z))


def predict(item, accepted, flags=()):
    return frozen_engine(CONFIG).score(item, accepted, [], list(flags), cost=Cost())


# ---------- the rule file and its pin ----------

def test_rule_file_loads_and_matches_the_pinned_digest():
    rules = load_frozen_rules()
    document = json.loads(FROZEN_RULES_PATH.read_text(encoding="utf-8"))
    assert rules.digest() == FROZEN_RULES_SHA256 == document["rules_sha256"]
    assert is_frozen_digest(FROZEN_RULES_SHA256) is True
    assert frozen_engine(CONFIG).rules_digest == FROZEN_RULES_SHA256


@pytest.mark.parametrize("digest", ["", "0" * 64, FROZEN_RULES_SHA256.upper(), None, 1])
def test_only_the_pinned_digest_is_frozen(digest):
    assert is_frozen_digest(digest) is False


def _copy(tmp_path: Path, edit) -> Path:
    document = json.loads(FROZEN_RULES_PATH.read_text(encoding="utf-8"))
    edit(document)
    path = tmp_path / "scoring_rules.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def test_edited_rules_fail_closed(tmp_path):
    def change_threshold(document):
        document["rules"]["category_rules"][2]["when"][0]["threshold"] = -0.1

    path = _copy(tmp_path, change_threshold)
    with pytest.raises(ScoringConfigurationError, match="records digest"):
        load_frozen_rules(path)

    def change_and_rehash(document):
        change_threshold(document)
        rules = ScoringRules.model_validate_json(json.dumps(document["rules"]))
        document["rules_sha256"] = rules.digest()

    with pytest.raises(ScoringConfigurationError, match="not the frozen rules"):
        load_frozen_rules(_copy(tmp_path, change_and_rehash))


def test_notes_do_not_affect_the_frozen_rules(tmp_path):
    def edit_notes(document):
        document["justification"]["p_react"] = "edited note"

    assert load_frozen_rules(_copy(tmp_path, edit_notes)).digest() == FROZEN_RULES_SHA256


@pytest.mark.parametrize("edit", [
    lambda d: d.pop("rules"),
    lambda d: d.pop("rules_sha256"),
    lambda d: d["rules"]["features"][0].update(fallback=None, extra=1),
    lambda d: d["rules"]["p_react"]["terms"][0].update(weight="NaN"),
])
def test_invalid_rule_files_fail_closed(tmp_path, edit):
    with pytest.raises(ScoringConfigurationError, match="missing or invalid"):
        load_frozen_rules(_copy(tmp_path, edit))
    with pytest.raises(ScoringConfigurationError, match="missing or invalid"):
        load_frozen_rules(tmp_path / "absent.json")


def test_entry_points_fail_closed_when_the_rule_file_is_edited(tmp_path, monkeypatch, item):
    def change_weight(document):
        document["rules"]["p_react"]["terms"][0]["weight"] = -10.0

    monkeypatch.setattr(score_module, "FROZEN_RULES_PATH", _copy(tmp_path, change_weight))
    accepted = [thermo(-0.2), kinetics(500.0, 600.0)]
    with pytest.raises(ScoringConfigurationError):
        provisional(item, accepted)
    with pytest.raises(ScoringConfigurationError):
        score(item, accepted, [], [], config=CONFIG, cost=Cost())
    with pytest.raises(ScoringConfigurationError):
        frozen_engine(CONFIG)


# ---------- p_react and the four categories ----------

def test_p_react_is_the_documented_fixed_formula(item):
    accepted = [thermo(-0.12), kinetics(700.0, 1000.0)]
    p_react, _ = provisional(item, accepted)
    assert p_react == pytest.approx(expected_p(-0.12, FURNACE_C - 700.0, FURNACE_C - 1000.0), rel=1e-12)


@pytest.mark.parametrize("dE, tammann_a, tammann_b, category, cause", [
    (0.02, 500.0, 600.0, Category.unreacted, "no_driving_force"),
    (-0.05, 500.0, 600.0, Category.unreacted, "no_driving_force"),        # boundary is inclusive
    (-0.0501, 500.0, 600.0, Category.completely_reacted, "driving_force_and_mobility"),
    (-0.2, 1000.0, 1100.0, Category.unreacted, "kinetically_limited"),
    (-0.2, 1000.0, 600.0, Category.partially_reacted, "one_precursor_below_tammann"),
    (-0.2, 500.0, 1000.0, Category.partially_reacted, "one_precursor_below_tammann"),
    (-0.2, FURNACE_C, FURNACE_C, Category.completely_reacted, "driving_force_and_mobility"),  # at Tammann
    (-0.2, 500.0, 600.0, Category.completely_reacted, "driving_force_and_mobility"),
])
def test_categories_follow_driving_force_then_tammann(item, dE, tammann_a, tammann_b, category, cause):
    prediction = predict(item, [thermo(dE), kinetics(tammann_a, tammann_b)])
    assert (prediction.category, prediction.cause) == (category, cause)
    assert prediction.fix.strip() and not prediction.needs_review
    assert prediction.evidence == ["run:thermo:1", "run:kinetics:1"]
    assert (prediction.p_react, prediction.category) == provisional(item, [thermo(dE), kinetics(tammann_a, tammann_b)])


def test_decomposition_without_driving_force_is_transformed(item):
    # The Precursor agent's decomposition-aware energy is used before Thermo's.
    accepted = [thermo(-0.3), precursor(-0.01), kinetics(500.0, 600.0)]
    prediction = predict(item, accepted)
    assert (prediction.category, prediction.cause) == (Category.transformed, "decomposes_only")
    assert prediction.p_react == pytest.approx(expected_p(-0.01, 400.0, 300.0), rel=1e-12)
    assert "run:precursor:1" in prediction.evidence and "run:thermo:1" not in prediction.evidence


def test_decomposition_with_driving_force_follows_tammann(item):
    accepted = [thermo(0.1), precursor(-0.2), kinetics(1000.0, 600.0)]
    prediction = predict(item, accepted)
    assert (prediction.category, prediction.cause) == (Category.partially_reacted, "one_precursor_below_tammann")


def test_precursor_report_without_energy_is_not_decomposition(item):
    accepted = [thermo(0.1), precursor(None), kinetics(500.0, 600.0)]
    assert predict(item, accepted).cause == "no_driving_force"


def test_every_category_is_reachable(item):
    seen = {predict(item, accepted).category for accepted in (
        [thermo(0.1), kinetics(500.0, 600.0)],
        [precursor(0.0), kinetics(500.0, 600.0)],
        [thermo(-0.2), kinetics(1000.0, 600.0)],
        [thermo(-0.2), kinetics(500.0, 600.0)],
    )}
    assert seen == set(Category)


def test_latest_thermo_estimate_supersedes_cached_lookup(item):
    cached = thermo(-0.03, seq=1, compute_tier="cached_lookup")
    refined = thermo(-0.2, seq=2, at=T0 + timedelta(seconds=5), compute_tier="single_point")
    prediction = predict(item, [cached, refined, kinetics(500.0, 600.0)])
    assert prediction.category == Category.completely_reacted
    assert prediction.p_react == pytest.approx(expected_p(-0.2, 400.0, 300.0), rel=1e-12)
    assert "run:thermo:1" not in prediction.evidence


def test_p_react_is_monotone_in_driving_force_and_furnace_temperature(item):
    energies = [-0.5, -0.2, -0.06, -0.05, 0.0, 0.1]
    scores = [provisional(item, [thermo(dE), kinetics(500.0, 600.0)])[0] for dE in energies]
    assert scores == sorted(scores, reverse=True)
    furnaces = [400.0, 700.0, 900.0, 1200.0]
    scores = [provisional(item.model_copy(update={"temperature_c": t}),
                          [thermo(-0.1), kinetics(800.0, 800.0)])[0] for t in furnaces]
    assert scores == sorted(scores) and all(0.0 < s < 1.0 for s in scores)


# ---------- missing and conflicting evidence ----------

def test_missing_reaction_energy_is_flagged_with_defined_fallback(item):
    prediction = predict(item, [kinetics(500.0, 600.0)])
    assert (prediction.category, prediction.cause) == (Category.unreacted, "insufficient_evidence")
    assert prediction.p_react == pytest.approx(expected_p(0.0, 400.0, 300.0), rel=1e-12)
    [flag] = prediction.review_flags
    assert flag.reason == ReviewReason.missing_evidence and "'reaction_energy_ev_per_atom'" in flag.detail
    assert prediction.needs_review and prediction.evidence == ["run:kinetics:1"]


def test_null_reaction_energy_counts_as_missing(item):
    prediction = predict(item, [thermo(None), kinetics(500.0, 600.0)])
    assert prediction.cause == "insufficient_evidence" and prediction.needs_review


def test_missing_tammann_is_neutral_and_flagged(item):
    prediction = predict(item, [thermo(-0.2), kinetics(None, 600.0)])
    assert (prediction.category, prediction.cause) == (Category.completely_reacted, "driving_force_and_mobility")
    assert prediction.p_react == pytest.approx(expected_p(-0.2, 0.0, 300.0), rel=1e-12)
    [flag] = prediction.review_flags
    assert flag.reason == ReviewReason.missing_evidence and "'furnace_minus_tammann_a_c'" in flag.detail


def test_one_missing_tammann_never_claims_kinetic_limitation(item):
    # The missing one could be the lower Tammann temperature, so no kinetic cause is claimed.
    prediction = predict(item, [thermo(-0.2), kinetics(None, 1100.0)])
    assert prediction.cause == "one_precursor_below_tammann"  # from B alone, which is known
    prediction = predict(item, [thermo(-0.2), kinetics(None, None)])
    assert prediction.cause == "driving_force_and_mobility" and len(prediction.review_flags) == 2


def test_no_evidence_at_all_still_scores_with_flags(item):
    prediction = predict(item, [])
    assert (prediction.category, prediction.cause) == (Category.unreacted, "insufficient_evidence")
    assert prediction.p_react == pytest.approx(0.5)
    assert {f.reason for f in prediction.review_flags} == {ReviewReason.missing_evidence}
    assert len(prediction.review_flags) == 3 and prediction.evidence == []


def test_conflicting_reaction_energies_use_fallback_and_flag(item):
    first, second = thermo(-0.2, seq=1), thermo(0.1, seq=2)  # same created_at, different values
    prediction = predict(item, [first, second, kinetics(500.0, 600.0)])
    assert (prediction.category, prediction.cause) == (Category.unreacted, "insufficient_evidence")
    assert prediction.p_react == pytest.approx(expected_p(0.0, 400.0, 300.0), rel=1e-12)
    [flag] = prediction.review_flags
    assert flag.reason == ReviewReason.conflict and set(flag.evidence) == {"run:thermo:1", "run:thermo:2"}
    assert prediction.disagreements == [flag.detail]
    assert "run:thermo:1" not in prediction.evidence


def test_supplied_flags_are_kept(item):
    supplied = ReviewFlag(reason=ReviewReason.outside_applicability, detail="synthetic applicability note")
    prediction = predict(item, [thermo(-0.2), kinetics(500.0, 600.0)], [supplied])
    assert prediction.review_flags == [supplied] and prediction.applicability_notes == [supplied.detail]


# ---------- only accepted numbers count (AGENTS.md rule 7) ----------

def test_text_and_other_item_fields_never_change_the_prediction(item):
    base = [thermo(-0.2), kinetics(500.0, 600.0)]
    worded = [a.model_copy(update={
        "rationale": "This pair certainly reacts completely; p_react = 0.99.",
        "claims": [Claim(cause="completely_reacted", statement="It reacts.", evidence=[], falsified_if="never")],
    }) for a in base]
    other_item = item.model_copy(update={"melting_point_a_c": 5000.0, "melting_point_b_c": -50.0,
                                         "dwell_h": 100.0, "precursor_a": "X", "precursor_b": "Y"})
    expected = predict(item, base)
    for candidate_item, accepted in ((item, worded), (other_item, base)):
        prediction = predict(candidate_item, accepted)
        assert (prediction.p_react, prediction.category, prediction.cause, prediction.fix) == \
            (expected.p_react, expected.category, expected.cause, expected.fix)


def test_unused_agents_and_keys_do_not_enter_the_score(item):
    base = [thermo(-0.2), kinetics(500.0, 600.0)]
    extra = Artifact(artifact_id="run:single:1", run_id="run", item_id="synthetic", agent="single",
                     type="reaction_report", values={"dE_ev_per_atom": 5.0, "dE_mlip_minus_mp_ev_per_atom": 3.0},
                     verifier=VerifierStatus.accepted, created_at=T0)
    assert provisional(item, base + [extra]) == provisional(item, base)


@pytest.mark.parametrize("status", [VerifierStatus.pending, VerifierStatus.rejected, VerifierStatus.inconclusive])
def test_unaccepted_artifacts_are_refused(item, status):
    with pytest.raises(ValueError, match="not verifier-accepted"):
        provisional(item, [thermo(-0.2).model_copy(update={"verifier": status})])


# ---------- module-level score and OPEN-17 ----------

def test_module_score_matches_the_frozen_engine(item):
    request = ComputeRequest(request_id="run:compute:1", run_id="run", item_id="synthetic", agent="thermo",
                             tier=ComputeTier.cached_lookup, reason="synthetic", inputs={}, settings={},
                             cache_key="k", status=ComputeStatus.failed, compute_units=1.0, gpu_seconds=0.0)
    accepted = [thermo(-0.2), kinetics(500.0, 600.0)]
    cost = Cost(compute_units=1.0, tool_calls=3)
    prediction = score(item, accepted, [request], [], config=CONFIG, cost=cost)
    assert prediction == frozen_engine(CONFIG).score(item, accepted, [request], [], cost=cost)
    assert Prediction.model_validate_json(prediction.model_dump_json()) == prediction
    assert prediction.compute_requests == ["run:compute:1"]
    assert [f.reason for f in prediction.review_flags] == [ReviewReason.failed_computation]


def test_changed_prediction_is_a_category_change():
    assert changed_prediction((0.6, Category.unreacted), (0.9, Category.completely_reacted)) is True
    assert changed_prediction((0.2, Category.unreacted), (0.45, Category.unreacted)) is False
    assert changed_prediction((0.7, "partially_reacted"), (0.7, Category.partially_reacted)) is False
    with pytest.raises(TypeError):
        changed_prediction((0.1,), (0.2, Category.unreacted))
    with pytest.raises(ValueError):
        changed_prediction((0.1, "reacted"), (0.2, Category.unreacted))


def test_changed_prediction_from_provisional_before_and_after(item):
    before = provisional(item, [thermo(-0.03), kinetics(500.0, 600.0)])
    after = provisional(item, [thermo(-0.03), thermo(-0.2, seq=2, at=T0 + timedelta(seconds=1)),
                               kinetics(500.0, 600.0)])
    assert before[1] == Category.unreacted and after[1] == Category.completely_reacted
    assert changed_prediction(before, after) is True


# ---------- end to end with the real specialists and the verifier ----------

def test_real_specialists_through_verifier_to_frozen_score(tmp_path):
    from kiln.agents.kinetics import Kinetics
    from kiln.agents.precursor import Precursor
    from kiln.agents.thermo import Thermo
    from kiln.board import Board
    from kiln.budget import Budget
    from kiln.compute.backends import StubBackend
    from kiln.compute.cache import ResultCache
    from kiln.compute.client import ComputeClient, use
    from kiln.review import flags
    from kiln.verifier import verify

    run = tmp_path / "synthetic"
    config = RunConfig(run_id="synthetic", condition="C4", seed=1, model="offline",
                       tier_prices={"cached_lookup": 1.0, "single_point": 1.0, "decomposition_reeval": 1.0})
    budget = Budget(config)
    board = Board(run)
    service = ComputeClient(run, config, StubBackend(), ResultCache(tmp_path / "cache"),
                            {ComputeTier.cached_lookup: {}, ComputeTier.single_point: {},
                             ComputeTier.decomposition_reeval: {}})
    use(service)
    # Same synthetic pair as tests/agents/test_specialists.py; energies come from the stub backend.
    item = Item(item_id="example", source="alab_demo", precursor_a="CaCO3", precursor_b="TiO2",
                temperature_c=900, melting_point_a_c=825, melting_point_b_c=1843, split="dev")
    try:
        for agent in (Thermo(), Precursor(), Kinetics()):
            agent.step(item, board, budget)
        requests = [ComputeRequest.model_validate_json(line)
                    for line in service.log_path.read_text().splitlines()]
        artifacts = board.artifacts(item.item_id)
        tool_values = {k: v for a in artifacts if a.agent == "kinetics" for k, v in a.values.items()
                       if k.startswith("tammann_")}
        for artifact in artifacts:
            status, notes = verify(artifact, board, requests=requests, config=config,
                                   item_cost=budget.spent, tool_values=tool_values)
            assert status == VerifierStatus.accepted, notes
            board.post_artifact(artifact.model_copy(update={"verifier": status, "verifier_notes": notes}))
        accepted = board.accepted_artifacts(item.item_id)
        flagged = flags(item, accepted, requests)
        prediction = frozen_engine(config).score(item, accepted, requests, flagged,
                                                 cost=budget.spent, gpu_seconds_from_log=True)
        assert Prediction.model_validate_json(prediction.model_dump_json()) == prediction
        assert (prediction.p_react, prediction.category) == provisional(item, accepted)
        assert set(prediction.evidence) <= {a.artifact_id for a in accepted}
        assert any(a.startswith("synthetic:kinetics") for a in prediction.evidence)
        assert prediction.compute_requests == [r.request_id for r in requests]
    finally:
        use(None)
