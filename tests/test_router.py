from __future__ import annotations

import json
from pathlib import Path

import pytest

from kiln import router
from kiln.router import NO_COMPETITOR, PairRecord, Policy, best_policy, cross_validate, evaluate, relaxation_effect

T = -0.05
PRICES = {"cached_lookup": 0.1, "single_point": 1.0, "bounded_relaxation": 30.0, "decomposition_reeval": 0.2}


def rec(a, b, mp, comp=NO_COMPETITOR, sp=None, rx=None):
    return PairRecord(a, b, mp, comp, sp, rx)


def test_threshold_comes_from_the_frozen_rules():
    assert router.driving_force_threshold() == pytest.approx(-0.05)


def test_flip_is_a_change_of_side_and_unknown_without_a_single_point():
    assert rec("A", "B", -0.04, sp=-0.06).flips(T) is True
    assert rec("A", "B", -0.04, sp=-0.045).flips(T) is False
    assert rec("A", "B", -0.04).flips(T) is None


def test_evaluate_counts_caught_unknown_and_units():
    pairs = [rec("A", "B", -0.049, sp=-0.06),      # flip, near the threshold
             rec("A", "C", 0.0, comp=0.01, sp=-0.06),  # flip, via a near-hull competitor
             rec("B", "C", -0.3, sp=-0.31),         # far from the threshold: no flip
             rec("C", "D", -0.051)]                 # near the threshold but never computed
    s = evaluate(pairs, Policy(window=0.01, competitor=0.02), T, PRICES)
    assert (s.escalated, s.caught, s.known_flips, s.unknown) == (3, 2, 2, 1)
    assert s.units == pytest.approx(4 * 0.1 + 3 * 1.0)
    assert evaluate(pairs, Policy(0.0, 0.0), T, PRICES).caught == 0


def test_best_policy_is_the_cheapest_that_catches_every_flip():
    pairs = [rec("A", "B", -0.045, sp=-0.06), rec("A", "C", -0.2, sp=-0.21), rec("B", "C", 0.0, sp=0.0)]
    pol = best_policy(pairs, T, PRICES)
    assert evaluate(pairs, pol, T, PRICES).caught == 1
    assert pol.window == pytest.approx(0.005) and pol.competitor == 0.0


def test_cross_validation_holds_out_by_precursor():
    pairs = [rec("A", "B", -0.045, sp=-0.06), rec("C", "D", -0.046, sp=-0.06), rec("A", "C", -0.3, sp=-0.3)]
    cv = cross_validate(pairs, T, PRICES)
    assert cv["folds"] == 4 and cv["held_out_pairs"] == 6   # each pair held out once per precursor
    assert cv["known_flips"] == 4


def test_relaxation_effect():
    pairs = [rec("A", "B", -0.04, sp=-0.06, rx=-0.061), rec("A", "C", -0.04, sp=-0.049, rx=-0.052)]
    eff = relaxation_effect(pairs, T)
    assert eff["pairs"] == 2 and eff["category_changed"] == 1
    assert eff["max_abs_diff_ev_per_atom"] == pytest.approx(0.003)
    assert eff["max_logit_shift"] == pytest.approx(0.06)


def test_load_pairs_merges_runs_and_skips_failures(tmp_path: Path):
    def line(tier, status, dE, a="CaO", b="TiO2", **extra):
        return json.dumps({"tier": tier, "status": status, "inputs": {"precursor_a": a, "precursor_b": b},
                           "result": {"dE_ev_per_atom": dE, **extra}, "compute_units": 1.0,
                           "moved_toward_label": True})   # label-derived: must be ignored
    for run, lines in {"C4-x-s0-heldout": [line("cached_lookup", "cached", -0.04, competitor_e_hull_ev_per_atom=0.02),
                                           line("bounded_relaxation", "failed", -9.0)],
                       "C4-x-s1-heldout": [line("single_point", "ok", -0.06, a="TiO2", b="CaO"),
                                           line("bounded_relaxation", "ok", -0.061)]}.items():
        (tmp_path / run).mkdir()
        (tmp_path / run / "compute_requests.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    [p] = router.load_pairs(tmp_path)
    assert (p.precursor_a, p.precursor_b) == ("CaO", "TiO2")
    assert (p.dE_mp, p.competitor_e_hull, p.dE_single_point, p.dE_relaxation) == (-0.04, 0.02, -0.06, -0.061)
