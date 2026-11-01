"""Preflight canary: prove the compute backend is real before a night starts.

Runs one cached_lookup and one single_point on the first item, through the same ComputeClient a real
run uses (zero prices, its own run folder under <runs-dir>/_canary/), and fails unless the lookup cites
the Materials Project and the single point comes from a real MLIP (not "stub"). A stub backend would
have failed this in seconds on Night 2 (protocol/amendments.md, 2026-11-01).

    python -m kiln.runners.canary --split heldout --items-file ~/kiln-items.jsonl --runs-dir runs
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from kiln.budget import Budget
from kiln.schemas import ComputeStatus, ComputeTier

__all__ = ["check", "main"]

USABLE = (ComputeStatus.ok, ComputeStatus.cached)


def check(lookup, single) -> list[str]:
    """Problems with the two canary requests; empty means the backend is real."""
    problems = []
    if lookup.status not in USABLE or lookup.result.get("source") != "materials_project":
        problems.append(f"cached_lookup: status {lookup.status.value}, source {lookup.result.get('source')!r} "
                        "(want materials_project)")
    model = single.result.get("model")
    if single.status not in USABLE or not model or model == "stub" or single.result.get("stub"):
        problems.append(f"single_point: status {single.status.value}, model {model!r} (want a real MLIP, not stub)")
    if single.status == ComputeStatus.ok and single.gpu_seconds <= 0 and single.settings.get("device", "cuda") != "cpu":
        problems.append("single_point: computed with 0 GPU-seconds on a GPU device")
    return problems


def main(argv: list[str] | None = None) -> int:
    from kiln.compute.backends import backend_from_env
    from kiln.compute.cache import ResultCache
    from kiln.compute.client import ComputeClient
    from kiln.compute.profile import load_tier_settings, profile_config
    from kiln.runners.conditions import _load_items, require_real_backend

    parser = argparse.ArgumentParser(prog="python -m kiln.runners.canary")
    parser.add_argument("--split", choices=["dev", "heldout"], required=True)
    parser.add_argument("--items-file", type=Path)
    parser.add_argument("--runs-dir", type=Path, default=Path("runs"))
    args = parser.parse_args(argv)

    backend = require_real_backend()
    item = sorted(_load_items(args.split, args.items_file), key=lambda i: i.item_id)[0]
    run_id = f"canary-{time.strftime('%Y%m%dT%H%M%S')}"
    config = profile_config(run_id)
    client = ComputeClient(args.runs_dir / "_canary" / run_id, config, backend_from_env(),
                           ResultCache(Path("cache") / "compute"), load_tier_settings())
    budget = Budget(config)
    inputs = {"precursor_a": item.precursor_a, "precursor_b": item.precursor_b}
    lookup = client.request(item, "thermo", ComputeTier.cached_lookup, "Canary: the backend must be real.", inputs, budget)
    single = client.request(item, "thermo", ComputeTier.single_point, "Canary: the backend must be real.", inputs, budget)
    problems = check(lookup, single)
    for p in problems:
        print(f"CANARY FAILED: {p}", file=sys.stderr)
    if problems:
        return 1
    print(f"canary ok: backend {backend}; {item.item_id} lookup from materials_project, single point "
          f"{single.result.get('model')} ({single.status.value}, {single.gpu_seconds:.1f} GPU-s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
