"""Baseline table (OPEN-08, protocol §4.2): AUROC of a ranking score, nothing else.

Synthetic items, energies, melting points and labels only.
"""
import hashlib

import pytest

import kiln.scoring.evaluate as evaluate_module
from kiln.baselines.b0 import (
    CompetitionMarginConfig,
    CompetitionMarginInput,
    DrivingForceConfig,
    DrivingForceInput,
    TemperatureRatioConfig,
    run_b0,
    run_b0_t,
    run_competition_margin,
)
from kiln.schemas import Category, Item, Label
from kiln.scoring.evaluate import (
    BASELINE_RANKING_SCORES,
    EvaluationLockedError,
    UnscoredLabel,
    baseline_scores_sha256,
    evaluate_baseline,
    read_labels_jsonl,
)

ZERO = DrivingForceConfig(dE_threshold_ev_per_atom=0.0)


def item(item_id, temperature_c=700.0, mp_a=None, mp_b=None, split="heldout"):
    return Item(item_id=item_id, source="precursor_genome", precursor_a=f"SynA{item_id}", precursor_b=f"SynB{item_id}",
                temperature_c=temperature_c, melting_point_a_c=mp_a, melting_point_b_c=mp_b, split=split)


def label(item_id, category):
    category = Category(category)
    return Label(item_id=item_id, category=category,
                 reacted=category in (Category.partially_reacted, Category.completely_reacted))


# B0: score = -dE. d has no energy (undetermined); e has no outcome to score (OPEN-12).
B0_ENERGIES = {"a": -0.3, "b": -0.1, "c": 0.05, "d": None, "e": -0.2, "f": 0.2}


def b0_case(energies=B0_ENERGIES, config=ZERO):
    items = [item(item_id) for item_id in energies]
    inputs = [DrivingForceInput(item_id=i, dE_ev_per_atom=dE, evidence=() if dE is None else (f"syn:compute:{i}",))
              for i, dE in energies.items()]
    labels = [label("a", "partially_reacted"), label("b", "unreacted"), label("c", "completely_reacted"),
              label("d", "completely_reacted"), UnscoredLabel(item_id="e"), label("f", "transformed")]
    return run_b0(items, inputs, config), items, labels


def no_labels():
    pytest.fail("labels loaded")


def posted(decisions, items):
    digest = baseline_scores_sha256(decisions, items)
    return lambda candidate: candidate == digest


def test_b0_auroc_uses_minus_dE_and_lists_undetermined_items():
    decisions, items, labels = b0_case()
    result = evaluate_baseline(decisions, items, lambda: labels, verify_posted_baseline_hash=posted(decisions, items))
    # Scored: a (0.3, reacted), b (0.1, not), c (-0.05, reacted), f (-0.2, not) -> 3 of 4 pairs ordered.
    assert result == {
        "condition": "B0",
        "ranking_score": "-dE_ev_per_atom",
        "scores_sha256": baseline_scores_sha256(decisions, items),
        "commitment": result["commitment"],
        "split": "heldout",
        "source": "precursor_genome",
        "n": 6,
        "n_determined": 5,
        "n_undetermined": 1,
        "n_unclassified_or_null": 1,
        "n_scored": 4,
        "auroc": 0.75,
        "undetermined": [{"item_id": "d", "review_flags": ["missing_evidence"]}],
        "not_reported": result["not_reported"],
    }
    assert "verified as posted" in result["commitment"]
    assert "p_react" in result["not_reported"] and "OPEN-08" in result["not_reported"]


def test_baseline_reports_no_p_react_brier_or_category_metrics():
    decisions, items, labels = b0_case()
    result = evaluate_baseline(decisions, items, lambda: labels, verify_posted_baseline_hash=posted(decisions, items))
    for key in ("p_react", "brier", "four_class_accuracy", "four_class_macro_f1", "coverage", "metrics", "category"):
        assert key not in result


def test_undetermined_item_is_never_imputed():
    decisions, items, labels = b0_case()
    flipped = [label("d", "unreacted") if getattr(x, "item_id", None) == "d" else x for x in labels]
    verify = posted(decisions, items)
    first = evaluate_baseline(decisions, items, lambda: labels, verify_posted_baseline_hash=verify)
    second = evaluate_baseline(decisions, items, lambda: flipped, verify_posted_baseline_hash=verify)
    assert first["auroc"] == second["auroc"] == 0.75
    assert first["n_scored"] == second["n_scored"] == 4


