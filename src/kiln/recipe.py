"""Recipe finder: name a target compound and a furnace temperature, get precursor pairs ranked.

Post-hackathon feature. It reuses the study's tools and prices but is NOT part of the pre-registered
evaluation, and its rankings are unvalidated: treat them as a triage list, not a prediction.

Cheapest first, with the frozen prices (protocol/frozen_settings.json):
1. Candidates: every pair of the precursor table whose elements cover the target's, where any
   extra element leaves as a gas (C as CO2, H as H2O, N as N2; O is exchanged with air as O2).
2. Screen, one cached_lookup per pair (Materials Project cache): the balanced reaction energy to
   the target, how far the target sits above the hull, what the pair's deepest reaction makes
   instead, the Tammann check, and decomposition or volatility below the furnace temperature.
3. Check, one single_point per pair (MACE): only leading candidates whose reaction energies sit
   within the energy margin of another leading candidate, where a better energy could change the
   order. A clear leader costs no GPU at all.

Ranking uses dG, an estimate at the furnace temperature: the 0 K reaction energy plus -T*S for each
gas molecule released (or +T*S for O2 taken from the air), with standard molar entropies at 1 atm
from NIST-JANAF. Solid entropies and heat capacities are left out. Pairs only.

    python -m kiln.recipe BaTiO3 --temp 900
    python -m kiln.recipe BaTiO3 --temp 900 --check 3 --json
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import re
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from itertools import combinations
from pathlib import Path
from typing import Any

import numpy as np
from pymatgen.analysis.phase_diagram import PhaseDiagram
from pymatgen.core import Composition
from pymatgen.entries.computed_entries import ComputedEntry

from kiln.tools import mp
from kiln.tools.precursors import DEFAULT_TABLE, props
from kiln.tools.tammann import tammann_c

__all__ = ["Balanced", "Candidate", "Recipe", "balance", "candidate_pairs", "check", "find", "screen"]

FROZEN_SETTINGS = Path(__file__).resolve().parents[2] / "protocol" / "frozen_settings.json"
# The gas each extra element leaves as. O2 is special: it may be released or taken from the air.
LEAVES_AS = {"C": "CO2", "H": "H2O", "N": "N2"}
TOL = 1e-6
SHALLOW_EV_PER_ATOM = 0.03   # a stable target this close to its neighbours' hull gets a byproduct note
# Standard molar entropy at 1 atm, J/(mol K), NIST-JANAF, at 298.15, 500, 1000 and 1500 K.
GAS_ENTROPY_K = (298.15, 500.0, 1000.0, 1500.0)
GAS_ENTROPY = {"CO2": (213.8, 234.9, 269.3, 292.2), "O2": (205.1, 220.7, 243.6, 258.1),
               "H2O": (188.8, 206.5, 232.7, 250.8), "N2": (191.6, 206.7, 228.2, 241.9)}
J_PER_MOL_PER_EV = 96485.33


def gas_ts_ev(gas: str, temperature_c: float) -> float:
    """T*S of one gas molecule at the furnace temperature, eV (entropy interpolated, held flat
    outside 298-1500 K)."""
    t = temperature_c + 273.15
    s = float(np.interp(t, GAS_ENTROPY_K, GAS_ENTROPY[gas]))
    return t * s / J_PER_MOL_PER_EV


def _prices() -> tuple[dict[str, float], float]:
    frozen = json.loads(FROZEN_SETTINGS.read_text(encoding="utf-8"))
    return frozen["tier_prices"], float(frozen["energy_margin_ev_per_atom"])


@dataclass(frozen=True)
class Balanced:
    """c1·P1 + c2·P2 + ... (+ O2 from air) -> target + gases, per formula unit of the target."""
    coeffs: tuple[float, ...]
    gases: dict[str, float]       # gas -> coefficient; a negative O2 means O2 taken from the air

    @property
    def a(self) -> float:
        return self.coeffs[0]

    @property
    def b(self) -> float:
        return self.coeffs[1] if len(self.coeffs) > 1 else 0.0

    def equation(self, pa: str, pb: str, target: str) -> str:
        return self.equation_n((pa, pb), target)

    def equation_n(self, precursors: Sequence[str], target: str) -> str:
        left = [f"{c:g} {p}" for c, p in zip(self.coeffs, precursors)]
        right = [target]
        for gas, n in self.gases.items():
            if n < -TOL:
                left.append(f"{-n:g} {gas}")
            elif n > TOL:
                right.append(f"{n:g} {gas}")
        return " + ".join(left) + " -> " + " + ".join(right)


def balance(pa: str, pb: str, target: str) -> Balanced | None:
    """Balance the pair to one formula unit of the target (see balance_n)."""
    return balance_n((pa, pb), target)


def balance_n(precursors: Sequence[str], target: str) -> Balanced | None:
    """Balance the precursors to one formula unit of the target, or None if it can't be done cleanly:
    an element the target lacks that cannot leave as a gas, a precursor that isn't needed, a gas
    that would have to be consumed (other than O2), or more than one way to balance."""
    comps, ct = [Composition(p) for p in precursors], Composition(target)
    n = len(comps)
    have = {el.symbol for c in comps for el in c.elements}
    need = {el.symbol for el in ct.elements}
    if not need <= have:
        return None
    extra = have - need
    if any(el not in LEAVES_AS and el != "O" for el in extra):
        return None
    gases = [LEAVES_AS[el] for el in sorted(extra) if el in LEAVES_AS]
    if "O" in have:
        gases.append("O2")
    species = [*comps, *(Composition(g) for g in gases)]
    elements = sorted(have)
    m = np.array([[c[el] * (1 if i < n else -1) for i, c in enumerate(species)] for el in elements], dtype=float)
    rhs = np.array([ct[el] for el in elements], dtype=float)
    if np.linalg.matrix_rank(m) < len(species):
        return None
    x, *_ = np.linalg.lstsq(m, rhs, rcond=None)
    if np.abs(m @ x - rhs).max() > 1e-8 or any(v <= TOL for v in x[:n]):
        return None
    coeffs = {g: float(round(v, 6)) for g, v in zip(gases, x[n:])}
    if any(v < -TOL for g, v in coeffs.items() if g != "O2"):
        return None
    return Balanced(tuple(float(round(v, 6)) for v in x[:n]), coeffs)


def candidate_pairs(target: str, precursors: Sequence[str]) -> list[tuple[str, str, Balanced]]:
    """Every pair that balances to the target, in table order."""
    out = []
    for pa, pb in combinations(precursors, 2):
        b = balance(pa, pb, target)
        if b is not None:
            out.append((pa, pb, b))
    return out


CARRIERS = {"O", "C", "H", "N"}   # elements a precursor may bring in and lose as gas or keep as anion


def cations(formula: str) -> set[str]:
    """The elements other than O, C, H and N: what each precursor has to supply."""
    return {el.symbol for el in Composition(formula).elements} - CARRIERS


def route_sizes(target: str) -> tuple[int, ...]:
    """How many precursors to try: one or two for a single-metal target, pairs for two metals,
    and k-1 or k precursors for k >= 3 metals (capped at 5)."""
    k = len(cations(target))
    if k == 0:
        return ()
    if k == 1:
        return (1, 2)
    if k == 2:
        return (2,)
    return (min(k, 5) - 1, min(k, 5))


MAX_COMBOS = 50_000   # balance attempts per route size before giving up on bigger recipes


def candidate_routes(target: str, precursors: Sequence[str], routes: str = "auto"
                     ) -> list[tuple[tuple[str, ...], Balanced]]:
    """Every precursor set that balances to the target. Pairs are found exactly as by
    candidate_pairs; other sizes only from precursors whose metals all appear in the target."""
    sizes = (2,) if routes == "pairs" else route_sizes(target)
    tc = cations(target)
    own = Composition(target).reduced_formula
    relevant = [p for p in precursors
                if cations(p) and cations(p) <= tc and Composition(p).reduced_formula != own]
    out: list[tuple[tuple[str, ...], Balanced]] = []
    for n in sizes:
        if n == 2:
            out += [((pa, pb), b) for pa, pb, b in candidate_pairs(target, precursors)]
            continue
        tried = 0
        for combo in combinations(relevant, n):
            if set().union(*(cations(p) for p in combo)) != tc:
                continue
            tried += 1
            if tried > MAX_COMBOS:
                break
            if (b := balance_n(combo, target)) is not None:
                out.append((combo, b))
    return out


@dataclass
class Candidate:
    precursor_a: str
    precursor_b: str
    equation: str
    status: str = "ok"                       # ok | no_mp_data | target_not_in_mp
    dE_mp_ev_per_atom: float | None = None   # 0 K reaction energy to the target, per atom of reactants
    dG_mp_ev_per_atom: float | None = None   # the same plus the gas entropy at the furnace temperature
    dG_mlip_ev_per_atom: float | None = None # dG with MACE energies, when checked
    target_e_hull_ev_per_atom: float | None = None
    target_depth_ev_per_atom: float | None = None  # phase-separation energy: < 0 means below its neighbours
    competing_phases: list[str] = field(default_factory=list)
    deepest_reaction_products: str | None = None
    flags: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    compute_units: float = 0.0
    score: float | None = None               # the learned ranker's score, when one is used
    precursors: list[str] = field(default_factory=list)   # all of them; a and b are the first two
    target_from_hull: bool = False           # target not in MP: its energy is the hull's at that composition

    def __post_init__(self) -> None:
        if not self.precursors:
            self.precursors = [p for p in (self.precursor_a, self.precursor_b) if p]

    @property
    def dG(self) -> float | None:
        return self.dG_mlip_ev_per_atom if self.dG_mlip_ev_per_atom is not None else self.dG_mp_ev_per_atom


@dataclass
class Recipe:
    target: str
    temperature_c: float
    candidates: list[Candidate]
    n_pairs_considered: int
    n_checked: int
    compute_units: float
    order_changed_by_check: bool = False

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        for c, row in zip(self.candidates, d["candidates"]):
            row["dG_ev_per_atom"] = c.dG
        return d


@lru_cache(maxsize=16)   # 16 systems: well inside a 512 MB host
def _energies(chemsys: str, cache_dir: str) -> tuple[ComputedEntry, ...]:
    """The cached entries without their crystal structures: the screen needs only energies, and
    building every structure is most of the load time. The MACE check loads full entries."""
    for base in (Path(cache_dir), *FALLBACK_DIRS):
        path = base / f"{chemsys}.json"
        if path.exists():
            rows = json.loads(path.read_text(encoding="utf-8"))
            break
        if (gz := path.with_suffix(".json.gz")).exists():   # the committed cache is gzipped
            rows = json.loads(gzip.decompress(gz.read_bytes()).decode("utf-8"))
            break
    else:
        raise mp.MissingCache(f"no cached Materials Project entries for {chemsys} in {cache_dir}")
    return tuple(ComputedEntry.from_dict({k: v for k, v in d.items() if k != "structure"}) for d in rows)


# Extra directories searched after `cache_dir`, e.g. a writable directory for systems fetched on demand.
FALLBACK_DIRS: list[Path] = []


def cached_systems(cache_dir: Path | str) -> list[str]:
    """Chemical systems in a cache directory (and FALLBACK_DIRS), plain or gzipped JSON."""
    return sorted({p.name.split(".")[0] for base in (Path(cache_dir), *FALLBACK_DIRS) if base.is_dir()
                   for p in base.iterdir() if p.name.endswith((".json", ".json.gz"))})


def has_system(chemsys: str, cache_dir: Path | str) -> bool:
    return any((base / f"{chemsys}{ext}").exists() for base in (Path(cache_dir), *FALLBACK_DIRS)
               for ext in (".json", ".json.gz"))


def missing_systems(target: str, precursors: Sequence[str], cache_dir: Path | str) -> list[str]:
    """Chemical systems the screen would need for `target` that no cache directory has."""
    return sorted({mp.chemsys_for(*combo) for combo, _ in candidate_routes(target, precursors)}
                  - {s for s in cached_systems(cache_dir)})


MP_THERMO_URL = "https://api.materialsproject.org/materials/thermo/"


def fetch_energies(chemsys: str, dst: Path, api_key: str, timeout: float = 30.0) -> Path:
    """Fetch one chemical system (all subsystems, GGA/GGA+U) from the Materials Project REST API into
    `dst` in the compact energies-only form. Same entries as mp_api's get_entries_in_chemsys, without
    the client (which hangs in server threads)."""
    import urllib.parse
    import urllib.request
    from itertools import combinations as combos
    els = sorted(chemsys.split("-"))
    subs = ["-".join(c) for n in range(1, len(els) + 1) for c in combos(els, n)]
    rows, skip = [], 0
    while True:
        query = urllib.parse.urlencode({"chemsys": ",".join(subs), "thermo_types": "GGA_GGA+U",
                                        "_fields": "entries", "_limit": 200, "_skip": skip})
        req = urllib.request.Request(f"{MP_THERMO_URL}?{query}",
                                     headers={"X-API-KEY": api_key, "User-Agent": "kiln-recipe-finder"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.load(resp)
        docs = payload.get("data", [])
        for doc in docs:
            for d in (doc.get("entries") or {}).values():
                e = ComputedEntry.from_dict({k: v for k, v in d.items() if k != "structure"})
                rows.append({"composition": e.composition.as_dict(), "energy": e.uncorrected_energy,
                             "correction": e.correction, "entry_id": str(e.entry_id)})
        skip += len(docs)
        if not docs or skip >= int(payload.get("meta", {}).get("total_doc", 0)):
            break
    dst = Path(dst)
    dst.mkdir(parents=True, exist_ok=True)
    path = dst / f"{chemsys}.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(rows, separators=(",", ":")), encoding="utf-8")
    tmp.replace(path)
    return path


def normalize_formula(text: str) -> str:
    """Repair a formula typed in the wrong case ("KMno4", "kmno4", "nacl") by splitting each run of
    letters into element symbols, changing as few letters' case as possible. A formula that already
    parses and has a lower-case letter is returned unchanged, so "Co" stays cobalt and "CO" stays
    carbon monoxide; rare elements (past Bi, noble gases) cost extra, so "BATIO3" is BaTiO3. Some
    inputs stay ambiguous ("nico3"), so callers should show the formula they used."""
    from pymatgen.core.periodic_table import Element
    text = text.strip()
    try:
        # pymatgen otherwise accepts unknown letters as dummy species. An all-capitals formula is
        # still re-read below, so "CUO" becomes CuO rather than carbon, uranium and oxygen.
        if Composition(text).valid and any(ch.islower() for ch in text):
            return text
    except Exception:
        pass
    symbols = {e.symbol for e in Element}
    # Rarely meant in a solid-state target: radioactive elements past Bi, noble gases, Tc and Pm.
    rare = {e.symbol for e in Element if e.Z > 83 or e.group == 18 or e.symbol in ("Tc", "Pm")}

    def split(run: str) -> list[str] | None:
        best: list[tuple[int, list[str]] | None] = [None] * (len(run) + 1)
        best[0] = (0, [])
        for i in range(len(run)):
            if best[i] is None:
                continue
            for n in (1, 2):
                piece = run[i:i + n]
                sym = piece[:1].upper() + piece[1:].lower()
                if len(piece) == n and sym in symbols:
                    cost = best[i][0] + sum(a != b for a, b in zip(piece, sym)) + 2 * (sym in rare)
                    if best[i + n] is None or cost < best[i + n][0]:
                        best[i + n] = (cost, best[i][1] + [sym])
        return best[-1][1] if best[-1] else None

    out = []
    for token in re.findall(r"[A-Za-z]+|[^A-Za-z]+", text):
        if token.isalpha():
            parts = split(token)
            if parts is None:
                return text
            out.append("".join(parts))
        else:
            out.append(token)
    return "".join(out)


def _lowest(entries: Sequence[ComputedEntry], formula: str) -> ComputedEntry | None:
    target = Composition(formula).reduced_formula
    matching = [e for e in entries if e.composition.reduced_formula == target]
    return min(matching, key=lambda e: e.energy_per_atom) if matching else None


def _energy_per_fu(entry: ComputedEntry, formula: str, energy_per_atom: float | None = None) -> float:
    per_atom = entry.energy_per_atom if energy_per_atom is None else energy_per_atom
    return float(per_atom) * Composition(formula).num_atoms


def _species(b: Balanced, pa: str, pb: str, target: str) -> list[tuple[str, float]]:
    return _species_n(b, (pa, pb), target)


def _species_n(b: Balanced, precursors: Sequence[str], target: str) -> list[tuple[str, float]]:
    """(formula, signed coefficient): reactants negative, products positive."""
    return [*((p, -c) for p, c in zip(precursors, b.coeffs)), (target, 1.0), *b.gases.items()]


def _reaction_energy(b: Balanced, pa: str, pb: str, target: str, per_fu: dict[str, float],
                     temperature_c: float | None = None) -> float:
    return _reaction_energy_n(b, (pa, pb), target, per_fu, temperature_c)


def _reaction_energy_n(b: Balanced, precursors: Sequence[str], target: str, per_fu: dict[str, float],
                       temperature_c: float | None = None) -> float:
    """Per atom of reactants. With a temperature, each gas term also gets -T*S (dG estimate)."""
    terms = _species_n(b, precursors, target)
    delta = sum(n * per_fu[f] for f, n in terms)
    if temperature_c is not None:
        delta -= sum(n * gas_ts_ev(g, temperature_c) for g, n in b.gases.items())
    reactant_atoms = sum(-n * Composition(f).num_atoms for f, n in terms if n < 0)
    return delta / reactant_atoms


_STABILITY: dict[tuple[str, str], tuple[float, float, tuple[str, ...]]] = {}


def _target_stability(target: str, entries: Sequence[ComputedEntry],
                      cache_dir: str) -> tuple[float, float, tuple[str, ...]]:
    """The target's e_hull, phase-separation energy and hull neighbours (the byproducts a mixture
    slightly off the target ratio, or an incomplete reaction, tends to make).

    These depend only on the target's own chemical system, which every candidate pair's cache file
    holds identically (MP fetches include subsystems), so they are computed once per target, on
    just its elements: the same values as on the pair's whole system, for a far smaller diagram."""
    key = (Composition(target).reduced_formula, cache_dir)
    if key not in _STABILITY:
        own = {el for el in Composition(target).elements}
        sub = [e for e in entries if set(e.composition.elements) <= own]
        pd = PhaseDiagram(sub)
        entry = _lowest(sub, target)
        decomp, depth = pd.get_decomp_and_phase_separation_energy(entry)
        _STABILITY[key] = (float(pd.get_e_above_hull(entry)), float(depth),
                           tuple(sorted({e.composition.reduced_formula for e in decomp} - {key[0]})))
    return _STABILITY[key]


