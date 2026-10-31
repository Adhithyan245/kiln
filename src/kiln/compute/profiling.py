"""Turn tier profiling measurements into a proposed price list and per-pair budget (Task 4).

Input is the summary `python -m kiln.compute.profile` writes (median and p90 GPU-seconds per tier
over uncached runs). Output is protocol/prices_proposal.json for Hemanath to freeze at code freeze.
This module proposes; it never freezes anything.

Pricing rules (plan Section 5.2):
- One compute unit = the median GPU-seconds of single_point.
- A GPU tier costs its median GPU-seconds in units, never below the floor.
- cached_lookup uses no GPU but costs the floor: caching must never make a condition cheaper.
- decomposition_reeval costs the sum of what it uses: two Materials Project reaction evaluations
  (as given, then decomposed), plus any GPU time it measured.

Per-pair budget: exactly one worthwhile escalation path (cached_lookup -> single_point ->
bounded_relaxation, plus one decomposition_reeval), so an agent can't run everything on every pair
and has to choose. Night 2 fit: the worst case (every item spends its whole budget) against the
GPU hours available; a second budget level fits only if a full second run also fits.

    python -m kiln.compute.profiling --summary results/profiling/<run>.json --hours 11 --workers 1
"""
from __future__ import annotations

import argparse
import json
import math
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from kiln.schemas import ComputeTier

__all__ = ["night2_fit", "propose", "propose_budget", "propose_prices"]

PROPOSAL_PATH = Path("protocol") / "prices_proposal.json"
FLOOR_UNITS = 0.1
ESCALATION_PATH = [ComputeTier.cached_lookup, ComputeTier.single_point, ComputeTier.bounded_relaxation,
                   ComputeTier.decomposition_reeval]
HELDOUT_ITEMS, CONDITIONS, SEEDS = 369, 4, 3       # plan Sections 4.1 and 6
RULES = [
    "1 compute unit = median single_point GPU-seconds",
    "GPU tiers: median GPU-seconds in units, never below the floor",
    "cached_lookup: the floor (caching never makes a condition cheaper)",
    "decomposition_reeval: two MP reaction evaluations (2 x floor) plus any measured GPU time",
    "budget per pair: one escalation path (cached_lookup + single_point + bounded_relaxation + decomposition_reeval)",
    "second budget level: only if a full second main run also fits Night 2",
]


def _round(units: float) -> float:
    return float(f"{units:.2g}") if units >= 1 else round(units, 2)


def propose_prices(tiers: Mapping[str, Mapping[str, Any]], floor: float = FLOOR_UNITS) -> dict[str, float]:
    """Compute-unit price per tier from the profiler's per-tier stats."""
    sp = (tiers.get(ComputeTier.single_point.value) or {}).get("median_gpu_seconds")
    if not sp or sp <= 0:
        raise ValueError("need a positive single_point median_gpu_seconds to define one compute unit")

    def gpu_units(tier: ComputeTier) -> float:
        median = (tiers.get(tier.value) or {}).get("median_gpu_seconds") or 0.0
        return median / sp

    if (tiers.get(ComputeTier.bounded_relaxation.value) or {}).get("median_gpu_seconds") is None:
        raise ValueError("bounded_relaxation was not profiled")
    return {
        ComputeTier.cached_lookup.value: floor,
        ComputeTier.single_point.value: 1.0,
        ComputeTier.bounded_relaxation.value: _round(max(floor, gpu_units(ComputeTier.bounded_relaxation))),
        ComputeTier.decomposition_reeval.value: _round(2 * floor + gpu_units(ComputeTier.decomposition_reeval)),
    }


def propose_budget(prices: Mapping[str, float]) -> float:
    """Units for one full escalation path per pair."""
    return _round(sum(prices[t.value] for t in ESCALATION_PATH))


def night2_fit(single_point_median_s: float, budget_units: float, *, hours: float, workers: int = 1,
               items: int = HELDOUT_ITEMS, conditions: int = CONDITIONS, seeds: int = SEEDS,
               margin: float = 0.7, tier_p90_s: Mapping[str, float] | None = None) -> dict[str, Any]:
    """GPU hours for the main run against the time available (only `margin` of it is planned for,
    leaving room for retries and the night runner).

    Worst case: every item, condition and seed spends its full budget on fresh calculations.
    With the result cache: identical calculations are computed once (every request is still
    charged in full), and a pair's tier request is the same in every condition and seed, so each
    pair needs at most one real calculation per tier; timed at the p90 GPU-seconds."""
    per_item_s = budget_units * single_point_median_s
    needed_h = items * conditions * seeds * per_item_s / 3600
    usable_h = hours * workers * margin
    out = {
        "worst_case_gpu_seconds_per_item": round(per_item_s, 2),
        "main_run_worst_case_gpu_hours": round(needed_h, 2),
        "usable_gpu_hours": round(usable_h, 2),
        "main_run_fits": needed_h <= usable_h,
        "second_budget_level_fits": 2 * needed_h <= usable_h,
        "assumptions": f"{items} held-out items x {conditions} conditions x {seeds} seeds; {hours} h x {workers} "
                       f"GPU worker(s), {int(margin * 100)}% of it planned for",
    }
    if tier_p90_s:
        cached_h = items * math.fsum(v for v in tier_p90_s.values() if v) / 3600
        out |= {"main_run_with_cache_gpu_hours_p90": round(cached_h, 2),
                "main_run_fits_with_cache": cached_h <= usable_h}
    return out


def propose(summary: Mapping[str, Any], *, hours: float, workers: int = 1, floor: float = FLOOR_UNITS,
            source: str = "", items: int = HELDOUT_ITEMS) -> dict[str, Any]:
    tiers = summary["tiers"]
    prices = propose_prices(tiers, floor)
    budget = propose_budget(prices)
    sp = float(tiers[ComputeTier.single_point.value]["median_gpu_seconds"])
    p90 = {t: float(s.get("p90_gpu_seconds") or 0.0) for t, s in tiers.items()}
    fit = night2_fit(sp, budget, hours=hours, workers=workers, items=items, tier_p90_s=p90)
    return {
        "status": "PROPOSAL (Adhi, compute science). Hemanath freezes prices and budget in protocol.md at code freeze.",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "measured_on": {"host": summary.get("host"), "machine": summary.get("machine"), "source": source},
        "compute_unit": f"median single_point GPU-seconds = {sp} s",
        "tier_prices": prices,
        "max_compute_units_per_item": budget,
        "night2": fit,
        "measurements": {t: dict(s) for t, s in tiers.items()},
        "rules": RULES,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m kiln.compute.profiling")
    parser.add_argument("--summary", type=Path, required=True, help="output of python -m kiln.compute.profile")
    parser.add_argument("--hours", type=float, required=True, help="GPU hours available for Night 2")
    parser.add_argument("--workers", type=int, default=1, help="GPU workers in Night 2 (GB10 + Brev)")
    parser.add_argument("--floor", type=float, default=FLOOR_UNITS)
    parser.add_argument("--items", type=int, default=HELDOUT_ITEMS, help="held-out items in the main run")
    parser.add_argument("--out", type=Path, default=PROPOSAL_PATH)
    args = parser.parse_args(argv)
    summary = json.loads(args.summary.read_text(encoding="utf-8"))
    proposal = propose(summary, hours=args.hours, workers=args.workers, floor=args.floor,
                       source=args.summary.as_posix(), items=args.items)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(proposal, indent=2), encoding="utf-8")
    print(json.dumps({k: proposal[k] for k in ("compute_unit", "tier_prices", "max_compute_units_per_item", "night2")},
                     indent=2))
    print(f"saved {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