def test_b0_threshold_changes_decisions_but_not_scores_digest_or_auroc():
    zero, items, labels = b0_case()
    shifted, _, _ = b0_case(config=DrivingForceConfig(dE_threshold_ev_per_atom=-0.15))
    assert [d.reacts for d in zero] != [d.reacts for d in shifted]
    assert baseline_scores_sha256(zero, items) == baseline_scores_sha256(shifted, items)
    verify = posted(zero, items)
    assert (evaluate_baseline(shifted, items, lambda: labels, verify_posted_baseline_hash=verify)["auroc"]
            == evaluate_baseline(zero, items, lambda: labels, verify_posted_baseline_hash=verify)["auroc"])


def test_b0_t_auroc_uses_the_temperature_ratio():
    items = [
        item("a", 700.0, 1000.0, 800.0),    # 973.15 / 1273.15 = 0.764, reacted
        item("b", 500.0, 1500.0, 200.0),    # 773.15 / 1773.15 = 0.436, not
        item("c", 900.0, 600.0, 700.0),     # 1173.15 / 973.15 = 1.205, reacted
        item("d", 900.0, None, 700.0),      # undetermined: the missing one could be the higher
        item("e", 1000.0, 900.0, 950.0),    # 1273.15 / 1223.15 = 1.041, not
    ]
    labels = [label("a", "completely_reacted"), label("b", "unreacted"), label("c", "partially_reacted"),
              label("d", "unreacted"), label("e", "transformed")]
    decisions = run_b0_t(items, TemperatureRatioConfig(ratio_threshold=1.0))
    result = evaluate_baseline(decisions, items, lambda: labels, verify_posted_baseline_hash=posted(decisions, items))
    assert result["condition"] == "B0-T"
    assert result["ranking_score"] == BASELINE_RANKING_SCORES["B0-T"]
    assert result["ranking_score"].startswith("ratio")
    assert (result["n"], result["n_undetermined"], result["n_scored"], result["auroc"]) == (5, 1, 4, 0.75)
    assert result["undetermined"] == [{"item_id": "d", "review_flags": ["missing_evidence"]}]
    # No ratio threshold is frozen (OPEN-25): the one the code needs to run does not change the scores.
    other = run_b0_t(items, TemperatureRatioConfig(ratio_threshold=0.5))
    assert baseline_scores_sha256(other, items) == result["scores_sha256"]


def test_b0_t_decision_must_come_from_these_items():
    items = [item("a", 700.0, 1000.0, 800.0), item("b", 500.0, 1500.0, 200.0)]
    decisions = run_b0_t([item("a", 800.0, 1000.0, 800.0), items[1]], TemperatureRatioConfig(ratio_threshold=1.0))
    with pytest.raises(ValueError, match="not computed from this item's temperatures"):
        evaluate_baseline(decisions, items, no_labels, verify_posted_baseline_hash=lambda _: True)


def test_baseline_gate_is_fail_closed():
    decisions, items, _ = b0_case()

    def broken(digest):
        raise RuntimeError("unavailable")

    for verify in (None, lambda digest: False, lambda digest: "yes", lambda digest: 1, broken):
        with pytest.raises(EvaluationLockedError, match="[Bb]aseline scores"):
            evaluate_baseline(decisions, items, no_labels, verify_posted_baseline_hash=verify)
    with pytest.raises(EvaluationLockedError):
        evaluate_baseline(decisions, items, no_labels)


def test_verifier_sees_the_scores_digest():
    decisions, items, labels = b0_case()
    seen = []
    evaluate_baseline(decisions, items, lambda: labels, verify_posted_baseline_hash=lambda d: seen.append(d) is None)
    assert seen == [baseline_scores_sha256(decisions, items)]


def test_re_chosen_scores_do_not_match_the_posted_digest():
    decisions, items, labels = b0_case()
    verify = posted(decisions, items)
    for energies in ({**B0_ENERGIES, "a": -0.31}, {**B0_ENERGIES, "d": -0.1}, {**B0_ENERGIES, "a": None}):
        changed, _, _ = b0_case(energies)
        with pytest.raises(EvaluationLockedError):
            evaluate_baseline(changed, items, no_labels, verify_posted_baseline_hash=verify)
    b0_t = run_b0_t(items, TemperatureRatioConfig(ratio_threshold=1.0))  # same items, other baseline
    with pytest.raises(EvaluationLockedError):
        evaluate_baseline(b0_t, items, no_labels, verify_posted_baseline_hash=verify)


