import gzip
import json
from collections import Counter

import numpy as np
import pytest

from kiln import recipe
from kiln import recipe_benchmark as rb
from kiln import recipe_rank as rr


def test_family_counts():
    assert rr.family_counts("BaCO3", "TiO2") == {"n_hydroxide": 0, "n_peroxide": 0, "n_salt": 0, "n_carbonate": 1}
    assert rr.family_counts("BaO2", "LiOH") == {"n_hydroxide": 1, "n_peroxide": 1, "n_salt": 0, "n_carbonate": 0}
    assert rr.family_counts("NH4H2PO4", "Li2CO3")["n_salt"] == 1


def test_thermal_features(tmp_path):
    table = tmp_path / "t.csv"
    table.write_text('formula,melting_point_c,decomposes_at_c\n"A2O","500","unknown"\n"BO","1500","700"\n'
                     '"CO2x","unknown","unknown"\n', encoding="utf-8")
    t = rr.thermal("A2O", "BO", 900.0, str(table))
    assert t["melts_below_T"] == 1 and t["decomposes_below_T"] == 1
    assert t["T_over_Tmelt_min"] == pytest.approx((900 + 273.15) / (500 + 273.15))
    assert rr.thermal("CO2x", "CO2x", 900.0, str(table))["T_over_Tmelt_min"] == 0.5


def test_expected_random_rr():
    assert rb._expected_random_rr(1, 1) == 1.0
    assert rb._expected_random_rr(2, 1) == pytest.approx(0.75)
    assert rb._expected_random_rr(3, 3) == 1.0


def _groups(n=40, seed=0):
    rng = np.random.default_rng(seed)
    out = []
    for i in range(n):
        X = rng.normal(size=(5, len(rr.FEATURES)))
        hit = np.zeros(5)
        hit[int(np.argmax(X[:, 0]))] = 1   # the published pair is the one with the largest feature 0
        out.append(rr.Group(f"T{i}", f"S{i}", X, hit, [("a", "b")] * 5))
    return out


def test_fit_learns_a_separable_ranking():
    gs = _groups()
    w, mu, sd = rr.fit(gs, 0.0)
    assert int(np.argmax(w)) == 0
    assert rr.mrr(gs, rr.model_score(w, mu, sd)) > 0.95
    assert rr.cross_validate(gs, l2s=(0.03,))[0.03] > 0.9


def test_ranker_round_trip(tmp_path):
    w = np.arange(len(rr.FEATURES), dtype=float)
    r = rr.Ranker(w, np.zeros_like(w), np.ones_like(w), Counter({"TiO2": 3}), meta={"summary": "s"})
    path = tmp_path / "ranker.json"
    r.save(path)
    back = rr.Ranker.load(path)
    assert back.features == rr.FEATURES and back.counts["TiO2"] == 3 and back.meta["summary"] == "s"
    assert np.allclose(back.w, w)
    assert rr.Ranker.load(tmp_path / "missing.json") is None


def test_gzipped_cache_is_read(tmp_path):
    rows = [{"composition": {"Ba": 1, "O": 1}, "energy": -10.0, "correction": 0.0, "entry_id": "mp-1"}]
    (tmp_path / "Ba-O.json.gz").write_bytes(gzip.compress(json.dumps(rows).encode()))
    (tmp_path / "O-Ti.json").write_text(json.dumps(rows), encoding="utf-8")
    assert recipe.cached_systems(tmp_path) == ["Ba-O", "O-Ti"]
    entries = recipe._energies("Ba-O", str(tmp_path))
    assert len(entries) == 1 and entries[0].uncorrected_energy == -10.0


@pytest.mark.parametrize("typed, expected", [
    ("KMno4", "KMnO4"), ("kmno4", "KMnO4"), ("nacl", "NaCl"), ("BATIO3", "BaTiO3"), ("LIFEPO4", "LiFePO4"),
    ("ca(oh)2", "Ca(OH)2"), ("CUO", "CuO"), ("CO", "CO"), ("Co", "Co"), ("CoO", "CoO"), ("BaTiO3", "BaTiO3"),
    ("Qq2", "Qq2"),
])
def test_normalize_formula(typed, expected):
    assert recipe.normalize_formula(typed) == expected


def test_fallback_dirs_and_missing_systems(tmp_path, monkeypatch):
    rows = [{"composition": {"Ba": 1, "O": 1}, "energy": -10.0, "correction": 0.0, "entry_id": "mp-1"}]
    main, live = tmp_path / "main", tmp_path / "live"
    main.mkdir()
    live.mkdir()
    (live / "Ba-C-O-Ti.json").write_text(json.dumps(rows), encoding="utf-8")
    monkeypatch.setattr(recipe, "FALLBACK_DIRS", [live])
    assert recipe.has_system("Ba-C-O-Ti", main) and "Ba-C-O-Ti" in recipe.cached_systems(main)
    assert len(recipe._energies("Ba-C-O-Ti", str(main))) == 1
    missing = recipe.missing_systems("BaTiO3", ["BaCO3", "TiO2", "BaO"], main)
    assert "Ba-C-O-Ti" not in missing and "Ba-O-Ti" in missing


