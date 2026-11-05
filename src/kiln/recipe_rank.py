"""A learned, interpretable ranking for the recipe finder, fitted on published recipes.

The thermodynamic screen alone ranks precursor pairs worse than random against what chemists
actually use (dev MRR 0.60 vs 0.70 random on targets with several fully computed candidates): it
favours energetic, gas-releasing precursors (peroxides, hydroxides) that labs rarely choose. This
module scores each candidate with a few physical and practical features and a pairwise logistic
model (numpy, L2), fitted only on the benchmark's dev split, tuned by cross-validation inside dev
(folds by chemical system), and checked once on test.

Features (all known before any synthesis; nothing from the target's own published recipes):
  dG, dE_0K               reaction free-energy estimate and 0 K energy, eV/atom
  no_driving_force        1 if dG >= 0
  precursor_e_hull_max    how far the less stable precursor sits above its hull, eV/atom
  n_hydroxide, n_peroxide, n_salt (N or P), n_carbonate   precursor families in the pair
  gas_per_atom            gas molecules released per reactant atom
  log_popularity_min      log(1 + how often the rarer precursor appears in published recipes),
                          counted from dev-split recipes only, leaving the scored target out
  below_tammann, volatile number of the corresponding screen flags
  n_oxide                 plain oxides in the pair
  melts_below_T, decomposes_below_T   precursors whose melting or decomposition point (from the
                          precursor table) is below the furnace temperature
  T_over_Tmelt_min        furnace temperature over the lower precursor melting point, in kelvin
                          (0.5 when neither is known)
"""
from __future__ import annotations

import csv
import json
import lzma
import math
import re
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
from pymatgen.analysis.phase_diagram import PhaseDiagram
from pymatgen.core import Composition

from kiln import recipe
from kiln import recipe_benchmark as rb

FEATURES = ("dG", "dE_0K", "no_driving_force", "precursor_e_hull_max", "n_hydroxide", "n_peroxide",
            "n_salt", "n_carbonate", "gas_per_atom", "log_popularity_min", "below_tammann", "volatile",
            "n_oxide", "melts_below_T", "decomposes_below_T", "T_over_Tmelt_min")
PEROXIDES = {"BaO2", "SrO2", "CaO2", "Li2O2", "Na2O2", "ZnO2", "MgO2"}


def family_counts(*formulas: str) -> dict[str, int]:
    def fam(f: str) -> str:
        c = Composition(f)
        els = {e.symbol for e in c.elements}
        if Composition(f).reduced_formula in PEROXIDES:
            return "peroxide"
        if "C" in els and "O" in els:
            return "carbonate"
        if "N" in els or "P" in els:
            return "salt"
        if "H" in els:
            return "hydroxide"
        return "oxide"
    fams = Counter(fam(f) for f in formulas)
    return {"n_hydroxide": fams["hydroxide"], "n_peroxide": fams["peroxide"],
            "n_salt": fams["salt"], "n_carbonate": fams["carbonate"]}


@lru_cache(maxsize=512)
def precursor_e_hull(formula: str, cache_dir: str) -> float:
    """The precursor's own distance above the hull of its chemical system (0 for a stable phase)."""
    own = {e.symbol for e in Composition(formula).elements}
    for system in recipe.cached_systems(cache_dir):
        if own <= set(system.split("-")):
            entries = [e for e in recipe._energies(system, cache_dir) if
                       {x.symbol for x in e.composition.elements} <= own]
            entry = recipe._lowest(entries, formula)
            if entry is not None:
                return float(PhaseDiagram(entries).get_e_above_hull(entry))
    return 0.0


def popularity(source: Path = rb.SOURCE, split: str = "dev") -> dict[str, Counter]:
    """Per target, how often each precursor appears in published recipes of `split` targets.
    Returned per target so the scored target's own recipes can be left out."""
    reactions = json.load(lzma.open(source, "rt", encoding="utf-8"))["reactions"]
    per_target: dict[str, Counter] = {}
    for r in reactions:
        if not rb._simple(r["target"]):
            continue
        t = rb.reduced(r["target"]["material_formula"])
        if t is None or rb.split_of(t) != split:
            continue
        counts = per_target.setdefault(t, Counter())
        for p in r["precursors"]:
            if rb._simple(p) and (f := rb.reduced(p["material_formula"])):
                counts[f] += 1
    return per_target


