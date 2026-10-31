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

First calculations on a new host (Task 1): one single point and one bounded relaxation on one
structure, saved to cache/first_calcs.json. On the GB10:
    export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
    python -m kiln.compute.tiers first-calcs --formula TiO2
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from pymatgen.core import Composition, Structure
from pymatgen.entries.computed_entries import ComputedEntry, ComputedStructureEntry
from pymatgen.io.ase import AseAtomsAdaptor

from kiln.compute.backends import BackendResult, Result
from kiln.compute.convergence import converged, max_force, max_stress
from kiln.compute.energy_reference import corrected_entry, phase_differences
from kiln.schemas import ComputeStatus, ComputeTier
from kiln.tools import mp

__all__ = ["CalculatorFactory", "LocalBackend", "StructureResult", "TierRun", "bounded_relaxation",
           "first_calcs", "mace_calculator", "run_tier", "single_point", "structure_from_cache"]

FIRST_CALCS_PATH = Path("cache") / "first_calcs.json"
TIER_SETTINGS_PATH = Path("env") / "gb10" / "tier_settings.json"

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


def _decomposition(inputs: dict[str, Any], cache_dir: Path, settings: dict[str, Any] | None = None,
                   calculator_factory: CalculatorFactory | None = None) -> BackendResult:
    """Two input forms: {"temperature_c", "properties": {formula: {decomposes_at_c,
    decomposition_product}}} decides decomposition from the furnace temperature (kiln.compute.
    decomposition); {"decomposed": {precursor: product}} uses a decision already made."""
    a, b = _pair(inputs)
    if "properties" in inputs:
        from kiln.compute.decomposition import reevaluate

        if "temperature_c" not in inputs:
            raise ValueError("inputs with properties need temperature_c")
        r = reevaluate(a, b, float(inputs["temperature_c"]), dict(inputs["properties"]), cache_dir=cache_dir,
                       settings=settings or None, calculator_factory=calculator_factory)
        if r.status == ComputeStatus.failed:
            return BackendResult(ComputeStatus.failed, {"error": r.error})
        return BackendResult(ComputeStatus.ok, {
            "dE_ev_per_atom": r.dE_after_ev_per_atom, "products": r.products_after,
            "mixing_ratio": r.mixing_ratio_after, "reactants": r.reactants_after,
            "dE_before_ev_per_atom": r.dE_before_ev_per_atom, "products_before": r.products_before,
            "decomposed": ", ".join(f"{k}->{v}" for k, v in r.decomposed.items()),
            "decomposition_unknown": ", ".join(r.unknown), "changed": r.changed,
            "filled_by_single_point": ", ".join(r.filled_by_single_point),
            "source": "materials_project"})
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

    relax = tier == ComputeTier.bounded_relaxation
    run = (bounded_relaxation if relax else single_point)(
        [e.structure for e in phases], settings, calculator_factory=calculator_factory)
    failed = [f"{e.entry_id}: {r.error}" for e, r in zip(phases, run.results) if r.status == ComputeStatus.failed]
    if failed:
        return BackendResult(ComputeStatus.failed, {"error": "; ".join(failed)})
    totals = [float(r.energy_ev) for r in run.results]       # raw MLIP totals, eV, for each cell
    mlip_entries = [corrected_entry(e, total) for e, total in zip(phases, totals)]
    not_converged = [str(e.entry_id) for e, r in zip(phases, run.results) if r.status == ComputeStatus.not_converged]
    steps_used = max((r.steps or 0 for r in run.results), default=0)
    worst_phase = max(abs(d.mlip_minus_mp_ev_per_atom) for d in phase_differences(phases, totals))

    mlip_r = mp.reaction_energy(a, b, mlip_entries)
    mp_r = mp.reaction_energy(a, b, phases)
    result: Result = {
        **_reaction_result(mlip_r),
        "dE_mp_ev_per_atom": mp_r.dE_ev_per_atom,
        "dE_mlip_minus_mp_ev_per_atom": mlip_r.dE_ev_per_atom - mp_r.dE_ev_per_atom,
        "max_abs_phase_mlip_minus_mp_ev_per_atom": worst_phase,
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


# ---------- structure-level tiers ----------

@dataclass(frozen=True)
class StructureResult:
    """One structure's outcome. Energies are raw MLIP values for the given cell (no MP2020
    correction; see kiln.compute.energy_reference)."""
    status: ComputeStatus
    n_atoms: int
    energy_ev: float | None = None
    energy_ev_per_atom: float | None = None
    max_force_ev_per_a: float | None = None
    max_stress_ev_per_a3: float | None = None
    steps: int | None = None            # relaxation only
    error: str = ""


@dataclass(frozen=True)
class TierRun:
    tier: ComputeTier
    backend: str
    settings: dict[str, Any]
    results: list[StructureResult] = field(default_factory=list)
    wall_s: float = 0.0
    gpu_seconds: float = 0.0            # wall time on a CUDA device; 0 on CPU

    @property
    def status(self) -> ComputeStatus:
        """failed if any structure failed, else not_converged if any didn't converge, else ok."""
        statuses = {r.status for r in self.results}
        for worst in (ComputeStatus.failed, ComputeStatus.not_converged):
            if worst in statuses:
                return worst
        return ComputeStatus.ok


def single_point(structures: Structure | Sequence[Structure], settings: dict[str, Any], *,
                 calculator_factory: CalculatorFactory | None = None) -> TierRun:
    """MLIP energy, forces and stress of each structure as given."""
    return _run_structures(ComputeTier.single_point, structures, settings, calculator_factory)


def bounded_relaxation(structures: Structure | Sequence[Structure], settings: dict[str, Any], *,
                       calculator_factory: CalculatorFactory | None = None) -> TierRun:
    """Variable-cell relaxation of each structure: converged only when max force <= fmax_ev_per_a
    AND max |stress| <= stress_tol_ev_per_a3, within max_steps; otherwise not_converged."""
    return _run_structures(ComputeTier.bounded_relaxation, structures, settings, calculator_factory)


def _run_structures(tier: ComputeTier, structures: Structure | Sequence[Structure],
                    settings: dict[str, Any], calculator_factory: CalculatorFactory | None) -> TierRun:
    backend = str(settings.get("backend", "ase"))
    items = [structures] if isinstance(structures, Structure) else list(structures)
    device = str(settings.get("device", "cuda"))
    if backend == "nvalchemi":
        return _run_nvalchemi(tier, items, settings, device)
    if backend != "ase":
        raise NotImplementedError(f"unknown backend {backend!r}; use 'ase' or 'nvalchemi'")
    calc = (calculator_factory or mace_calculator)(settings)
    relax = tier == ComputeTier.bounded_relaxation
    results: list[StructureResult] = []
    _sync(device)
    start = time.perf_counter()
    for structure in items:
        n = len(structure)
        try:
            atoms = AseAtomsAdaptor.get_atoms(structure)
            atoms.calc = calc
            steps = None
            status = ComputeStatus.ok
            if relax:
                ok, steps = _relax(atoms, settings)
                status = ComputeStatus.ok if ok else ComputeStatus.not_converged
            energy = float(atoms.get_potential_energy())
            results.append(StructureResult(status, n, energy, energy / n, max_force(atoms.get_forces()),
                                           max_stress(atoms.get_stress()), steps))
        except Exception as exc:  # one bad structure is a logged failure, never a crash or a gap
            results.append(StructureResult(ComputeStatus.failed, n, error=f"{type(exc).__name__}: {exc}"))
    _sync(device)
    wall = time.perf_counter() - start
    gpu = wall if device.startswith("cuda") else 0.0
    return TierRun(tier, backend, dict(settings), results, round(wall, 3), round(gpu, 3))


# ---------- NVIDIA ALCHEMI Toolkit backend ----------

@lru_cache(maxsize=2)
def _nvalchemi_model(model: str, device: str, dtype: str) -> Any:
    import torch
    from nvalchemi.models.mace import MACEWrapper  # GPU-host dependency, imported lazily

    m = MACEWrapper.from_checkpoint(model, device=torch.device(device), dtype=getattr(torch, dtype),
                                    enable_cueq=device.startswith("cuda"))
    m.set_config("active_outputs", {"energy", "forces", "stress"})
    return m


def _run_nvalchemi(tier: ComputeTier, items: list[Structure], settings: dict[str, Any], device: str) -> TierRun:
    """All structures in one GPU batch through the ALCHEMI Toolkit (FIRE2VariableCell for relaxations).

    Convergence uses the same definition as the ASE path, not the kit's: max per-atom force norm
    <= fmax_ev_per_a AND max |stress component| <= stress_tol_ev_per_a3 (the kit uses the stress
    Frobenius norm). Each structure's status is then re-checked from its final forces and stress
    with kiln.compute.convergence. The Toolkit counts steps for the whole batch, so a relaxed
    structure's `steps` is the batch's step count (exact when the batch holds one structure).
    """
    import torch
    from nvalchemi.data import AtomicData, Batch
    from nvalchemi.dynamics import FIRE2VariableCell
    from nvalchemi.dynamics.base import ConvergenceHook, DynamicsStage

    relax = tier == ComputeTier.bounded_relaxation
    dtype = str(settings.get("dtype", "float32"))
    torch_dtype = getattr(torch, dtype)
    model = _nvalchemi_model(str(settings["model"]), device, dtype)
    data = []
    for s in items:
        n = len(s)
        d = AtomicData.from_atoms(AseAtomsAdaptor.get_atoms(s), device="cpu", dtype=torch_dtype)
        d.forces, d.energy = torch.zeros(n, 3, dtype=torch_dtype), torch.zeros(1, 1, dtype=torch_dtype)
        d.velocities, d.stress = torch.zeros(n, 3, dtype=torch_dtype), torch.zeros(1, 3, 3, dtype=torch_dtype)
        data.append(d)
    fmax = float(settings.get("fmax_ev_per_a", 0.05))
    s_tol = float(settings.get("stress_tol_ev_per_a3", 0.001))
    hook = ConvergenceHook(criteria=[
        {"key": "forces", "threshold": fmax, "reduce_op": "norm", "reduce_dims": -1},
        {"key": "stress", "threshold": s_tol,
         "custom_op": lambda s: s.reshape(s.shape[0], -1).abs().amax(dim=-1) <= s_tol},
    ])
    opt = FIRE2VariableCell(model=model, dt=float(settings.get("dt", 0.1)),
                            n_steps=int(settings["max_steps"]) if relax else 0, convergence_hook=hook)
    for h in model.make_neighbor_hooks():
        opt.register_hook(h, stage=DynamicsStage.BEFORE_COMPUTE)
    _sync(device)
    start = time.perf_counter()
    try:
        batch = Batch.from_data_list(data, device=torch.device(device))
        if relax:
            batch = opt.run(batch)
        else:
            # A single point is one model evaluation, run the way the Toolkit runs it inside a step
            # (neighbor list in the BEFORE_COMPUTE hooks), with no position or cell update.
            # run(n_steps=0) evaluates nothing.
            opt._call_hooks(DynamicsStage.BEFORE_COMPUTE, batch)
            opt.compute(batch)
            opt._call_hooks(DynamicsStage.AFTER_COMPUTE, batch)
    except Exception as exc:  # the whole batch failed: every structure is a logged failure
        _sync(device)
        wall = time.perf_counter() - start
        failed = [StructureResult(ComputeStatus.failed, len(s), error=f"{type(exc).__name__}: {exc}") for s in items]
        return TierRun(tier, "nvalchemi", dict(settings), failed, round(wall, 3), round(wall if device.startswith("cuda") else 0.0, 3))
    _sync(device)
    wall = time.perf_counter() - start
    energies = batch.energy.detach().double().reshape(-1).cpu().numpy()
    forces = batch.forces.detach().double().cpu().numpy()
    stress = batch.stress.detach().double().reshape(-1, 3, 3).cpu().numpy()
    owner = batch.batch_idx.detach().cpu().numpy()
    steps = int(getattr(opt, "step_count", 0)) if relax else None
    results = []
    for i, s in enumerate(items):
        n = len(s)
        f, st = forces[owner == i], stress[i]
        status = ComputeStatus.ok
        if relax:
            status = ComputeStatus.ok if converged(f, st, fmax, s_tol) else ComputeStatus.not_converged
        e = float(energies[i])
        results.append(StructureResult(status, n, e, e / n, max_force(f), max_stress(st), steps))
    return TierRun(tier, "nvalchemi", dict(settings), results, round(wall, 3),
                   round(wall if device.startswith("cuda") else 0.0, 3))


def run_tier(tier: ComputeTier, inputs: dict[str, Any], settings: dict[str, Any], *,
             cache_dir: Path = mp.CACHE_DIR,
             calculator_factory: CalculatorFactory = mace_calculator) -> BackendResult:
    start = time.perf_counter()
    if tier == ComputeTier.cached_lookup:
        out = _mp_lookup(inputs, cache_dir)
    elif tier == ComputeTier.decomposition_reeval:
        out = _decomposition(inputs, cache_dir, settings, calculator_factory)
    elif tier in (ComputeTier.single_point, ComputeTier.bounded_relaxation):
        out = _mlip(tier, inputs, settings, cache_dir, calculator_factory)
    else:
        raise ValueError(f"unknown tier {tier!r}")
    # GPU-seconds are wall time of the MLIP tiers on the GPU host; the MP tiers use no GPU.
    gpu = tier in (ComputeTier.single_point, ComputeTier.bounded_relaxation)
    return BackendResult(out.status, out.result, gpu_seconds=time.perf_counter() - start if gpu else 0.0)


def structure_from_cache(formula: str, cache_dir: Path = mp.CACHE_DIR) -> ComputedStructureEntry:
    """Lowest-energy Materials Project structure for a formula, from the local cache.

    The cache holds one file per pair's chemical system (e.g. Ca-O-Ti.json), so every cached
    system that contains the formula's elements is searched, not only its own.
    """
    target = Composition(formula).reduced_formula
    elements = set(mp.chemsys_for(formula).split("-"))
    # Smallest systems first (the formula's own system if cached); MP returns the same entries for a
    # formula in every system that contains it, so the first file with a match is enough.
    candidates = sorted((p for p in Path(cache_dir).glob("*.json") if elements <= set(p.stem.split("-"))),
                        key=lambda p: (len(p.stem.split("-")), p.stem))
    for path in candidates:
        entries = [e for e in mp.load_entries(path.stem, cache_dir=cache_dir)
                   if isinstance(e, ComputedStructureEntry) and e.composition.reduced_formula == target]
        if entries:
            return min(entries, key=lambda e: e.energy_per_atom)
    raise ValueError(f"no cached Materials Project structure for {target} in {cache_dir}")


def _sync(device: str) -> None:
    """Wait for queued GPU work so wall time measures the calculation, not the launch."""
    if str(device).startswith("cuda"):
        try:
            import torch
        except ImportError:  # fake calculators in tests need no torch
            return
        if torch.cuda.is_available():
            torch.cuda.synchronize()


def _measure(atoms: Any) -> dict[str, float]:
    n = len(atoms)
    return {"energy_ev_per_atom": float(atoms.get_potential_energy()) / n,
            "max_force_ev_per_a": max_force(atoms.get_forces()),
            "max_stress_ev_per_a3": max_stress(atoms.get_stress())}


def _timed(device: str, work: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    """Run one calculation; a crash is recorded as status failed, never raised or dropped."""
    _sync(device)
    start = time.perf_counter()
    try:
        out = work()
    except Exception as exc:
        out = {"status": ComputeStatus.failed.value, "error": f"{type(exc).__name__}: {exc}"}
    _sync(device)
    wall = time.perf_counter() - start
    gpu = str(device).startswith("cuda")
    return {**out, "wall_s": round(wall, 3), "gpu_seconds": round(wall, 3) if gpu else 0.0}


def _host() -> dict[str, Any]:
    info: dict[str, Any] = {"platform": platform.platform(), "python": platform.python_version(),
                            "PYTORCH_CUDA_ALLOC_CONF": os.environ.get("PYTORCH_CUDA_ALLOC_CONF")}
    try:
        info["nvidia_driver"] = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,driver_version", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=20, check=True).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        info["nvidia_driver"] = None
    return info


def first_calcs(structure: Structure, settings: dict[str, Any], *, source: str,
                calculator_factory: CalculatorFactory | None = None) -> dict[str, Any]:
    """One single point and one bounded relaxation (force AND stress, step cap) on one structure.

    settings are the bounded_relaxation block of env/gb10/tier_settings.json: model, device,
    dtype, fmax_ev_per_a, stress_tol_ev_per_a3, max_steps. The calculator is built (and its
    weights loaded) before timing starts, so wall time covers only the calculations.
    """
    device = str(settings.get("device", "cuda"))
    calc = (calculator_factory or mace_calculator)(settings)

    def single_point() -> dict[str, Any]:
        atoms = AseAtomsAdaptor.get_atoms(structure)
        atoms.calc = calc
        return {"status": ComputeStatus.ok.value, **_measure(atoms)}

    def relaxation() -> dict[str, Any]:
        atoms = AseAtomsAdaptor.get_atoms(structure)
        atoms.calc = calc
        ok, steps = _relax(atoms, settings)
        status = ComputeStatus.ok if ok else ComputeStatus.not_converged
        return {"status": status.value, "steps": steps, "max_steps": int(settings["max_steps"]),
                **_measure(atoms), "final_volume_a3": float(atoms.get_volume()),
                "initial_volume_a3": float(structure.volume)}

    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "formula": structure.composition.reduced_formula,
        "n_atoms": len(structure),
        "source": source,
        "device": device,
        "cpu_dry_run": not device.startswith("cuda"),
        "settings": {k: settings[k] for k in sorted(settings)},
        "host": _host(),
        "single_point": _timed(device, single_point),
        "bounded_relaxation": _timed(device, relaxation),
    }


def _print_table(record: dict[str, Any]) -> None:
    print(f"{record['formula']} ({record['n_atoms']} atoms) from {record['source']} on {record['device']}"
          + ("  [CPU DRY RUN, not the GB10 result]" if record["cpu_dry_run"] else ""))
    for name in ("single_point", "bounded_relaxation"):
        r = record[name]
        if r["status"] == ComputeStatus.failed.value:
            print(f"  {name:<19} FAILED  {r['error']}")
            continue
        steps = f"  steps {r['steps']}/{r['max_steps']}" if "steps" in r else ""
        print(f"  {name:<19} {r['status']:<13} E {r['energy_ev_per_atom']:.5f} eV/atom"
              f"  max F {r['max_force_ev_per_a']:.4f} eV/A  max stress {r['max_stress_ev_per_a3']:.5f} eV/A^3"
              f"{steps}  wall {r['wall_s']} s  GPU {r['gpu_seconds']} s")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m kiln.compute.tiers")
    sub = parser.add_subparsers(dest="command", required=True)
    fc = sub.add_parser("first-calcs", help="one single point and one bounded relaxation (Task 1)")
    fc.add_argument("--formula", default="TiO2", help="oxide to take from the Materials Project cache")
    fc.add_argument("--cache-dir", type=Path, default=mp.CACHE_DIR)
    fc.add_argument("--structure-file", type=Path, help="use this CIF/POSCAR instead of the cache")
    fc.add_argument("--settings", type=Path, default=TIER_SETTINGS_PATH)
    fc.add_argument("--device", help="override the settings' device (cpu for a dry run)")
    fc.add_argument("--max-steps", type=int, help="override the step cap")
    fc.add_argument("--dtype", choices=["float32", "float64"], help="override the settings' precision")
    fc.add_argument("--out", type=Path, default=FIRST_CALCS_PATH)
    args = parser.parse_args(argv)

    settings = dict(json.loads(args.settings.read_text(encoding="utf-8"))["bounded_relaxation"])
    if args.device:
        settings["device"] = args.device
    if args.dtype:
        settings["dtype"] = args.dtype
    if args.max_steps is not None:
        settings["max_steps"] = args.max_steps
    if args.structure_file:
        structure, source = Structure.from_file(str(args.structure_file)), f"file:{args.structure_file.name}"
    else:
        entry = structure_from_cache(args.formula, args.cache_dir)
        structure, source = entry.structure, f"materials_project:{entry.entry_id}"

    record = first_calcs(structure, settings, source=source)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(record, indent=2), encoding="utf-8")
    _print_table(record)
    print(f"saved {args.out}")
    return 0 if record["single_point"]["status"] != ComputeStatus.failed.value else 1


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


if __name__ == "__main__":
    raise SystemExit(main())

