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
    request = ComputeRequest(request_id="r", run_id="synthetic", item_id="a", agent="thermo", tier="single_point", reason="test", inputs={}, settings={}, cache_key="x", status="cached", compute_units=2, gpu_seconds=3, p_react_before=0.2, p_react_after=0.8)
    result = evaluate(path, items, lambda: labels, verify_posted_hash=verify, compute_requests=[request], bootstrap_samples=200, bootstrap_seed=12)
    assert result["prediction_sha256"] == expected_hash
    assert result["metrics"] == {"n": 4, "auroc": 0.875, "four_class_accuracy": 0.5, "brier": pytest.approx(0.1425), "coverage": 0.75, "flagged_accuracy": 0.0, "unflagged_accuracy": pytest.approx(2/3), "flagged_n": 1, "unflagged_n": 3}
    assert result["compute_requests"][0].moved_toward_label is True
    assert request.moved_toward_label is None
    assert result["compute_allocation"][0]["compute_units"] == 2
    assert result["compute_allocation"][0]["status"] == "cached"
    assert result["bootstrap"]["intervals"] == {}


def test_precursor_overlap_is_one_cluster_and_auc_undefined(tmp_path):
    path, items, labels = fixture(tmp_path)
    for i, item in enumerate(items):
        item.precursor_a, item.precursor_b = f"X{i}", f"X{i+1}"
    for label in labels:
        label.category, label.reacted = Category.unreacted, False
    result = evaluate(path, items, lambda: labels, verify_posted_hash=lambda _: True)
    assert result["metrics"]["auroc"] is None
    assert result["bootstrap"]["intervals"] == {}
    assert result["bootstrap"]["reason"]


def test_invalid_inputs_and_label_consistency(tmp_path):
    path, items, labels = fixture(tmp_path)
    with pytest.raises(ValueError, match="same nonempty"):
        evaluate(path, items[:-1], lambda: pytest.fail("labels loaded"), verify_posted_hash=lambda _: True)
    with pytest.raises(ValueError, match="same item IDs"):
        evaluate(path, items, lambda: labels[:-1], verify_posted_hash=lambda _: True)
    labels[0].reacted = False
    with pytest.raises(ValueError, match="agree with category"):
        evaluate(path, items, lambda: labels, verify_posted_hash=lambda _: True)


def test_bootstrap_is_unavailable_without_an_agreed_method(tmp_path):
    path, items, labels = fixture(tmp_path)
    original = [json.loads(line) for line in path.read_text().splitlines()]
    predictions = []
    more_items = []
    more_labels = []
    for i in range(12):
        for j in range(4):
            item_id = f"{i}-{j}"
            prediction = dict(original[j], item_id=item_id)
            predictions.append(prediction)
            more_items.append(items[j].model_copy(update={"item_id": item_id, "precursor_a": f"A{i}", "precursor_b": f"B{i}"}))
            more_labels.append(labels[j].model_copy(update={"item_id": item_id}))
    path.write_text("\n".join(json.dumps(p) for p in predictions))
    kwargs = dict(verify_posted_hash=lambda _: True, bootstrap_samples=200, bootstrap_seed=7)
    first = evaluate(path, more_items, lambda: more_labels, **kwargs)["bootstrap"]
    second = evaluate(path, more_items, lambda: more_labels, **kwargs)["bootstrap"]
    assert first == second
    assert first["method"] is None
    assert first["intervals"] == {}
    assert "overlapping precursor clusters" in first["reason"]


def test_missing_referenced_compute_request_blocks_label_loading(tmp_path):
    path, items, labels = fixture(tmp_path)
    predictions = [json.loads(line) for line in path.read_text().splitlines()]
    predictions[0]["compute_requests"] = ["missing-request"]
    path.write_text("\n".join(json.dumps(prediction) for prediction in predictions))

    def load_labels():
        pytest.fail("labels loaded despite missing compute request")

    with pytest.raises(ValueError, match="missing referenced compute requests.*missing-request"):
        evaluate(path, items, load_labels, verify_posted_hash=lambda _: True)