def test_scores_digest_is_canonical():
    decisions, items, _ = b0_case()
    digest = baseline_scores_sha256(decisions, items)
    assert len(digest) == 64 and int(digest, 16) >= 0
    assert baseline_scores_sha256(list(reversed(decisions)), list(reversed(items))) == digest
    # dE = 0.0 and dE = -0.0 both score 0.0, so they commit to the same bytes.
    plus, minus = b0_case({"a": 0.0, "b": -0.1})[0], b0_case({"a": -0.0, "b": -0.1})[0]
    two = [item("a"), item("b")]
    assert baseline_scores_sha256(plus, two) == baseline_scores_sha256(minus, two)


def test_wrong_inputs_block_label_loading():
    decisions, items, _ = b0_case()
    b0_t = run_b0_t(items, TemperatureRatioConfig(ratio_threshold=1.0))
    margins = run_competition_margin(
        items,
        [CompetitionMarginInput(item_id=i.item_id, dE_best_ev_per_atom=-0.2, best_evidence=("syn:1",),
                                dE_competing_ev_per_atom=-0.1, competing_evidence=("syn:2",)) for i in items],
        CompetitionMarginConfig(margin_threshold_ev_per_atom=0.06),
    )
    verify = lambda _: True  # noqa: E731
    with pytest.raises(TypeError, match="B60meV"):
        evaluate_baseline(margins, items, no_labels, verify_posted_baseline_hash=verify)
    with pytest.raises(ValueError, match="one baseline"):
        evaluate_baseline([*decisions[:3], *b0_t[3:]], items, no_labels, verify_posted_baseline_hash=verify)
    with pytest.raises(ValueError, match="same nonempty set"):
        evaluate_baseline(decisions[:-1], items, no_labels, verify_posted_baseline_hash=verify)
    with pytest.raises(ValueError, match="same nonempty set"):
        evaluate_baseline([], [], no_labels, verify_posted_baseline_hash=verify)
    with pytest.raises(ValueError, match="duplicate baseline decision"):
        evaluate_baseline([*decisions, decisions[0]], items, no_labels, verify_posted_baseline_hash=verify)
    mixed = [items[0].model_copy(update={"split": "dev"}), *items[1:]]
    with pytest.raises(ValueError, match="one split and one source"):
        evaluate_baseline(decisions, mixed, no_labels, verify_posted_baseline_hash=verify)


def test_labels_must_cover_exactly_the_baseline_items():
    decisions, items, labels = b0_case()
    verify = posted(decisions, items)
    with pytest.raises(ValueError, match="labels and baseline decisions must contain the same item IDs"):
        evaluate_baseline(decisions, items, lambda: labels[:-1], verify_posted_baseline_hash=verify)
    bad = [Label(item_id="a", category="unreacted", reacted=True), *labels[1:]]
    with pytest.raises(ValueError, match="agree with category"):
        evaluate_baseline(decisions, items, lambda: bad, verify_posted_baseline_hash=verify)


def test_auroc_is_undefined_when_one_class_is_absent():
    decisions, items, labels = b0_case()
    unreacted = [label(i.item_id, "unreacted") for i in items]
    result = evaluate_baseline(decisions, items, lambda: unreacted, verify_posted_baseline_hash=posted(decisions, items))
    assert result["auroc"] is None and result["n_scored"] == 5


def test_baseline_reads_a_stored_label_file(tmp_path):
    decisions, items, _ = b0_case()
    path = tmp_path / "synthetic_labels.jsonl"
    path.write_text("".join(f'{{"item_id": "{i}", "category": {c}}}\n' for i, c in (
        ("a", '"Partially Reacted"'), ("b", '"unreacted"'), ("c", '"Completely-Reacted"'),
        ("d", '"completely reacted"'), ("e", '"Unclassified"'), ("f", '"TRANSFORMED"'))))
    result = evaluate_baseline(decisions, items, lambda: read_labels_jsonl(path),
                               verify_posted_baseline_hash=posted(decisions, items))
    assert (result["auroc"], result["n_scored"], result["n_unclassified_or_null"]) == (0.75, 4, 1)
    # The commitment holds -dE per item (null when undetermined).
    scores = {"a": 0.3, "b": 0.1, "c": -0.05, "d": None, "e": 0.2, "f": -0.2}
    assert result["scores_sha256"] == hashlib.sha256(evaluate_module._baseline_canonical("B0", scores)).hexdigest()
