"""Put ALCHEMI (MACE) energies on the Materials Project scale, so the two can be compared.

Materials Project energies are GGA/GGA+U totals plus the MP2020 correction (anion and Hubbard-U
terms), stored per entry as `entry.correction`. MACE-MPA-0 is trained on the raw GGA/GGA+U
energies, so the matching MLIP value for the same cell is the MLIP total plus that same entry's
correction. Comparing anything else mixes energy references.

The MLIP total must be for the same cell (same atoms) as the entry; a relaxed cell keeps its atoms.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from pymatgen.entries.computed_entries import ComputedEntry

__all__ = ["PhaseDifference", "corrected_energy", "corrected_entry", "phase_differences"]


def corrected_energy(mlip_total_ev: float, entry: ComputedEntry) -> float:
    """MLIP total energy for the entry's cell, on the Materials Project scale (eV)."""
    return float(mlip_total_ev) + float(entry.correction)


def corrected_entry(entry: ComputedEntry, mlip_total_ev: float) -> ComputedEntry:
    """A ComputedEntry holding the MLIP energy with the entry's own MP2020 correction."""
    return ComputedEntry(entry.composition, float(mlip_total_ev), correction=entry.correction,
                         entry_id=entry.entry_id)


@dataclass(frozen=True)
class PhaseDifference:
    entry_id: str
    formula: str
    mlip_ev_per_atom: float     # MLIP + MP2020 correction
    mp_ev_per_atom: float       # Materials Project, corrected
    mlip_minus_mp_ev_per_atom: float


def phase_differences(entries: Sequence[ComputedEntry], mlip_totals_ev: Sequence[float]) -> list[PhaseDifference]:
    """ALCHEMI-minus-Materials-Project energy per atom for each phase, both on the MP2020 scale."""
    if len(entries) != len(mlip_totals_ev):
        raise ValueError(f"{len(entries)} entries but {len(mlip_totals_ev)} MLIP energies")
    out = []
    for entry, total in zip(entries, mlip_totals_ev):
        n = entry.composition.num_atoms
        mlip = corrected_energy(total, entry) / n
        mp = float(entry.energy_per_atom)
        out.append(PhaseDifference(str(entry.entry_id), entry.composition.reduced_formula, mlip, mp, mlip - mp))
    return out
