from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("pymatgen", reason="compute extras (pymatgen) not installed; see env/gb10/setup.sh")
pytest.importorskip("ase", reason="compute extras (ase) not installed; see env/gb10/setup.sh")

from kiln import recipe  # noqa: E402
from kiln.recipe import Candidate, balance, close_calls, find, gas_ts_ev  # noqa: E402
from kiln.tools import mp  # noqa: E402
from tests.compute.test_tiers import FakeMLIP  # noqa: E402
from tests.tools.mp_fixtures import ca_ti_o_entries  # noqa: E402

FAKE = {"model": "fake", "device": "cpu"}


@pytest.fixture
def cache_dir(tmp_path: Path) -> Path:
    mp._write_entries(tmp_path / "Ca-O-Ti.json", ca_ti_o_entries())
    return tmp_path


def test_balance_carbonate_releases_co2():
    b = balance("BaCO3", "TiO2", "BaTiO3")
    assert (b.a, b.b) == (1.0, 1.0)
    assert b.gases == {"CO2": 1.0, "O2": 0.0}
    assert b.equation("BaCO3", "TiO2", "BaTiO3") == "1 BaCO3 + 1 TiO2 -> BaTiO3 + 1 CO2"


def test_balance_takes_oxygen_from_air():
    b = balance("Li2CO3", "MnO", "LiMn2O4")
    assert b.gases["O2"] == pytest.approx(-0.75)
    assert "0.75 O2 ->" in b.equation("Li2CO3", "MnO", "LiMn2O4")


@pytest.mark.parametrize("pa, pb, target", [
    ("CaO", "TiO2", "BaTiO3"),      # Ba missing
    ("CaO", "ZrO2", "CaO"),         # ZrO2 not needed, and Zr cannot leave as a gas
    ("BaCO3", "BaO2", "BaTiO3"),    # Ti missing
    ("NiO", "TiO2", "TiO2"),        # NiO not needed
])
def test_balance_rejects(pa, pb, target):
    assert balance(pa, pb, target) is None


def test_gas_entropy_grows_with_temperature():
    assert gas_ts_ev("CO2", 900) > gas_ts_ev("CO2", 25) > 0
    # 1173 K, S about 277 J/(mol K): about 3.4 eV per CO2 molecule
    assert gas_ts_ev("CO2", 900) == pytest.approx(3.37, abs=0.05)


def test_find_screens_with_cached_energies(cache_dir):
    r = find("CaTiO3", 1000, n_check=3, cache_dir=cache_dir, precursors=["CaO", "TiO2"])
    assert r.n_pairs_considered == 1 and r.n_checked == 0   # one candidate: nothing to separate
    c = r.candidates[0]
    assert c.status == "ok"
    assert c.dE_mp_ev_per_atom == pytest.approx(-0.04)     # mp_fixtures: -0.2 eV per 5 atoms
    assert c.dG_mp_ev_per_atom == pytest.approx(-0.04)     # no gas in or out
    assert c.target_e_hull_ev_per_atom == pytest.approx(0.0)
    assert r.compute_units == pytest.approx(0.1)


def test_missing_cache_is_reported_not_guessed(tmp_path):
    r = find("CaTiO3", 1000, n_check=0, cache_dir=tmp_path, precursors=["CaO", "TiO2"])
    assert r.candidates[0].status == "no_mp_data"
    assert r.candidates[0].dG is None


def test_close_calls_only_when_order_is_in_doubt():
    def cand(name, dg):
        return Candidate(name, "X", "", dG_mp_ev_per_atom=dg)

    clear = [cand("A", -0.50), cand("B", -0.20), cand("C", -0.10)]
    assert close_calls(clear, 3, 0.05) == []
    tight = [cand("A", -0.30), cand("B", -0.27), cand("C", -0.10)]
    assert [c.precursor_a for c in close_calls(tight, 3, 0.05)] == ["A", "B"]


def test_check_recomputes_with_mlip_energies(cache_dir):
    b = balance("CaO", "TiO2", "CaTiO3")
    c = Candidate("CaO", "TiO2", "")
    recipe.check(c, "CaTiO3", 1000, b, FAKE, cache_dir=cache_dir,
                 calculator_factory=lambda s: FakeMLIP(shift={"CaTiO3": -0.01}))
    # 0.01 eV/atom lower for CaTiO3 (5 atoms) deepens the reaction by 0.05 eV over 5 reactant atoms
    assert c.dG_mlip_ev_per_atom == pytest.approx(-0.05, abs=1e-6)
    assert c.dG == c.dG_mlip_ev_per_atom
    assert c.compute_units == pytest.approx(1.0)


def test_byproducts_are_the_targets_hull_neighbours(cache_dir):
    c = find("CaTiO3", 1000, n_check=0, cache_dir=cache_dir, precursors=["CaO", "TiO2"]).candidates[0]
    # mp_fixtures: CaTiO3 is 0.2 eV per 5 atoms below CaO + TiO2
    assert c.target_depth_ev_per_atom == pytest.approx(-0.04)
    assert c.competing_phases == ["CaO", "TiO2"]
    assert not any("byproducts" in n for n in c.notes)   # 40 meV/atom is not shallow


def test_compact_cache_gives_the_same_screen(cache_dir, tmp_path):
    out = tmp_path / "energies"
    assert recipe.compact_cache(cache_dir, out) == 1
    assert "structure" not in (out / "Ca-O-Ti.json").read_text(encoding="utf-8")
    full = find("CaTiO3", 1000, n_check=0, cache_dir=cache_dir, precursors=["CaO", "TiO2"]).candidates[0]
    small = find("CaTiO3", 1000, n_check=0, cache_dir=out, precursors=["CaO", "TiO2"]).candidates[0]
    assert small.dG == pytest.approx(full.dG)
    assert small.competing_phases == full.competing_phases
