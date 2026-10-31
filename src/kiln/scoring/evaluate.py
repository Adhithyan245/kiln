"""Locked, all-pairs evaluation; no label source or posting service is assumed.

A caller must supply an independent verifier of an externally posted SHA-256.
A local hash file, a posting attempt, or a receipt without verification is not
proof. The verifier must return the literal True for the supplied digest before
``load_labels`` is called. Integrators are responsible for binding that verifier
to the project's eventual trusted posting/receipt contract. This module does not
post anything or provide a real label loader.

Reported on all pairs, flagged included: binary AUROC and Brier, four-class
accuracy and macro-F1, coverage, flagged and unflagged accuracy, and compute
accounting (totals, per tier, per tier and status). Bootstrap intervals and
"correct changes" are unavailable until their definitions are agreed.
"""
from __future__ import annotations

import hashlib
import json
import math
from bisect import bisect_left, bisect_right
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from kiln.schemas import Category, ComputeRequest, ComputeTier, Item, Label, Prediction


class EvaluationLockedError(RuntimeError):
    """The prediction commitment could not be independently verified."""


def _unique(rows: Iterable[Any], name: str) -> dict[str, Any]:
    result = {}
    for row in rows:
        if row.item_id in result:
            raise ValueError(f"duplicate {name} item_id: {row.item_id}")
        result[row.item_id] = row
    return result


def _f1_by_class(rows: list[tuple[Prediction, Label]]) -> list[dict[str, Any]]:
    # F1 = 2TP / (2TP + FP + FN); undefined (None) when a class is absent from
    # both labels and predictions, rather than silently set to 0 or dropped.
    result = []
    for category in Category:
        tp = sum(p.category == category and label.category == category for p, label in rows)
        fp = sum(p.category == category and label.category != category for p, label in rows)
        fn = sum(p.category != category and label.category == category for p, label in rows)
        denominator = 2 * tp + fp + fn
        result.append({
            "category": category.value,
            "support": tp + fn,
            "predicted": tp + fp,
            "f1": 2 * tp / denominator if denominator else None,
        })
    return result


def _metrics(rows: list[tuple[Prediction, Label]]) -> dict[str, Any]:
    n = len(rows)
    positives = [p.p_react for p, label in rows if label.reacted]
    negatives = sorted(p.p_react for p, label in rows if not label.reacted)
    auc = None
    if positives and negatives:
        midranks = sum((bisect_left(negatives, score) + bisect_right(negatives, score)) / 2 for score in positives)
        auc = midranks / (len(positives) * len(negatives))

    def accuracy(subset: list[tuple[Prediction, Label]]) -> float | None:
        return sum(p.category == label.category for p, label in subset) / len(subset) if subset else None

    per_class = _f1_by_class(rows)
    scores = [entry["f1"] for entry in per_class]
    flagged = [(p, label) for p, label in rows if p.needs_review]
    unflagged = [(p, label) for p, label in rows if not p.needs_review]
    return {
        "n": n,
        "auroc": auc,
        "four_class_accuracy": accuracy(rows),
        "four_class_macro_f1": None if None in scores else sum(scores) / len(scores),
        "four_class_f1": per_class,
        "brier": sum((p.p_react - int(label.reacted)) ** 2 for p, label in rows) / n,
        "coverage": len(unflagged) / n,
        "flagged_accuracy": accuracy(flagged),
        "unflagged_accuracy": accuracy(unflagged),
        "flagged_n": len(flagged),
        "unflagged_n": len(unflagged),
    }


def _tally(requests: list[ComputeRequest], moved: dict[str, bool | None]) -> dict[str, Any]:
    # changed_prediction is counted as logged; its definition is OPEN-17, so it
    # is neither derived from the before/after scores nor checked against them.
    return {
        "requests": len(requests),
        "compute_units": math.fsum(r.compute_units for r in requests),
        "gpu_seconds": math.fsum(r.gpu_seconds for r in requests),
        "changed_prediction_known": sum(r.changed_prediction is not None for r in requests),
        "changed_prediction": sum(r.changed_prediction is True for r in requests),
        "movement_known": sum(moved[r.request_id] is not None for r in requests),
        "moved_toward_label": sum(moved[r.request_id] is True for r in requests),
    }


def _bootstrap(samples: int, seed: int) -> dict[str, Any]:
    # Each pair has two potentially overlapping precursor memberships. No
    # validated resampling procedure or inferential contract is specified yet.
    # Connected-component resampling is not a substitute for that protocol.
    return {
        "method": None,
        "samples": samples,
        "seed": seed,
        "intervals": {},
        "reason": "Unavailable: an agreed and validated bootstrap method for overlapping precursor clusters is required.",
    }


