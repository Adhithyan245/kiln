import hashlib
import json

import pytest

from kiln.schemas import Category, ComputeRequest, Item, Label, Prediction, ReviewFlag, ReviewReason
from kiln.scoring.evaluate import EvaluationLockedError, evaluate


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
