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

A secondary binary split (``secondary_binary_split``) reports AUROC and Brier
with only ``completely_reacted`` counted as reacted, as the Precursor Genome
paper recommends reporting both splits. It sits next to the primary metrics,
whose split (partially or completely reacted) is unchanged.

A ``hard_subset`` slice is reported next to the all-pairs metrics, never
instead of them, when the caller supplies a per-item thermodynamic-competition
margin (computed upstream, e.g. by the B60meV baseline; None when unknown) and a
margin threshold. Every item goes into exactly one bucket, from margins and
formula text only. The definition is committed like the predictions: its
SHA-256 (``hard_subset_definition_sha256``, over a canonical JSON of the
threshold, the rules and every item's formulas and margin) must be confirmed as
independently posted by a caller-supplied ``verify_posted_hard_subset_hash``
before labels are loaded, so the threshold and margins cannot be re-chosen
after seeing per-bucket metrics. Integrators bind that verifier to the posting
contract, as for predictions. The buckets are:

- ``hard``: the margin is known and below the threshold, or a precursor formula
  matches a carbonate, hydroxide or ammonium rule (``HARD_SUBSET_FORMULA_RULES``);
- ``easy``: the margin is known, at or above the threshold, and no formula rule matches;
- ``unknown``: the margin is unknown and no formula rule matches.

Each bucket reports the same metrics as all pairs, plus counts by trigger. This
module computes no energies.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from bisect import bisect_left, bisect_right
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Any

from pydantic import ValidationError

from kiln.schemas import Category, ComputeRequest, ComputeTier, Item, Label, Prediction


class EvaluationLockedError(RuntimeError):
    """A posted commitment (predictions or hard-subset definition) could not be independently verified."""


# ---------- Hard subset (formula text and caller-supplied margins only) ----------

HARD_SUBSET_MARGIN_TRIGGER = "margin_below_threshold"

# Regular expressions over the formula text, matched case-sensitively after
# Unicode subscript digits become ASCII digits. An uppercase letter always
# starts an element symbol, so "CO3" is carbon then oxygen (never Co), "OH" is
# oxygen then hydrogen, and "NH4" is nitrogen then hydrogen (never Na, Nb, Ni).
# The rules assume conventional ion-group notation (Li2CO3, Mg(OH)2, NH4Cl).
# They do NOT recognise formulas reordered by electronegativity, as pymatgen's
# reduced_formula writes them (LiHO, Mg(HO)2, H4NCl, Cu2H2CO5): those match no
# rule. The per-formula table in the report shows what each formula matched.
HARD_SUBSET_FORMULA_RULES: Mapping[str, str] = MappingProxyType({
    # CO3 not followed by a digit. Bicarbonate (HCO3) counts; oxalate (C2O4) does not.
    "carbonate": r"CO3(?![0-9])",
    # O then H, where H is not the start of He, Hf, Hg, Ho or Hs. Oxyhydroxides
    # (FeOOH) count; water of crystallization (·H2O) does not.
    "hydroxide": r"OH(?![a-z])",
    # NH4 not followed by a digit. Ammonia (NH3), hydrazine (N2H4) and
    # substituted ammonium (N(CH3)4) do not count.
    "ammonium": r"NH4(?![0-9])",
})
_FORMULA_PATTERNS = {name: re.compile(pattern) for name, pattern in HARD_SUBSET_FORMULA_RULES.items()}
_SUBSCRIPT_DIGITS = str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789")
HARD_SUBSET_TRIGGERS = (HARD_SUBSET_MARGIN_TRIGGER, *HARD_SUBSET_FORMULA_RULES)
HARD_SUBSET_BUCKETS = ("hard", "easy", "unknown")
HARD_SUBSET_DEFINITION_VERSION = "kiln.hard_subset.v1"  # bump when the bucket rules or canonical form change


def formula_triggers(formula: str) -> tuple[str, ...]:
    """Names of the hard-subset formula rules that ``formula`` matches, in rule order."""
    if not isinstance(formula, str):
        raise TypeError(f"formula must be a str, got {type(formula).__name__}")
    text = formula.translate(_SUBSCRIPT_DIGITS)
    return tuple(name for name, pattern in _FORMULA_PATTERNS.items() if pattern.search(text))


def _is_real(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _hard_subset_inputs(
    item_map: dict[str, Item],
    margins: Mapping[str, float | None] | None,
    threshold: float | None,
) -> tuple[dict[str, float | None], float]:
    """Validate the hard-subset inputs; return margins as float or None, and the threshold as float."""
    if margins is None or threshold is None:
        raise ValueError(
            "hard_subset_margins and hard_subset_margin_threshold_ev_per_atom must be supplied together"
        )
    if not isinstance(margins, Mapping):
        raise TypeError(f"hard_subset_margins must be a mapping, got {type(margins).__name__}")
    if not _is_real(threshold) or threshold <= 0:
        raise ValueError("hard_subset_margin_threshold_ev_per_atom must be a finite number above 0")
    missing = sorted(set(item_map) - set(margins))
    if missing:
        raise ValueError(f"no hard-subset margin entry for items {missing}; state None for an unknown margin")
    unknown = sorted(set(margins) - set(item_map), key=str)
    if unknown:
        raise ValueError(f"hard-subset margin entries for unknown items: {unknown}")
    for item_id, margin in margins.items():
        if margin is None:
            continue
        if not _is_real(margin):
            raise ValueError(f"hard-subset margin for {item_id!r} must be a finite number or None, got {margin!r}")
        if margin < 0:
            raise ValueError(
                f"hard-subset margin for {item_id!r} is negative ({margin!r}); a competition margin "
                "(dE_competing - dE_best) is nonnegative by construction"
            )
    normalized = {item_id: None if margins[item_id] is None else float(margins[item_id]) for item_id in item_map}
    return normalized, float(threshold)


def _hard_subset_canonical(item_map: dict[str, Item], margins: dict[str, float | None], threshold: float) -> bytes:
    """Canonical JSON of everything that decides the buckets: the definition
    version, threshold, margin rule, formula rules and text handling, and every
    item's ID, precursor formulas and margin, sorted by item ID."""
    payload = {
        "version": HARD_SUBSET_DEFINITION_VERSION,
        "margin_threshold_ev_per_atom": threshold,
        "margin_rule": "hard when margin_ev_per_atom is known and < margin_threshold_ev_per_atom",
        "formula_rules": dict(HARD_SUBSET_FORMULA_RULES),
        "formula_text": "case-sensitive; Unicode subscript digits read as ASCII digits",
        "items": [
            [item_id, item_map[item_id].precursor_a, item_map[item_id].precursor_b, margins[item_id]]
            for item_id in sorted(item_map)
        ],
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")


def hard_subset_definition_sha256(
    items: Iterable[Item],
    margins: Mapping[str, float | None],
    threshold: float,
) -> str:
    """SHA-256 of the canonical hard-subset definition, to post before unblinding.

    Uses the same validation and canonical form as ``evaluate``, so the digest a
    caller posts is the one ``evaluate`` asks ``verify_posted_hard_subset_hash``
    to confirm. Input order and int-versus-float spelling of a margin do not
    change it; a changed threshold, margin, formula, item or rule does.
    """
    item_map = _unique(items, "item")
    if not item_map:
        raise ValueError("at least one item is required")
    normalized, threshold_value = _hard_subset_inputs(item_map, margins, threshold)
    return hashlib.sha256(_hard_subset_canonical(item_map, normalized, threshold_value)).hexdigest()


def _hard_subset_assign(
    item_map: dict[str, Item],
    margins: Mapping[str, float | None] | None,
    threshold: float | None,
) -> dict[str, Any] | None:
    """Validate the hard-subset inputs, digest the definition and put every item in one bucket.

    Runs before labels are loaded, so labels cannot influence the assignment and
    bad inputs never cause a label read. Returns None when neither input is given.
    """
    if margins is None and threshold is None:
        return None
    margins, threshold = _hard_subset_inputs(item_map, margins, threshold)
    digest = hashlib.sha256(_hard_subset_canonical(item_map, margins, threshold)).hexdigest()
    formula_table = {
        formula: list(formula_triggers(formula))
        for formula in sorted({f for item in item_map.values() for f in (item.precursor_a, item.precursor_b)})
    }
    assignments = []
    for item_id in sorted(item_map):
        item, margin = item_map[item_id], margins[item_id]
        triggers = [HARD_SUBSET_MARGIN_TRIGGER] if margin is not None and margin < threshold else []
        matched = set(formula_table[item.precursor_a]) | set(formula_table[item.precursor_b])
        triggers += [name for name in HARD_SUBSET_FORMULA_RULES if name in matched]
        bucket = "hard" if triggers else "unknown" if margin is None else "easy"
        assignments.append({
            "item_id": item_id,
            "bucket": bucket,
            "margin_ev_per_atom": margin,
            "triggers": triggers,
        })
    return {"threshold": threshold, "sha256": digest, "assignments": assignments, "formula_triggers": formula_table}


def _verify_hard_subset_commitment(plan: dict[str, Any] | None, verify: Callable[[str], bool] | None) -> None:
    """Fail closed unless the hard-subset definition digest is independently
    verified as posted, so the threshold and margins cannot be re-chosen after
    seeing per-bucket metrics."""
    if plan is None:
        if verify is not None:
            raise ValueError("verify_posted_hard_subset_hash was supplied without a hard-subset definition")
        return
    try:
        verified = verify is not None and verify(plan["sha256"]) is True
    except Exception as exc:
        raise EvaluationLockedError("Unable to verify posted hard-subset definition hash") from exc
    if not verified:
        raise EvaluationLockedError("Hard-subset definition hash has not been independently verified as posted")


def _hard_subset_report(plan: dict[str, Any] | None, rows: dict[str, tuple[Prediction, Label]]) -> dict[str, Any]:
    if plan is None:
        return {
            "available": False,
            "reason": "Unavailable: no per-item margins and margin threshold were supplied.",
        }
    assignments = plan["assignments"]
    by_bucket = {bucket: [a["item_id"] for a in assignments if a["bucket"] == bucket] for bucket in HARD_SUBSET_BUCKETS}
    if sum(map(len, by_bucket.values())) != len(rows) or {a["item_id"] for a in assignments} != set(rows):
        raise RuntimeError("hard-subset buckets must hold every evaluated item exactly once")
    hard = [a for a in assignments if a["bucket"] == "hard"]
    return {
        "available": True,
        "definition_sha256": plan["sha256"],
        "definition": {
            "version": HARD_SUBSET_DEFINITION_VERSION,
            "commitment": (
                "definition_sha256 (canonical JSON of the threshold, rules and every item's formulas and margin) "
                "was verified as posted by verify_posted_hard_subset_hash before labels were loaded"
            ),
            "margin_threshold_ev_per_atom": plan["threshold"],
            "hard": "margin_ev_per_atom known and < margin_threshold_ev_per_atom, or any precursor formula matches a formula rule",
            "easy": "margin_ev_per_atom known and >= margin_threshold_ev_per_atom, and no formula rule matches",
            "unknown": "margin_ev_per_atom unknown and no formula rule matches",
            "formula_rules": dict(HARD_SUBSET_FORMULA_RULES),
            "formula_notation": "conventional ion-group notation; electronegativity-ordered formulas (e.g. LiHO) match no rule",
        },
        "n": len(rows),
        **{bucket: _slice_metrics([rows[item_id] for item_id in ids]) for bucket, ids in by_bucket.items()},
        "trigger_counts": {trigger: sum(trigger in a["triggers"] for a in assignments) for trigger in HARD_SUBSET_TRIGGERS},
        "hard_with_unknown_margin": sum(a["margin_ev_per_atom"] is None for a in hard),
        "formula_triggers": plan["formula_triggers"],
        "assignments": assignments,
    }


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


def _complete_only(rows: list[tuple[Prediction, Label]]) -> dict[str, Any]:
    """AUROC and Brier with only completely_reacted counted as reacted (the secondary split)."""
    positive = [label.category == Category.completely_reacted for _, label in rows]
    positives = [p.p_react for (p, _), pos in zip(rows, positive) if pos]
    negatives = sorted(p.p_react for (p, _), pos in zip(rows, positive) if not pos)
    auc = None
    if positives and negatives:
        midranks = sum((bisect_left(negatives, score) + bisect_right(negatives, score)) / 2 for score in positives)
        auc = midranks / (len(positives) * len(negatives))
    return {"reacted_means": "completely_reacted only", "n": len(rows), "n_reacted": len(positives), "auroc": auc,
            "brier": sum((p.p_react - int(pos)) ** 2 for (p, _), pos in zip(rows, positive)) / len(rows)}


def _slice_metrics(rows: list[tuple[Prediction, Label]]) -> dict[str, Any]:
    """``_metrics`` for a slice that may be empty: an empty slice reports n = 0
    and None for every rate, never 0 and never a division error."""
    if rows:
        return _metrics(rows)
    return {
        "n": 0,
        "auroc": None,
        "four_class_accuracy": None,
        "four_class_macro_f1": None,
        "four_class_f1": _f1_by_class([]),
        "brier": None,
        "coverage": None,
        "flagged_accuracy": None,
        "unflagged_accuracy": None,
        "flagged_n": 0,
        "unflagged_n": 0,
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


def read_labels_jsonl(path: str | Path) -> list[Label]:
    """Read a JSON Lines label file; pass it to ``evaluate`` only as the ``load_labels`` callback.

    Kept in this module because it is the only one allowed to read labels (AGENTS.md rule 1).
    Errors name the line number and fields only, never label values.
    """
    labels = []
    with Path(path).open(encoding="utf-8") as stream:
        for number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                labels.append(Label.model_validate_json(line))
            except ValidationError as exc:
                names = ", ".join(sorted({".".join(map(str, e["loc"])) or e["type"] for e in exc.errors()}))
                raise ValueError(f"labels line {number} failed Label validation for {names}") from None
    return labels


def evaluate(
    predictions_path: str | Path,
    items: Iterable[Item],
    load_labels: Callable[[], Iterable[Label]],
    *,
    verify_posted_hash: Callable[[str], bool] | None = None,
    compute_requests: Iterable[ComputeRequest] = (),
    bootstrap_samples: int = 1000,
    bootstrap_seed: int = 0,
    hard_subset_margins: Mapping[str, float | None] | None = None,
    hard_subset_margin_threshold_ev_per_atom: float | None = None,
    verify_posted_hard_subset_hash: Callable[[str], bool] | None = None,
) -> dict[str, Any]:
    """Evaluate one frozen JSONL run after independent confirmation of its hash.

    The returned updated requests are copies; append-only logs are not mutated.
    A missing score on either side leaves movement unknown; equal distance is
    reported as False. Macro-F1 is None unless all four categories appear in the
    labels or predictions. Bootstrap intervals are unavailable pending an agreed method for overlapping clusters.

    ``hard_subset_margins`` maps every item ID to its competition margin in
    eV/atom (None when unknown); ``hard_subset_margin_threshold_ev_per_atom`` has
    no default. Supply both for the ``hard_subset`` slice, or neither, in which
    case the slice is reported as unavailable. Both are checked, and every item
    assigned to a bucket, before labels are loaded. With the slice requested,
    ``verify_posted_hard_subset_hash`` must return the literal True for the
    definition digest (see ``hard_subset_definition_sha256``) or
    ``EvaluationLockedError`` is raised and labels are never loaded.
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
    hard_plan = _hard_subset_assign(item_map, hard_subset_margins, hard_subset_margin_threshold_ev_per_atom)
    _verify_hard_subset_commitment(hard_plan, verify_posted_hard_subset_hash)
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
        "secondary_binary_split": _complete_only(list(rows.values())),
        "hard_subset": _hard_subset_report(hard_plan, rows),
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
