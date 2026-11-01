import csv
import hashlib
import json
import math
from pathlib import Path

import pytest

from kiln.schemas import Category, ComputeRequest, Item, Label, Prediction, ReviewFlag, ReviewReason
from kiln.scoring.evaluate import (
    HARD_SUBSET_FORMULA_LIST,
    EvaluationLockedError,
    evaluate,
    formula_triggers,
    hard_subset_definition_sha256,
)


def fixture(tmp_path):
    predictions = [
        Prediction(run_id="synthetic", condition="B0", seed=1, item_id="a", p_react=0.8, category=Category.completely_reacted, cause="", fix="", evidence=[], cost={}, needs_review=True, review_flags=[ReviewFlag(reason=ReviewReason.conflict, detail="synthetic")]),
        Prediction(run_id="synthetic", condition="B0", seed=1, item_id="b", p_react=0.4, category=Category.unreacted, cause="", fix="", evidence=[], cost={}),
        Prediction(run_id="synthetic", condition="B0", seed=1, item_id="c", p_react=0.4, category=Category.transformed, cause="", fix="", evidence=[], cost={}),
        Prediction(run_id="synthetic", condition="B0", seed=1, item_id="d", p_react=0.1, category=Category.unreacted, cause="", fix="", evidence=[], cost={}),
    ]
    items = [Item(item_id=p.item_id, source="alab_demo", precursor_a=f"X{i}", precursor_b=f"Y{i}", temperature_c=500, split="dev") for i, p in enumerate(predictions)]
    labels = [Label(item_id="a", category="partially_reacted", reacted=True), Label(item_id="b", category="unreacted", reacted=False), Label(item_id="c", category="completely_reacted", reacted=True), Label(item_id="d", category="unreacted", reacted=False)]
    path = tmp_path / "predictions.jsonl"
    path.write_text("\n".join(p.model_dump_json() for p in predictions) + "\n")
    return path, items, labels


def request(request_id, item_id, tier="single_point", status="ok", **fields):
    return ComputeRequest(request_id=request_id, run_id="synthetic", item_id=item_id, agent="thermo", tier=tier, reason="test", inputs={}, settings={}, cache_key=request_id, status=status, **fields)


def no_labels():
    pytest.fail("labels loaded")


def test_hash_gate_is_fail_closed(tmp_path):
    path, items, labels = fixture(tmp_path)
    calls = []
    def load():
        calls.append(True)
        return labels
    for verify in (None, lambda digest: False, lambda digest: "yes"):
        with pytest.raises(EvaluationLockedError):
            evaluate(path, items, load, verify_posted_hash=verify)
    def broken(digest):
        raise RuntimeError("unavailable")
    with pytest.raises(EvaluationLockedError):
        evaluate(path, items, load, verify_posted_hash=broken)
    (tmp_path / "prediction.sha256").write_text(hashlib.sha256(path.read_bytes()).hexdigest())
    with pytest.raises(EvaluationLockedError):
        evaluate(path, items, load)
    assert calls == []


def test_snapshot_metrics_and_compute_allocation(tmp_path):
    path, items, labels = fixture(tmp_path)
    expected_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    def verify(digest):
        assert digest == expected_hash
        path.write_text("changed after hashing")
        return True
    logged = request("r", "a", status="cached", compute_units=2, gpu_seconds=3, p_react_before=0.2, p_react_after=0.8)
    result = evaluate(path, items, lambda: labels, verify_posted_hash=verify, compute_requests=[logged], bootstrap_samples=200, bootstrap_seed=12)
    assert result["prediction_sha256"] == expected_hash
    assert (result["split"], result["source"]) == ("dev", "alab_demo")
    metrics = dict(result["metrics"])
    assert metrics.pop("four_class_f1") == [
        {"category": "unreacted", "support": 2, "predicted": 2, "f1": 1.0},
        {"category": "transformed", "support": 0, "predicted": 1, "f1": 0.0},
        {"category": "partially_reacted", "support": 1, "predicted": 0, "f1": 0.0},
        {"category": "completely_reacted", "support": 1, "predicted": 1, "f1": 0.0},
    ]
    assert metrics == {"n": 4, "n_scored": 4, "n_unclassified_or_null": 0, "auroc": 0.875, "four_class_accuracy": 0.5, "four_class_macro_f1": 0.25, "brier": pytest.approx(0.1425), "coverage": 0.75, "flagged_accuracy": 0.0, "unflagged_accuracy": pytest.approx(2/3), "flagged_n": 1, "unflagged_n": 3}
    assert result["compute_requests"][0].moved_toward_label is True
    assert logged.moved_toward_label is None
    assert result["compute_allocation"][0]["compute_units"] == 2
    assert result["compute_allocation"][0]["status"] == "cached"
    assert result["bootstrap"]["intervals"] == {}


