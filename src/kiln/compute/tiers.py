"""What each tier computes. Runs on the GPU host behind the compute service, never in an agent.

Inputs (all tiers): {"precursor_a": "CaO", "precursor_b": "TiO2"}; decomposition_reeval adds
{"decomposed": {"CaCO3": "CaO"}} (precursor -> the product it becomes, from the precursor table).

- cached_lookup         Materials Project interface reaction energy from cache/mp (CPU).
- decomposition_reeval  The same, with decomposed precursors replaced by their products (CPU).
- single_point          MLIP energy of every candidate phase at its MP structure (GPU).
- bounded_relaxation    Variable-cell relaxation of every candidate phase, stopping only when
                        max force <= fmax AND max |stress| <= stress_tol, hard step cap (GPU).

MLIP energies are put on the Materials Project scale by adding the MP2020 correction MP applied to
the same entry (MACE-MPA-0 is trained on raw GGA/GGA+U energies), then the reaction energy is
recomputed on the same phase set as the MP value it is compared with. Result keys carry units.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
from typing import Any

from pymatgen.core import Composition
from pymatgen.entries.computed_entries import ComputedEntry
from pymatgen.io.ase import AseAtomsAdaptor

from kiln.compute.backends import BackendResult, Result
from kiln.compute.convergence import converged
from kiln.schemas import ComputeStatus, ComputeTier
from kiln.tools import mp

__all__ = ["CalculatorFactory", "LocalBackend", "mace_calculator", "run_tier"]

CalculatorFactory = Callable[[dict[str, Any]], Any]   # settings -> ASE calculator


@lru_cache(maxsize=4)
def _mace(model: str, device: str, dtype: str) -> Any:
    from mace.calculators import mace_mp  # GPU-host dependency, imported lazily

    return mace_mp(model=model, device=device, default_dtype=dtype)


def mace_calculator(settings: dict[str, Any]) -> Any:
    """MACE calculator from settings: model (e.g. "medium-mpa-0"), device, dtype. Loaded once."""
    return _mace(settings["model"], settings.get("device", "cuda"), settings.get("dtype", "float64"))


def _pair(inputs: dict[str, Any]) -> tuple[str, str]:
    try:
        return str(inputs["precursor_a"]), str(inputs["precursor_b"])
    except KeyError as exc:
        raise ValueError(f"inputs need precursor_a and precursor_b, missing {exc}") from None


def _reaction_result(r: mp.ReactionEnergy, prefix: str = "") -> Result:
    return {f"{prefix}dE_ev_per_atom": r.dE_ev_per_atom,
            f"{prefix}products": r.products,
            f"{prefix}mixing_ratio": r.mixing_ratio}


def _mp_lookup(inputs: dict[str, Any], cache_dir: Path) -> BackendResult:
    a, b = _pair(inputs)
    entries = mp.load_entries(mp.chemsys_for(a, b), cache_dir=cache_dir)
    return BackendResult(ComputeStatus.ok, {**_reaction_result(mp.reaction_energy(a, b, entries)),
                                            "source": "materials_project"})


def _decomposition(inputs: dict[str, Any], cache_dir: Path) -> BackendResult:
    a, b = _pair(inputs)
    decomposed: dict[str, str] = dict(inputs.get("decomposed") or {})
    unknown = set(decomposed) - {a, b}
    if unknown:
        raise ValueError(f"decomposed names precursors not in the pair: {sorted(unknown)}")
    a2, b2 = decomposed.get(a, a), decomposed.get(b, b)
    entries = mp.load_entries(mp.chemsys_for(a, b), cache_dir=cache_dir)
    result = mp.reaction_energy(a2, b2, entries)
    return BackendResult(ComputeStatus.ok, {**_reaction_result(result), "reactants": f"{a2}+{b2}",
                                            "source": "materials_project"})


def _phase_set(a: str, b: str, settings: dict[str, Any], cache_dir: Path) -> list[ComputedEntry]:
    """Candidates within the hull window, plus each precursor's lowest-energy entry."""
    window = float(settings["ehull_max_ev_per_atom"])
    phases = mp.candidates(a, b, ehull_max_ev_per_atom=window, cache_dir=cache_dir)
    all_entries = mp.load_entries(mp.chemsys_for(a, b), cache_dir=cache_dir)
    ids = {e.entry_id for e in phases}
    for formula in (a, b):
        target = Composition(formula).reduced_formula
        matching = [e for e in all_entries if e.composition.reduced_formula == target]
        if not matching:
            raise ValueError(f"no Materials Project entry for precursor {formula}")
        best = min(matching, key=lambda e: e.energy_per_atom)
        if best.entry_id not in ids:
            phases.append(best)
            ids.add(best.entry_id)
    return phases


