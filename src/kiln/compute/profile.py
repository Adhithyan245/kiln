"""Profile the tiers on development pairs, and pre-warm the cache for Night 1.

Every request goes through ComputeClient (AGENTS.md rule 8) under its own run, with zero tier
prices because prices are what this measures. Output: median and p90 GPU-seconds per tier over
real (uncached) runs, status counts, and each tier's median relative to single_point. It proposes
no prices; choosing them is CJ's call, recorded in the protocol (OPEN-02, OPEN-03).

Profiling and pre-warm runs are tagged condition "N1" until the protocol names them (OPEN-21).

    python -m kiln.compute.profile --pairs 20 --seed 0          # profile a dev sample
    python -m kiln.compute.profile --prewarm                     # every dev + held-out pair
"""
from __future__ import annotations

import argparse
import json
import platform
import random
import statistics
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from kiln.budget import Budget, BudgetExceeded
from kiln.compute.backends import backend_from_env
from kiln.compute.cache import ResultCache
from kiln.compute.client import ComputeClient
from kiln.schemas import ComputeRequest, ComputeStatus, ComputeTier, Item, RunConfig

__all__ = ["profile_config", "load_tier_settings", "run_profile", "summarize", "main"]

SETTINGS_FILE = Path("env") / "gb10" / "tier_settings.json"
REFERENCE_TIER = ComputeTier.single_point


def profile_config(run_id: str) -> RunConfig:
    return RunConfig(
        run_id=run_id, condition="N1", seed=0, model="none",
        max_tool_calls_per_item=10**6, max_tokens_per_item=0, max_compute_units_per_item=10**6,
        tier_prices={t.value: 0.0 for t in ComputeTier},
    )


def load_tier_settings(path: Path = SETTINGS_FILE) -> dict[ComputeTier, dict[str, Any]]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return {ComputeTier(k): dict(v) for k, v in raw.items() if not k.startswith("_")}


def run_profile(items: Sequence[Item], tiers: Sequence[ComputeTier], client: ComputeClient,
                budget_for: Callable[[Item], Budget], progress: Callable[[str], None] = print) -> list[ComputeRequest]:
    out: list[ComputeRequest] = []
    for n, item in enumerate(items, 1):
        budget = budget_for(item)
        for tier in tiers:
            try:
                req = client.request(item, "single", tier, f"Profiling {tier.value} on a development pair.",
                                     {"precursor_a": item.precursor_a, "precursor_b": item.precursor_b}, budget)
            except BudgetExceeded:
                raise  # zero prices: this would be a bug, never skip silently
            out.append(req)
            progress(f"[{n}/{len(items)}] {item.item_id} {tier.value}: {req.status.value} {req.gpu_seconds:.2f}s")
    return out


def _quantile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(q * (len(ordered) - 1))))]


def summarize(requests: Sequence[ComputeRequest]) -> dict[str, Any]:
    tiers: dict[str, Any] = {}
    for tier in ComputeTier:
        rows = [r for r in requests if r.tier == tier]
        if not rows:
            continue
        timed = [r.gpu_seconds for r in rows if r.status != ComputeStatus.cached]
        tiers[tier.value] = {
            "n": len(rows),
            "status": {s.value: sum(r.status == s for r in rows) for s in ComputeStatus},
            "median_gpu_seconds": statistics.median(timed) if timed else None,
            "p90_gpu_seconds": _quantile(timed, 0.9) if timed else None,
        }
    ref = (tiers.get(REFERENCE_TIER.value) or {}).get("median_gpu_seconds")
    for stats in tiers.values():
        med = stats["median_gpu_seconds"]
        stats[f"median_relative_to_{REFERENCE_TIER.value}"] = med / ref if ref and med is not None else None
    return {"host": platform.node(), "machine": platform.machine(), "tiers": tiers,
            "note": "Measurements only. Prices and the per-item budget are set by CJ (OPEN-02/03)."}


def _items(split: str) -> list[Item]:
    from kiln.data import load_items  # agent-visible items only; never labels

    return load_items(split)  # type: ignore[arg-type]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m kiln.compute.profile")
    parser.add_argument("--pairs", type=int, default=20, help="dev pairs to sample (ignored with --prewarm)")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--tiers", nargs="+", default=[t.value for t in ComputeTier
                                                       if t != ComputeTier.decomposition_reeval])
    parser.add_argument("--prewarm", action="store_true", help="run every dev and held-out pair")
    parser.add_argument("--settings", type=Path, default=SETTINGS_FILE)
    parser.add_argument("--runs-dir", type=Path, default=Path("runs"))
    parser.add_argument("--cache-dir", type=Path, default=Path("cache") / "compute")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    if args.prewarm:
        items, run_id = _items("dev") + _items("heldout"), "night1-prewarm"
    else:
        dev = _items("dev")
        items = random.Random(args.seed).sample(dev, min(args.pairs, len(dev)))
        run_id = f"profile-{platform.node() or 'host'}-s{args.seed}"
    config = profile_config(run_id)
    client = ComputeClient(args.runs_dir / run_id, config, backend_from_env(), ResultCache(args.cache_dir),
                           load_tier_settings(args.settings))
    if not client.healthy():
        print("compute backend is not healthy; check KILN_COMPUTE_BACKEND / KILN_COMPUTE_URL", file=sys.stderr)
        return 2
    requests = run_profile(items, [ComputeTier(t) for t in args.tiers], client, lambda _: Budget(config))
    summary = summarize(requests)
    out = args.out or Path("results") / "profiling" / f"{run_id}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary["tiers"], indent=2))
    print(f"wrote {out}")
    failed = sum(r.status in (ComputeStatus.failed, ComputeStatus.not_converged) for r in requests)
    print(f"{failed} of {len(requests)} requests failed or did not converge (logged, not hidden)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