def test_fetch_energies_pages_and_writes_compact_rows(tmp_path, monkeypatch):
    import io
    entry = {"@module": "pymatgen.entries.computed_entries", "@class": "ComputedEntry",
             "composition": {"Ba": 1.0, "O": 1.0}, "energy": -12.0, "correction": -0.5,
             "energy_adjustments": [], "entry_id": "mp-1-GGA", "parameters": {}, "data": {}}
    pages = [{"data": [{"entries": {"GGA": entry}}], "meta": {"total_doc": 2}},
             {"data": [{"entries": {"GGA": {**entry, "entry_id": "mp-2-GGA"}}}], "meta": {"total_doc": 2}}]
    seen = []

    def fake_urlopen(req, timeout):
        seen.append(req.full_url)
        assert req.get_header("X-api-key") == "k"
        return io.BytesIO(json.dumps(pages[len(seen) - 1]).encode())
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    path = recipe.fetch_energies("Ba-O", tmp_path, "k")
    rows = json.loads(path.read_text(encoding="utf-8"))
    assert [r["entry_id"] for r in rows] == ["mp-1-GGA", "mp-2-GGA"] and len(seen) == 2
    assert "chemsys=Ba%2CO%2CBa-O" in seen[0] and "_skip=1" in seen[1]
    e = recipe._energies("Ba-O", str(tmp_path))[0]
    assert e.uncorrected_energy == -12.0 and e.correction == -0.5


def test_balance_n_matches_pairs_and_handles_other_sizes():
    pair = recipe.balance("BaCO3", "TiO2", "BaTiO3")
    assert pair == recipe.balance_n(("BaCO3", "TiO2"), "BaTiO3") and pair.coeffs == (1.0, 1.0)
    triple = recipe.balance_n(("BaCO3", "CuO", "Y2O3"), "YBa2Cu3O7")
    assert triple.coeffs == (2.0, 3.0, 0.5) and triple.gases["CO2"] == 2.0
    single = recipe.balance_n(("Li2CO3",), "Li2O")
    assert single.coeffs == (1.0,) and single.gases["CO2"] == 1.0
    assert recipe.balance_n(("BaCO3", "TiO2", "BaO"), "BaTiO3") is None   # more than one way


def test_route_sizes_and_candidate_routes():
    assert recipe.route_sizes("CuO") == (1, 2) and recipe.route_sizes("BaTiO3") == (2,)
    assert recipe.route_sizes("YBa2Cu3O7") == (2, 3) and recipe.route_sizes("CO2") == ()
    pool = ["BaCO3", "CuO", "Y2O3", "TiO2", "Li2CO3"]
    routes = {combo for combo, _ in recipe.candidate_routes("YBa2Cu3O7", pool)}
    assert routes == {("BaCO3", "CuO", "Y2O3")}
    assert {combo for combo, _ in recipe.candidate_routes("Li2O", pool)} == {("Li2CO3",)}
    assert recipe.candidate_routes("YBa2Cu3O7", pool, routes="pairs") == []


def test_doped_target_uses_the_hull_energy(tmp_path):
    from pymatgen.entries.computed_entries import ComputedEntry
    rows = []
    for formula, e in {"Ba": -1.9, "Sr": -1.6, "Ti": -7.8, "O": -4.9, "BaO": -11.0, "SrO": -11.5,
                       "TiO2": -26.9, "BaTiO3": -40.5, "SrTiO3": -41.0}.items():
        c = ComputedEntry(formula, e)
        rows.append({"composition": c.composition.as_dict(), "energy": e, "correction": 0.0, "entry_id": formula})
    b = recipe.balance_n(("BaO", "SrO", "TiO2"), "Ba0.9Sr0.1TiO3")
    (tmp_path / f"{recipe.mp.chemsys_for('BaO', 'SrO', 'TiO2')}.json").write_text(json.dumps(rows), encoding="utf-8")
    c = recipe.screen_route("Ba0.9Sr0.1TiO3", 1200, ("BaO", "SrO", "TiO2"), b, cache_dir=tmp_path)
    assert c.status == "ok" and c.target_from_hull and set(c.competing_phases) == {"BaTiO3", "SrTiO3"}
    expected = (0.9 * -40.5 + 0.1 * -41.0) - (0.9 * -11.0 + 0.1 * -11.5 + -26.9)
    assert c.dE_mp_ev_per_atom == pytest.approx(expected / (0.9 * 2 + 0.1 * 2 + 3))
    assert any("best case" in f for f in c.flags)
