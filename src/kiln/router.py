"""Escalation router: from the run logs, when does a GPU calculation change Kiln's answer?

Post-study analysis; not part of the pre-registered evaluation. Label-free: the target is whether
the MACE energy would change Kiln's own call under the frozen scoring rules (the reaction energy on
the other side of the rules' -0.05 eV/atom driving-force threshold), never whether that call was
right. `moved_toward_label` in the logs is derived from labels and is never read here.

Per pair, from the logged results (identical across runs, since calculations are cached):
  cheap evidence  Materials Project reaction energy and nearest near-hull competitor (cached_lookup)
  GPU evidence    MACE single point and, when run, bounded relaxation reaction energies

A router decides from the cheap evidence alone which pairs get a single point. It is scored on the
pairs whose single point is in the logs; pairs it would escalate that were never computed are
counted as unknown, not as caught. Choosing the router on the same pairs it is scored on is
optimistic, so `cross_validate` holds out every pair containing one precursor at a time.

    python -m kiln.router                     # runs-h100/
    python -m kiln.router --runs runs-h100 --json
"""
from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

__all__ = ["PairRecord", "Policy", "Score", "cross_validate", "evaluate", "load_pairs", "relaxation_effect"]

ROOT = Path(__file__).resolve().parents[2]
RULES = ROOT / "protocol" / "scoring_rules.json"
FROZEN_SETTINGS = ROOT / "protocol" / "frozen_settings.json"
NO_COMPETITOR = float("inf")
EDGE = 1e-9
WINDOWS = (0.0, 0.005, 0.01, 0.015, 0.02, 0.03, 0.05)          # |dE - threshold|, eV/atom
COMPETITOR_CUTS = (0.0, 0.005, 0.01, 0.02, 0.03, 0.05, 0.1)    # competitor e_hull, eV/atom


def driving_force_threshold(path: Path = RULES) -> float:
    """The reaction-energy threshold of the frozen category rules (no_driving_force at >= it)."""
    rules = json.loads(Path(path).read_text(encoding="utf-8"))["rules"]["category_rules"]
    for rule in rules:
        for cond in rule["when"]:
            if cond["subject"] == "reaction_energy_ev_per_atom" and cond["op"] == "ge":
                return float(cond["threshold"])
    raise ValueError("no reaction-energy threshold in the frozen scoring rules")


@dataclass(frozen=True)
class PairRecord:
    precursor_a: str
    precursor_b: str
    dE_mp: float                       # cached_lookup reaction energy, eV/atom
    competitor_e_hull: float           # nearest near-hull competitor on the join, inf if none
    dE_single_point: float | None = None
    dE_relaxation: float | None = None

    def flips(self, threshold: float) -> bool | None:
        """Would the single point put the pair on the other side of the threshold? None: not computed."""
        if self.dE_single_point is None:
            return None
        return (self.dE_mp >= threshold) != (self.dE_single_point >= threshold)


def load_pairs(runs: Path) -> list[PairRecord]:
    """One record per precursor pair from every run's compute log (ok or cached results only)."""
    found: dict[tuple[str, str], dict[str, dict]] = {}
    for log in sorted(Path(runs).glob("*/compute_requests.jsonl")):
        for line in log.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            if r.get("status") not in ("ok", "cached") or not r.get("result"):
                continue
            key = tuple(sorted((r["inputs"]["precursor_a"], r["inputs"]["precursor_b"])))
            found.setdefault(key, {}).setdefault(r["tier"], r["result"])
    out = []
    for (a, b), tiers in sorted(found.items()):
        lookup = tiers.get("cached_lookup")
        if lookup is None or lookup.get("dE_ev_per_atom") is None:
            continue
        comp = lookup.get("competitor_e_hull_ev_per_atom")
        sp, rx = tiers.get("single_point"), tiers.get("bounded_relaxation")
        out.append(PairRecord(a, b, float(lookup["dE_ev_per_atom"]),
                              NO_COMPETITOR if comp is None else float(comp),
                              None if sp is None else float(sp["dE_ev_per_atom"]),
                              None if rx is None else float(rx["dE_ev_per_atom"])))
    return out


