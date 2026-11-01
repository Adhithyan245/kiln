from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("pymatgen", reason="compute extras (pymatgen) not installed; see env/gb10/setup.sh")
pytest.importorskip("ase", reason="compute extras (ase) not installed; see env/gb10/setup.sh")

import numpy as np  # noqa: E402
from ase.calculators.calculator import Calculator, all_changes  # noqa: E402
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


def test_cached_lookup_reports_the_nearest_off_hull_competitor(cache_dir: Path) -> None:
    # The product CaTiO3 is on the hull (never the competitor); Ca2O2 is a CaO polymorph (a reactant,
    # excluded); the metastable CaTiO3 polymorph 0.04 eV/atom above the hull is the competitor.
    out = run_tier(ComputeTier.cached_lookup, PAIR, {}, cache_dir=cache_dir)
    assert out.result["competitor_e_hull_status"] == "ok"
    assert out.result["competitor_e_hull_ev_per_atom"] == pytest.approx(0.04)
    assert out.result["competitor_formula"] == "CaTiO3"


def test_no_off_hull_phase_on_the_join_is_none_not_zero() -> None:
    from kiln.compute.tiers import nearest_competitor

    entries = [e for e in ca_ti_o_entries() if e.composition.reduced_formula != "CaTiO3"
               or e.energy_per_atom == min(x.energy_per_atom for x in ca_ti_o_entries()
                                           if x.composition.reduced_formula == "CaTiO3")]
    assert nearest_competitor("CaO", "TiO2", entries) == {
        "competitor_e_hull_ev_per_atom": None, "competitor_formula": None,
        "competitor_e_hull_status": "none_on_join"}


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


def _toolkit_leaving(stuck: set[int]):
    """A stand-in for the ALCHEMI Toolkit batch: real (fake-MLIP) energies, but the structures at
    the given batch positions come back not_converged, as 3 of 40 did on the GB10."""
    from dataclasses import replace

    from kiln.compute import tiers

    def run(tier, items, settings, device):
        out = tiers._run_ase(tier, items, settings, factory(FakeMLIP()), device)
        results = [replace(r, status=ComputeStatus.not_converged, steps=settings.get("max_steps")) if i in stuck else r
                   for i, r in enumerate(out.results)]
        return replace(out, backend="nvalchemi", results=results, gpu_seconds=1.0)
    return run


def test_nvalchemi_plus_ase_reruns_only_what_the_toolkit_left(cache_dir: Path, monkeypatch) -> None:
    from kiln.compute import tiers

    monkeypatch.setattr(tiers, "_run_nvalchemi", _toolkit_leaving({1}))
    structures = [structure_from_cache(f, cache_dir).structure for f in ("CaO", "TiO2", "CaTiO3")]
    run = tiers.bounded_relaxation(structures, {**RELAX, "device": "cpu", "backend": "nvalchemi+ase"},
                                   calculator_factory=factory(FakeMLIP()))
    assert run.backend == "nvalchemi+ase" and run.n_finished_by_ase == 1
    assert [r.status for r in run.results] == [ComputeStatus.ok] * 3       # ASE finished the stuck one
    assert run.results[1].steps == 0                                        # it came from ASE, not the toolkit
    assert run.gpu_seconds == 1.0                                           # toolkit time plus ASE (0 on CPU)


def test_mlip_result_names_the_backend_and_how_many_ase_finished(cache_dir: Path, monkeypatch) -> None:
    from kiln.compute import tiers

    monkeypatch.setattr(tiers, "_run_nvalchemi", _toolkit_leaving({0}))
    out = run_tier(ComputeTier.bounded_relaxation, PAIR, {**RELAX, "backend": "nvalchemi+ase"}, cache_dir=cache_dir,
                   calculator_factory=factory(FakeMLIP()))
    assert out.status == ComputeStatus.ok and out.result["n_not_converged"] == 0
    assert out.result["backend"] == "nvalchemi+ase"
    assert out.result["n_finished_by_ase"] == 2          # first structure of each batch (single points, relaxations)
    default = run_tier(ComputeTier.bounded_relaxation, PAIR, RELAX, cache_dir=cache_dir,
                       calculator_factory=factory(FakeMLIP()))
    assert "backend" not in default.result and "n_finished_by_ase" not in default.result


