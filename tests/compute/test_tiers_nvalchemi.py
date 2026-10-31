"""The ALCHEMI Toolkit backend agrees with the ASE path. Runs only where nvalchemi, MACE and a CUDA
GPU are available (the GB10); skipped everywhere else."""
from __future__ import annotations

import pytest

pytest.importorskip("pymatgen", reason="compute extras not installed")
pytest.importorskip("nvalchemi", reason="ALCHEMI Toolkit not installed (GB10 only)")
pytest.importorskip("mace", reason="mace-torch not installed (GB10 only)")
torch = pytest.importorskip("torch")
if not torch.cuda.is_available():
    pytest.skip("needs a CUDA GPU", allow_module_level=True)

from pymatgen.core import Lattice, Structure  # noqa: E402

from kiln.compute.tiers import bounded_relaxation, single_point  # noqa: E402
from kiln.schemas import ComputeStatus  # noqa: E402

BASE = {"model": "medium-mpa-0", "device": "cuda", "dtype": "float32",
        "fmax_ev_per_a": 0.05, "stress_tol_ev_per_a3": 0.001, "max_steps": 500}


def _structures() -> list[Structure]:
    rutile = Structure.from_spacegroup("P4_2/mnm", Lattice.tetragonal(4.70, 3.00), ["Ti", "O"],
                                       [[0, 0, 0], [0.305, 0.305, 0]])        # 3% strained
    rocksalt = Structure.from_spacegroup("Fm-3m", Lattice.cubic(4.90), ["Ca", "O"], [[0, 0, 0], [0.5, 0.5, 0.5]])
    return [rutile, rocksalt]


def test_single_point_matches_ase() -> None:
    s = _structures()
    ase = single_point(s, {**BASE, "backend": "ase"})
    nv = single_point(s, {**BASE, "backend": "nvalchemi"})
    assert nv.backend == "nvalchemi" and nv.status == ComputeStatus.ok
    for a, b in zip(ase.results, nv.results):
        assert b.energy_ev_per_atom == pytest.approx(a.energy_ev_per_atom, abs=1e-3)    # within 1 meV/atom
        assert b.max_stress_ev_per_a3 == pytest.approx(a.max_stress_ev_per_a3, abs=2e-4)  # same units and scale


def test_relaxation_matches_ase_and_both_converge() -> None:
    s = _structures()
    ase = bounded_relaxation(s, {**BASE, "backend": "ase"})
    nv = bounded_relaxation(s, {**BASE, "backend": "nvalchemi"})
    assert ase.status == ComputeStatus.ok and nv.status == ComputeStatus.ok
    for a, b in zip(ase.results, nv.results):
        assert b.energy_ev_per_atom == pytest.approx(a.energy_ev_per_atom, abs=1e-3)
        assert b.max_force_ev_per_a <= BASE["fmax_ev_per_a"] and b.max_stress_ev_per_a3 <= BASE["stress_tol_ev_per_a3"]


def test_step_cap_gives_honest_not_converged() -> None:
    nv = bounded_relaxation(_structures()[:1], {**BASE, "backend": "nvalchemi", "max_steps": 2})
    r = nv.results[0]
    assert r.status == ComputeStatus.not_converged and r.max_stress_ev_per_a3 > BASE["stress_tol_ev_per_a3"]