def leave_out(pop: dict[str, Counter], target: str) -> Counter:
    total = Counter()
    for t, c in pop.items():
        if t != target:
            total.update(c)
    return total


@lru_cache(maxsize=4)
def _table_rows(table: str) -> dict[str, dict[str, float | None]]:
    def num(v: str) -> float | None:
        try:
            return float(v)
        except (TypeError, ValueError):
            return None
    with Path(table).open(encoding="utf-8-sig", newline="") as fh:
        return {r["formula"].strip(): {"melt": num(r.get("melting_point_c")), "dec": num(r.get("decomposes_at_c"))}
                for r in csv.DictReader(fh)}


def thermal(*args) -> dict[str, float]:
    """thermal(*precursors, temperature_c, table)."""
    *formulas, temperature_c, table = args
    rows = _table_rows(table)
    got = [rows.get(f, {"melt": None, "dec": None}) for f in formulas]
    melts = [r["melt"] for r in got if r["melt"] is not None]
    return {"melts_below_T": float(sum(m < temperature_c for m in melts)),
            "decomposes_below_T": float(sum(r["dec"] is not None and r["dec"] < temperature_c for r in got)),
            "T_over_Tmelt_min": (temperature_c + 273.15) / (min(melts) + 273.15) if melts else 0.5}


def features(c: recipe.Candidate, b: recipe.Balanced, counts: Counter, cache_dir: str,
             temperature_c: float, table: str) -> dict[str, float]:
    precs = c.precursors
    gas_out = sum(n for g, n in b.gases.items() if n > 0)
    atoms = sum(k * Composition(f).num_atoms for k, f in zip(b.coeffs, precs))
    fam = family_counts(*precs)
    return {
        "dG": c.dG, "dE_0K": c.dE_mp_ev_per_atom, "no_driving_force": float(c.dG >= 0),
        "precursor_e_hull_max": max(precursor_e_hull(f, cache_dir) for f in precs),
        **{k: float(v) for k, v in fam.items()},
        "gas_per_atom": gas_out / atoms if atoms else 0.0,
        "log_popularity_min": math.log1p(min(counts[rb.reduced(f)] for f in precs)),
        "below_tammann": float(any("Tammann" in f for f in c.flags)),
        "volatile": float(any("volatile" in f for f in c.flags)),
        "n_oxide": float(len(precs) - sum(fam.values())),
        **thermal(*precs, temperature_c, table),
    }


@dataclass
class Group:
    target: str
    system: str
    X: np.ndarray          # candidates x features
    hit: np.ndarray        # 1 for a published pair
    pairs: list[tuple[str, str]]


def groups(items: list[dict], pop: dict[str, Counter], cache_dir: Path,
           table: Path = recipe.DEFAULT_TABLE, hull_targets: bool = False) -> list[Group]:
    """One group per benchmark target with at least two fully computed candidates and a hit.
    By default only targets Materials Project has (as the ranker was fitted); with hull_targets=True
    only those it lacks, screened with the hull-energy estimate."""
    out = []
    pool = recipe._formulas(table)
    for item in items:
        counts = leave_out(pop, item["target"])
        balanced = {(pa, pb): b for pa, pb, b in recipe.candidate_pairs(item["target"], pool)}
        r = recipe.find(item["target"], item["temperature_c"], n_check=0, cache_dir=cache_dir, table=table,
                        routes="pairs")
        cands = [c for c in r.candidates if c.status == "ok" and c.dG is not None
                 and c.target_from_hull == hull_targets]
        hits = {tuple(p) for p in item["pairs"]}
        pairs = [tuple(sorted((c.precursor_a, c.precursor_b))) for c in cands]
        y = np.array([p in hits for p in pairs], dtype=float)
        if len(cands) < 2 or not y.any():
            continue
        X = np.array([[features(c, balanced[(c.precursor_a, c.precursor_b)], counts, str(cache_dir),
                                item["temperature_c"], str(table))[f]
                       for f in FEATURES] for c in cands])
        system = "-".join(sorted(e.symbol for e in Composition(item["target"]).elements))
        out.append(Group(item["target"], system, X, y, pairs))
    return out


