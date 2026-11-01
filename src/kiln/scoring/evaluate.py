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

Stored category strings (OPEN-11, protocol §3.1). ``read_labels_jsonl`` is the
only code that reads a stored category string. ``normalize_category`` trims it,
lower-cases it and turns spaces and hyphens into underscores, then maps the
dataset README's documented names: ``unreacted``, ``transformed``,
``partially_reacted`` and ``completely_reacted`` to the matching ``Category``,
and ``unclassified`` or a null to the OPEN-12 rule. Any other string stops the
evaluation before any metric is computed (fail closed), and no error message
contains the string.

Items with no outcome to score (OPEN-12, protocol §3.1 and §7: an
``unclassified`` or null category, read as ``UnscoredLabel``) stay in the hashed
predictions and in coverage, which needs no label. They are left out of AUROC,
Brier, four-class accuracy and macro-F1, and flagged and unflagged accuracy, so
``flagged_n`` and ``unflagged_n`` count scored items only. Every metrics block
reports ``n`` (all items, the coverage denominator), ``n_scored`` and
``n_unclassified_or_null``.

A secondary binary split (``secondary_binary_split``) reports AUROC and Brier
with only ``completely_reacted`` counted as reacted, as the Precursor Genome
paper recommends reporting both splits. It sits next to the primary metrics,
whose split (partially or completely reacted) is unchanged.

A ``hard_subset`` slice is reported next to the all-pairs metrics, never
instead of them, when the caller supplies a per-item thermodynamic-competition
margin (computed upstream, e.g. by the B60meV baseline; None when unknown) and a
margin threshold. Every item goes into exactly one bucket, from margins and the
explicit formula list of protocol §4.3 (OPEN-26) only. The definition is
committed like the predictions: its SHA-256 (``hard_subset_definition_sha256``,
over a canonical JSON of the threshold, the formula list and every item's
formulas and margin) must be confirmed as independently posted by a
caller-supplied ``verify_posted_hard_subset_hash`` before labels are loaded, so
the threshold and margins cannot be re-chosen after seeing per-bucket metrics.
Integrators bind that verifier to the posting contract, as for predictions. The
buckets are:

- ``hard``: the margin is known and below the threshold, or either precursor
  formula is on the list (``HARD_SUBSET_FORMULA_LIST``);
- ``easy``: the margin is known, at or above the threshold, and neither formula is on the list;
- ``unknown``: the margin is unknown and neither formula is on the list.

Each bucket reports the same metrics as all pairs, plus counts by trigger.

Baselines (OPEN-08, protocol §4.2) are scored by ``evaluate_baseline``, for
their own table, by AUROC of their ranking score only: ``-dE_ev_per_atom`` for
B0 and the temperature ratio for B0-T. Nothing maps them to ``p_react`` or
``Category``, so they have no Brier score or category accuracy. An undetermined
decision (a missing input) is listed, never imputed, and left out of the AUROC.
The scores are committed like the predictions: their SHA-256
(``baseline_scores_sha256``) must be confirmed as independently posted by a
caller-supplied ``verify_posted_baseline_hash`` before labels are loaded.