_HULL: dict[tuple[str, str], tuple[float, tuple[str, ...]] | None] = {}


def _hull_target(target: str, entries: Sequence[ComputedEntry], cache_dir: str
                 ) -> tuple[float, tuple[str, ...]] | None:
    """For a target with no Materials Project entry (doped, non-stoichiometric, or not computed):
    the energy per formula unit of the stable phase mixture at its composition, and those phases.
    A real doped or mixed phase sits at or above this, so a driving force from it is a best case."""
    comp = Composition(target)
    key = (comp.formula, cache_dir)
    if key not in _HULL:
        own = set(comp.elements)
        sub = [e for e in entries if set(e.composition.elements) <= own]
        if not sub or {el for e in sub for el in e.composition.elements} != own:
            _HULL[key] = None
        else:
            try:
                pd = PhaseDiagram(sub)
                energy = float(pd.get_hull_energy_per_atom(comp)) * comp.num_atoms
                phases = tuple(sorted({e.composition.reduced_formula for e in pd.get_decomposition(comp)}))
                _HULL[key] = (energy, phases)
            except Exception:   # e.g. an element with no elemental reference entry
                _HULL[key] = None
    return _HULL[key]


def screen(target: str, temperature_c: float, pa: str, pb: str, b: Balanced, *,
           cache_dir: Path = mp.CACHE_DIR, table: Path = DEFAULT_TABLE, price: float = 0.1) -> Candidate:
    """The cheap tier for one pair: Materials Project energies plus the precursor table."""
    return screen_route(target, temperature_c, (pa, pb), b, cache_dir=cache_dir, table=table, price=price)


