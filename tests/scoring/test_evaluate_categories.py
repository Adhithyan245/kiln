"""OPEN-11 (stored category strings) and OPEN-12 (no outcome to score), protocol §3.1 and §7.

Synthetic labels only: every category string here is made up for the test or is
one of the dataset README's documented display names written in the protocol.
"""
import json

import pytest

from kiln.schemas import Category, ComputeRequest, Item, Label, Prediction, ReviewFlag, ReviewReason
from kiln.scoring.evaluate import (
    CATEGORY_NAMES,
    UnscoredLabel,
    evaluate,
    hard_subset_definition_sha256,
    normalize_category,
    read_labels_jsonl,
)

SECRET = "SYNTHETIC-SECRET-CATEGORY"  # stands in for a stored value that must never be printed


def fixture(tmp_path):
    predictions = [
        Prediction(run_id="synthetic", condition="C1", seed=1, item_id="a", p_react=0.8, category=Category.completely_reacted, cause="", fix="", evidence=[], cost={}, needs_review=True, review_flags=[ReviewFlag(reason=ReviewReason.conflict, detail="synthetic")]),
        Prediction(run_id="synthetic", condition="C1", seed=1, item_id="b", p_react=0.4, category=Category.unreacted, cause="", fix="", evidence=[], cost={}),
        Prediction(run_id="synthetic", condition="C1", seed=1, item_id="c", p_react=0.4, category=Category.transformed, cause="", fix="", evidence=[], cost={}),
        Prediction(run_id="synthetic", condition="C1", seed=1, item_id="d", p_react=0.1, category=Category.unreacted, cause="", fix="", evidence=[], cost={}),
    ]
    items = [Item(item_id=p.item_id, source="alab_demo", precursor_a=f"X{i}", precursor_b=f"Y{i}", temperature_c=500, split="dev") for i, p in enumerate(predictions)]
    path = tmp_path / "predictions.jsonl"
    path.write_text("\n".join(p.model_dump_json() for p in predictions) + "\n")
    return path, items


def write_labels(tmp_path, records):
    path = tmp_path / "synthetic_labels.jsonl"
    path.write_text("".join((record if isinstance(record, str) else json.dumps(record)) + "\n" for record in records))
    return path


def no_labels():
    pytest.fail("labels loaded")


# ---------- normalize_category ----------

@pytest.mark.parametrize("stored, expected", [
    ("unreacted", Category.unreacted),
    ("Unreacted", Category.unreacted),
    ("  UNREACTED\t", Category.unreacted),
    ("transformed", Category.transformed),
    ("Transformed", Category.transformed),
    ("partially reacted", Category.partially_reacted),
    ("Partially Reacted", Category.partially_reacted),
    ("partially-reacted", Category.partially_reacted),
    ("partially_reacted", Category.partially_reacted),
    ("completely reacted", Category.completely_reacted),
    ("Completely-Reacted", Category.completely_reacted),
    (" completely_reacted ", Category.completely_reacted),
    ("unclassified", None),
    ("Unclassified", None),
    (" UNCLASSIFIED ", None),
    (None, None),
])
def test_documented_names_map_after_normalization(stored, expected):
    assert normalize_category(stored) is expected


@pytest.mark.parametrize("stored", [
    "",
    "   ",
    "reacted",
    "partial",
    "complete",
    "unknown",
    "completely  reacted",      # two spaces: normalization does not collapse runs
    "completely_reacted_",
    "partially.reacted",
    "not reacted",
    "n/a",
    "null",
    SECRET,
    0,
    1.0,
    True,
    ["unreacted"],
    {"name": "unreacted"},
])
def test_any_other_value_fails_closed_without_echoing_it(stored):
    with pytest.raises(ValueError) as caught:
        normalize_category(stored)
    # The message is the same whatever the value, so it cannot carry the value.
    with pytest.raises(ValueError) as reference:
        normalize_category("zz-probe" if isinstance(stored, str) else 0)
    assert str(caught.value) == str(reference.value)
    assert caught.value.__cause__ is None


def test_category_names_are_exactly_the_four_documented_classes():
    assert dict(CATEGORY_NAMES) == {category.value: category for category in Category}
    with pytest.raises(TypeError):
        CATEGORY_NAMES["reacted"] = Category.completely_reacted


# ---------- read_labels_jsonl ----------

