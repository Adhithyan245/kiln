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