def test_secondary_split_counts_only_completely_reacted_and_leaves_primary_unchanged(tmp_path):
    path, items, labels = fixture(tmp_path)
    result = evaluate(path, items, lambda: labels, verify_posted_hash=lambda digest: True)
    # Only c is completely reacted (score 0.4); a (0.8, partially reacted) now counts as not reacted.
    assert result["secondary_binary_split"] == {"reacted_means": "completely_reacted only", "n": 4, "n_scored": 4, "n_reacted": 1,
                                                "auroc": 0.5, "brier": pytest.approx(1.17 / 4)}
    assert result["metrics"]["auroc"] == 0.875 and result["metrics"]["brier"] == pytest.approx(0.1425)


def test_compute_totals_by_tier_and_logged_changes(tmp_path):
    path, items, labels = fixture(tmp_path)
    requests = [
        request("r1", "a", status="cached", compute_units=2, gpu_seconds=3, p_react_before=0.2, p_react_after=0.8, changed_prediction=True),
        request("r2", "b", compute_units=2, gpu_seconds=5, p_react_before=0.5, p_react_after=0.4, changed_prediction=False),
        request("r3", "c", tier="bounded_relaxation", status="not_converged", compute_units=5, gpu_seconds=7, p_react_before=0.4),
        request("r4", "d", tier="decomposition_reeval", status="failed", compute_units=1, p_react_before=0.1, p_react_after=0.3, changed_prediction=True),
        request("r5", "d", tier="cached_lookup", compute_units=1, p_react_before=0.3, p_react_after=0.3, changed_prediction=False),
    ]
    result = evaluate(path, items, lambda: labels, verify_posted_hash=lambda _: True, compute_requests=requests)
    assert [r.moved_toward_label for r in result["compute_requests"]] == [True, True, None, False, False]
    assert all(r.moved_toward_label is None for r in requests)
    assert result["compute_total"] == {"requests": 5, "compute_units": 11, "gpu_seconds": 15, "changed_prediction_known": 4, "changed_prediction": 2, "movement_known": 4, "moved_toward_label": 2}
    by_tier = {row.pop("tier"): row for row in result["compute_by_tier"]}
    assert list(by_tier) == ["cached_lookup", "single_point", "bounded_relaxation", "decomposition_reeval"]
    assert by_tier["cached_lookup"] == {"requests": 1, "compute_units": 1, "gpu_seconds": 0, "changed_prediction_known": 1, "changed_prediction": 0, "movement_known": 1, "moved_toward_label": 0}
    assert by_tier["single_point"] == {"requests": 2, "compute_units": 4, "gpu_seconds": 8, "changed_prediction_known": 2, "changed_prediction": 1, "movement_known": 2, "moved_toward_label": 2}
    assert by_tier["bounded_relaxation"] == {"requests": 1, "compute_units": 5, "gpu_seconds": 7, "changed_prediction_known": 0, "changed_prediction": 0, "movement_known": 0, "moved_toward_label": 0}
    assert by_tier["decomposition_reeval"] == {"requests": 1, "compute_units": 1, "gpu_seconds": 0, "changed_prediction_known": 1, "changed_prediction": 1, "movement_known": 1, "moved_toward_label": 0}
    assert [(row["tier"], row["status"], row["requests"]) for row in result["compute_allocation"]] == [
        ("bounded_relaxation", "not_converged", 1), ("cached_lookup", "ok", 1), ("decomposition_reeval", "failed", 1), ("single_point", "cached", 1), ("single_point", "ok", 1),
    ]
    assert result["correct_changes"]["count"] is None
    assert "OPEN-17" in result["correct_changes"]["reason"]


