"""Tier prices and cache keys, and compute accounting for finished runs.

Prices are read from RunConfig.tier_prices and never defaulted: a tier without a frozen
price cannot be charged, so it cannot be run.

Accounting reads a run folder (runs/<run_id>/: config.json, compute_requests.jsonl,
predictions.jsonl, board/artifacts.jsonl) and reports totals per request, pair and condition,
checks them against the request log exactly, and builds the compute-allocation table that
compares conditions. It needs no labels: `moved_toward_label` is read only where the evaluator
has already filled it in after unblinding.

`changed_prediction` is not in the log (the client writes each request before the caller knows
the score after it), so `replay_changes` derives it after the run: for each request, the fixed
provisional score on the item's accepted evidence just before and just after the artifact that
first used the request. It needs the frozen scoring rules (OPEN-05) and an agreed definition of
"changed" (OPEN-17), so it is off unless the caller passes both.

    python -m kiln.compute.accounting runs/C4-s0 runs/C1-s0 --out results/compute_allocation.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from kiln.schemas import (
    Artifact, Category, ComputeRequest, ComputeStatus, ComputeTier, Item, Prediction, RunConfig,
    VerifierStatus,
)

__all__ = ["MissingPrice", "RunData", "allocation_row", "allocation_table", "cache_key", "category_flip",
           "load_run", "pair_totals", "price", "reconcile", "replay_changes", "to_markdown"]


class MissingPrice(Exception):
    """RunConfig.tier_prices has no usable price for a tier."""


def price(config: RunConfig, tier: ComputeTier) -> float:
    value = config.tier_prices.get(tier.value)
    if value is None:
        raise MissingPrice(f"no frozen price for tier {tier.value!r} in RunConfig.tier_prices")
    if not math.isfinite(value) or value < 0:
        raise MissingPrice(f"invalid price for tier {tier.value!r}: {value}")
    return float(value)


def cache_key(tier: ComputeTier, inputs: dict[str, Any], settings: dict[str, Any]) -> str:
    """sha256 of canonical JSON of (tier, inputs, settings); independent of dict order."""
    canonical = json.dumps(
        {"tier": tier.value, "inputs": inputs, "settings": settings},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("ascii")).hexdigest()


# ---------- reading a run ----------

@dataclass(frozen=True)
class RunData:
    run_dir: Path
    config: RunConfig
    requests: list[ComputeRequest]
    predictions: list[Prediction]

    @property
    def run_id(self) -> str:
        return self.config.run_id


def _jsonl(path: Path) -> list[str]:
    return [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.exists() else []


def load_run(run_dir: str | Path) -> RunData:
    run_dir = Path(run_dir)
    config = RunConfig.model_validate_json((run_dir / "config.json").read_text(encoding="utf-8"))
    requests = [ComputeRequest.model_validate_json(line) for line in _jsonl(run_dir / "compute_requests.jsonl")]
    predictions = [Prediction.model_validate_json(line) for line in _jsonl(run_dir / "predictions.jsonl")]
    return RunData(run_dir, config, requests, predictions)


# ---------- totals and reconciliation ----------

def _close(a: float, b: float) -> bool:
    return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9)


def _empty_total() -> dict[str, Any]:
    return {"compute_units": 0.0, "gpu_seconds": 0.0, "requests": 0, "by_tier": {t.value: 0 for t in ComputeTier}}


def pair_totals(run: RunData) -> dict[str, dict[str, Any]]:
    """Per item: compute units charged, GPU-seconds, request count and requests per tier."""
    out: dict[str, dict[str, Any]] = {}
    for r in run.requests:
        t = out.setdefault(r.item_id, _empty_total())
        t["compute_units"] = math.fsum([t["compute_units"], r.compute_units])
        t["gpu_seconds"] = math.fsum([t["gpu_seconds"], r.gpu_seconds])
        t["requests"] += 1
        t["by_tier"][r.tier.value] += 1
    for p in run.predictions:
        out.setdefault(p.item_id, _empty_total())
    return out


def reconcile(run: RunData) -> list[str]:
    """Every mismatch between the request log and the predictions' costs. Empty means exact."""
    problems: list[str] = []
    ids = [r.request_id for r in run.requests]
    if len(ids) != len(set(ids)):
        problems.append("duplicate request ids in compute_requests.jsonl")
    for r in run.requests:
        if r.run_id != run.run_id:
            problems.append(f"{r.request_id}: belongs to run {r.run_id}, not {run.run_id}")
        if not math.isfinite(r.compute_units) or r.compute_units < 0:
            problems.append(f"{r.request_id}: invalid compute_units {r.compute_units}")
    predicted = {p.item_id: p for p in run.predictions}
    if len(predicted) != len(run.predictions):
        problems.append("more than one prediction for an item")
    for item_id, t in pair_totals(run).items():
        p = predicted.get(item_id)
        if p is None:
            problems.append(f"{item_id}: {t['requests']} compute requests but no prediction")
        elif not _close(p.cost.compute_units, t["compute_units"]):
            problems.append(f"{item_id}: prediction charged {p.cost.compute_units} units, request log totals {t['compute_units']}")
    if not _close(math.fsum(p.cost.compute_units for p in run.predictions), math.fsum(r.compute_units for r in run.requests)):
        problems.append("run total: predictions' compute units differ from the request log total")
    return problems


# ---------- allocation table ----------

def _quantile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(q * (len(ordered) - 1))))]