def screen_route(target: str, temperature_c: float, precursors: Sequence[str], b: Balanced, *,
                 cache_dir: Path = mp.CACHE_DIR, table: Path = DEFAULT_TABLE, price: float = 0.1) -> Candidate:
    """The cheap tier for one recipe of one or more precursors."""
    precursors = tuple(precursors)
    pair = len(precursors) == 2
    c = Candidate(precursors[0], precursors[1] if len(precursors) > 1 else "",
                  b.equation_n(precursors, target), compute_units=price, precursors=list(precursors))
    try:
        entries = list(_energies(mp.chemsys_for(*precursors), str(cache_dir)))
    except mp.MissingCache:
        c.status = "no_mp_data"
        c.flags.append("no cached Materials Project data for this " + ("pair" if pair else "recipe"))
        return c
    formulas = [f for f, _ in _species_n(b, precursors, target)]
    found = {f: _lowest(entries, f) for f in formulas}
    hull = None
    if found[target] is None:
        hull = _hull_target(target, entries, str(cache_dir))
        if hull is None:
            c.status = "target_not_in_mp"
            c.flags.append(f"{target} is not in the Materials Project data for this system")
            return c
    missing = [f for f, e in found.items() if e is None and f != target]
    if missing:
        c.status = "no_mp_data"
        c.flags.append("no Materials Project entry for " + ", ".join(missing))
        return c
    per_fu = {f: _energy_per_fu(e, f) for f, e in found.items() if e is not None}
    if hull is not None:
        per_fu[target] = hull[0]
    c.dE_mp_ev_per_atom = _reaction_energy_n(b, precursors, target, per_fu)
    c.dG_mp_ev_per_atom = _reaction_energy_n(b, precursors, target, per_fu, temperature_c)
    if hull is not None:
        c.target_from_hull = True
        c.competing_phases = [f for f in hull[1] if f != Composition(target).reduced_formula]
        c.flags.append(f"{target} is not in the Materials Project, so its energy is that of the stable phases at "
                       f"its composition ({', '.join(hull[1])}); a doped or mixed phase sits at or above it, "
                       "so this driving force is a best case")
    else:
        e_hull, depth, competing = _target_stability(target, entries, str(cache_dir))
        c.target_e_hull_ev_per_atom, c.target_depth_ev_per_atom, c.competing_phases = e_hull, depth, list(competing)
    if c.dG_mp_ev_per_atom >= -TOL:
        c.flags.append("no driving force to the target at this temperature")
    if c.target_e_hull_ev_per_atom is not None and c.target_e_hull_ev_per_atom > 0.05:
        c.flags.append(f"target is {c.target_e_hull_ev_per_atom:.3f} eV/atom above the hull (metastable)")
    depth = c.target_depth_ev_per_atom
    if depth is not None and depth <= 0 and -depth < SHALLOW_EV_PER_ATOM and c.competing_phases:
        c.notes.append(f"only {-depth * 1000:.0f} meV/atom below its neighbours "
                       f"{', '.join(c.competing_phases)}: watch for those as byproducts")
    if not c.target_from_hull and pair and not any(abs(n) > TOL for n in b.gases.values()):
        # closed system: the a-b line is the whole story
        pa, pb = precursors
        try:
            deepest = mp.reaction_energy(pa, pb, entries)
            c.deepest_reaction_products = deepest.products
            if Composition(target).reduced_formula not in deepest.products.split("+"):
                c.notes.append(f"the pair's deepest reaction makes {deepest.products}, not {target}")
        except (ValueError, IndexError):
            pass

    tammann = {}
    for f in precursors:
        p = props(f, path=table)
        if p.melting_point_c is not None:
            tammann[f] = tammann_c(p.melting_point_c)
        if p.decomposes_at_c is not None and p.decomposes_at_c <= temperature_c:
            into = f" into {p.decomposition_product}" if p.decomposition_product else ""
            c.notes.append(f"{f} decomposes{into} by {p.decomposes_at_c:g} °C, before reacting")
        if p.volatile_above_c is not None and p.volatile_above_c <= temperature_c:
            c.flags.append(f"{f} is volatile above {p.volatile_above_c:g} °C: material may be lost")
    if len(tammann) < len(precursors):
        c.notes.append("melting point missing for " + ", ".join(f for f in precursors if f not in tammann))
    if tammann and all(temperature_c < t for t in tammann.values()):
        c.flags.append("furnace is below " + ("both Tammann temperatures" if pair else
                       "the Tammann temperature" if len(precursors) == 1 else "every Tammann temperature")
                       + ": atoms may barely move")
    return c