def test_empty_compute_log_reports_zero_rows_for_every_tier(tmp_path):
    path, items, labels = fixture(tmp_path)
    result = evaluate(path, items, lambda: labels, verify_posted_hash=lambda _: True)
    assert result["compute_total"]["requests"] == 0
    assert [row["requests"] for row in result["compute_by_tier"]] == [0, 0, 0, 0]
    assert result["compute_allocation"] == []


def test_auroc_and_macro_f1_undefined_when_classes_absent(tmp_path):
    path, items, labels = fixture(tmp_path)
    for label in labels:
        label.category, label.reacted = Category.unreacted, False
    metrics = evaluate(path, items, lambda: labels, verify_posted_hash=lambda _: True)["metrics"]
    assert metrics["auroc"] is None
    assert metrics["four_class_macro_f1"] is None
    assert [entry["f1"] for entry in metrics["four_class_f1"]] == [pytest.approx(2/3), 0.0, None, 0.0]


def test_invalid_inputs_and_label_consistency(tmp_path):
    path, items, labels = fixture(tmp_path)
    with pytest.raises(ValueError, match="same nonempty"):
        evaluate(path, items[:-1], no_labels, verify_posted_hash=lambda _: True)
    with pytest.raises(ValueError, match="same item IDs"):
        evaluate(path, items, lambda: labels[:-1], verify_posted_hash=lambda _: True)
    labels[0].reacted = False
    with pytest.raises(ValueError, match="agree with category"):
        evaluate(path, items, lambda: labels, verify_posted_hash=lambda _: True)


@pytest.mark.parametrize("field, value", [("split", "heldout"), ("source", "precursor_genome")])
def test_mixed_split_or_source_blocks_label_loading(tmp_path, field, value):
    path, items, _ = fixture(tmp_path)
    items[0] = items[0].model_copy(update={field: value})
    with pytest.raises(ValueError, match="one split and one source"):
        evaluate(path, items, no_labels, verify_posted_hash=lambda _: True)


def test_bootstrap_is_unavailable_without_an_agreed_method(tmp_path):
    path, items, labels = fixture(tmp_path)
    bootstrap = evaluate(path, items, lambda: labels, verify_posted_hash=lambda _: True, bootstrap_samples=200, bootstrap_seed=7)["bootstrap"]
    assert bootstrap["method"] is None
    assert bootstrap["intervals"] == {}
    assert "overlapping precursor clusters" in bootstrap["reason"]


def test_missing_referenced_compute_request_blocks_label_loading(tmp_path):
    path, items, labels = fixture(tmp_path)
    predictions = [json.loads(line) for line in path.read_text().splitlines()]
    predictions[0]["compute_requests"] = ["missing-request"]
    path.write_text("\n".join(json.dumps(prediction) for prediction in predictions))
    with pytest.raises(ValueError, match="missing referenced compute requests.*missing-request"):
        evaluate(path, items, no_labels, verify_posted_hash=lambda _: True)


def test_request_referenced_by_another_item_blocks_label_loading(tmp_path):
    path, items, labels = fixture(tmp_path)
    predictions = [json.loads(line) for line in path.read_text().splitlines()]
    predictions[0]["compute_requests"] = ["r"]
    path.write_text("\n".join(json.dumps(prediction) for prediction in predictions))
    with pytest.raises(ValueError, match="referenced by a different item"):
        evaluate(path, items, no_labels, verify_posted_hash=lambda _: True, compute_requests=[request("r", "b")])


def test_prefilled_moved_toward_label_blocks_label_loading(tmp_path):
    path, items, _ = fixture(tmp_path)
    with pytest.raises(ValueError, match="moved_toward_label must be unset"):
        evaluate(path, items, no_labels, verify_posted_hash=lambda _: True, compute_requests=[request("r", "a", moved_toward_label=False)])