def test_relaxation_with_converged_forces_but_high_stress_is_not_converged(cache_dir: Path) -> None:
    out = run_tier(ComputeTier.bounded_relaxation, PAIR, RELAX, cache_dir=cache_dir,
                   calculator_factory=factory(FakeMLIP(stress=0.01)))
    assert out.status == ComputeStatus.not_converged
    # elemental references get a single point, so every relaxed structure fails the stress test
    assert out.result["n_not_converged"] == out.result["n_structures"] - out.result["n_elements_single_point"]
    assert out.result["n_elements_single_point"] == 3                # Ca, Ti, O2
    assert out.result["max_steps_used"] == RELAX["max_steps"]


class OneStuckMLIP(FakeMLIP):
    """Converges everything except one phase, whose stress never drops. `stuck` is a reduced formula
    (every cell with it) or a Structure (only that exact cell: same formula, atoms and volume)."""

    def __init__(self, stuck) -> None:
        super().__init__()
        self.stuck = stuck

    def _is_stuck(self) -> bool:
        formula = Composition(self.atoms.get_chemical_formula(mode="metal")).reduced_formula
        if isinstance(self.stuck, str):
            return formula == self.stuck
        return formula == self.stuck.composition.reduced_formula and len(self.atoms) == len(self.stuck)

    def calculate(self, atoms=None, properties=("energy",), system_changes=all_changes) -> None:
        super().calculate(atoms, properties, system_changes)
        if self._is_stuck():
            self.results["stress"] = np.full(6, 0.01)


def test_stuck_competitor_is_dropped_and_listed_not_a_failed_request(cache_dir: Path) -> None:
    from kiln.compute.tiers import _phase_selection
    phases, required, elements = _phase_selection("CaO", "TiO2", RELAX, cache_dir)
    key = lambda e: (e.composition.reduced_formula, len(e.structure))
    competitors = [e for e in phases if str(e.entry_id) not in required | elements
                   and sum(key(p) == key(e) for p in phases) == 1]     # only this cell has that formula and size
    if not competitors:
        pytest.skip("fixture has no uniquely identifiable near-hull competitor on the CaO-TiO2 line")
    out = run_tier(ComputeTier.bounded_relaxation, PAIR, RELAX, cache_dir=cache_dir,
                   calculator_factory=factory(OneStuckMLIP(competitors[0].structure)))
    assert out.status == ComputeStatus.ok
    assert out.result["n_competitors_dropped"] >= 1 and "competitors_dropped_ids" in out.result


def test_stuck_required_phase_makes_the_request_not_converged(cache_dir: Path) -> None:
    out = run_tier(ComputeTier.bounded_relaxation, PAIR, RELAX, cache_dir=cache_dir,
                   calculator_factory=factory(OneStuckMLIP("CaTiO3")))          # the product
    assert out.status == ComputeStatus.not_converged
    assert "not_converged_ids" in out.result


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


# ---------- first calculations on a new host (Task 1) ----------

from kiln.compute import tiers as tiers_module
from kiln.compute.tiers import first_calcs, main, structure_from_cache

FIRST_FIELDS = {"status", "energy_ev_per_atom", "max_force_ev_per_a", "max_stress_ev_per_a3",
                "wall_s", "gpu_seconds"}


class CrashingMLIP(Calculator):
    implemented_properties = ["energy", "forces", "stress"]

    def calculate(self, atoms=None, properties=("energy",), system_changes=all_changes) -> None:
        raise RuntimeError("CUDA out of memory")


def test_structure_from_cache_picks_lowest_energy_structure(cache_dir: Path) -> None:
    entry = structure_from_cache("TiO2", cache_dir)   # only Ca-O-Ti.json is cached, as on the GB10
    tio2 = [e for e in ca_ti_o_entries() if e.composition.reduced_formula == "TiO2"]
    assert entry.composition.reduced_formula == "TiO2"
    assert entry.energy_per_atom == min(e.energy_per_atom for e in tio2)


def test_structure_from_cache_unknown_formula_raises(cache_dir: Path) -> None:
    with pytest.raises((ValueError, mp.MissingCache)):
        structure_from_cache("Li2O", cache_dir)