def _rank(cands: list[Candidate]) -> list[Candidate]:
    return sorted(cands, key=lambda c: (c.status != "ok", len(c.flags),
                                        c.dG if c.dG is not None else float("inf")))


def close_calls(ranked: Sequence[Candidate], k: int, margin: float) -> list[Candidate]:
    """Leading candidates (top k, usable) whose energy is within `margin` of another leader."""
    lead = [c for c in ranked if c.status == "ok" and c.dG is not None and len(c.precursors) == 2
            and not c.target_from_hull][:k]
    return [c for c in lead if any(o is not c and abs(o.dG - c.dG) <= margin for o in lead)]


def check(c: Candidate, target: str, temperature_c: float, b: Balanced, settings: dict[str, Any], *,
          cache_dir: Path = mp.CACHE_DIR, calculator_factory=None, price: float = 1.0) -> None:
    """The GPU tier for one pair: MACE single points of every species, MP2020-corrected."""
    from kiln.compute.energy_reference import corrected_energy
    from kiln.compute.tiers import single_point

    entries = mp.load_entries(mp.chemsys_for(c.precursor_a, c.precursor_b), cache_dir=cache_dir)
    formulas = [f for f, _ in _species(b, c.precursor_a, c.precursor_b, target)]
    found = {f: _lowest(entries, f) for f in formulas}
    c.compute_units += price
    if any(not hasattr(e, "structure") for e in found.values()):
        c.notes.append("MACE check skipped: a species has no structure in the cache")
        return
    run = single_point([found[f].structure for f in formulas], settings, calculator_factory=calculator_factory)
    if any(r.energy_ev is None for r in run.results):
        c.notes.append("MACE check failed: " + "; ".join(r.error for r in run.results if r.error))
        return
    per_fu = {}
    for f, r in zip(formulas, run.results):
        e = found[f]
        per_atom = corrected_energy(r.energy_ev, e) / e.composition.num_atoms
        per_fu[f] = _energy_per_fu(e, f, per_atom)
    c.dG_mlip_ev_per_atom = _reaction_energy(b, c.precursor_a, c.precursor_b, target, per_fu, temperature_c)