# ---------- hard_subset slice (synthetic formulas, margins and labels only) ----------

THRESHOLD = 0.125  # made up; not a proposed protocol value


def hard_fixture(tmp_path, formulas=None):
    """The shared fixture with chosen precursor formulas. Default buckets:
    a: carbonate precursor, margin above threshold -> hard (formula only)
    b: no formula rule, margin below threshold    -> hard (margin)
    c: no formula rule, margin above threshold    -> easy
    d: no formula rule, margin unknown            -> unknown
    """
    path, items, labels = fixture(tmp_path)
    formulas = formulas or {"a": ("SynA", "Li2CO3"), "b": ("SynB", "SynC"), "c": ("SynD", "SynE"), "d": ("SynF", "SynG")}
    items = [item.model_copy(update=dict(zip(("precursor_a", "precursor_b"), formulas[item.item_id]))) for item in items]
    margins = {"a": 0.5, "b": 0.0625, "c": 0.25, "d": None}
    return path, items, labels, margins


def run_hard(path, items, labels, margins, threshold=THRESHOLD):
    """Evaluate with the hard-subset definition posted first, as a real caller must."""
    posted = hard_subset_definition_sha256(items, margins, threshold)
    return evaluate(path, items, lambda: labels, verify_posted_hash=lambda _: True,
                    hard_subset_margins=margins, hard_subset_margin_threshold_ev_per_atom=threshold,
                    verify_posted_hard_subset_hash=lambda digest: digest == posted)


def test_hard_subset_buckets_every_item_and_reports_the_same_metrics(tmp_path):
    path, items, labels, margins = hard_fixture(tmp_path)
    result = run_hard(path, items, labels, margins)
    hard_subset = result["hard_subset"]
    assert hard_subset["available"] is True
    assert hard_subset["n"] == 4
    assert [(a["item_id"], a["bucket"], a["triggers"]) for a in hard_subset["assignments"]] == [
        ("a", "hard", ["carbonate"]),
        ("b", "hard", ["margin_below_threshold"]),
        ("c", "easy", []),
        ("d", "unknown", []),
    ]
    assert [a["margin_ev_per_atom"] for a in hard_subset["assignments"]] == [0.5, 0.0625, 0.25, None]
    assert sum(hard_subset[bucket]["n"] for bucket in ("hard", "easy", "unknown")) == 4
    hard = dict(hard_subset["hard"])
    hard.pop("four_class_f1")
    assert hard == {"n": 2, "n_scored": 2, "n_unclassified_or_null": 0, "auroc": 1.0, "four_class_accuracy": 0.5, "four_class_macro_f1": None, "brier": pytest.approx(0.1),
                    "coverage": 0.5, "flagged_accuracy": 0.0, "unflagged_accuracy": 1.0, "flagged_n": 1, "unflagged_n": 1}
    easy = dict(hard_subset["easy"])
    easy.pop("four_class_f1")
    assert easy == {"n": 1, "n_scored": 1, "n_unclassified_or_null": 0, "auroc": None, "four_class_accuracy": 0.0, "four_class_macro_f1": None, "brier": pytest.approx(0.36),
                    "coverage": 1.0, "flagged_accuracy": None, "unflagged_accuracy": 0.0, "flagged_n": 0, "unflagged_n": 1}
    unknown = dict(hard_subset["unknown"])
    unknown.pop("four_class_f1")
    assert unknown == {"n": 1, "n_scored": 1, "n_unclassified_or_null": 0, "auroc": None, "four_class_accuracy": 1.0, "four_class_macro_f1": None, "brier": pytest.approx(0.01),
                       "coverage": 1.0, "flagged_accuracy": None, "unflagged_accuracy": 1.0, "flagged_n": 0, "unflagged_n": 1}
    assert set(hard_subset["hard"]) == set(result["metrics"])
    assert hard_subset["trigger_counts"] == {"margin_below_threshold": 1, "carbonate": 1, "hydroxide": 0, "ammonium": 0}
    assert hard_subset["hard_with_unknown_margin"] == 0
    assert hard_subset["formula_triggers"]["Li2CO3"] == ["carbonate"]
    assert set(hard_subset["formula_triggers"]) == {f for item in items for f in (item.precursor_a, item.precursor_b)}
    assert hard_subset["definition"]["margin_threshold_ev_per_atom"] == THRESHOLD
    assert hard_subset["definition"]["formula_list"] == dict(HARD_SUBSET_FORMULA_LIST)
    assert hard_subset["definition_sha256"] == hard_subset_definition_sha256(items, margins, THRESHOLD)
    assert "verified as posted" in hard_subset["definition"]["commitment"]
    assert hard_subset["definition"]["version"] == "kiln.hard_subset.v2"