This module computes no energies.
"""
from __future__ import annotations

import hashlib
import json
import math
from bisect import bisect_left, bisect_right
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from kiln.baselines.b0 import DrivingForceDecision, TemperatureRatioDecision
from kiln.schemas import Category, ComputeRequest, ComputeTier, Item, Label, Prediction


class EvaluationLockedError(RuntimeError):
    """A posted commitment (predictions, hard-subset definition or baseline scores) could not be independently verified."""


# ---------- Stored category strings (OPEN-11) and items with no outcome (OPEN-12) ----------

# The dataset README's documented display names after normalization (protocol
# §3.1). Written from the README, never from the stored values, which nobody
# prints or inspects.
CATEGORY_NAMES: Mapping[str, Category] = MappingProxyType({
    "unreacted": Category.unreacted,
    "transformed": Category.transformed,
    "partially_reacted": Category.partially_reacted,
    "completely_reacted": Category.completely_reacted,
})
# Documented, but with no outcome to score (OPEN-12); a null category is read the same way.
UNSCORED_CATEGORY_NAMES = frozenset({"unclassified"})
_REACTED = frozenset({Category.partially_reacted, Category.completely_reacted})  # protocol §3.2


class UnscoredLabel(BaseModel):
    """A label whose stored category is ``unclassified`` or null: the item has
    no outcome to score (OPEN-12, protocol §3.1). It carries no category and no
    ``reacted`` value. ``read_labels_jsonl`` builds it; ``evaluate`` and
    ``evaluate_baseline`` keep the item in coverage and out of every label-based
    metric."""
    model_config = ConfigDict(frozen=True, extra="forbid")
    item_id: str


def normalize_category(stored: object) -> Category | None:
    """Map one stored category value to a ``Category`` (OPEN-11, protocol §3.1).

    Trims the string, lower-cases it and turns spaces and hyphens into
    underscores, then maps a documented name in ``CATEGORY_NAMES``. Returns None
    for ``unclassified`` or a null (no outcome to score, OPEN-12). Anything else
    raises ``ValueError`` whose message never contains the value, so no stored
    label string is printed (AGENTS.md rule 1).
    """
    if stored is None:
        return None
    if not isinstance(stored, str):
        raise ValueError("the stored category is neither a string nor null")
    name = stored.strip().lower().replace(" ", "_").replace("-", "_")
    if name in UNSCORED_CATEGORY_NAMES:
        return None
    category = CATEGORY_NAMES.get(name)
    if category is None:
        raise ValueError(
            "the stored category is not one of the documented names (unreacted, transformed, partially reacted, "
            "completely reacted, unclassified); evaluation stops before any metric is computed (OPEN-11)"
        )
    return category


def _label_from_line(line: str, number: int) -> Label | UnscoredLabel:
    """One JSON Lines label record: ``item_id``, ``category`` (the stored string
    or null) and optionally ``reacted``. ``reacted`` is derived from the category
    when absent or null and must agree with it when given. Errors name the line
    number and fields only, never a label value."""
    try:
        record = json.loads(line)
    except ValueError:
        raise ValueError(f"labels line {number} is not valid JSON") from None
    if not isinstance(record, dict):
        raise ValueError(f"labels line {number} is not a JSON object")
    if "category" not in record:
        raise ValueError(f"labels line {number} has no category field")
    try:
        category = normalize_category(record["category"])
    except ValueError as exc:
        raise ValueError(f"labels line {number}: {exc}") from None
    reacted = record.get("reacted")
    if reacted is not None and not isinstance(reacted, bool):
        raise ValueError(f"labels line {number}: reacted must be true, false or null")
    model: type[BaseModel]
    if category is None:
        if reacted is not None:
            raise ValueError(
                f"labels line {number}: reacted is set, but an unclassified or null category has no outcome (OPEN-12)"
            )
        model, fields = UnscoredLabel, {"item_id": record.get("item_id")}
    else:
        derived = category in _REACTED
        if reacted is not None and reacted != derived:
            raise ValueError(f"labels line {number}: label reacted must agree with category")
        model, fields = Label, {"item_id": record.get("item_id"), "category": category, "reacted": derived}
    try:
        return model.model_validate(fields)  # type: ignore[return-value]
    except ValidationError as exc:
        names = ", ".join(sorted({".".join(map(str, e["loc"])) or e["type"] for e in exc.errors()}))
        raise ValueError(f"labels line {number} failed {model.__name__} validation for {names}") from None


def read_labels_jsonl(path: str | Path) -> list[Label | UnscoredLabel]:
    """Read a JSON Lines label file; pass it to ``evaluate`` or ``evaluate_baseline``
    only as the ``load_labels`` callback.

    Kept in this module because it is the only one allowed to read labels (AGENTS.md
    rule 1). Each stored category goes through ``normalize_category`` (OPEN-11);
    ``unclassified`` or null gives an ``UnscoredLabel`` (OPEN-12), and any other
    unmapped string raises before any metric is computed. Errors name the line
    number and fields only, never label values.
    """
    labels = []
    with Path(path).open(encoding="utf-8") as stream:
        for number, line in enumerate(stream, 1):
            if line.strip():
                labels.append(_label_from_line(line, number))
    return labels


def _load_labels(
    load_labels: Callable[[], Iterable[Label | UnscoredLabel]], item_ids: set[str], what: str
) -> dict[str, Label | None]:
    """Call ``load_labels``, only after every gate has passed, and check what it
    returns. None marks an item with no outcome to score (OPEN-12)."""
    loaded = list(load_labels())
    for label in loaded:
        if not isinstance(label, (Label, UnscoredLabel)):
            raise TypeError("load_labels must yield Label or UnscoredLabel objects")
    labels = _unique(loaded, "label")
    if set(labels) != item_ids:
        raise ValueError(f"labels and {what} must contain the same item IDs")
    result: dict[str, Label | None] = {}
    for item_id, label in labels.items():
        if isinstance(label, Label) and label.reacted != (label.category in _REACTED):
            raise ValueError("label reacted must agree with category")
        result[item_id] = label if isinstance(label, Label) else None
    return result


# ---------- Hard subset (the explicit formula list and caller-supplied margins only) ----------

HARD_SUBSET_MARGIN_TRIGGER = "margin_below_threshold"
HARD_SUBSET_FORMULA_GROUPS = ("carbonate", "hydroxide", "ammonium")

# The explicit formula list of protocol §4.3 (OPEN-26), written in the ledger's
# own notation, which kiln.data copies into Item.precursor_a and precursor_b
# unchanged. The ledger writes 9 of its 46 formulas pymatgen-style (Al(HO)3,
# LiH3O2, PH6NO4, ...), so text rules cannot classify every precursor;
# membership by formula is this list, matched as exact strings, and nothing else.
# Deliberately not on the list (protocol §4.3): FeH4(CO3)2 (iron(II) oxalate
# dihydrate; oxalate is not carbonate), B(HO)3 (boric acid, H3BO3) and
# KP(HO2)2 (KH2PO4).
HARD_SUBSET_FORMULA_LIST: Mapping[str, str] = MappingProxyType({
    "BaCO3": "carbonate",
    "CaCO3": "carbonate",
    "Li2CO3": "carbonate",
    "Na2CO3": "carbonate",
    "SrCO3": "carbonate",
    "K4H6C2O9": "carbonate",    # K2CO3·1.5H2O, potassium carbonate sesquihydrate
    "Al(HO)3": "hydroxide",     # Al(OH)3
    "La(HO)3": "hydroxide",     # La(OH)3
    "LiH3O2": "hydroxide",      # LiOH·H2O
    "PH6NO4": "ammonium",       # NH4H2PO4
    "PH9(NO2)2": "ammonium",    # (NH4)2HPO4
})
HARD_SUBSET_TRIGGERS = (HARD_SUBSET_MARGIN_TRIGGER, *HARD_SUBSET_FORMULA_GROUPS)
HARD_SUBSET_BUCKETS = ("hard", "easy", "unknown")
# Bump when the bucket rules or canonical form change. v2: the explicit formula
# list (OPEN-26) replaced the v1 carbonate, hydroxide and ammonium regexes.
HARD_SUBSET_DEFINITION_VERSION = "kiln.hard_subset.v2"
_FORMULA_MATCH = "exact string match against formula_list, in the ledger's notation; no other formula rule"


def formula_triggers(formula: str) -> tuple[str, ...]:
    """The group (carbonate, hydroxide or ammonium) of ``formula`` on the explicit
    hard-subset formula list, as a one-element tuple, or () when it is not on the list.

    An exact string match in the ledger's notation: no case folding, no subscript
    or whitespace handling and no chemistry, so ``Mg(OH)2`` or ``LiOH`` written
    conventionally is not on the list.
    """
    if not isinstance(formula, str):
        raise TypeError(f"formula must be a str, got {type(formula).__name__}")
    group = HARD_SUBSET_FORMULA_LIST.get(formula)
    return () if group is None else (group,)


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


def _canonical_json(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")


def _hard_subset_canonical(item_map: dict[str, Item], margins: dict[str, float | None], threshold: float) -> bytes:
    """Canonical JSON of everything that decides the buckets: the definition
    version, threshold, margin rule, formula list and how it is matched, and every
    item's ID, precursor formulas and margin, sorted by item ID."""
    return _canonical_json({
        "version": HARD_SUBSET_DEFINITION_VERSION,
        "margin_threshold_ev_per_atom": threshold,
        "margin_rule": "hard when margin_ev_per_atom is known and < margin_threshold_ev_per_atom",
        "formula_rule": "hard when precursor_a or precursor_b is on formula_list",
        "formula_list": dict(HARD_SUBSET_FORMULA_LIST),
        "formula_match": _FORMULA_MATCH,
        "items": [
            [item_id, item_map[item_id].precursor_a, item_map[item_id].precursor_b, margins[item_id]]
            for item_id in sorted(item_map)
        ],
    })