def _formulas(table: Path) -> list[str]:
    with Path(table).open(encoding="utf-8-sig", newline="") as stream:
        return [row["formula"].strip() for row in csv.DictReader(stream)]


def find(target: str, temperature_c: float, *, n_check: int = 3, cache_dir: Path = mp.CACHE_DIR,
         table: Path = DEFAULT_TABLE, precursors: Sequence[str] | None = None,
         settings: dict[str, Any] | None = None, calculator_factory=None, ranker=None,
         routes: str = "auto") -> Recipe:
    """Screen every candidate pair cheaply, then MACE-check only the close calls at the top.

    With a `ranker` (kiln.recipe_rank.Ranker), the screened candidates are ordered by its learned
    score instead of by driving force; the screen's numbers, flags and notes are unchanged.
    `routes="auto"` also tries one precursor for single-metal targets and three or more for targets
    with three or more metals; `routes="pairs"` is the pairs-only search the benchmark uses."""
    prices, margin = _prices()
    pool = list(precursors) if precursors is not None else _formulas(table)
    pairs = candidate_routes(target, pool, routes)
    balanced = {combo: b for combo, b in pairs}
    cands = [screen_route(target, temperature_c, combo, b, cache_dir=cache_dir, table=table,
                          price=prices["cached_lookup"]) for combo, b in pairs]
    ranked = _rank(cands)
    before = [(c.precursor_a, c.precursor_b) for c in ranked]
    to_check = close_calls(ranked, n_check, margin) if n_check > 0 else []
    if to_check:
        if settings is None:
            from kiln.compute.profile import load_tier_settings
            from kiln.schemas import ComputeTier
            settings = load_tier_settings()[ComputeTier.single_point]
        for c in to_check:
            check(c, target, temperature_c, balanced[tuple(c.precursors)], settings, cache_dir=cache_dir,
                  calculator_factory=calculator_factory, price=prices["single_point"])
        ranked = _rank(ranked)
    changed = [(c.precursor_a, c.precursor_b) for c in ranked] != before
    if ranker is not None:
        usable = [c for c in ranked if c.status == "ok" and c.dG is not None]
        for c in usable:
            c.score = ranker.score(c, balanced[tuple(c.precursors)], str(cache_dir),
                                   temperature_c, str(table))
        ranked = sorted(usable, key=lambda c: -c.score) + [c for c in ranked if c not in usable]
    return Recipe(target.strip(), temperature_c, ranked, len(pairs), len(to_check),
                  round(sum(c.compute_units for c in ranked), 3), changed)