def test_hard_subset_leaves_all_pairs_results_unchanged(tmp_path):
    path, items, labels, margins = hard_fixture(tmp_path)
    plain = evaluate(path, items, lambda: labels, verify_posted_hash=lambda _: True)
    sliced = run_hard(path, items, labels, margins)
    assert plain["hard_subset"] == {"available": False, "reason": "Unavailable: no per-item margins and margin threshold were supplied."}
    for key in plain:
        if key != "hard_subset":
            assert sliced[key] == plain[key], key


def test_hard_subset_still_needs_the_posted_hash(tmp_path):
    path, items, labels, margins = hard_fixture(tmp_path)
    with pytest.raises(EvaluationLockedError):
        evaluate(path, items, no_labels, hard_subset_margins=margins, hard_subset_margin_threshold_ev_per_atom=THRESHOLD)


def test_unposted_hard_subset_definition_blocks_label_loading(tmp_path):
    path, items, _, margins = hard_fixture(tmp_path)
    def broken(digest):
        raise RuntimeError("unavailable")
    for verify in (None, lambda digest: False, lambda digest: "yes", broken):
        with pytest.raises(EvaluationLockedError, match="[Hh]ard-subset definition"):
            evaluate(path, items, no_labels, verify_posted_hash=lambda _: True,
                     hard_subset_margins=margins, hard_subset_margin_threshold_ev_per_atom=THRESHOLD,
                     verify_posted_hard_subset_hash=verify)


def test_re_chosen_threshold_margins_or_formulas_do_not_match_the_posted_definition(tmp_path):
    # Threshold shopping: post one definition, then try to evaluate with another.
    path, items, labels, margins = hard_fixture(tmp_path)
    posted = {hard_subset_definition_sha256(items, margins, THRESHOLD)}
    def verify(digest):
        return digest in posted
    result = evaluate(path, items, lambda: labels, verify_posted_hash=lambda _: True,
                      hard_subset_margins=margins, hard_subset_margin_threshold_ev_per_atom=THRESHOLD,
                      verify_posted_hard_subset_hash=verify)
    assert result["hard_subset"]["definition_sha256"] in posted
    renamed = [items[0].model_copy(update={"precursor_b": "SynZ"}), *items[1:]]
    for changed_items, changed_margins, threshold in (
        (items, margins, THRESHOLD * 2),
        (items, {**margins, "c": 0.0625}, THRESHOLD),
        (items, {**margins, "d": 0.5}, THRESHOLD),
        (renamed, margins, THRESHOLD),
    ):
        with pytest.raises(EvaluationLockedError):
            evaluate(path, changed_items, no_labels, verify_posted_hash=lambda _: True,
                     hard_subset_margins=changed_margins, hard_subset_margin_threshold_ev_per_atom=threshold,
                     verify_posted_hard_subset_hash=verify)


