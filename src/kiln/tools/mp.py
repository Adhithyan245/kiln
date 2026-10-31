"""Materials Project phases near the hull, cached per chemical system.

Online only in `fetch_chemsys` (Night 1, needs MP_API_KEY). Everything else runs offline from
cache/mp/<chemsys>.json, which holds MP's GGA/GGA+U entries with the MP2020 corrections MP already
applied (`entry.correction`). Energies are eV/atom.

Agents never call this module directly for energies: the compute service's `cached_lookup` and
`decomposition_reeval` tiers do, so every lookup is charged and logged (AGENTS.md rule 8).

    python -m kiln.tools.mp fetch --all-pairs      # every chemical system in dev + held-out items
    python -m kiln.tools.mp fetch --precursors-file precursors.txt   # no ledger on this host
    python -m kiln.tools.mp fetch --chemsys Ca-O-Ti
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from pymatgen.analysis.interface_reactions import InterfacialReactivity
from pymatgen.analysis.phase_diagram import PhaseDiagram
from pymatgen.core import Composition
from pymatgen.entries.computed_entries import ComputedEntry, ComputedStructureEntry

__all__ = [
    "CACHE_DIR", "MissingCache", "ReactionEnergy",
    "chemsys_for", "fetch_chemsys", "load_entries", "candidates", "reaction_energy",
]

CACHE_DIR = Path("cache") / "mp"


class MissingCache(LookupError):
    """The chemical system has not been fetched; run `python -m kiln.tools.mp fetch` first."""


@dataclass(frozen=True)
class ReactionEnergy:
    dE_ev_per_atom: float     # most negative interface reaction energy along the a-b tie line
    mixing_ratio: float       # pymatgen InterfacialReactivity x at that kink (per-atom fraction of a)
    products: str             # reduced formulas joined by "+", sorted


def chemsys_for(*formulas: str) -> str:
    elements = {el.symbol for f in formulas for el in Composition(f).elements}
    return "-".join(sorted(elements))


def _path(chemsys: str, cache_dir: Path) -> Path:
    return Path(cache_dir) / f"{chemsys}.json"


def fetch_chemsys(chemsys: str, *, cache_dir: Path = CACHE_DIR, api_key: str | None = None) -> Path:
    """Download every MP entry in the chemical system (and its subsystems). Skips if cached."""
    path = _path(chemsys, cache_dir)
    if path.exists():
        return path
    from mp_api.client import MPRester  # online-only dependency, imported lazily

    key = api_key or os.environ.get("MP_API_KEY")
    if not key:
        raise RuntimeError("MP_API_KEY is not set")
    with MPRester(key) as mpr:
        entries = mpr.get_entries_in_chemsys(
            chemsys.split("-"), additional_criteria={"thermo_types": ["GGA_GGA+U"]},
        )
    _write_entries(path, entries)
    return path


def _str_keys(value: object) -> object:
    """Dict keys as plain strings, recursively. MP returns entry.data["oxidation_states"] keyed by
    pymatgen Element objects, which pymatgen's own as_dict() can't serialise."""
    if isinstance(value, dict):
        return {str(k): _str_keys(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_str_keys(v) for v in value]
    return value


def _write_entries(path: Path, entries: list[ComputedEntry]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    for e in entries:
        e.data = _str_keys(e.data)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            # default=str: MP also returns entry_id as an EntryID object rather than a string.
            json.dump([e.as_dict() for e in entries], f, default=str)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def load_entries(chemsys: str, *, cache_dir: Path = CACHE_DIR) -> list[ComputedEntry]:
    path = _path(chemsys, cache_dir)
    if not path.exists():
        raise MissingCache(f"no cached Materials Project entries for {chemsys} at {path}")
    out: list[ComputedEntry] = []
    for d in json.loads(path.read_text(encoding="utf-8")):
        cls = ComputedStructureEntry if "structure" in d else ComputedEntry
        out.append(cls.from_dict(d))
    return out


def candidates(
    formula_a: str,
    formula_b: str,
    *,
    ehull_max_ev_per_atom: float = 0.100,
    cache_dir: Path = CACHE_DIR,
) -> list[ComputedEntry]:
    """Phases in the pair's chemical system within ehull_max of the hull (elements included)."""
    entries = load_entries(chemsys_for(formula_a, formula_b), cache_dir=cache_dir)
    pd = PhaseDiagram(entries)
    return [e for e in entries if pd.get_e_above_hull(e) <= ehull_max_ev_per_atom + 1e-9]


def reaction_energy(formula_a: str, formula_b: str, entries: list[ComputedEntry]) -> ReactionEnergy:
    """Most negative closed-system interface reaction energy between a and b, eV/atom.

    Uses the reactants' own entry energies (use_hull_energy=False), so a metastable precursor
    keeps its real energy. A result of 0 means no reaction is favoured along the tie line.
    """
    pd = PhaseDiagram(entries)
    ir = InterfacialReactivity(Composition(formula_a), Composition(formula_b), pd,
                               norm=True, use_hull_energy=False)
    _, x, energy, reaction, _ = min(ir.get_kinks(), key=lambda k: k[2])
    products = "+".join(sorted(c.reduced_formula for c in reaction.products))
    return ReactionEnergy(dE_ev_per_atom=float(energy), mixing_ratio=float(x), products=products)


def _all_pair_chemsys() -> list[str]:
    from kiln.data import load_items  # agent-visible items only; never labels

    systems = {chemsys_for(i.precursor_a, i.precursor_b)
               for split in ("dev", "heldout") for i in load_items(split)}
    return sorted(systems)


def pair_chemsys_from_precursors(formulas: list[str]) -> list[str]:
    """Chemical systems of every pair of the given precursors (no ledger needed on this host)."""
    unique = sorted(set(formulas))
    return sorted({chemsys_for(a, b) for i, a in enumerate(unique) for b in unique[i + 1:]})


def _read_precursors(path: Path) -> list[str]:
    lines = [l.split("#", 1)[0].strip() for l in path.read_text(encoding="utf-8").splitlines()]
    return [l for l in lines if l]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m kiln.tools.mp")
    sub = parser.add_subparsers(dest="cmd", required=True)
    fetch = sub.add_parser("fetch", help="download chemical systems into the cache (resumable)")
    group = fetch.add_mutually_exclusive_group(required=True)
    group.add_argument("--all-pairs", action="store_true", help="pairs from kiln.data (needs the ledger here)")
    group.add_argument("--precursors-file", type=Path,
                       help="one precursor formula per line; fetches every pair's chemical system")
    group.add_argument("--chemsys", action="append")
    fetch.add_argument("--cache-dir", type=Path, default=CACHE_DIR)
    args = parser.parse_args(argv)

    if args.all_pairs:
        systems = _all_pair_chemsys()
    elif args.precursors_file:
        systems = pair_chemsys_from_precursors(_read_precursors(args.precursors_file))
    else:
        systems = sorted(set(args.chemsys))
    failed = 0
    for n, chemsys in enumerate(systems, 1):
        try:
            fetch_chemsys(chemsys, cache_dir=args.cache_dir)
            print(f"[{n}/{len(systems)}] {chemsys} ok")
        except Exception as exc:  # report and carry on; a rerun resumes from the cache
            failed += 1
            print(f"[{n}/{len(systems)}] {chemsys} FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
    print(f"{len(systems) - failed}/{len(systems)} chemical systems cached")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
