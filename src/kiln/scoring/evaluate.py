"""Locked, all-pairs evaluation; no label source or posting service is assumed.

A caller must supply an independent verifier of an externally posted SHA-256.
A local hash file, a posting attempt, or a receipt without verification is not
proof. The verifier must return the literal True for the supplied digest before
``load_labels`` is called. Integrators are responsible for binding that verifier
to the project's eventual trusted posting/receipt contract. This module does not
post anything or provide a real label loader.
"""
from __future__ import annotations

import hashlib
import json
import math
from bisect import bisect_left, bisect_right
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from kiln.schemas import Category, ComputeRequest, Item, Label, Prediction


class EvaluationLockedError(RuntimeError):
    """The prediction commitment could not be independently verified."""


def _unique(rows: Iterable[Any], name: str) -> dict[str, Any]:
    result = {}
    for row in rows:
        if row.item_id in result:
            raise ValueError(f"duplicate {name} item_id: {row.item_id}")
        result[row.item_id] = row
    return result


def _metrics(rows: list[tuple[Prediction, Label]]) -> dict[str, Any]:
    n = len(rows)
    positives = [p.p_react for p, label in rows if label.reacted]
    negatives = [p.p_react for p, label in rows if not label.reacted]
    auc = None
    if positives and negatives:
        negatives.sort()
        auc = sum((bisect_left(negatives, score) + bisect_right(negatives, score)) / 2 for score in positives) / (len(positives) * len(negatives))
    def accuracy(subset: list[tuple[Prediction, Label]]) -> float | None:
        return sum(p.category == label.category for p, label in subset) / len(subset) if subset else None
    flagged = [(p, label) for p, label in rows if p.needs_review]
    unflagged = [(p, label) for p, label in rows if not p.needs_review]
    return {
        "n": n, "auroc": auc, "four_class_accuracy": accuracy(rows),
        "brier": sum((p.p_react - int(label.reacted)) ** 2 for p, label in rows) / n,
        "coverage": len(unflagged) / n,
        "flagged_accuracy": accuracy(flagged), "unflagged_accuracy": accuracy(unflagged),
        "flagged_n": len(flagged), "unflagged_n": len(unflagged),
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
    reported as False. Bootstrap intervals are unavailable pending an agreed method for overlapping clusters.
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
    if len({(p.run_id, p.condition, p.seed) for p in predictions}) != 1:
        raise ValueError("predictions must belong to one run, condition, and seed")
    for p in predictions:
        if not math.isfinite(p.p_react) or not 0 <= p.p_react <= 1:
            raise ValueError("p_react must be finite and between 0 and 1")
        if p.needs_review != bool(p.review_flags):
            raise ValueError("needs_review must agree with review_flags")
    requests = list(compute_requests)
    if len({r.request_id for r in requests}) != len(requests):
        raise ValueError("duplicate compute request ID")
    for request in requests:
        if request.item_id not in pred or request.run_id != predictions[0].run_id:
            raise ValueError("compute request does not belong to this run and item set")
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
    updated = []
    allocation: dict[tuple[str, str], dict[str, Any]] = {}
    for request in requests:
        before, after = request.p_react_before, request.p_react_after
        target = int(labels[request.item_id].reacted)
        moved = None if before is None or after is None else abs(after - target) < abs(before - target)
        updated.append(request.model_copy(update={"moved_toward_label": moved}))
        key = (request.tier.value, request.status.value)
        bucket = allocation.setdefault(key, {"tier": key[0], "status": key[1], "requests": 0, "compute_units": 0.0, "gpu_seconds": 0.0, "movement_known": 0, "moved_toward_label": 0})
        bucket["requests"] += 1
        bucket["compute_units"] += request.compute_units
        bucket["gpu_seconds"] += request.gpu_seconds
        bucket["movement_known"] += moved is not None
        bucket["moved_toward_label"] += moved is True
    return {"prediction_sha256": digest, "metrics": _metrics(list(rows.values())), "bootstrap": _bootstrap(bootstrap_samples, bootstrap_seed), "compute_allocation": [allocation[k] for k in sorted(allocation)], "compute_requests": updated}
