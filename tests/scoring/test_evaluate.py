import hashlib
import json
import math

import pytest

from kiln.schemas import Category, ComputeRequest, Item, Label, Prediction, ReviewFlag, ReviewReason
from kiln.scoring.evaluate import HARD_SUBSET_FORMULA_RULES, EvaluationLockedError, evaluate, formula_triggers


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
    assert metrics == {"n": 4, "auroc": 0.875, "four_class_accuracy": 0.5, "four_class_macro_f1": 0.25, "brier": pytest.approx(0.1425), "coverage": 0.75, "flagged_accuracy": 0.0, "unflagged_accuracy": pytest.approx(2/3), "flagged_n": 1, "unflagged_n": 3}
    assert result["compute_requests"][0].moved_toward_label is True
    assert logged.moved_toward_label is None
    assert result["compute_allocation"][0]["compute_units"] == 2
    assert result["compute_allocation"][0]["status"] == "cached"
    assert result["bootstrap"]["intervals"] == {}


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
    return evaluate(path, items, lambda: labels, verify_posted_hash=lambda _: True,
                    hard_subset_margins=margins, hard_subset_margin_threshold_ev_per_atom=threshold)


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
    assert hard == {"n": 2, "auroc": 1.0, "four_class_accuracy": 0.5, "four_class_macro_f1": None, "brier": pytest.approx(0.1),
                    "coverage": 0.5, "flagged_accuracy": 0.0, "unflagged_accuracy": 1.0, "flagged_n": 1, "unflagged_n": 1}
    easy = dict(hard_subset["easy"])
    easy.pop("four_class_f1")
    assert easy == {"n": 1, "auroc": None, "four_class_accuracy": 0.0, "four_class_macro_f1": None, "brier": pytest.approx(0.36),
                    "coverage": 1.0, "flagged_accuracy": None, "unflagged_accuracy": 0.0, "flagged_n": 0, "unflagged_n": 1}
    unknown = dict(hard_subset["unknown"])
    unknown.pop("four_class_f1")
    assert unknown == {"n": 1, "auroc": None, "four_class_accuracy": 1.0, "four_class_macro_f1": None, "brier": pytest.approx(0.01),
                       "coverage": 1.0, "flagged_accuracy": None, "unflagged_accuracy": 1.0, "flagged_n": 0, "unflagged_n": 1}
    assert set(hard_subset["hard"]) == set(result["metrics"])
    assert hard_subset["trigger_counts"] == {"margin_below_threshold": 1, "carbonate": 1, "hydroxide": 0, "ammonium": 0}
    assert hard_subset["hard_with_unknown_margin"] == 0
    assert hard_subset["formula_triggers"]["Li2CO3"] == ["carbonate"]
    assert set(hard_subset["formula_triggers"]) == {f for item in items for f in (item.precursor_a, item.precursor_b)}
    assert hard_subset["definition"]["margin_threshold_ev_per_atom"] == THRESHOLD
    assert hard_subset["definition"]["formula_rules"] == dict(HARD_SUBSET_FORMULA_RULES)


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


def test_margin_threshold_boundary_is_strict(tmp_path):
    path, items, labels, margins = hard_fixture(tmp_path)
    margins.update(b=THRESHOLD, c=math.nextafter(THRESHOLD, 0.0))
    buckets = {a["item_id"]: a["bucket"] for a in run_hard(path, items, labels, margins)["hard_subset"]["assignments"]}
    assert buckets == {"a": "hard", "b": "easy", "c": "hard", "d": "unknown"}


def test_formula_rule_makes_an_unknown_margin_hard_and_either_precursor_counts(tmp_path):
    formulas = {"a": ("Mg(OH)2", "SynA"), "b": ("SynB", "NH4H2PO4"), "c": ("Cu2(OH)2CO3", "SynC"), "d": ("SynD", "SynE")}
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
    # A mixed-anion item counts once in the bucket and once under each trigger.
    assert hard_subset["trigger_counts"] == {"margin_below_threshold": 0, "carbonate": 1, "hydroxide": 2, "ammonium": 1}


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


@pytest.mark.parametrize("formula, expected", [
    # carbonate
    ("Li2CO3", ("carbonate",)),
    ("La2(CO3)3", ("carbonate",)),
    ("Bi2O2CO3", ("carbonate",)),
    ("NaHCO3", ("carbonate",)),              # bicarbonate counts as carbonate, not hydroxide
    ("KHCO3", ("carbonate",)),
    ("Co3O4", ()),                          # cobalt: case-sensitive, Co is not C + O
    ("CaC2O4", ()),                         # oxalate is not carbonate
    ("Mn(CH3COO)2", ()),                    # acetate is not carbonate or hydroxide
    ("CaC2", ()),
    # hydroxide
    ("LiOH", ("hydroxide",)),
    ("Mg(OH)2", ("hydroxide",)),
    ("Mg[OH]2", ("hydroxide",)),
    ("FeOOH", ("hydroxide",)),              # oxyhydroxide counts
    ("FeO(OH)", ("hydroxide",)),
    ("HfO2", ()),
    ("Ho2O3", ()),
    ("SrOHfO2", ()),                        # O then Hf (hafnium) is not hydroxide
    ("OsO4", ()),
    # hydrates: water of crystallization never triggers a rule
    ("LiOH·H2O", ("hydroxide",)),
    ("Mg(NO3)2·6H2O", ()),
    ("Ni(NO3)2.6H2O", ()),
    ("CuSO4*5H2O", ()),
    ("Na2CO3·10H2O", ("carbonate",)),
    ("(NH4)6Mo7O24·4H2O", ("ammonium",)),
    ("H2O", ()),
    # ammonium
    ("NH4Cl", ("ammonium",)),
    ("[NH4]Cl", ("ammonium",)),
    ("NH4H2PO4", ("ammonium",)),
    ("(NH4)2HPO4", ("ammonium",)),
    ("NH4VO3", ("ammonium",)),
    ("NH3", ()),
    ("N2H4", ()),                           # hydrazine
    ("N(CH3)4Cl", ()),                      # substituted ammonium is not matched
    ("NiO", ()),
    ("Nb2O5", ()),
    ("NaH2PO4", ()),                        # acid salt hydrogen is not hydroxide
    # mixed anions: every matching rule is reported
    ("Cu2(OH)2CO3", ("carbonate", "hydroxide")),
    ("Ca10(PO4)6(OH)2", ("hydroxide",)),
    ("NH4HCO3", ("carbonate", "ammonium")),
    ("(NH4)2CO3", ("carbonate", "ammonium")),
    # Unicode subscripts are read as digits; matching is case-sensitive
    ("Li₂CO₃", ("carbonate",)),
    ("Mg(OH)₂", ("hydroxide",)),
    ("NH₄Cl", ("ammonium",)),
    ("li2co3", ()),
    # Known limits, pinned so any change is deliberate (see PR decisions):
    ("VOHPO4", ("hydroxide",)),             # false positive: O directly before an acid-salt H
    ("B(OH)3", ("hydroxide",)),             # same compound as H3BO3, which matches nothing
    ("H3BO3", ()),
    ("LiHO", ()),                           # pymatgen reduced_formula notation is not recognised
    ("Mg(HO)2", ()),
    ("H4NCl", ()),
    ("Cu2H2CO5", ()),
])
def test_formula_rule_edge_cases(formula, expected):
    assert formula_triggers(formula) == expected


def test_formula_rules_read_text_only():
    with pytest.raises(TypeError):
        formula_triggers(None)
    with pytest.raises(TypeError):
        HARD_SUBSET_FORMULA_RULES["carbonate"] = "C"
