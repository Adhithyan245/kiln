from __future__ import annotations

from pathlib import Path

import pytest

from kiln.tools import mp
from tests.tools.mp_fixtures import ca_ti_o_entries


def test_chemsys_is_sorted_and_deduplicated() -> None:
    assert mp.chemsys_for("TiO2", "CaO") == "Ca-O-Ti"
    assert mp.chemsys_for("Li2CO3", "TiO2") == "C-Li-O-Ti"


def test_reaction_energy_finds_the_favoured_product() -> None:
    result = mp.reaction_energy("CaO", "TiO2", ca_ti_o_entries())
    assert result.products == "CaTiO3"
    assert result.dE_ev_per_atom == pytest.approx(-0.04, abs=1e-9)
    assert result.mixing_ratio == pytest.approx(0.4, abs=1e-9)  # per-atom fraction of CaO


def test_no_reaction_is_zero() -> None:
    entries = [e for e in ca_ti_o_entries() if e.composition.reduced_formula != "CaTiO3"]
    assert mp.reaction_energy("CaO", "TiO2", entries).dE_ev_per_atom == pytest.approx(0.0, abs=1e-9)


def test_cache_round_trip_keeps_structures_and_corrections(tmp_path: Path) -> None:
    entries = ca_ti_o_entries()
    mp._write_entries(tmp_path / "Ca-O-Ti.json", entries)
    loaded = mp.load_entries("Ca-O-Ti", cache_dir=tmp_path)
    assert [e.entry_id for e in loaded] == [e.entry_id for e in entries]
    assert all(e.structure is not None for e in loaded)
    assert [e.correction for e in loaded] == pytest.approx([e.correction for e in entries])
    assert [e.energy for e in loaded] == pytest.approx([e.energy for e in entries])


def test_missing_cache_raises(tmp_path: Path) -> None:
    with pytest.raises(mp.MissingCache):
        mp.load_entries("Ca-O-Ti", cache_dir=tmp_path)


def test_candidates_apply_the_hull_window(tmp_path: Path) -> None:
    mp._write_entries(tmp_path / "Ca-O-Ti.json", ca_ti_o_entries())
    ids = {e.entry_id.split("-", 2)[2] for e in mp.candidates("CaO", "TiO2", cache_dir=tmp_path)}
    assert "CaTiO3_meta" in ids and "Ca2O2" not in ids
    assert {"Ca", "Ti", "O2", "CaO", "TiO2", "CaTiO3"} <= ids


def test_fetch_skips_cached_system_without_network(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("MP_API_KEY", raising=False)
    mp._write_entries(tmp_path / "Ca-O-Ti.json", ca_ti_o_entries())
    assert mp.fetch_chemsys("Ca-O-Ti", cache_dir=tmp_path) == tmp_path / "Ca-O-Ti.json"


def test_fetch_without_key_fails_loudly(tmp_path: Path, monkeypatch) -> None:
    pytest.importorskip("mp_api")
    monkeypatch.delenv("MP_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="MP_API_KEY"):
        mp.fetch_chemsys("Ca-O-Ti", cache_dir=tmp_path)