def test_definition_digest_is_canonical_and_validated(tmp_path):
    _, items, _, margins = hard_fixture(tmp_path)
    digest = hard_subset_definition_sha256(items, margins, THRESHOLD)
    assert len(digest) == 64 and int(digest, 16) >= 0
    assert hard_subset_definition_sha256(list(reversed(items)), dict(reversed(list(margins.items()))), THRESHOLD) == digest
    assert hard_subset_definition_sha256(items, {**margins, "a": 1}, THRESHOLD) == hard_subset_definition_sha256(items, {**margins, "a": 1.0}, THRESHOLD)
    with pytest.raises(ValueError, match="finite number or None"):
        hard_subset_definition_sha256(items, {**margins, "a": float("nan")}, THRESHOLD)
    with pytest.raises(ValueError, match="supplied together"):
        hard_subset_definition_sha256(items, margins, None)
    with pytest.raises(ValueError, match="at least one item"):
        hard_subset_definition_sha256([], {}, THRESHOLD)


def test_hard_subset_verifier_without_a_definition_is_a_wiring_error(tmp_path):
    path, items, _, _ = hard_fixture(tmp_path)
    with pytest.raises(ValueError, match="without a hard-subset definition"):
        evaluate(path, items, no_labels, verify_posted_hash=lambda _: True, verify_posted_hard_subset_hash=lambda _: True)


def test_each_verifier_sees_its_own_digest(tmp_path):
    path, items, labels, margins = hard_fixture(tmp_path)
    seen = {}
    evaluate(path, items, lambda: labels,
             verify_posted_hash=lambda digest: seen.setdefault("predictions", digest) is not None,
             hard_subset_margins=margins, hard_subset_margin_threshold_ev_per_atom=THRESHOLD,
             verify_posted_hard_subset_hash=lambda digest: seen.setdefault("hard_subset", digest) is not None)
    assert seen == {"predictions": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "hard_subset": hard_subset_definition_sha256(items, margins, THRESHOLD)}


def test_margin_threshold_boundary_is_strict(tmp_path):
    path, items, labels, margins = hard_fixture(tmp_path)
    margins.update(b=THRESHOLD, c=math.nextafter(THRESHOLD, 0.0))
    buckets = {a["item_id"]: a["bucket"] for a in run_hard(path, items, labels, margins)["hard_subset"]["assignments"]}
    assert buckets == {"a": "hard", "b": "easy", "c": "hard", "d": "unknown"}


def test_listed_formula_makes_an_unknown_margin_hard_and_either_precursor_counts(tmp_path):
    formulas = {"a": ("La(HO)3", "SynA"), "b": ("SynB", "PH6NO4"), "c": ("K4H6C2O9", "LiH3O2"), "d": ("SynD", "SynE")}
    path, items, labels, margins = hard_fixture(tmp_path, formulas)
    margins.update(a=None, b=None, c=None)
    hard_subset = run_hard(path, items, labels, margins)["hard_subset"]
    assert [(a["item_id"], a["bucket"], a["triggers"]) for a in hard_subset["assignments"]] == [
        ("a", "hard", ["hydroxide"]),
        ("b", "hard", ["ammonium"]),
        ("c", "hard", ["carbonate", "hydroxide"]),
        ("d", "unknown", []),
    ]
    assert hard_subset["hard"]["n"] == 3
    assert hard_subset["easy"]["n"] == 0
    assert hard_subset["unknown"]["n"] == 1
    assert hard_subset["hard_with_unknown_margin"] == 3
    # An item with two listed precursors counts once in the bucket and once under each group.
    assert hard_subset["trigger_counts"] == {"margin_below_threshold": 0, "carbonate": 1, "hydroxide": 2, "ammonium": 1}


def test_formulas_the_regexes_misread_are_bucketed_by_the_list(tmp_path):
    # Protocol §4.3 (OPEN-26): the v1 regexes missed pymatgen-style listed
    # formulas and matched iron(II) oxalate (FeH4(CO3)2); the list decides.
    formulas = {"a": ("Al(HO)3", "SynA"), "b": ("SynB", "PH9(NO2)2"), "c": ("FeH4(CO3)2", "SynC"), "d": ("B(HO)3", "KP(HO2)2")}
    path, items, labels, margins = hard_fixture(tmp_path, formulas)
    margins.update(a=0.5, b=0.5, c=0.5, d=0.5)
    assignments = run_hard(path, items, labels, margins)["hard_subset"]["assignments"]
    assert [(a["item_id"], a["bucket"], a["triggers"]) for a in assignments] == [
        ("a", "hard", ["hydroxide"]),
        ("b", "hard", ["ammonium"]),
        ("c", "easy", []),
        ("d", "easy", []),
    ]


