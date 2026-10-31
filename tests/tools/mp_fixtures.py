"""Made-up Ca-Ti-O entries for tests. Energies are invented, not Materials Project data.

CaO + TiO2 -> CaTiO3 releases 0.2 eV per CaTiO3 (5 atoms): -0.04 eV/atom at x(CaO) = 2/5.
"""
from __future__ import annotations

from pymatgen.core import Lattice, Structure
from pymatgen.entries.computed_entries import ComputedStructureEntry

# formula -> (species list, total energy eV, MP2020-style correction eV)
_PHASES = {
    "Ca": (["Ca"], -2.0, 0.0),
    "Ti": (["Ti"], -7.8, 0.0),
    "O2": (["O", "O"], -9.8, 0.0),
    "CaO": (["Ca", "O"], -12.9, -0.7),
    "TiO2": (["Ti", "O", "O"], -26.9, -1.4),
    "CaTiO3": (["Ca", "Ti", "O", "O", "O"], -40.0, -2.1),
    "Ca2O2": (["Ca", "Ca", "O", "O"], -25.0, -1.4),   # 0.2 eV/atom above CaO: outside 100 meV
    "CaTiO3_meta": (["Ca", "Ti", "O", "O", "O"], -39.8, -2.1),  # 0.04 eV/atom above: inside
}


def _structure(species: list[str]) -> Structure:
    n = len(species)
    coords = [[i / n, i / n, i / n] for i in range(n)]
    return Structure(Lattice.cubic(3.0 + n), species, coords)


def ca_ti_o_entries() -> list[ComputedStructureEntry]:
    # `energy` above is the corrected total; pymatgen stores uncorrected + correction, as MP does.
    return [
        ComputedStructureEntry(_structure(species), energy - correction, correction=correction,
                               entry_id=f"test-{i}-{name}")
        for i, (name, (species, energy, correction)) in enumerate(_PHASES.items())
    ]
