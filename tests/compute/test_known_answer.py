"""NVIDIA's ALCHEMI known-answer test, reproduced with Kiln's MACE setup: a rattled 64-atom Si
diamond cell relaxed at fixed cell must reach -5.41238 eV/atom (MACE-MPA-0 medium, float32).
GB10 / CUDA only; the passing kit run is logged in results/gb10/known_answer_si_20261031.jsonl."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("ase", reason="compute extras not installed")
pytest.importorskip("mace", reason="mace-torch not installed (GB10 only)")
torch = pytest.importorskip("torch")

EXPECTED_EV_PER_ATOM = -5.41238
LOG = Path(__file__).resolve().parents[2] / "results" / "gb10" / "known_answer_si_20261031.jsonl"


def test_logged_kit_run_passed() -> None:
    record = json.loads(LOG.read_text(encoding="utf-8"))   # the kit writes one pretty-printed JSON object
    r = record["result"]
    assert r["nvalchemi_E_per_atom"] == pytest.approx(EXPECTED_EV_PER_ATOM, abs=1e-4)
    assert r["ase_ref_relaxed_E_per_atom"] == pytest.approx(EXPECTED_EV_PER_ATOM, abs=1e-4)
    assert record["versions"]["gpu"] == "NVIDIA GB10"


@pytest.mark.skipif(not torch.cuda.is_available(), reason="needs a CUDA GPU (GB10)")
def test_kiln_mace_setup_reproduces_the_known_answer() -> None:
    from ase.build import bulk
    from ase.optimize import FIRE

    from kiln.compute.tiers import mace_calculator

    si = bulk("Si", "diamond", a=5.43, cubic=True).repeat((2, 2, 2))
    si.rattle(0.05, seed=0)
    si.calc = mace_calculator({"model": "medium-mpa-0", "device": "cuda", "dtype": "float32"})
    FIRE(si, logfile=None).run(fmax=0.01, steps=2000)
    assert si.get_potential_energy() / len(si) == pytest.approx(EXPECTED_EV_PER_ATOM, abs=2e-4)