def test_label_file_display_names_become_categories_and_reacted_is_derived(tmp_path):
    path = write_labels(tmp_path, [
        {"item_id": "a", "category": "Partially Reacted"},
        {"item_id": "b", "category": "UNREACTED", "reacted": None},
        {"item_id": "c", "category": "completely-reacted", "reacted": True},
        {"item_id": "d", "category": "Transformed", "reacted": False, "note": "extra fields are ignored"},
        {"item_id": "e", "category": "Unclassified"},
        {"item_id": "f", "category": None},
        "",
    ])
    assert read_labels_jsonl(path) == [
        Label(item_id="a", category=Category.partially_reacted, reacted=True),
        Label(item_id="b", category=Category.unreacted, reacted=False),
        Label(item_id="c", category=Category.completely_reacted, reacted=True),
        Label(item_id="d", category=Category.transformed, reacted=False),
        UnscoredLabel(item_id="e"),
        UnscoredLabel(item_id="f"),
    ]


@pytest.mark.parametrize("line, match", [
    ({"item_id": "a", "category": SECRET}, "not one of the documented names"),
    ({"item_id": "a", "category": 7}, "neither a string nor null"),
    ({"item_id": "a"}, "has no category field"),
    ({"item_id": "a", "category": "completely reacted", "reacted": False}, "reacted must agree with category"),
    ({"item_id": "a", "category": "unreacted", "reacted": "true"}, "reacted must be true, false or null"),
    ({"item_id": "a", "category": "unclassified", "reacted": False}, "has no outcome"),
    ({"item_id": "a", "category": None, "reacted": True}, "has no outcome"),
    ({"category": "unreacted"}, "failed Label validation for item_id"),
    ({"item_id": None, "category": "unclassified"}, "failed UnscoredLabel validation for item_id"),
    ([SECRET], "not a JSON object"),
    (f'{{"item_id": "a", "category": "{SECRET}"', "not valid JSON"),
])
def test_bad_label_lines_fail_closed_naming_the_line_only(tmp_path, line, match):
    path = write_labels(tmp_path, [{"item_id": "ok", "category": "unreacted"}, line])
    with pytest.raises(ValueError, match=f"labels line 2.*{match}") as caught:
        read_labels_jsonl(path)
    assert SECRET not in str(caught.value)
    error = caught.value
    assert error.__cause__ is None and (error.__context__ is None or error.__suppress_context__)


# ---------- evaluate with display names and items with no outcome ----------

def test_display_name_label_file_scores_like_canonical_labels(tmp_path):
    path, items = fixture(tmp_path)
    canonical = [Label(item_id="a", category="partially_reacted", reacted=True), Label(item_id="b", category="unreacted", reacted=False),
                 Label(item_id="c", category="completely_reacted", reacted=True), Label(item_id="d", category="unreacted", reacted=False)]
    stored = write_labels(tmp_path, [
        {"item_id": "a", "category": "Partially Reacted"}, {"item_id": "b", "category": "unreacted"},
        {"item_id": "c", "category": "Completely-Reacted"}, {"item_id": "d", "category": " UNREACTED "},
    ])
    expected = evaluate(path, items, lambda: canonical, verify_posted_hash=lambda _: True)
    assert evaluate(path, items, lambda: read_labels_jsonl(stored), verify_posted_hash=lambda _: True) == expected
    assert expected["metrics"]["auroc"] == 0.875


def test_unmapped_stored_category_stops_evaluation_before_any_metric(tmp_path):
    path, items = fixture(tmp_path)
    stored = write_labels(tmp_path, [
        {"item_id": "a", "category": "partially reacted"}, {"item_id": "b", "category": SECRET},
        {"item_id": "c", "category": "completely reacted"}, {"item_id": "d", "category": "unreacted"},
    ])
    with pytest.raises(ValueError, match="labels line 2: the stored category is not one of the documented names") as caught:
        evaluate(path, items, lambda: read_labels_jsonl(stored), verify_posted_hash=lambda _: True)
    assert SECRET not in str(caught.value)


def unscored_b_labels():
    return [Label(item_id="a", category="partially_reacted", reacted=True), UnscoredLabel(item_id="b"),
            Label(item_id="c", category="completely_reacted", reacted=True), Label(item_id="d", category="unreacted", reacted=False)]


def test_item_with_no_outcome_stays_in_coverage_and_leaves_every_label_metric(tmp_path):
    path, items = fixture(tmp_path)
    result = evaluate(path, items, unscored_b_labels, verify_posted_hash=lambda _: True)
    metrics = dict(result["metrics"])
    per_class = metrics.pop("four_class_f1")
    # Scored items: a (0.8, partially), c (0.4, completely), d (0.1, unreacted). b is flag-free and counts in coverage only.
    assert metrics == {"n": 4, "n_scored": 3, "n_unclassified_or_null": 1, "auroc": 1.0, "four_class_accuracy": pytest.approx(1 / 3),
                       "four_class_macro_f1": 0.25, "brier": pytest.approx(0.41 / 3), "coverage": 0.75,
                       "flagged_accuracy": 0.0, "unflagged_accuracy": 0.5, "flagged_n": 1, "unflagged_n": 2}
    assert per_class == [
        {"category": "unreacted", "support": 1, "predicted": 1, "f1": 1.0},
        {"category": "transformed", "support": 0, "predicted": 1, "f1": 0.0},
        {"category": "partially_reacted", "support": 1, "predicted": 0, "f1": 0.0},
        {"category": "completely_reacted", "support": 1, "predicted": 1, "f1": 0.0},
    ]
    assert result["secondary_binary_split"] == {"reacted_means": "completely_reacted only", "n": 4, "n_scored": 3,
                                                "n_reacted": 1, "auroc": 0.5, "brier": pytest.approx(1.01 / 3)}