@dataclass(frozen=True)
class Policy:
    """Escalate to a single point when the cheap energy is within `window` of the threshold, or a
    competitor phase sits within `competitor` eV/atom of the hull. Never relax."""
    window: float
    competitor: float

    def escalates(self, p: PairRecord, threshold: float) -> bool:
        # EDGE: a pair exactly on a window edge stays in despite float rounding
        return abs(p.dE_mp - threshold) <= self.window + EDGE or p.competitor_e_hull <= self.competitor + EDGE


@dataclass(frozen=True)
class Score:
    escalated: int
    caught: int          # known flips the policy escalates
    known_flips: int
    unknown: int         # escalated pairs with no logged single point
    units: float         # lookups for every pair plus a single point per escalation

    @property
    def recall(self) -> float | None:
        return self.caught / self.known_flips if self.known_flips else None


def evaluate(pairs: Sequence[PairRecord], policy: Policy, threshold: float, prices: dict[str, float]) -> Score:
    esc = [p for p in pairs if policy.escalates(p, threshold)]
    flips = [p for p in pairs if p.flips(threshold)]
    return Score(len(esc), sum(1 for p in esc if p.flips(threshold)), len(flips),
                 sum(1 for p in esc if p.dE_single_point is None),
                 round(len(pairs) * prices["cached_lookup"] + len(esc) * prices["single_point"], 3))


def _grid() -> Iterable[Policy]:
    return (Policy(w, c) for w in WINDOWS for c in COMPETITOR_CUTS)


def best_policy(pairs: Sequence[PairRecord], threshold: float, prices: dict[str, float]) -> Policy:
    """The cheapest grid policy that catches every known flip in `pairs` (ties: the narrower rule)."""
    scored = [(evaluate(pairs, pol, threshold, prices), pol) for pol in _grid()]
    full = [(s, pol) for s, pol in scored if s.caught == s.known_flips]
    return min(full, key=lambda t: (t[0].escalated, t[1].window + t[1].competitor))[1]


def cross_validate(pairs: Sequence[PairRecord], threshold: float, prices: dict[str, float]) -> dict:
    """Hold out every pair containing one precursor, choose the policy on the rest, score it on
    the held-out pairs. A pair is held out twice (once per precursor); totals count each fold."""
    precursors = sorted({f for p in pairs for f in (p.precursor_a, p.precursor_b)})
    caught = flips = escalated = held = 0
    for f in precursors:
        test = [p for p in pairs if f in (p.precursor_a, p.precursor_b)]
        train = [p for p in pairs if f not in (p.precursor_a, p.precursor_b)]
        s = evaluate(test, best_policy(train, threshold, prices), threshold, prices)
        caught, flips, escalated, held = caught + s.caught, flips + s.known_flips, escalated + s.escalated, held + len(test)
    return {"folds": len(precursors), "held_out_pairs": held, "escalated": escalated,
            "escalation_rate": escalated / held if held else None,
            "caught": caught, "known_flips": flips, "recall": caught / flips if flips else None}


def relaxation_effect(pairs: Sequence[PairRecord], threshold: float) -> dict:
    """What the 30-unit relaxation added over the 1-unit single point, where both were logged."""
    both = [p for p in pairs if p.dE_single_point is not None and p.dE_relaxation is not None]
    diffs = [abs(p.dE_relaxation - p.dE_single_point) for p in both]
    changed = sum(1 for p in both if (p.dE_single_point >= threshold) != (p.dE_relaxation >= threshold))
    return {"pairs": len(both), "category_changed": changed,
            "max_abs_diff_ev_per_atom": max(diffs) if diffs else None,
            # p_react's logistic weight on the reaction energy is -20 per eV/atom
            "max_logit_shift": 20 * max(diffs) if diffs else None}


