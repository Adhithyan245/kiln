"""Benchmark the recipe finder against published solid-state syntheses.

Source: the text-mined solid-state synthesis dataset (Kononova et al., Sci. Data 6, 203, 2019,
doi:10.1038/s41597-019-0224-1; CC BY 4.0; github.com/CederGroupHub/text-mined-synthesis_public).
Download `solid-state_dataset_20200713.json.xz` into cache/textmined/ (not committed).

One benchmark item per target compound: every published two-precursor recipe for it whose
precursors are both in the pool, and the median furnace temperature of those recipes. The recipe
finder ranks all pairs from the pool that balance to the target; a "hit" is a published pair.
What chemists chose is a convention as well as chemistry, so this measures agreement with
practice, not the best possible route. Targets are split 50/50 by chemical system (a stable
hash), so a tuning choice made on `dev` is checked on `test` without near-duplicate targets.

    python -m kiln.recipe_benchmark build            # cache/textmined -> data/recipe-benchmark.jsonl
    python -m kiln.recipe_benchmark score --split dev
"""
from __future__ import annotations

import argparse
import hashlib
import json
import lzma
import random
import statistics
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from pymatgen.core import Composition

from kiln import recipe

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "cache" / "textmined" / "solid-state_dataset_20200713.json.xz"
BENCHMARK = ROOT / "data" / "recipe-benchmark.jsonl"
DEFAULT_TEMP_C = 900.0


def reduced(formula: str) -> str | None:
    try:
        c = Composition(formula)
    except Exception:
        return None
    return c.reduced_formula if c.num_atoms > 0 else None


def _simple(material: dict) -> bool:
    """A single, fully specified compound: no variables, additives or mixtures."""
    return (not material.get("amounts_vars") and not material.get("elements_vars")
            and not material.get("additives") and len(material.get("composition") or []) == 1)


def _max_temperature(reaction: dict) -> float | None:
    temps = []
    for op in reaction.get("operations") or []:
        if op.get("type") != "HeatingOperation":
            continue
        for t in (op.get("conditions") or {}).get("heating_temperature") or []:
            if t.get("units") in ("°C", "C") and t.get("max_value") is not None:
                temps.append(float(t["max_value"]))
    temps = [t for t in temps if 100 <= t <= 2000]
    return max(temps) if temps else None


def split_of(target: str) -> str:
    """dev or test, from a stable hash of the target's chemical system."""
    system = "-".join(sorted(el.symbol for el in Composition(target).elements))
    return "dev" if int(hashlib.sha256(system.encode()).hexdigest(), 16) % 2 == 0 else "test"


def build(source: Path = SOURCE, pool: list[str] | None = None) -> list[dict]:
    """Benchmark items from the dataset, restricted to recipes whose precursors are both in `pool`."""
    pool = pool if pool is not None else recipe._formulas(recipe.DEFAULT_TABLE)
    by_reduced = {reduced(f): f for f in pool}
    reactions = json.load(lzma.open(source, "rt", encoding="utf-8"))["reactions"]
    items: dict[str, dict] = {}
    for r in reactions:
        if len(r["precursors"]) != 2 or not _simple(r["target"]) or not all(_simple(p) for p in r["precursors"]):
            continue
        target = reduced(r["target"]["material_formula"])
        names = [by_reduced.get(reduced(p["material_formula"])) for p in r["precursors"]]
        if target is None or None in names or names[0] == names[1] or target in by_reduced:
            continue
        item = items.setdefault(target, {"target": target, "pairs": set(), "temperatures": [], "dois": set()})
        item["pairs"].add(tuple(sorted(names)))
        if (t := _max_temperature(r)) is not None:
            item["temperatures"].append(t)
        item["dois"].add(r.get("doi") or "")
    out = []
    for target, item in sorted(items.items()):
        temps = item["temperatures"]
        out.append({"target": target, "split": split_of(target),
                    "pairs": sorted(list(p) for p in item["pairs"]),
                    "temperature_c": statistics.median(temps) if temps else DEFAULT_TEMP_C,
                    "temperature_known": bool(temps), "n_recipes": len(item["dois"])})
    return out


def load(path: Path = BENCHMARK) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


@dataclass
class Result:
    target: str
    n_candidates: int
    rank: int | None          # 1-based rank of the best published pair among Kiln's candidates
    random_expected_rr: float  # expected reciprocal rank of the best published pair under a random order


def _expected_random_rr(n: int, k: int) -> float:
    """E[1/rank of the first of k hits] when n candidates are shuffled uniformly."""
    if not k or not n:
        return 0.0
    # P(first hit at position r) = C(n-r, k-1) / C(n, k)
    from math import comb
    return sum(comb(n - r, k - 1) / comb(n, k) / r for r in range(1, n - k + 2))


def score_item(item: dict, finder=recipe.find, **kwargs) -> Result:
    kwargs.setdefault("routes", "pairs")   # the benchmark holds two-precursor recipes
    r = finder(item["target"], item["temperature_c"], n_check=0, **kwargs)
    ranked = [tuple(sorted((c.precursor_a, c.precursor_b))) for c in r.candidates]
    hits = {tuple(p) for p in item["pairs"]}
    found = [i + 1 for i, p in enumerate(ranked) if p in hits]
    return Result(item["target"], len(ranked), found[0] if found else None,
                  _expected_random_rr(len(ranked), sum(p in hits for p in ranked)))


def summarize(results: list[Result]) -> dict:
    covered = [r for r in results if r.rank is not None]
    n = len(covered)
    multi = [r for r in covered if r.n_candidates > 1]
    def frac(pred, rows):
        return round(sum(1 for r in rows if pred(r)) / len(rows), 4) if rows else None
    return {
        "targets": len(results), "covered": n,
        "top1": frac(lambda r: r.rank == 1, covered), "top3": frac(lambda r: r.rank <= 3, covered),
        "mrr": round(sum(1 / r.rank for r in covered) / n, 4) if n else None,
        "random_mrr": round(sum(r.random_expected_rr for r in covered) / n, 4) if n else None,
        # Targets with a single candidate are trivially top-1; the real test is the rest.
        "multi_candidate": len(multi),
        "multi_top1": frac(lambda r: r.rank == 1, multi),
        "multi_mrr": round(sum(1 / r.rank for r in multi) / len(multi), 4) if multi else None,
        "multi_random_mrr": round(sum(r.random_expected_rr for r in multi) / len(multi), 4) if multi else None,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m kiln.recipe_benchmark", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--source", type=Path, default=SOURCE)
    b.add_argument("--out", type=Path, default=BENCHMARK)
    s = sub.add_parser("score")
    s.add_argument("--split", choices=("dev", "test", "all"), default="dev")
    s.add_argument("--cache-dir", type=Path, default=ROOT / "data" / "mp-energies")
    s.add_argument("--limit", type=int)
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if args.cmd == "build":
        items = build(args.source)
        args.out.write_text("".join(json.dumps(i, separators=(",", ":")) + "\n" for i in items), encoding="utf-8")
        by = defaultdict(int)
        for i in items:
            by[i["split"]] += 1
        print(f"wrote {len(items)} targets to {args.out} ({dict(by)})")
        return 0
    items = [i for i in load() if args.split == "all" or i["split"] == args.split][: args.limit]
    results = [score_item(i, cache_dir=args.cache_dir) for i in items]
    print(json.dumps(summarize(results), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