def _mlip(tier: ComputeTier, inputs: dict[str, Any], settings: dict[str, Any], cache_dir: Path,
          calculator_factory: CalculatorFactory) -> BackendResult:
    a, b = _pair(inputs)
    phases = _phase_set(a, b, settings, cache_dir)
    limit = int(settings["max_structures"])
    if len(phases) > limit:
        return BackendResult(ComputeStatus.failed,
                             {"error": f"{len(phases)} phases exceed max_structures={limit}"})
    max_atoms = int(settings["max_atoms"])
    too_big = [e.entry_id for e in phases if len(e.structure) > max_atoms]
    if too_big:
        return BackendResult(ComputeStatus.failed,
                             {"error": f"structures above max_atoms={max_atoms}: {', '.join(map(str, too_big))}"})

    calc = calculator_factory(settings)
    relax = tier == ComputeTier.bounded_relaxation
    mlip_entries: list[ComputedEntry] = []
    not_converged: list[str] = []
    steps_used = 0
    for entry in phases:
        atoms = AseAtomsAdaptor.get_atoms(entry.structure)
        atoms.calc = calc
        if relax:
            ok, steps = _relax(atoms, settings)
            steps_used = max(steps_used, steps)
            if not ok:
                not_converged.append(str(entry.entry_id))
        energy = float(atoms.get_potential_energy())          # raw MLIP total, eV, for this cell
        mlip_entries.append(ComputedEntry(entry.composition, energy, correction=entry.correction,
                                          entry_id=entry.entry_id))

    mlip_r = mp.reaction_energy(a, b, mlip_entries)
    mp_r = mp.reaction_energy(a, b, phases)
    result: Result = {
        **_reaction_result(mlip_r),
        "dE_mp_ev_per_atom": mp_r.dE_ev_per_atom,
        "dE_mlip_minus_mp_ev_per_atom": mlip_r.dE_ev_per_atom - mp_r.dE_ev_per_atom,
        "mp_products": mp_r.products,
        "model": str(settings["model"]),
        "n_structures": len(phases),
    }
    if relax:
        result["max_steps_used"] = steps_used
        result["n_not_converged"] = len(not_converged)
        if not_converged:
            result["not_converged_ids"] = ", ".join(not_converged)
            return BackendResult(ComputeStatus.not_converged, result)
    return BackendResult(ComputeStatus.ok, result)


def _relax(atoms: Any, settings: dict[str, Any]) -> tuple[bool, int]:
    """FIRE2 on a FrechetCellFilter. Stops on our own force AND stress test, never the filter's."""
    from ase.filters import FrechetCellFilter
    from ase.optimize.fire2 import FIRE2

    fmax, s_tol, cap = (float(settings["fmax_ev_per_a"]), float(settings["stress_tol_ev_per_a3"]),
                        int(settings["max_steps"]))
    opt = FIRE2(FrechetCellFilter(atoms), logfile=None)
    for _ in opt.irun(fmax=0.0, steps=cap):          # fmax=0: the filter's mixed criterion never stops us
        if converged(atoms.get_forces(), atoms.get_stress(), fmax, s_tol):
            return True, opt.nsteps
    return converged(atoms.get_forces(), atoms.get_stress(), fmax, s_tol), opt.nsteps


def run_tier(tier: ComputeTier, inputs: dict[str, Any], settings: dict[str, Any], *,
             cache_dir: Path = mp.CACHE_DIR,
             calculator_factory: CalculatorFactory = mace_calculator) -> BackendResult:
    start = time.perf_counter()
    if tier == ComputeTier.cached_lookup:
        out = _mp_lookup(inputs, cache_dir)
    elif tier == ComputeTier.decomposition_reeval:
        out = _decomposition(inputs, cache_dir)
    elif tier in (ComputeTier.single_point, ComputeTier.bounded_relaxation):
        out = _mlip(tier, inputs, settings, cache_dir, calculator_factory)
    else:
        raise ValueError(f"unknown tier {tier!r}")
    # GPU-seconds are wall time of the MLIP tiers on the GPU host; the MP tiers use no GPU.
    gpu = tier in (ComputeTier.single_point, ComputeTier.bounded_relaxation)
    return BackendResult(out.status, out.result, gpu_seconds=time.perf_counter() - start if gpu else 0.0)


class LocalBackend:
    """Runs tiers in this process: on the GPU host inside the service, or in tests."""

    name = "local"

    def __init__(self, cache_dir: Path = mp.CACHE_DIR,
                 calculator_factory: CalculatorFactory = mace_calculator) -> None:
        self.cache_dir = Path(cache_dir)
        self.calculator_factory = calculator_factory

    def run(self, tier: ComputeTier, inputs: dict[str, Any], settings: dict[str, Any]) -> BackendResult:
        return run_tier(tier, inputs, settings, cache_dir=self.cache_dir,
                        calculator_factory=self.calculator_factory)

    def healthy(self) -> bool:
        return self.cache_dir.is_dir()