def test_first_calcs_converged_records_every_field(cache_dir: Path) -> None:
    entry = structure_from_cache("TiO2", cache_dir)
    record = first_calcs(entry.structure, {**RELAX, "device": "cpu"}, source="test",
                         calculator_factory=factory(FakeMLIP()))
    sp, relax = record["single_point"], record["bounded_relaxation"]
    assert FIRST_FIELDS <= sp.keys() and FIRST_FIELDS | {"steps", "max_steps"} <= relax.keys()
    assert sp["status"] == relax["status"] == "ok"
    assert sp["energy_ev_per_atom"] == pytest.approx(entry.uncorrected_energy_per_atom)
    assert relax["steps"] <= RELAX["max_steps"]
    assert record["cpu_dry_run"] is True and sp["gpu_seconds"] == relax["gpu_seconds"] == 0.0
    assert record["formula"] == "TiO2" and record["n_atoms"] == len(entry.structure)
    assert record["settings"]["fmax_ev_per_a"] == 0.05 and record["settings"]["stress_tol_ev_per_a3"] == 0.001


def test_first_calcs_reports_not_converged_honestly(cache_dir: Path) -> None:
    entry = structure_from_cache("TiO2", cache_dir)
    record = first_calcs(entry.structure, {**RELAX, "device": "cpu", "max_steps": 1}, source="test",
                         calculator_factory=factory(FakeMLIP(stress=0.01)))
    relax = record["bounded_relaxation"]
    assert relax["status"] == "not_converged"
    assert relax["steps"] == 1 and relax["max_steps"] == 1
    assert relax["max_stress_ev_per_a3"] == pytest.approx(0.01)   # final stress is kept, not hidden


def test_first_calcs_records_a_crash_as_failed(cache_dir: Path) -> None:
    entry = structure_from_cache("TiO2", cache_dir)
    record = first_calcs(entry.structure, {**RELAX, "device": "cpu"}, source="test",
                         calculator_factory=factory(CrashingMLIP()))
    for name in ("single_point", "bounded_relaxation"):
        assert record[name]["status"] == "failed"
        assert "CUDA out of memory" in record[name]["error"]