def _share(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def allocation_row(run: RunData, changes: Mapping[str, Mapping[str, Any]] | None = None) -> dict[str, Any]:
    """One row of the compute-allocation table. `changes` is replay_changes output, if run."""
    units = [t["compute_units"] for t in pair_totals(run).values()]
    total = math.fsum(units)
    budget = run.config.max_compute_units_per_item
    reqs = run.requests
    changed = ({rid: bool(c["changed"]) for rid, c in changes.items()} if changes is not None
               else {r.request_id: bool(r.changed_prediction) for r in reqs if r.changed_prediction is not None})
    moved = {r.request_id: bool(r.moved_toward_label) for r in reqs if r.moved_toward_label is not None}
    n_changed = sum(changed.values())
    changed_and_moved_known = [rid for rid in moved if changed.get(rid)]
    return {
        "run_id": run.run_id, "condition": run.config.condition, "seed": run.config.seed, "model": run.config.model,
        "items": len(units),
        "requests": len(reqs),
        "compute_units_total": total,
        "units_per_pair_mean": statistics.fmean(units) if units else None,
        "units_per_pair_median": statistics.median(units) if units else None,
        "units_per_pair_p90": _quantile(units, 0.9) if units else None,
        "budget_share_mean": (statistics.fmean(units) / budget) if units and budget else None,
        "requests_by_tier": {t.value: sum(r.tier == t for r in reqs) for t in ComputeTier},
        "cache_hit_share": _share(sum(r.status == ComputeStatus.cached for r in reqs), len(reqs)),
        "failed": sum(r.status == ComputeStatus.failed for r in reqs),
        "not_converged": sum(r.status == ComputeStatus.not_converged for r in reqs),
        "changed_prediction_known": len(changed),
        "changed_prediction_share": _share(n_changed, len(changed)),
        "changed_per_unit": (n_changed / total) if changed and total else None,
        "changed_source": "replay" if changes is not None else "log",
        "moved_toward_label_known": len(moved),
        "moved_toward_label_share_of_changed": _share(sum(moved[rid] for rid in changed_and_moved_known),
                                                      len(changed_and_moved_known)),
        "reconciliation_problems": reconcile(run),
    }


def allocation_table(runs: Iterable[RunData]) -> list[dict[str, Any]]:
    return sorted((allocation_row(r) for r in runs), key=lambda row: (row["condition"], row["seed"], row["run_id"]))


def _fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.3g}"
    return str(value)


def to_markdown(rows: Sequence[Mapping[str, Any]]) -> str:
    tiers = [t.value for t in ComputeTier]
    head = ["condition", "seed", "items", "units/pair (median)", "budget share", "requests",
            *[f"{t} reqs" for t in tiers], "cache hits", "failed", "not conv.", "changed share", "moved toward lab"]
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for r in rows:
        cells = [r["condition"], r["seed"], r["items"], r["units_per_pair_median"], r["budget_share_mean"],
                 r["requests"], *[r["requests_by_tier"][t] for t in tiers], r["cache_hit_share"], r["failed"],
                 r["not_converged"], r["changed_prediction_share"], r["moved_toward_label_share_of_changed"]]
        lines.append("| " + " | ".join(_fmt(c) for c in cells) + " |")
    return "\n".join(lines) + "\n"


# ---------- replay: did each request change the provisional prediction? ----------

Provisional = Callable[[Item, list[Artifact]], tuple[float, Category]]
ChangedRule = Callable[[tuple[float, Category], tuple[float, Category]], bool]


def category_flip(before: tuple[float, Category], after: tuple[float, Category]) -> bool:
    """One candidate OPEN-17 definition: the four-class category changed. Not a default."""
    return before[1] != after[1]


def _artifacts(run_dir: Path) -> list[Artifact]:
    """Latest state of each artifact, in first-posted order (the board is append-only)."""
    latest: dict[str, Artifact] = {}
    for line in _jsonl(run_dir / "board" / "artifacts.jsonl"):
        a = Artifact.model_validate_json(line)
        latest[a.artifact_id] = a
    return list(latest.values())


def replay_changes(run: RunData, items: Mapping[str, Item], provisional: Provisional,
                   changed: ChangedRule) -> dict[str, dict[str, Any]]:
    """For each request: provisional (p_react, category) on the item's accepted evidence just before
    and just after the first accepted artifact that cites it. A request no accepted artifact uses
    changed nothing. Deterministic and label-free; `provisional` must be the frozen scoring rules'
    and `changed` the agreed OPEN-17 definition."""
    out: dict[str, dict[str, Any]] = {}
    by_item: dict[str, list[Artifact]] = {}
    for a in _artifacts(run.run_dir):
        by_item.setdefault(a.item_id, []).append(a)
    for item_id, artifacts in by_item.items():
        item = items[item_id]
        accepted: list[Artifact] = []
        for a in sorted(artifacts, key=lambda x: x.created_at):
            if a.verifier != VerifierStatus.accepted:
                continue
            before = provisional(item, list(accepted))
            accepted.append(a)
            after = provisional(item, list(accepted))
            for rid in a.compute_requests:
                out.setdefault(rid, {"before": before, "after": after, "changed": bool(changed(before, after))})
    for r in run.requests:
        out.setdefault(r.request_id, {"before": None, "after": None, "changed": False})
    return out


# ---------- command line ----------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m kiln.compute.accounting")
    parser.add_argument("runs", nargs="+", type=Path, help="run folders (runs/<run_id>)")
    parser.add_argument("--out", type=Path, default=Path("results") / "compute_allocation.json")
    args = parser.parse_args(argv)
    rows = allocation_table(load_run(r) for r in args.runs)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    table = to_markdown(rows)
    args.out.with_suffix(".md").write_text(table, encoding="utf-8")
    print(table)
    bad = [(r["run_id"], p) for r in rows for p in r["reconciliation_problems"]]
    for run_id, problem in bad:
        print(f"RECONCILIATION {run_id}: {problem}")
    print(f"saved {args.out} and {args.out.with_suffix('.md')}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
