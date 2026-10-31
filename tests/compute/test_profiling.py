from __future__ import annotations

import json
from pathlib import Path

import pytest

from kiln.compute.profiling import main, night2_fit, propose, propose_budget, propose_prices

# Made-up profiler output, in the shape `python -m kiln.compute.profile` writes.
SUMMARY = {
    "host": "test-host", "machine": "aarch64",
    "tiers": {
        "cached_lookup": {"n": 20, "median_gpu_seconds": 0.0, "p90_gpu_seconds": 0.0, "status": {"ok": 20}},
        "single_point": {"n": 20, "median_gpu_seconds": 2.0, "p90_gpu_seconds": 3.0, "status": {"ok": 20}},
        "bounded_relaxation": {"n": 20, "median_gpu_seconds": 12.0, "p90_gpu_seconds": 30.0,
                               "status": {"ok": 18, "not_converged": 2}},
        "decomposition_reeval": {"n": 20, "median_gpu_seconds": 0.0, "p90_gpu_seconds": 0.0, "status": {"ok": 20}},
    },
}


def test_prices_are_in_single_point_units_with_a_floor() -> None:
    prices = propose_prices(SUMMARY["tiers"])
    assert prices == {"cached_lookup": 0.1, "single_point": 1.0, "bounded_relaxation": 6.0,
                      "decomposition_reeval": 0.2}


def test_cached_lookup_is_never_free() -> None:
    assert propose_prices(SUMMARY["tiers"], floor=0.25)["cached_lookup"] == 0.25


def test_decomposition_adds_any_gpu_time_it_used() -> None:
    tiers = {**SUMMARY["tiers"], "decomposition_reeval": {"median_gpu_seconds": 1.0}}
    assert propose_prices(tiers)["decomposition_reeval"] == pytest.approx(0.7)   # 2 x 0.1 + 1.0 / 2.0


def test_budget_is_one_escalation_path() -> None:
    assert propose_budget(propose_prices(SUMMARY["tiers"])) == pytest.approx(7.3)   # 0.1 + 1 + 6 + 0.2


def test_night2_fit_worst_case() -> None:
    fit = night2_fit(2.0, 7.3, hours=11, workers=1)
    # 369 x 4 x 3 items, each spending 7.3 units x 2 s = 14.6 GPU-s -> about 17.96 GPU hours
    assert fit["main_run_worst_case_gpu_hours"] == pytest.approx(17.96, abs=0.01)
    assert fit["usable_gpu_hours"] == pytest.approx(7.7)
    assert fit["main_run_fits"] is False and fit["second_budget_level_fits"] is False
    more = night2_fit(2.0, 7.3, hours=11, workers=4)
    assert more["main_run_fits"] is True and more["second_budget_level_fits"] is False


def test_missing_single_point_is_refused() -> None:
    with pytest.raises(ValueError):
        propose_prices({"bounded_relaxation": {"median_gpu_seconds": 5.0}})
    with pytest.raises(ValueError):
        propose_prices({"single_point": {"median_gpu_seconds": 2.0}})


def test_command_writes_the_proposal(tmp_path: Path) -> None:
    summary = tmp_path / "profile.json"
    summary.write_text(json.dumps(SUMMARY))
    out = tmp_path / "prices_proposal.json"
    assert main(["--summary", str(summary), "--hours", "11", "--workers", "2", "--out", str(out)]) == 0
    saved = json.loads(out.read_text())
    assert saved["status"].startswith("PROPOSAL")
    assert saved["tier_prices"]["bounded_relaxation"] == 6.0
    assert saved["max_compute_units_per_item"] == pytest.approx(7.3)
    assert saved["measurements"]["bounded_relaxation"]["status"] == {"ok": 18, "not_converged": 2}
    assert saved["measured_on"]["host"] == "test-host"
    assert propose(SUMMARY, hours=11)["night2"]["assumptions"].startswith("369 held-out items")


def test_cache_aware_estimate_counts_one_calculation_per_pair_and_tier() -> None:
    fit = night2_fit(2.0, 7.3, hours=11, workers=1, items=346,
                     tier_p90_s={"single_point": 3.0, "bounded_relaxation": 30.0, "cached_lookup": 0.0})
    assert fit["main_run_with_cache_gpu_hours_p90"] == pytest.approx(346 * 33.0 / 3600, abs=0.01)
    assert fit["main_run_fits_with_cache"] is True
    assert fit["assumptions"].startswith("346 held-out items")


def test_items_option_reaches_the_proposal(tmp_path: Path) -> None:
    summary = tmp_path / "profile.json"
    summary.write_text(json.dumps(SUMMARY))
    out = tmp_path / "p.json"
    assert main(["--summary", str(summary), "--hours", "11", "--items", "346", "--out", str(out)]) == 0
    assert json.loads(out.read_text())["night2"]["assumptions"].startswith("346 held-out items")