def evaluate(
    predictions_path: str | Path,
    items: Iterable[Item],
    load_labels: Callable[[], Iterable[Label]],
    *,
    verify_posted_hash: Callable[[str], bool] | None = None,
    compute_requests: Iterable[ComputeRequest] = (),
    bootstrap_samples: int = 1000,
    bootstrap_seed: int = 0,
) -> dict[str, Any]:
    """Evaluate one frozen JSONL run after independent confirmation of its hash.

    The returned updated requests are copies; append-only logs are not mutated.
    A missing score on either side leaves movement unknown; equal distance is
    reported as False. Macro-F1 is None unless all four categories appear in the
    labels or predictions. Bootstrap intervals are unavailable pending an agreed method for overlapping clusters.
    """
    if not isinstance(bootstrap_samples, int) or isinstance(bootstrap_samples, bool) or bootstrap_samples < 0:
        raise ValueError("bootstrap_samples must be a nonnegative integer")
    payload = Path(predictions_path).read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    try:
        verified = verify_posted_hash is not None and verify_posted_hash(digest) is True
    except Exception as exc:
        raise EvaluationLockedError("Unable to verify posted prediction hash") from exc
    if not verified:
        raise EvaluationLockedError("Prediction hash has not been independently verified as posted")
    predictions = [Prediction.model_validate(json.loads(line)) for line in payload.splitlines() if line.strip()]
    pred = _unique(predictions, "prediction")
    item_map = _unique(items, "item")
    if not pred or set(pred) != set(item_map):
        raise ValueError("predictions and items must contain the same nonempty set of item IDs")
    splits = {item.split for item in item_map.values()}
    sources = {item.source for item in item_map.values()}
    if len(splits) != 1 or len(sources) != 1:
        raise ValueError("items must share one split and one source")
    if len({(p.run_id, p.condition, p.seed) for p in predictions}) != 1:
        raise ValueError("predictions must belong to one run, condition, and seed")
    for p in predictions:
        if not math.isfinite(p.p_react) or not 0 <= p.p_react <= 1:
            raise ValueError("p_react must be finite and between 0 and 1")
        if p.needs_review != bool(p.review_flags):
            raise ValueError("needs_review must agree with review_flags")
    requests = list(compute_requests)
    by_id = {r.request_id: r for r in requests}
    if len(by_id) != len(requests):
        raise ValueError("duplicate compute request ID")
    referenced = {request_id for prediction in predictions for request_id in prediction.compute_requests}
    missing = referenced - set(by_id)
    if missing:
        raise ValueError(f"missing referenced compute requests: {sorted(missing)}")
    for p in predictions:
        for request_id in p.compute_requests:
            if by_id[request_id].item_id != p.item_id:
                raise ValueError(f"compute request {request_id} is referenced by a different item")
    for request in requests:
        if request.item_id not in pred or request.run_id != predictions[0].run_id:
            raise ValueError("compute request does not belong to this run and item set")
        if request.moved_toward_label is not None:
            raise ValueError("moved_toward_label must be unset before evaluation")
        for value in (request.p_react_before, request.p_react_after):
            if value is not None and (not math.isfinite(value) or not 0 <= value <= 1):
                raise ValueError("request scores must be finite and between 0 and 1")
        if not math.isfinite(request.compute_units) or request.compute_units < 0 or not math.isfinite(request.gpu_seconds) or request.gpu_seconds < 0:
            raise ValueError("request costs must be finite and nonnegative")
    labels = _unique(load_labels(), "label")
    if set(labels) != set(pred):
        raise ValueError("labels and predictions must contain the same item IDs")
    for label in labels.values():
        if label.reacted != (label.category in (Category.partially_reacted, Category.completely_reacted)):
            raise ValueError("label reacted must agree with category")
    rows = {item_id: (p, labels[item_id]) for item_id, p in pred.items()}
    moved: dict[str, bool | None] = {}
    for request in requests:
        before, after = request.p_react_before, request.p_react_after
        target = int(labels[request.item_id].reacted)
        moved[request.request_id] = None if before is None or after is None else abs(after - target) < abs(before - target)
    updated = [request.model_copy(update={"moved_toward_label": moved[request.request_id]}) for request in requests]
    by_tier_status: dict[tuple[str, str], list[ComputeRequest]] = {}
    for request in requests:
        by_tier_status.setdefault((request.tier.value, request.status.value), []).append(request)
    return {
        "prediction_sha256": digest,
        "split": splits.pop(),
        "source": sources.pop(),
        "metrics": _metrics(list(rows.values())),
        "bootstrap": _bootstrap(bootstrap_samples, bootstrap_seed),
        "compute_total": _tally(requests, moved),
        "compute_by_tier": [{"tier": tier.value, **_tally([r for r in requests if r.tier == tier], moved)} for tier in ComputeTier],
        "compute_allocation": [{"tier": tier, "status": status, **_tally(by_tier_status[(tier, status)], moved)} for tier, status in sorted(by_tier_status)],
        "correct_changes": {
            "count": None,
            "reason": "Unavailable: no agreed definition; changed_prediction is OPEN-17 and extra allocation tables are OPEN-14.",
        },
        "compute_requests": updated,
    }
