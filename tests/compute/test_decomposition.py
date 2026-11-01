from __future__ import annotations

import math
from pathlib import Path

import pytest

pytest.importorskip("pymatgen", reason="compute extras (pymatgen) not installed; see env/gb10/setup.sh")

from pymatgen.core import Composition, Lattice, Structure  # noqa: E402
from pymatgen.entries.computed_entries import ComputedEntry, ComputedStructureEntry  # noqa: E402

from kiln.compute.decomposition import PrecursorProps, decomposed_reactants, reevaluate  # noqa: E402
from kiln.compute.tiers import run_tier  # noqa: E402
from kiln.schemas import ComputeStatus, ComputeTier  # noqa: E402
from kiln.tools import mp  # noqa: E402

# MADE-UP energies (eV/atom), shaped so that CaCO3 is stable at 0 K, CaO + TiO2 -> CaTiO3 is
# strongly favoured and CaCO3 + TiO2 -> CaTiO3 + CO2 only weakly. Not real data, test-only.
ENERGY_PER_ATOM = {"Ca": 0.0, "Ti": 0.0, "O2": 0.0, "C": 0.0,
                   "CaO": -3.3, "TiO2": -3.4, "CaTiO3": -3.5, "CO2": -1.4, "CaCO3": -2.25}
# Test values for the property table, not sourced data (those come from data/precursor_props.csv).
CACO3 = {"decomposes_at_c": 825.0, "decomposition_product": "CaO"}
TIO2 = {"decomposes_at_c": None, "decomposition_product": None}


def carbonate_entries() -> list[ComputedEntry]:
    out = []
    for i, (formula, e) in enumerate(ENERGY_PER_ATOM.items()):
        comp = Composition(formula)
        out.append(ComputedEntry(comp, e * comp.num_atoms, entry_id=f"test-{i}"))
    return out


def test_carbonate_decomposes_above_its_temperature() -> None:
    a, b, decomposed, unknown = decomposed_reactants("CaCO3", "TiO2", 900.0, {"CaCO3": CACO3, "TiO2": TIO2})
    assert (a, b) == ("CaO", "TiO2")
    assert decomposed == {"CaCO3": "CaO"}
    assert unknown == ["TiO2"]              # no data for TiO2: kept as is, and reported


def test_caco3_tio2_above_decomposition_is_computed_with_cao() -> None:
    """Task 3 done-when: above CaCO3's decomposition temperature the reaction uses CaO."""
    r = reevaluate("CaCO3", "TiO2", 900.0, {"CaCO3": CACO3, "TiO2": TIO2}, entries=carbonate_entries())
    assert r.status == ComputeStatus.ok
    assert r.reactants_before == "CaCO3+TiO2" and r.reactants_after == "CaO+TiO2"
    assert r.products_after == "CaTiO3"
    assert r.dE_after_ev_per_atom == pytest.approx(-0.14)          # (5 * -3.5 - (2 * -3.3 + 3 * -3.4)) / 5
    assert r.dE_before_ev_per_atom == pytest.approx(-0.03125)      # CaCO3 + TiO2 -> CaTiO3 + CO2
    assert r.dE_after_ev_per_atom < r.dE_before_ev_per_atom
    assert r.changed is True


def test_below_decomposition_temperature_nothing_changes() -> None:
    r = reevaluate("CaCO3", "TiO2", 700.0, {"CaCO3": CACO3, "TiO2": TIO2}, entries=carbonate_entries())
    assert r.status == ComputeStatus.ok
    assert r.decomposed == {} and r.reactants_after == "CaCO3+TiO2"
    assert r.dE_after_ev_per_atom == r.dE_before_ev_per_atom
    assert r.changed is False


def test_unknown_decomposition_is_never_guessed() -> None:
    r = reevaluate("CaCO3", "TiO2", 1200.0, {}, entries=carbonate_entries())
    assert r.status == ComputeStatus.ok
    assert r.decomposed == {} and sorted(r.unknown) == ["CaCO3", "TiO2"]