def fit(gs: list[Group], l2: float, iters: int = 400, lr: float = 0.1) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Pairwise logistic ranking: a published pair should score above each unpublished one.
    Returns (weights, feature mean, feature scale) on standardized features."""
    allx = np.vstack([g.X for g in gs])
    mu, sd = allx.mean(0), allx.std(0)
    sd[sd == 0] = 1.0
    diffs = []
    for g in gs:
        Z = (g.X - mu) / sd
        for i in np.flatnonzero(g.hit):
            for j in np.flatnonzero(g.hit == 0):
                diffs.append(Z[i] - Z[j])
    D = np.array(diffs)
    w = np.zeros(D.shape[1])
    for _ in range(iters):   # gradient descent on mean log-loss of sigma(D w) + l2 |w|^2
        s = 1 / (1 + np.exp(-(D @ w)))
        grad = -(D * (1 - s)[:, None]).mean(0) + 2 * l2 * w
        w -= lr * grad
    return w, mu, sd


def mrr(gs: list[Group], score) -> float:
    total = 0.0
    for g in gs:
        order = np.argsort(-score(g))
        total += 1.0 / (1 + int(np.flatnonzero(g.hit[order])[0]))
    return total / len(gs) if gs else float("nan")


def model_score(w, mu, sd):
    return lambda g: ((g.X - mu) / sd) @ w


def cross_validate(gs: list[Group], l2s=(0.0, 0.01, 0.03, 0.1, 0.3), k: int = 5) -> dict[float, float]:
    """MRR per L2 strength, folds by chemical system (stable hash)."""
    import hashlib
    fold = {g.system: int(hashlib.sha256(g.system.encode()).hexdigest(), 16) % k for g in gs}
    out = {}
    for l2 in l2s:
        scores = []
        for f in range(k):
            train = [g for g in gs if fold[g.system] != f]
            test = [g for g in gs if fold[g.system] == f]
            if not test or not train:
                continue
            w, mu, sd = fit(train, l2)
            scores.append((mrr(test, model_score(w, mu, sd)), len(test)))
        out[l2] = sum(s * n for s, n in scores) / sum(n for _, n in scores)
    return out


RANKER_PATH = Path(__file__).resolve().parents[2] / "data" / "recipe-ranker.json"


class Ranker:
    """A fitted model: weights on standardized FEATURES plus the popularity counts it was given."""

    def __init__(self, weights, mu, sd, counts: Counter, features=FEATURES, meta: dict | None = None):
        self.w, self.mu, self.sd = np.asarray(weights), np.asarray(mu), np.asarray(sd)
        self.counts, self.features, self.meta = counts, tuple(features), meta or {}

    def score(self, c: recipe.Candidate, b: recipe.Balanced, cache_dir: str, temperature_c: float,
              table: str) -> float:
        f = features(c, b, self.counts, cache_dir, temperature_c, table)
        x = np.array([f[k] for k in self.features])
        return float(((x - self.mu) / self.sd) @ self.w)

    def save(self, path: Path = RANKER_PATH) -> None:
        Path(path).write_text(json.dumps({
            "features": list(self.features), "weights": self.w.tolist(), "mean": self.mu.tolist(),
            "scale": self.sd.tolist(), "popularity": dict(self.counts.most_common()), "meta": self.meta,
        }, indent=1), encoding="utf-8")

    @classmethod
    def load(cls, path: Path = RANKER_PATH) -> "Ranker | None":
        if not Path(path).is_file():
            return None
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(d["weights"], d["mean"], d["scale"], Counter(d["popularity"]), d["features"], d.get("meta"))
