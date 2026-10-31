from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest
from ase.calculators.calculator import Calculator, all_changes
from pymatgen.core import Composition

from kiln.budget import Budget
from kiln.compute.cache import ResultCache
from kiln.compute.client import ComputeClient
from kiln.compute.convergence import converged, max_force, max_stress
from kiln.compute.tiers import LocalBackend, run_tier
from kiln.schemas import ComputeStatus, ComputeTier
from kiln.tools import mp
from tests.compute.helpers import TEST_SETTINGS, make_config, make_item
from tests.tools.mp_fixtures import ca_ti_o_entries

PAIR = {"precursor_a": "CaO", "precursor_b": "TiO2"}
MLIP = {"model": "fake", "ehull_max_ev_per_atom": 0.1, "max_structures": 20, "max_atoms": 50}
RELAX = {**MLIP, "fmax_ev_per_a": 0.05, "stress_tol_ev_per_a3": 0.001, "max_steps": 15}


class FakeMLIP(Calculator):
    """Returns each phase's uncorrected MP energy per atom (plus an optional shift), constant
    forces and stress. Stands in for MACE; not physics."""

    implemented_properties = ["energy", "forces", "stress"]

    def __init__(self, shift: dict[str, float] | None = None, stress: float = 0.0) -> None:
        super().__init__()
        self.per_atom = {}
        for e in ca_ti_o_entries():
            f = e.composition.reduced_formula
            self.per_atom[f] = min(self.per_atom.get(f, 0.0), e.uncorrected_energy_per_atom)
        self.shift = shift or {}
        self.stress_value = stress

    def calculate(self, atoms=None, properties=("energy",), system_changes=all_changes) -> None:
        super().calculate(atoms, properties, system_changes)
        f = Composition(self.atoms.get_chemical_formula(mode="metal")).reduced_formula
        n = len(self.atoms)
        self.results = {
            "energy": (self.per_atom[f] + self.shift.get(f, 0.0)) * n,
            "forces": np.zeros((n, 3)),
            "stress": np.full(6, self.stress_value),
        }


@pytest.fixture
def cache_dir(tmp_path: Path) -> Path:
    mp._write_entries(tmp_path / "Ca-O-Ti.json", ca_ti_o_entries())
    return tmp_path


def factory(calc: Calculator):
    return lambda settings: calc


def test_convergence_needs_force_and_stress() -> None:
    forces, stress = np.zeros((2, 3)), np.array([0.0, 0, 0, 0, 0, 0.002])
    assert max_force([[3.0, 4.0, 0.0]]) == pytest.approx(5.0)
    assert max_stress(stress) == pytest.approx(0.002)
    assert not converged(forces, stress, 0.05, 0.001)
    assert converged(forces, stress, 0.05, 0.003)


def test_cached_lookup(cache_dir: Path) -> None:
    out = run_tier(ComputeTier.cached_lookup, PAIR, {}, cache_dir=cache_dir)
    assert out.status == ComputeStatus.ok
    assert out.result["dE_ev_per_atom"] == pytest.approx(-0.04)
    assert out.result["products"] == "CaTiO3" and out.result["source"] == "materials_project"
    assert out.gpu_seconds == 0.0


def test_decomposition_reeval_replaces_precursor(cache_dir: Path) -> None:
    inputs = {"precursor_a": "CaTiO3", "precursor_b": "TiO2", "decomposed": {"CaTiO3": "CaO"}}
    out = run_tier(ComputeTier.decomposition_reeval, inputs, {}, cache_dir=cache_dir)
    assert out.result["reactants"] == "CaO+TiO2"
    assert out.result["dE_ev_per_atom"] == pytest.approx(-0.04)
    with pytest.raises(ValueError):
        run_tier(ComputeTier.decomposition_reeval, {**inputs, "decomposed": {"SrCO3": "SrO"}}, {},
                 cache_dir=cache_dir)