def _print(r: Recipe, top: int) -> None:
    print(f"Target {r.target} at {r.temperature_c:g} °C: {r.n_pairs_considered} precursor pairs balance; "
          f"{r.n_checked} MACE-checked; {r.compute_units:g} compute units.")
    if not r.candidates:
        print("No pair from the precursor table balances to this target.")
        return
    for i, c in enumerate(r.candidates[:top], 1):
        dG = "n/a" if c.dG is None else f"{c.dG:+.3f} eV/atom" + (" (MACE)" if c.dG_mlip_ev_per_atom is not None else "")
        print(f"\n{i}. {c.precursor_a} + {c.precursor_b}   dG {dG}   [{c.status}]")
        print(f"   {c.equation}")
        for f in c.flags:
            print(f"   ! {f}")
        for n in c.notes:
            print(f"   - {n}")
    if r.order_changed_by_check:
        print("\nThe MACE check changed the order of the leading candidates.")
    print("\nUnvalidated triage list: approximate dG (gas entropy only), pairs only, not part of the "
          "pre-registered study.")


ENERGY_CACHE_DIR = Path("cache") / "mp-energies"
EXTENDED_TABLE = Path(__file__).resolve().parents[2] / "data" / "precursor_props_extended.csv"


def compact_cache(src: Path = mp.CACHE_DIR, dst: Path = ENERGY_CACHE_DIR) -> int:
    """Write an energies-only copy of the cache: composition, uncorrected energy, MP2020
    correction and id per entry, no structures. About 23 MB instead of 1.5 GB for the 702 pair
    systems, and the screen gives the same results from it; the MACE check still needs `src`."""
    dst = Path(dst)
    dst.mkdir(parents=True, exist_ok=True)
    n = 0
    for path in sorted(Path(src).glob("*.json")):
        rows = []
        for d in json.loads(path.read_text(encoding="utf-8")):
            e = ComputedEntry.from_dict({k: v for k, v in d.items() if k != "structure"})
            rows.append({"composition": e.composition.as_dict(), "energy": e.uncorrected_energy,
                         "correction": e.correction, "entry_id": e.entry_id})
        (dst / path.name).write_text(json.dumps(rows, separators=(",", ":")), encoding="utf-8")
        n += 1
    return n


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m kiln.recipe", description=__doc__.split("\n")[0])
    ap.add_argument("target", nargs="?", help="target compound, e.g. BaTiO3")
    ap.add_argument("--temp", type=float, help="furnace temperature, °C")
    ap.add_argument("--compact-cache", type=Path, metavar="DIR",
                    help=f"write the energies-only cache to DIR (e.g. {ENERGY_CACHE_DIR}) and exit")
    ap.add_argument("--check", type=int, default=3, help="leading candidates eligible for a MACE check (0: none)")
    ap.add_argument("--top", type=int, default=10, help="candidates to print")
    ap.add_argument("--cache-dir", type=Path, default=mp.CACHE_DIR)
    ap.add_argument("--device", help="device for the MACE check (default: the tier settings', e.g. cuda)")
    ap.add_argument("--json", action="store_true", help="print the full result as JSON")
    ap.add_argument("--learned", action="store_true",
                    help="use the 159-precursor table and the learned ranker (data/recipe-ranker.json); "
                         "pair with --cache-dir data/mp-energies")
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):   # degree signs and arrows on a Windows console
        sys.stdout.reconfigure(encoding="utf-8")
    if args.compact_cache:
        n = compact_cache(args.cache_dir, args.compact_cache)
        print(f"wrote {n} energies-only chemical systems to {args.compact_cache}")
        return 0
    if not args.target or args.temp is None:
        ap.error("give a target and --temp, or --compact-cache DIR")
    try:
        Composition(args.target)
    except Exception:
        print(f"not a chemical formula: {args.target}", file=sys.stderr)
        return 2
    settings = None
    if args.device:
        from kiln.compute.profile import load_tier_settings
        from kiln.schemas import ComputeTier
        settings = {**load_tier_settings()[ComputeTier.single_point], "device": args.device}
    extra: dict[str, Any] = {}
    if args.learned:
        from kiln import recipe_rank
        extra = {"table": EXTENDED_TABLE, "ranker": recipe_rank.Ranker.load()}
        if extra["ranker"] is None:
            print(f"no fitted ranker at {recipe_rank.RANKER_PATH}", file=sys.stderr)
            return 2
    r = find(args.target, args.temp, n_check=args.check, cache_dir=args.cache_dir, settings=settings, **extra)
    if args.json:
        print(json.dumps(r.to_dict(), indent=2))
    else:
        _print(r, args.top)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