def hard_subset_definition_sha256(
    items: Iterable[Item],
    margins: Mapping[str, float | None],
    threshold: float,
) -> str:
    """SHA-256 of the canonical hard-subset definition, to post before unblinding.

    Uses the same validation and canonical form as ``evaluate``, so the digest a
    caller posts is the one ``evaluate`` asks ``verify_posted_hard_subset_hash``
    to confirm. Input order and int-versus-float spelling of a margin do not
    change it; a changed threshold, margin, formula, item or formula list does.
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
        triggers += [group for group in HARD_SUBSET_FORMULA_GROUPS if group in matched]
        bucket = "hard" if triggers else "unknown" if margin is None else "easy"
        assignments.append({
            "item_id": item_id,
            "bucket": bucket,
            "margin_ev_per_atom": margin,
            "triggers": triggers,
        })
    return {"threshold": threshold, "sha256": digest, "assignments": assignments, "formula_triggers": formula_table}


def _verify_posted(digest: str, verify: Callable[[str], bool] | None, what: str) -> None:
    """Fail closed unless ``verify`` returns the literal True for ``digest``."""
    try:
        verified = verify is not None and verify(digest) is True
    except Exception as exc:
        raise EvaluationLockedError(f"Unable to verify posted {what} hash") from exc
    if not verified:
        raise EvaluationLockedError(f"{what[0].upper()}{what[1:]} hash has not been independently verified as posted")


def _verify_hard_subset_commitment(plan: dict[str, Any] | None, verify: Callable[[str], bool] | None) -> None:
    """Fail closed unless the hard-subset definition digest is independently
    verified as posted, so the threshold and margins cannot be re-chosen after
    seeing per-bucket metrics."""
    if plan is None:
        if verify is not None:
            raise ValueError("verify_posted_hard_subset_hash was supplied without a hard-subset definition")
        return
    _verify_posted(plan["sha256"], verify, "hard-subset definition")


def _hard_subset_report(plan: dict[str, Any] | None, rows: dict[str, tuple[Prediction, Label | None]]) -> dict[str, Any]:
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
                "definition_sha256 (canonical JSON of the threshold, formula list and every item's formulas and margin) "
                "was verified as posted by verify_posted_hard_subset_hash before labels were loaded"
            ),
            "margin_threshold_ev_per_atom": plan["threshold"],
            "hard": "margin_ev_per_atom known and < margin_threshold_ev_per_atom, or either precursor formula is on formula_list",
            "easy": "margin_ev_per_atom known and >= margin_threshold_ev_per_atom, and neither formula is on formula_list",
            "unknown": "margin_ev_per_atom unknown and neither formula is on formula_list",
            "formula_list": dict(HARD_SUBSET_FORMULA_LIST),
            "formula_match": _FORMULA_MATCH,
            "source": "protocol §4.3 (OPEN-26)",
        },
        "n": len(rows),
        **{bucket: _metrics([rows[item_id] for item_id in ids]) for bucket, ids in by_bucket.items()},
        "trigger_counts": {trigger: sum(trigger in a["triggers"] for a in assignments) for trigger in HARD_SUBSET_TRIGGERS},
        "hard_with_unknown_margin": sum(a["margin_ev_per_atom"] is None for a in hard),
        "formula_triggers": plan["formula_triggers"],
        "assignments": assignments,
    }


# ---------- Shared checks and metrics ----------

def _unique(rows: Iterable[Any], name: str) -> dict[str, Any]:
    result = {}
    for row in rows:
        if row.item_id in result:
            raise ValueError(f"duplicate {name} item_id: {row.item_id}")
        result[row.item_id] = row
    return result


def _split_and_source(item_map: dict[str, Item]) -> tuple[str, str]:
    splits = {item.split for item in item_map.values()}
    sources = {item.source for item in item_map.values()}
    if len(splits) != 1 or len(sources) != 1:
        raise ValueError("items must share one split and one source")
    return splits.pop(), sources.pop()


def _auroc(scored: Iterable[tuple[float, bool]]) -> float | None:
    """Mann-Whitney AUROC of (score, positive) pairs, ties counted as one half;
    None when either class is absent."""
    pairs = list(scored)
    positives = [score for score, positive in pairs if positive]
    negatives = sorted(score for score, positive in pairs if not positive)
    if not positives or not negatives:
        return None
    midranks = sum((bisect_left(negatives, score) + bisect_right(negatives, score)) / 2 for score in positives)
    return midranks / (len(positives) * len(negatives))


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


def _metrics(rows: list[tuple[Prediction, Label | None]]) -> dict[str, Any]:
    """All-pairs metrics for ``rows``, which may be empty (a hard-subset bucket).

    Coverage counts every row; every label-based metric uses only rows with an
    outcome to score (label not None, OPEN-12). An empty denominator gives n = 0
    or None, never 0 for a rate and never a division error.
    """
    n = len(rows)
    scored = [(p, label) for p, label in rows if label is not None]

    def accuracy(subset: list[tuple[Prediction, Label]]) -> float | None:
        return sum(p.category == label.category for p, label in subset) / len(subset) if subset else None

    per_class = _f1_by_class(scored)
    scores = [entry["f1"] for entry in per_class]
    flagged = [(p, label) for p, label in scored if p.needs_review]
    unflagged = [(p, label) for p, label in scored if not p.needs_review]
    return {
        "n": n,
        "n_scored": len(scored),
        "n_unclassified_or_null": n - len(scored),
        "auroc": _auroc((p.p_react, label.reacted) for p, label in scored),
        "four_class_accuracy": accuracy(scored),
        "four_class_macro_f1": None if None in scores else sum(scores) / len(scores),
        "four_class_f1": per_class,
        "brier": sum((p.p_react - int(label.reacted)) ** 2 for p, label in scored) / len(scored) if scored else None,
        "coverage": sum(not p.needs_review for p, _ in rows) / n if n else None,
        "flagged_accuracy": accuracy(flagged),
        "unflagged_accuracy": accuracy(unflagged),
        "flagged_n": len(flagged),
        "unflagged_n": len(unflagged),
    }


def _complete_only(rows: list[tuple[Prediction, Label | None]]) -> dict[str, Any]:
    """AUROC and Brier with only completely_reacted counted as reacted (the
    secondary split), over items with an outcome to score."""
    scored = [(p.p_react, label.category == Category.completely_reacted) for p, label in rows if label is not None]
    return {
        "reacted_means": "completely_reacted only",
        "n": len(rows),
        "n_scored": len(scored),
        "n_reacted": sum(positive for _, positive in scored),
        "auroc": _auroc(scored),
        "brier": sum((score - int(positive)) ** 2 for score, positive in scored) / len(scored) if scored else None,
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


# ---------- Agent runs ----------

def evaluate(
    predictions_path: str | Path,
    items: Iterable[Item],
    load_labels: Callable[[], Iterable[Label | UnscoredLabel]],
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
    A missing score on either side, or an item with no outcome to score, leaves
    movement unknown; equal distance is reported as False. Macro-F1 is None
    unless all four categories appear in the scored labels or predictions.
    Bootstrap intervals are unavailable pending an agreed method for overlapping clusters.

    ``load_labels`` yields ``Label`` or ``UnscoredLabel`` objects (use
    ``read_labels_jsonl`` for a stored label file); an ``UnscoredLabel`` item
    stays in coverage and out of every label-based metric (OPEN-12).

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
    _verify_posted(digest, verify_posted_hash, "prediction")
    predictions = [Prediction.model_validate(json.loads(line)) for line in payload.splitlines() if line.strip()]
    pred = _unique(predictions, "prediction")
    item_map = _unique(items, "item")
    if not pred or set(pred) != set(item_map):
        raise ValueError("predictions and items must contain the same nonempty set of item IDs")
    split, source = _split_and_source(item_map)
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
    labels = _load_labels(load_labels, set(pred), "predictions")
    rows = {item_id: (p, labels[item_id]) for item_id, p in pred.items()}
    moved: dict[str, bool | None] = {}
    for request in requests:
        before, after, label = request.p_react_before, request.p_react_after, labels[request.item_id]
        if before is None or after is None or label is None:
            moved[request.request_id] = None
        else:
            target = int(label.reacted)
            moved[request.request_id] = abs(after - target) < abs(before - target)
    updated = [request.model_copy(update={"moved_toward_label": moved[request.request_id]}) for request in requests]
    by_tier_status: dict[tuple[str, str], list[ComputeRequest]] = {}
    for request in requests:
        by_tier_status.setdefault((request.tier.value, request.status.value), []).append(request)
    return {
        "prediction_sha256": digest,
        "split": split,
        "source": source,
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


# ---------- Baselines (OPEN-08): AUROC of a ranking score, nothing else ----------

BaselineDecision = DrivingForceDecision | TemperatureRatioDecision

# Protocol §4.2. A higher score ranks an item as more likely to react.
BASELINE_RANKING_SCORES: Mapping[str, str] = MappingProxyType({
    "B0": "-dE_ev_per_atom",
    "B0-T": "ratio = T_dwell(K) / T_melt_higher(K)",
})
BASELINE_SCORES_VERSION = "kiln.baseline_scores.v1"  # bump when the ranking scores or canonical form change


def _ranking_score(decision: BaselineDecision) -> float | None:
    """The protocol §4.2 ranking score; None for an undetermined decision."""
    if isinstance(decision, DrivingForceDecision):
        dE = decision.dE_ev_per_atom
        return None if dE is None else 0.0 - dE  # 0.0 - dE, so dE = 0 scores 0.0, never -0.0
    return decision.ratio


def _baseline_inputs(
    decisions: Iterable[BaselineDecision], items: Iterable[Item]
) -> tuple[str, dict[str, Item], dict[str, BaselineDecision], dict[str, float | None]]:
    """Validate one baseline's decisions against the items (no labels involved)
    and return its condition, the items, the decisions and the ranking scores."""
    decisions = list(decisions)
    for decision in decisions:
        if not isinstance(decision, (DrivingForceDecision, TemperatureRatioDecision)):
            raise TypeError(
                "baseline decisions must be B0 DrivingForceDecision or B0-T TemperatureRatioDecision objects; "
                f"got {type(decision).__name__}. B60meV is a margin feature with no ranking score (protocol §4.2)"
            )
    by_id = _unique(decisions, "baseline decision")
    item_map = _unique(items, "item")
    if not by_id or set(by_id) != set(item_map):
        raise ValueError("baseline decisions and items must contain the same nonempty set of item IDs")
    conditions = {decision.condition for decision in decisions}
    if len(conditions) != 1:
        raise ValueError("baseline decisions must all come from one baseline (B0 or B0-T)")
    for decision in decisions:
        if isinstance(decision, TemperatureRatioDecision):
            item = item_map[decision.item_id]
            if (decision.temperature_c, decision.melting_point_a_c, decision.melting_point_b_c) != (
                item.temperature_c, item.melting_point_a_c, item.melting_point_b_c
            ):
                raise ValueError(f"B0-T decision for {decision.item_id!r} was not computed from this item's temperatures")
    scores = {item_id: _ranking_score(by_id[item_id]) for item_id in sorted(item_map)}
    for item_id, score in scores.items():
        if score is not None and not math.isfinite(score):
            raise ValueError(f"ranking score for {item_id!r} must be finite")
    return conditions.pop(), item_map, by_id, scores


def _baseline_canonical(condition: str, scores: dict[str, float | None]) -> bytes:
    """Canonical JSON of what decides a baseline's AUROC: the version, the
    baseline, its ranking-score definition and every item's score (null when
    undetermined), sorted by item ID."""
    return _canonical_json({
        "version": BASELINE_SCORES_VERSION,
        "condition": condition,
        "ranking_score": BASELINE_RANKING_SCORES[condition],
        "higher_score_ranks_as": "reacted",
        "items": [[item_id, scores[item_id]] for item_id in sorted(scores)],
    })


def baseline_scores_sha256(decisions: Iterable[BaselineDecision], items: Iterable[Item]) -> str:
    """SHA-256 of one baseline's canonical ranking scores, to post before unblinding.

    Uses the same validation and canonical form as ``evaluate_baseline``, so the
    digest a caller posts is the one ``evaluate_baseline`` asks
    ``verify_posted_baseline_hash`` to confirm. Input order does not change it; a
    changed score, item or baseline does.
    """
    condition, _, _, scores = _baseline_inputs(decisions, items)
    return hashlib.sha256(_baseline_canonical(condition, scores)).hexdigest()


def evaluate_baseline(
    decisions: Iterable[BaselineDecision],
    items: Iterable[Item],
    load_labels: Callable[[], Iterable[Label | UnscoredLabel]],
    *,
    verify_posted_baseline_hash: Callable[[str], bool] | None = None,
) -> dict[str, Any]:
    """One row of the baseline table (OPEN-08, protocol §4.2): AUROC of the
    baseline's ranking score against the binary outcome, and nothing else.

    ``decisions`` are one baseline's results for every item: B0
    ``DrivingForceDecision`` (score ``-dE_ev_per_atom``) or B0-T
    ``TemperatureRatioDecision`` (score: the ratio). Thresholds and ``reacts``
    are not used. Nothing maps a decision to ``p_react`` or ``Category``, so no
    Brier score, category accuracy or coverage is reported. An undetermined
    decision (a missing input, carrying its ``missing_evidence`` flag) is listed
    under ``undetermined``, counted in ``n``, never imputed, and left out of the
    AUROC, as is an item with no outcome to score (OPEN-12).

    ``verify_posted_baseline_hash`` must return the literal True for the scores
    digest (see ``baseline_scores_sha256``) or ``EvaluationLockedError`` is
    raised and labels are never loaded.
    """
    condition, item_map, by_id, scores = _baseline_inputs(decisions, items)
    split, source = _split_and_source(item_map)
    digest = hashlib.sha256(_baseline_canonical(condition, scores)).hexdigest()
    _verify_posted(digest, verify_posted_baseline_hash, "baseline scores")
    labels = _load_labels(load_labels, set(item_map), "baseline decisions")
    undetermined = [
        {"item_id": item_id, "review_flags": [flag.reason.value for flag in by_id[item_id].review_flags]}
        for item_id, score in scores.items() if score is None
    ]
    scored = []
    for item_id, score in scores.items():
        label = labels[item_id]
        if score is not None and label is not None:
            scored.append((score, label.reacted))
    return {
        "condition": condition,
        "ranking_score": BASELINE_RANKING_SCORES[condition],
        "scores_sha256": digest,
        "commitment": (
            "scores_sha256 (canonical JSON of the baseline, its ranking score and every item's score) "
            "was verified as posted by verify_posted_baseline_hash before labels were loaded"
        ),
        "split": split,
        "source": source,
        "n": len(scores),
        "n_determined": len(scores) - len(undetermined),
        "n_undetermined": len(undetermined),
        "n_unclassified_or_null": sum(label is None for label in labels.values()),
        "n_scored": len(scored),
        "auroc": _auroc(scored),
        "undetermined": undetermined,
        "not_reported": (
            "Brier, four-class accuracy and coverage: baselines are not mapped to p_react or Category "
            "(protocol §4.2, OPEN-08)"
        ),
    }
