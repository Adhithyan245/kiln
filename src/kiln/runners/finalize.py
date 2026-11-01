"""OPEN-23: give every item a prediction before the hash, without inventing evidence.

After run_conditions, an item that crashed (failed_items.jsonl) or was never reached has no line in
predictions.jsonl. This step scores each such item on empty evidence, with a missing_evidence flag
saying why, through the run's own scorer. Its cost is what its logged compute requests were charged,
so accounting still reconciles. Each finalized item is recorded in finalized_items.jsonl, and a count
per run is printed.

    python -m kiln.runners.finalize --split heldout --items-file ~/kiln-items.jsonl --runs-dir runs
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from filelock import FileLock

from kiln.schemas import ComputeRequest, Cost, Item, ReviewFlag, ReviewReason, RunConfig

__all__ = ["finalize_run", "main"]


def _scorer(config: dict):
    if "scorer" in config.get("stub_parts", []):
        from kiln.runners.stubs import StubScorer

        return StubScorer
    from kiln.scoring.score import frozen_engine

    return frozen_engine


def finalize_run(run_dir: Path, items: list[Item]) -> int:
    """Score every item of `items` that has no prediction in `run_dir`. Returns how many."""
    from kiln.runners.conditions import _append_jsonl, _atomic_write, _lines, _read_requests

    config = json.loads((run_dir / "config.json").read_text(encoding="utf-8"))
    cfg = RunConfig.model_validate(config["run_config"])
    with FileLock(str(run_dir / ".run.lock")):          # never alongside a runner still working on it
        pred_path, cost_path = run_dir / "predictions.jsonl", run_dir / "cost.json"
        done = {json.loads(line)["item_id"] for line in _lines(pred_path)}
        failed = {}
        for line in _lines(run_dir / "failed_items.jsonl"):
            row = json.loads(line)
            failed[row["item_id"]] = row["error"]
        missing = [i for i in sorted(items, key=lambda i: i.item_id) if i.item_id not in done]
        if not missing:
            return 0
        scorer = _scorer(config)(cfg)
        requests = _read_requests(run_dir / "compute_requests.jsonl")
        costs = json.loads(cost_path.read_text(encoding="utf-8")) if cost_path.exists() else {}
        for item in missing:
            reqs: list[ComputeRequest] = [r for r in requests if r.item_id == item.item_id]
            why = f"crashed: {failed[item.item_id]}" if item.item_id in failed else "never reached"
            flag = ReviewFlag(reason=ReviewReason.missing_evidence,
                              detail=f"No prediction from the run ({why}); scored on empty evidence (OPEN-23).")
            cost = Cost(compute_units=sum(r.compute_units for r in reqs), gpu_seconds=sum(r.gpu_seconds for r in reqs))
            prediction = scorer.score(item, [], reqs, [flag], cost=cost)
            _append_jsonl(pred_path, prediction.model_dump(mode="json"))
            _append_jsonl(run_dir / "finalized_items.jsonl", {"item_id": item.item_id, "reason": why,
                                                               "compute_requests": len(reqs)})
            costs[item.item_id] = prediction.cost.model_dump()
        _atomic_write(cost_path, json.dumps(costs, indent=1))
        return len(missing)


def main(argv: list[str] | None = None) -> int:
    from kiln.runners.conditions import _load_items

    parser = argparse.ArgumentParser(prog="python -m kiln.runners.finalize")
    parser.add_argument("--split", choices=["dev", "heldout"], required=True)
    parser.add_argument("--items-file", type=Path)
    parser.add_argument("--runs-dir", type=Path, default=Path("runs"))
    args = parser.parse_args(argv)
    items = _load_items(args.split, args.items_file)
    runs = sorted(p.parent for p in args.runs_dir.glob(f"*-{args.split}/config.json"))
    if not runs:
        raise SystemExit(f"no {args.split} runs under {args.runs_dir}")
    for run_dir in runs:
        print(f"{run_dir.name}: finalized {finalize_run(run_dir, items)} items with no prediction")
    return 0


if __name__ == "__main__":
    sys.exit(main())