def test_changing_the_formula_list_changes_the_definition_digest(tmp_path, monkeypatch):
    from types import MappingProxyType

    import kiln.scoring.evaluate as module

    _, items, _, margins = hard_fixture(tmp_path)
    digest = hard_subset_definition_sha256(items, margins, THRESHOLD)
    monkeypatch.setattr(module, "HARD_SUBSET_FORMULA_LIST",
                        MappingProxyType({**HARD_SUBSET_FORMULA_LIST, "FeH4(CO3)2": "carbonate"}))
    assert hard_subset_definition_sha256(items, margins, THRESHOLD) != digest


def test_margin_and_formula_triggers_are_both_recorded(tmp_path):
    path, items, labels, margins = hard_fixture(tmp_path)
    margins["a"] = 0.0
    (first,) = [a for a in run_hard(path, items, labels, margins)["hard_subset"]["assignments"] if a["item_id"] == "a"]
    assert first["triggers"] == ["margin_below_threshold", "carbonate"]


def test_empty_buckets_report_n_zero_and_undefined_rates(tmp_path):
    path, items, labels, margins = hard_fixture(tmp_path, {i: ("SynA", "SynB") for i in "abcd"})
    hard_subset = run_hard(path, items, labels, {i: None for i in "abcd"})["hard_subset"]
    assert hard_subset["unknown"]["n"] == 4
    for bucket in ("hard", "easy"):
        metrics = hard_subset[bucket]
        assert metrics["n"] == 0
        assert all(metrics[key] is None for key in ("auroc", "four_class_accuracy", "four_class_macro_f1", "brier",
                                                     "coverage", "flagged_accuracy", "unflagged_accuracy"))
        assert [entry["f1"] for entry in metrics["four_class_f1"]] == [None] * 4
        assert set(metrics) == set(hard_subset["unknown"])


def test_bucket_assignment_does_not_depend_on_labels(tmp_path):
    path, items, labels, margins = hard_fixture(tmp_path)
    first = run_hard(path, items, labels, margins)["hard_subset"]["assignments"]
    flipped = [Label(item_id=label.item_id, category=Category.unreacted, reacted=False) for label in labels]
    assert run_hard(path, items, flipped, margins)["hard_subset"]["assignments"] == first


def test_hard_subset_parameters_come_together_and_have_no_default(tmp_path):
    path, items, _, margins = hard_fixture(tmp_path)
    for kwargs in ({"hard_subset_margins": margins}, {"hard_subset_margin_threshold_ev_per_atom": THRESHOLD}):
        with pytest.raises(ValueError, match="supplied together"):
            evaluate(path, items, no_labels, verify_posted_hash=lambda _: True, **kwargs)


@pytest.mark.parametrize("change, error, match", [
    ({"drop": "d"}, ValueError, r"no hard-subset margin entry for items \['d'\]"),
    ({"extra": "z"}, ValueError, "unknown items"),
    ({"a": float("nan")}, ValueError, "finite number or None"),
    ({"a": float("inf")}, ValueError, "finite number or None"),
    ({"a": True}, ValueError, "finite number or None"),
    ({"a": "0.5"}, ValueError, "finite number or None"),
    ({"a": -0.0625}, ValueError, "nonnegative by construction"),
])
def test_bad_margins_block_label_loading(tmp_path, change, error, match):
    path, items, _, margins = hard_fixture(tmp_path)
    if "drop" in change:
        margins.pop(change["drop"])
    elif "extra" in change:
        margins[change["extra"]] = 0.5
    else:
        margins.update(change)
    with pytest.raises(error, match=match):
        evaluate(path, items, no_labels, verify_posted_hash=lambda _: True,
                 hard_subset_margins=margins, hard_subset_margin_threshold_ev_per_atom=THRESHOLD)