def test_missing_product_entry_fails_honestly() -> None:
    entries = [e for e in carbonate_entries() if e.composition.reduced_formula != "CaO"]
    r = reevaluate("CaCO3", "TiO2", 900.0, {"CaCO3": CACO3}, entries=entries)
    assert r.status == ComputeStatus.failed
    assert "CaO" in r.error and "fetch" in r.error


def test_missing_energy_is_filled_by_single_point_with_correction() -> None:
    import numpy as np
    from ase.calculators.calculator import Calculator, all_changes

    class FixedEnergy(Calculator):  # stands in for MACE: a fixed -3.3 eV/atom
        implemented_properties = ["energy", "forces", "stress"]

        def calculate(self, atoms=None, properties=("energy",), system_changes=all_changes) -> None:
            super().calculate(atoms, properties, system_changes)
            n = len(self.atoms)
            self.results = {"energy": -3.3 * n, "forces": np.zeros((n, 3)), "stress": np.zeros(6)}

    cao = Structure(Lattice.cubic(4.8), ["Ca", "O"], [[0, 0, 0], [0.5, 0.5, 0.5]])
    entries = [e for e in carbonate_entries() if e.composition.reduced_formula != "CaO"]
    entries.append(ComputedStructureEntry(cao, math.nan, correction=0.0, entry_id="test-cao-no-energy"))
    r = reevaluate("CaCO3", "TiO2", 900.0, {"CaCO3": CACO3}, entries=entries,
                   settings={"model": "fake", "device": "cpu"}, calculator_factory=lambda s: FixedEnergy())
    assert r.status == ComputeStatus.ok
    assert r.filled_by_single_point == ["test-cao-no-energy"]
    assert r.dE_after_ev_per_atom == pytest.approx(-0.14)


def test_missing_energy_without_settings_fails() -> None:
    cao = Structure(Lattice.cubic(4.8), ["Ca", "O"], [[0, 0, 0], [0.5, 0.5, 0.5]])
    entries = [e for e in carbonate_entries() if e.composition.reduced_formula != "CaO"]
    entries.append(ComputedStructureEntry(cao, math.nan, entry_id="test-cao-no-energy"))
    r = reevaluate("CaCO3", "TiO2", 900.0, {"CaCO3": CACO3}, entries=entries)
    assert r.status == ComputeStatus.failed and "test-cao-no-energy" in r.error


def test_tier_takes_temperature_and_properties(tmp_path: Path) -> None:
    mp._write_entries(tmp_path / "C-Ca-O-Ti.json", carbonate_entries())
    inputs = {"precursor_a": "CaCO3", "precursor_b": "TiO2", "temperature_c": 900.0,
              "properties": {"CaCO3": CACO3, "TiO2": TIO2}}
    out = run_tier(ComputeTier.decomposition_reeval, inputs, {}, cache_dir=tmp_path)
    assert out.status == ComputeStatus.ok
    assert out.result["reactants"] == "CaO+TiO2" and out.result["decomposed"] == "CaCO3->CaO"
    assert out.result["dE_ev_per_atom"] == pytest.approx(-0.14)
    assert out.result["dE_before_ev_per_atom"] == pytest.approx(-0.03125)
    assert out.result["changed"] is True and out.gpu_seconds == 0.0


def test_tier_needs_temperature_with_properties(tmp_path: Path) -> None:
    mp._write_entries(tmp_path / "C-Ca-O-Ti.json", carbonate_entries())
    with pytest.raises(ValueError):
        run_tier(ComputeTier.decomposition_reeval,
                 {"precursor_a": "CaCO3", "precursor_b": "TiO2", "properties": {"CaCO3": CACO3}}, {},
                 cache_dir=tmp_path)


def test_props_from_table_row() -> None:
    p = PrecursorProps.from_dict({"decomposes_at_c": "825", "decomposition_product": "CaO"})
    assert p == PrecursorProps(825.0, "CaO")
    assert PrecursorProps.from_dict({}) == PrecursorProps(None, None)