def test_first_calcs_command_writes_json(tmp_path: Path, cache_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = tmp_path / "tier_settings.json"
    settings.write_text(json.dumps({"bounded_relaxation": {**RELAX, "device": "cuda", "dtype": "float64"}}))
    monkeypatch.setattr(tiers_module, "mace_calculator", factory(FakeMLIP()))
    out = tmp_path / "first_calcs.json"
    code = main(["first-calcs", "--formula", "TiO2", "--cache-dir", str(cache_dir), "--settings", str(settings),
                 "--device", "cpu", "--out", str(out)])
    assert code == 0
    saved = json.loads(out.read_text())
    assert saved["source"].startswith("materials_project:")
    assert saved["device"] == "cpu" and saved["cpu_dry_run"] is True
    assert saved["single_point"]["status"] == "ok" and saved["bounded_relaxation"]["status"] == "ok"


# ---------- structure-level tiers (Task 2) ----------

from kiln.compute.tiers import bounded_relaxation, single_point


def _structures(cache_dir: Path) -> list:
    return [structure_from_cache(f, cache_dir).structure for f in ("TiO2", "CaO", "CaTiO3")]


def test_single_point_batch_matches_one_by_one(cache_dir: Path) -> None:
    structures = _structures(cache_dir)
    calc = factory(FakeMLIP())
    batch = single_point(structures, {**MLIP, "device": "cpu"}, calculator_factory=calc)
    singles = [single_point(s, {**MLIP, "device": "cpu"}, calculator_factory=calc).results[0] for s in structures]
    assert batch.status == ComputeStatus.ok and batch.backend == "ase"
    assert [r.energy_ev for r in batch.results] == pytest.approx([r.energy_ev for r in singles])
    assert all(r.steps is None for r in batch.results)
    assert batch.gpu_seconds == 0.0                      # CPU: no GPU-seconds claimed


def test_bounded_relaxation_converged(cache_dir: Path) -> None:
    run = bounded_relaxation(_structures(cache_dir), {**RELAX, "device": "cpu"}, calculator_factory=factory(FakeMLIP()))
    assert run.status == ComputeStatus.ok
    assert all(r.status == ComputeStatus.ok and r.steps is not None and r.steps <= RELAX["max_steps"] for r in run.results)


def test_bounded_relaxation_forced_not_converged_keeps_final_numbers(cache_dir: Path) -> None:
    run = bounded_relaxation(_structures(cache_dir), {**RELAX, "device": "cpu", "max_steps": 2},
                             calculator_factory=factory(FakeMLIP(stress=0.01)))
    assert run.status == ComputeStatus.not_converged
    for r in run.results:
        assert r.status == ComputeStatus.not_converged and r.steps == 2
        assert r.max_force_ev_per_a == pytest.approx(0.0)        # forces pass...
        assert r.max_stress_ev_per_a3 == pytest.approx(0.01)     # ...stress doesn't, and it's reported
        assert r.energy_ev is not None


def test_one_failing_structure_is_reported_not_raised(cache_dir: Path) -> None:
    run = single_point(_structures(cache_dir), {**MLIP, "device": "cpu"}, calculator_factory=factory(CrashingMLIP()))
    assert run.status == ComputeStatus.failed
    assert all(r.status == ComputeStatus.failed and "CUDA out of memory" in r.error for r in run.results)


def test_relaxation_tier_reports_worst_phase_mlip_minus_mp(cache_dir: Path) -> None:
    out = run_tier(ComputeTier.single_point, PAIR, MLIP, cache_dir=cache_dir,
                   calculator_factory=factory(FakeMLIP(shift={"CaTiO3": 0.03})))
    assert out.status == ComputeStatus.ok
    assert out.result["max_abs_phase_mlip_minus_mp_ev_per_atom"] == pytest.approx(0.03)


def test_unknown_backend_is_refused_loudly(cache_dir: Path) -> None:
    with pytest.raises(NotImplementedError):
        single_point(_structures(cache_dir), {**MLIP, "backend": "nope"}, calculator_factory=factory(FakeMLIP()))


# ---------- phase set: only what the a-b reaction depends on ----------

from kiln.compute.tiers import _on_join, _phase_set


def test_phase_set_reproduces_the_full_reaction_energy(cache_dir: Path) -> None:
    full = mp.load_entries("Ca-O-Ti", cache_dir=cache_dir)
    phases = _phase_set("CaO", "TiO2", {"ehull_max_ev_per_atom": 0.1, "max_structures": 40}, cache_dir)
    assert len(phases) <= len(full)
    r_full, r_small = mp.reaction_energy("CaO", "TiO2", full), mp.reaction_energy("CaO", "TiO2", phases)
    assert r_small.dE_ev_per_atom == pytest.approx(r_full.dE_ev_per_atom, abs=1e-9)
    assert r_small.products == r_full.products


def test_phase_set_always_keeps_reactants_products_and_elements(cache_dir: Path) -> None:
    phases = _phase_set("CaO", "TiO2", {"ehull_max_ev_per_atom": 0.1, "max_structures": 0}, cache_dir)  # no competitors
    formulas = {e.composition.reduced_formula for e in phases}
    assert {"CaO", "TiO2", "CaTiO3"} <= formulas                 # reactants and the product
    assert {"Ca", "Ti", "O2"} <= formulas                        # elemental references


def test_competitors_are_capped(cache_dir: Path) -> None:
    required = _phase_set("CaO", "TiO2", {"ehull_max_ev_per_atom": 0.1, "max_structures": 0}, cache_dir)
    capped = _phase_set("CaO", "TiO2", {"ehull_max_ev_per_atom": 0.1, "max_structures": len(required) + 1}, cache_dir)
    assert len(required) <= len(capped) <= len(required) + 1


def test_on_join() -> None:
    a, b = Composition("CaO"), Composition("TiO2")
    assert _on_join(Composition("CaTiO3"), a, b) and _on_join(Composition("Ca2TiO4"), a, b)
    assert not _on_join(Composition("Ti2O3"), a, b) and not _on_join(Composition("Ca"), a, b)