@pytest.mark.parametrize("threshold", [0, 0.0, -0.125, float("nan"), float("inf"), True, "0.125"])
def test_bad_threshold_blocks_label_loading(tmp_path, threshold):
    path, items, _, margins = hard_fixture(tmp_path)
    with pytest.raises(ValueError, match="finite number above 0"):
        evaluate(path, items, no_labels, verify_posted_hash=lambda _: True,
                 hard_subset_margins=margins, hard_subset_margin_threshold_ev_per_atom=threshold)


def test_margins_must_be_a_mapping(tmp_path):
    path, items, _, margins = hard_fixture(tmp_path)
    with pytest.raises(TypeError, match="mapping"):
        evaluate(path, items, no_labels, verify_posted_hash=lambda _: True,
                 hard_subset_margins=list(margins.items()), hard_subset_margin_threshold_ev_per_atom=THRESHOLD)


# The list exactly as protocol §4.3 writes it (OPEN-26), in ledger notation.
PROTOCOL_FORMULA_LIST = {
    "BaCO3": "carbonate", "CaCO3": "carbonate", "Li2CO3": "carbonate", "Na2CO3": "carbonate",
    "SrCO3": "carbonate", "K4H6C2O9": "carbonate",
    "Al(HO)3": "hydroxide", "La(HO)3": "hydroxide", "LiH3O2": "hydroxide",
    "PH6NO4": "ammonium", "PH9(NO2)2": "ammonium",
}
NOT_ON_LIST = ("FeH4(CO3)2", "B(HO)3", "KP(HO2)2")  # protocol §4.3, named as deliberately excluded


def test_formula_list_is_the_protocol_list():
    assert dict(HARD_SUBSET_FORMULA_LIST) == PROTOCOL_FORMULA_LIST
    assert len(HARD_SUBSET_FORMULA_LIST) == 11
    assert not set(NOT_ON_LIST) & set(HARD_SUBSET_FORMULA_LIST)


def test_formula_list_uses_the_ledger_notation_of_the_precursor_table():
    # data/precursor_props.csv holds the 46 precursor formulas in the notation
    # kiln.data copies into Item (agent-visible data, no labels). Every listed
    # formula, and every formula the protocol deliberately leaves off, must be
    # spelled exactly as there, or exact matching would silently miss it.
    table = Path(__file__).resolve().parents[2] / "data" / "precursor_props.csv"
    with table.open(newline="", encoding="utf-8") as stream:
        formulas = {row["formula"] for row in csv.DictReader(stream)}
    assert len(formulas) == 46
    assert set(HARD_SUBSET_FORMULA_LIST) <= formulas
    assert set(NOT_ON_LIST) <= formulas


@pytest.mark.parametrize("formula, expected", [
    *[(formula, (group,)) for formula, group in PROTOCOL_FORMULA_LIST.items()],
    # deliberately off the list (protocol §4.3)
    ("FeH4(CO3)2", ()),                     # iron(II) oxalate dihydrate: the v1 CO3 regex matched it
    ("B(HO)3", ()),                         # boric acid
    ("KP(HO2)2", ()),                       # KH2PO4
    # other ledger formulas
    ("Co3O4", ()),
    ("HfO2", ()),
    ("MnO2", ()),
    # exact string match: conventional notation, case, whitespace and subscripts are not normalized
    ("Al(OH)3", ()),
    ("LiOH·H2O", ()),
    ("NH4H2PO4", ()),
    ("(NH4)2HPO4", ()),
    ("K2CO3", ()),
    ("Mg(OH)2", ()),
    ("li2co3", ()),
    (" Li2CO3", ()),
    ("Li2CO3 ", ()),
    ("Li₂CO₃", ()),
    ("", ()),
])
def test_formula_list_membership(formula, expected):
    assert formula_triggers(formula) == expected


def test_formula_list_reads_text_only_and_is_read_only():
    with pytest.raises(TypeError):
        formula_triggers(None)
    with pytest.raises(TypeError):
        HARD_SUBSET_FORMULA_LIST["MgO"] = "hydroxide"