def test_item_with_no_outcome_has_unknown_compute_movement(tmp_path):
    path, items = fixture(tmp_path)
    requests = [
        ComputeRequest(request_id="r1", run_id="synthetic", item_id="b", agent="thermo", tier="single_point", reason="test",
                       inputs={}, settings={}, cache_key="r1", compute_units=2, p_react_before=0.5, p_react_after=0.4),
        ComputeRequest(request_id="r2", run_id="synthetic", item_id="d", agent="thermo", tier="single_point", reason="test",
                       inputs={}, settings={}, cache_key="r2", compute_units=2, p_react_before=0.5, p_react_after=0.4),
    ]
    result = evaluate(path, items, unscored_b_labels, verify_posted_hash=lambda _: True, compute_requests=requests)
    assert [r.moved_toward_label for r in result["compute_requests"]] == [None, True]
    assert result["compute_total"]["movement_known"] == 1
    assert result["compute_total"]["compute_units"] == 4  # still charged and counted


def test_item_with_no_outcome_keeps_its_hard_subset_bucket(tmp_path):
    path, items = fixture(tmp_path)
    margins = {"a": 0.5, "b": 0.0625, "c": 0.25, "d": None}
    posted = hard_subset_definition_sha256(items, margins, 0.125)
    hard_subset = evaluate(path, items, unscored_b_labels, verify_posted_hash=lambda _: True,
                           hard_subset_margins=margins, hard_subset_margin_threshold_ev_per_atom=0.125,
                           verify_posted_hard_subset_hash=lambda digest: digest == posted)["hard_subset"]
    assert {a["item_id"]: a["bucket"] for a in hard_subset["assignments"]} == {"a": "easy", "b": "hard", "c": "easy", "d": "unknown"}
    hard = hard_subset["hard"]
    assert (hard["n"], hard["n_scored"], hard["n_unclassified_or_null"], hard["coverage"]) == (1, 0, 1, 1.0)
    assert all(hard[key] is None for key in ("auroc", "brier", "four_class_accuracy", "four_class_macro_f1",
                                             "flagged_accuracy", "unflagged_accuracy"))


def test_every_item_without_an_outcome_leaves_rates_undefined_not_zero(tmp_path):
    path, items = fixture(tmp_path)
    result = evaluate(path, items, lambda: [UnscoredLabel(item_id=i) for i in "abcd"], verify_posted_hash=lambda _: True)
    metrics = result["metrics"]
    assert (metrics["n"], metrics["n_scored"], metrics["n_unclassified_or_null"], metrics["coverage"]) == (4, 0, 4, 0.75)
    assert all(metrics[key] is None for key in ("auroc", "brier", "four_class_accuracy", "four_class_macro_f1",
                                                "flagged_accuracy", "unflagged_accuracy"))
    assert result["secondary_binary_split"]["brier"] is None


def test_unscored_label_must_still_name_an_evaluated_item(tmp_path):
    path, items = fixture(tmp_path)
    labels = [*unscored_b_labels()[:3], UnscoredLabel(item_id="z")]
    with pytest.raises(ValueError, match="same item IDs"):
        evaluate(path, items, lambda: labels, verify_posted_hash=lambda _: True)
    with pytest.raises(ValueError, match="duplicate label"):
        evaluate(path, items, lambda: [*unscored_b_labels(), UnscoredLabel(item_id="b")], verify_posted_hash=lambda _: True)


def test_load_labels_must_yield_label_objects(tmp_path):
    path, items = fixture(tmp_path)
    raw = [{"item_id": i, "category": "unreacted", "reacted": False} for i in "abcd"]
    with pytest.raises(TypeError, match="Label or UnscoredLabel"):
        evaluate(path, items, lambda: raw, verify_posted_hash=lambda _: True)


def test_unscored_label_carries_no_outcome():
    with pytest.raises(ValueError):
        UnscoredLabel(item_id="a", category="unreacted")
    with pytest.raises(ValueError):
        UnscoredLabel(item_id="a", reacted=False)