def test_single_point_matching_mp_gives_zero_difference(cache_dir: Path) -> None:
    out = run_tier(ComputeTier.single_point, PAIR, MLIP, cache_dir=cache_dir,
                   calculator_factory=factory(FakeMLIP()))
    assert out.status == ComputeStatus.ok
    assert out.result["dE_ev_per_atom"] == pytest.approx(-0.04)
    assert out.result["dE_mlip_minus_mp_ev_per_atom"] == pytest.approx(0.0, abs=1e-9)
    assert out.result["model"] == "fake"


def test_single_point_applies_mp_correction_and_reports_difference(cache_dir: Path) -> None:
    # CaTiO3 0.01 eV/atom lower in the MLIP: 0.05 eV per 5-atom formula -> dE 0.01 more negative.
    out = run_tier(ComputeTier.single_point, PAIR, MLIP, cache_dir=cache_dir,
                   calculator_factory=factory(FakeMLIP(shift={"CaTiO3": -0.01})))
    assert out.result["dE_ev_per_atom"] == pytest.approx(-0.05)
    assert out.result["dE_mp_ev_per_atom"] == pytest.approx(-0.04)
    assert out.result["dE_mlip_minus_mp_ev_per_atom"] == pytest.approx(-0.01)


def test_relaxation_converges_when_forces_and_stress_are_small(cache_dir: Path) -> None:
    out = run_tier(ComputeTier.bounded_relaxation, PAIR, RELAX, cache_dir=cache_dir,
                   calculator_factory=factory(FakeMLIP()))
    assert out.status == ComputeStatus.ok
    assert out.result["n_not_converged"] == 0 and out.result["max_steps_used"] == 0


def test_relaxation_with_converged_forces_but_high_stress_is_not_converged(cache_dir: Path) -> None:
    out = run_tier(ComputeTier.bounded_relaxation, PAIR, RELAX, cache_dir=cache_dir,
                   calculator_factory=factory(FakeMLIP(stress=0.01)))
    assert out.status == ComputeStatus.not_converged
    assert out.result["n_not_converged"] == out.result["n_structures"]
    assert out.result["max_steps_used"] == RELAX["max_steps"]


def test_structure_limits_fail_honestly(cache_dir: Path) -> None:
    few = run_tier(ComputeTier.single_point, PAIR, {**MLIP, "max_structures": 2}, cache_dir=cache_dir,
                   calculator_factory=factory(FakeMLIP()))
    small = run_tier(ComputeTier.single_point, PAIR, {**MLIP, "max_atoms": 2}, cache_dir=cache_dir,
                     calculator_factory=factory(FakeMLIP()))
    assert few.status == small.status == ComputeStatus.failed
    assert "max_structures" in str(few.result["error"]) and "max_atoms" in str(small.result["error"])


def test_unknown_precursor_raises(cache_dir: Path) -> None:
    with pytest.raises(ValueError):
        run_tier(ComputeTier.single_point, {"precursor_a": "CaO2", "precursor_b": "TiO2"}, MLIP,
                 cache_dir=cache_dir, calculator_factory=factory(FakeMLIP()))


def test_missing_cache_becomes_a_logged_failure_through_the_client(tmp_path: Path, cache_dir: Path) -> None:
    settings: dict[ComputeTier, dict[str, Any]] = {**TEST_SETTINGS, ComputeTier.bounded_relaxation: RELAX}
    config = make_config()
    client = ComputeClient(tmp_path / "runs" / "test-run", config,
                           LocalBackend(cache_dir, factory(FakeMLIP())), ResultCache(tmp_path / "rc"), settings)
    budget = Budget(config)
    ok = client.request(make_item(), "thermo", ComputeTier.bounded_relaxation, "Refine.", PAIR, budget)
    missing = client.request(make_item(), "thermo", ComputeTier.cached_lookup, "Look up.",
                             {"precursor_a": "SrO", "precursor_b": "TiO2"}, budget)
    assert ok.status == ComputeStatus.ok and ok.result["dE_ev_per_atom"] == pytest.approx(-0.04)
    assert missing.status == ComputeStatus.failed and "MissingCache" in str(missing.result["error"])