def _units_by_tier(runs: Path, condition: str) -> dict[str, float]:
    totals: dict[str, float] = {}
    logs = sorted(Path(runs).glob(f"{condition}-*/compute_requests.jsonl"))
    for log in logs:
        for line in log.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            totals[r["tier"]] = totals.get(r["tier"], 0.0) + float(r.get("compute_units") or 0.0)
    return {k: v / len(logs) for k, v in totals.items()} if logs else {}


def report(runs: Path) -> dict:
    threshold = driving_force_threshold()
    prices = json.loads(FROZEN_SETTINGS.read_text(encoding="utf-8"))["tier_prices"]
    pairs = load_pairs(runs)
    frozen_rule = [p for p in pairs if (1e-6 < abs(p.dE_mp) <= 0.05) or (0 < p.competitor_e_hull <= 0.1)]
    chosen = best_policy(pairs, threshold, prices)
    return {
        "runs": str(runs), "pairs": len(pairs), "threshold_ev_per_atom": threshold,
        "with_single_point": sum(p.dE_single_point is not None for p in pairs),
        "known_flips": sum(bool(p.flips(threshold)) for p in pairs),
        "c4_units_per_run_by_tier": _units_by_tier(runs, "C4"),
        "relaxation_effect": relaxation_effect(pairs, threshold),
        "frozen_rule_escalations": len(frozen_rule),
        "in_sample_policy": {**asdict(chosen), **asdict(evaluate(pairs, chosen, threshold, prices))},
        "cross_validated": cross_validate(pairs, threshold, prices),
    }


def _print(r: dict) -> None:
    c4 = r["c4_units_per_run_by_tier"]
    total = sum(c4.values())
    rx = r["relaxation_effect"]
    pol, cv = r["in_sample_policy"], r["cross_validated"]
    print(f"{r['pairs']} pairs in {r['runs']}; {r['with_single_point']} have a MACE single point; "
          f"{r['known_flips']} of those flip Kiln's call at {r['threshold_ev_per_atom']} eV/atom.")
    if total:
        print(f"\nC4 spent {total:,.0f} units per run; relaxations were "
              f"{c4.get('bounded_relaxation', 0) / total:.1%} of it.")
    print(f"Relaxation vs single point on {rx['pairs']} pairs: {rx['category_changed']} category changes, "
          f"largest energy change {rx['max_abs_diff_ev_per_atom']:.4f} eV/atom "
          f"(p_react logit shift {rx['max_logit_shift']:.2f}).")
    print(f"\nThe study's escalation rule sent {r['frozen_rule_escalations']} of {r['pairs']} pairs to the GPU.")
    print(f"Cheapest rule catching every known flip (in sample): window {pol['window']} OR competitor "
          f"<= {pol['competitor']} eV/atom -> {pol['escalated']} pairs, {pol['caught']}/{pol['known_flips']} "
          f"flips, {pol['units']:g} units for the whole set ({pol['unknown']} escalations never computed).")
    print(f"Cross-validated (leave one precursor out, {cv['folds']} folds): escalates "
          f"{cv['escalation_rate']:.0%} of held-out pairs and catches {cv['caught']}/{cv['known_flips']} "
          f"held-out flips ({cv['recall']:.0%}).")
    print("\nLabel-free: a flip is a change in Kiln's own call, not a correct call. Only pairs the study's "
          "rule escalated have a single point, so flips elsewhere are unobserved.")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m kiln.router", description=__doc__.split("\n")[0])
    ap.add_argument("--runs", type=Path, default=ROOT / "runs-h100")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    r = report(args.runs)
    print(json.dumps(r, indent=2, default=str) if args.json else "", end="" if not args.json else "\n")
    if not args.json:
        _print(r)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
