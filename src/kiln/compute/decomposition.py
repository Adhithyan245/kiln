"""Decomposition-aware re-evaluation: the pair's reaction recomputed with what each precursor
actually is at the furnace temperature (e.g. CaCO3 is CaO above its decomposition temperature).

A precursor counts as decomposed only when its decomposition temperature is known AND the furnace
is at or above it. An unknown temperature is never guessed: the precursor stays as it is and is
listed in `unknown`, which the review flags turn into missing evidence. Decomposition temperatures
and products come from the Precursor agent's cited property table (data/precursor_props.csv).

Energies come from the Materials Project cache. A cached phase with a structure but no usable
energy gets a single_point MLIP energy with its MP2020 correction; a product with no cached entry
at all is a failure ("fetch this chemical system"), never an invented energy.
"""
from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pymatgen.core import Composition
from pymatgen.entries.computed_entries import ComputedEntry, ComputedStructureEntry

from kiln.compute.energy_reference import corrected_entry
from kiln.schemas import ComputeStatus
from kiln.tools import mp

__all__ = ["PrecursorProps", "Reevaluation", "decomposed_reactants", "reevaluate"]


@dataclass(frozen=True)
class PrecursorProps:
    """One precursor's row from the property table (None = unknown)."""
    decomposes_at_c: float | None = None
    decomposition_product: str | None = None

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> PrecursorProps:
        t = d.get("decomposes_at_c")
        return cls(None if t is None else float(t), d.get("decomposition_product") or None)


@dataclass(frozen=True)
class Reevaluation:
    status: ComputeStatus
    reactants_before: str                        # e.g. "CaCO3+TiO2"
    reactants_after: str                         # e.g. "CaO+TiO2"
    decomposed: dict[str, str] = field(default_factory=dict)   # precursor -> product used
    unknown: list[str] = field(default_factory=list)           # precursors with no decomposition data
    dE_before_ev_per_atom: float | None = None
    dE_after_ev_per_atom: float | None = None
    products_before: str = ""
    products_after: str = ""
    mixing_ratio_after: float | None = None
    filled_by_single_point: list[str] = field(default_factory=list)  # entry ids given MLIP energies
    error: str = ""

    @property
    def changed(self) -> bool:
        """Whether decomposition changed what reacts or what forms."""
        return bool(self.decomposed) and (self.products_after != self.products_before
                                          or self.reactants_after != self.reactants_before)


def decomposed_reactants(a: str, b: str, temperature_c: float,
                         properties: Mapping[str, PrecursorProps | Mapping[str, Any]]
                         ) -> tuple[str, str, dict[str, str], list[str]]:
    """Return (a', b', decomposed, unknown): each precursor replaced by its product when the
    furnace is at or above its known decomposition temperature."""
    decomposed: dict[str, str] = {}
    unknown: list[str] = []
    out = []
    for formula in (a, b):
        raw = properties.get(formula)
        props = raw if isinstance(raw, PrecursorProps) else PrecursorProps.from_dict(raw or {})
        if props.decomposes_at_c is None or props.decomposition_product is None:
            unknown.append(formula)
            out.append(formula)
        elif temperature_c >= props.decomposes_at_c:
            decomposed[formula] = props.decomposition_product
            out.append(props.decomposition_product)
        else:
            out.append(formula)
    return out[0], out[1], decomposed, unknown


def _fill_missing_energies(entries: list[ComputedEntry], settings: dict[str, Any] | None,
                           calculator_factory: Any) -> tuple[list[ComputedEntry], list[str]]:
    missing = [e for e in entries if not math.isfinite(float(e.uncorrected_energy))]
    if not missing:
        return entries, []
    unfixable = [str(e.entry_id) for e in missing if not isinstance(e, ComputedStructureEntry)]
    if unfixable or settings is None:
        raise ValueError(f"no energy and no way to compute one for {', '.join(str(e.entry_id) for e in missing)}")
    from kiln.compute.tiers import single_point  # local: tiers imports this module's callers

    run = single_point([e.structure for e in missing], settings, calculator_factory=calculator_factory)
    failed = [f"{e.entry_id}: {r.error}" for e, r in zip(missing, run.results) if r.status == ComputeStatus.failed]
    if failed:
        raise ValueError("single_point failed for " + "; ".join(failed))
    fixed = {id(e): corrected_entry(e, float(r.energy_ev)) for e, r in zip(missing, run.results)}
    return [fixed.get(id(e), e) for e in entries], [str(e.entry_id) for e in missing]


def reevaluate(a: str, b: str, temperature_c: float,
               properties: Mapping[str, PrecursorProps | Mapping[str, Any]], *,
               entries: list[ComputedEntry] | None = None, cache_dir: Path = mp.CACHE_DIR,
               settings: dict[str, Any] | None = None, calculator_factory: Any = None) -> Reevaluation:
    """Reaction energy of the pair as given and as it is at temperature_c, both from the same phases."""
    a2, b2, decomposed, unknown = decomposed_reactants(a, b, temperature_c, properties)
    base = dict(reactants_before=f"{a}+{b}", reactants_after=f"{a2}+{b2}", decomposed=decomposed, unknown=unknown)
    try:
        pool = list(entries) if entries is not None else mp.load_entries(mp.chemsys_for(a, b), cache_dir=cache_dir)
        present = {e.composition.reduced_formula for e in pool}
        absent = [f for f in {a2, b2} if Composition(f).reduced_formula not in present]
        if absent:
            raise ValueError(f"no cached entry for {', '.join(sorted(absent))}; fetch chemical system {mp.chemsys_for(a, b)}")
        pool, filled = _fill_missing_energies(pool, settings, calculator_factory)
        before = mp.reaction_energy(a, b, pool)
        after = before if (a2, b2) == (a, b) else mp.reaction_energy(a2, b2, pool)
    except (ValueError, mp.MissingCache) as exc:
        return Reevaluation(ComputeStatus.failed, **base, error=str(exc))
    return Reevaluation(ComputeStatus.ok, **base,
                        dE_before_ev_per_atom=before.dE_ev_per_atom, dE_after_ev_per_atom=after.dE_ev_per_atom,
                        products_before=before.products, products_after=after.products,
                        mixing_ratio_after=after.mixing_ratio, filled_by_single_point=filled)
