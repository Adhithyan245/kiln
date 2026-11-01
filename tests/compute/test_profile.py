from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

from kiln.budget import Budget
from kiln.compute.backends import BackendResult
from kiln.compute.cache import ResultCache
from kiln.compute.client import ComputeClient
from kiln.compute.profile import (_items, load_tier_settings, main, profile_config, read_items_file, run_profile,
                                  summarize, write_items_file)
from kiln.schemas import ComputeStatus, ComputeTier
from tests.compute.helpers import TEST_SETTINGS, make_item

SECONDS = {ComputeTier.cached_lookup: 0.0, ComputeTier.single_point: 2.0, ComputeTier.bounded_relaxation: 10.0}


class TimedBackend:
    name = "timed"

    def run(self, tier, inputs, settings):
        status = ComputeStatus.not_converged if inputs["precursor_a"] == "BaO" and tier == ComputeTier.bounded_relaxation else ComputeStatus.ok
        return BackendResult(status, {"dE_ev_per_atom": -0.01}, SECONDS[tier])

    def healthy(self):
        return True


def test_profile_goes_through_the_client_and_summarizes(tmp_path: Path) -> None:
    config = profile_config("profile-test")
    client = ComputeClient(tmp_path / "profile-test", config, TimedBackend(), ResultCache(tmp_path / "c"), TEST_SETTINGS)
    items = [make_item("PG-1"), make_item("PG-2").model_copy(update={"precursor_a": "BaO"})]
    tiers = list(SECONDS)
    requests = run_profile(items, tiers, client, lambda _: Budget(config), progress=lambda _: None)
    assert len(requests) == 6
    assert (tmp_path / "profile-test" / "compute_requests.jsonl").read_text().count("\n") == 6
    assert all(r.compute_units == 0.0 for r in requests)

    summary = summarize(requests)["tiers"]
    assert summary["single_point"]["median_gpu_seconds"] == 2.0
    assert summary["bounded_relaxation"]["median_relative_to_single_point"] == pytest.approx(5.0)
    assert summary["bounded_relaxation"]["status"]["not_converged"] == 1


def test_cached_requests_are_excluded_from_timing(tmp_path: Path) -> None:
    config = profile_config("profile-test")
    client = ComputeClient(tmp_path / "profile-test", config, TimedBackend(), ResultCache(tmp_path / "c"), TEST_SETTINGS)
    item = make_item()
    run_profile([item, item], [ComputeTier.single_point], client, lambda _: Budget(config), progress=lambda _: None)
    requests = run_profile([item], [ComputeTier.single_point], client, lambda _: Budget(config), progress=lambda _: None)
    assert requests[0].status == ComputeStatus.cached
    stats = summarize(requests)["tiers"]["single_point"]
    assert stats["median_gpu_seconds"] is None and stats["status"]["cached"] == 1


def test_items_file_round_trips_and_keeps_split_and_order(tmp_path: Path) -> None:
    items = [make_item("PG-3"), make_item("PG-1").model_copy(update={"split": "heldout"}), make_item("PG-2")]
    path = tmp_path / "items.jsonl"
    write_items_file(path, items)
    assert read_items_file(path) == items
    assert [i.item_id for i in _items("dev", path)] == ["PG-3", "PG-2"]
    assert [i.item_id for i in _items("heldout", path)] == ["PG-1"]


def test_items_file_gives_the_same_seeded_sample_as_the_ledger(tmp_path: Path, monkeypatch) -> None:
    dev = [make_item(f"PG-{n}") for n in range(30)]
    monkeypatch.setattr("kiln.data.load_items", lambda split: dev if split == "dev" else [])
    path = tmp_path / "items.jsonl"
    assert main(["--export-items", str(path)]) == 0
    sample = lambda items: [i.item_id for i in random.Random(0).sample(items, 20)]  # noqa: E731
    assert sample(_items("dev", path)) == sample(_items("dev"))


def _fake_ledger(path: Path) -> Path:
    # Made-up ledger: ten oxides paired with TiO2, two samples with no heating temperature, and a
    # stand-in label field that must never reach the items file.
    oxides = ["CaO", "MgO", "BaO", "SrO", "ZnO", "NiO", "CoO", "CuO", "FeO", "MnO"]
    samples = [{"sample_id": f"S{n}", "precursors": [{"formula": ox}, {"formula": "TiO2"}],
                "synthesis": {"heating_temperature": 900 + n}, "xrd_label": "SECRET"} for n, ox in enumerate(oxides)]
    samples[3]["synthesis"] = {"heating_temperature": None}
    samples[7]["synthesis"] = None
    path.write_text(json.dumps({"samples": samples}), encoding="utf-8")
    return path


def test_skip_missing_temperature_exports_only_complete_items(tmp_path: Path, monkeypatch, capsys) -> None:
    ledger = _fake_ledger(tmp_path / "ledger.json")
    monkeypatch.setattr("kiln.data.DEFAULT_LEDGER", ledger)
    out = tmp_path / "items.jsonl"
    assert main(["--export-items", str(out), "--skip-missing-temperature"]) == 0
    printed = capsys.readouterr().out
    assert "left out 2 samples" in printed and "S3" not in printed and "S7" not in printed
    items = read_items_file(out)
    assert sorted(i.item_id for i in items) == sorted(f"S{n}" for n in range(10) if n not in (3, 7))
    assert "SECRET" not in out.read_text(encoding="utf-8")


def test_export_without_the_flag_still_fails_on_a_missing_temperature(tmp_path: Path, monkeypatch) -> None:
    from kiln.data import LedgerRecordError, load_items

    ledger = _fake_ledger(tmp_path / "ledger.json")
    monkeypatch.setattr("kiln.data.load_items", lambda split: load_items(split, ledger))
    with pytest.raises(LedgerRecordError):
        main(["--export-items", str(tmp_path / "items.jsonl")])


def test_bundled_settings_load_and_satisfy_the_client(tmp_path: Path) -> None:
    settings = load_tier_settings(Path(__file__).parents[2] / "env" / "gb10" / "tier_settings.json")
    assert set(settings) == set(ComputeTier)
    # float32 decided in docs/compute-decisions.md; part of the cache key, so profile and fill with it
    assert settings[ComputeTier.single_point]["dtype"] == settings[ComputeTier.bounded_relaxation]["dtype"] == "float32"
    ComputeClient(tmp_path / "x", profile_config("x"), TimedBackend(), ResultCache(tmp_path / "c"), settings)


def test_h100_settings_are_the_gb10_settings_on_the_toolkit_backend(monkeypatch) -> None:
    root = Path(__file__).parents[2]
    gb10 = load_tier_settings(root / "env" / "gb10" / "tier_settings.json")
    monkeypatch.setenv("KILN_TIER_SETTINGS", str(root / "env" / "h100" / "tier_settings.json"))
    h100 = load_tier_settings()
    toolkit = {"backend", "fire_tmax", "fire_maxstep", "dt"}
    for tier in ComputeTier:
        assert {k: v for k, v in h100[tier].items() if k not in toolkit} == gb10[tier]   # same physics otherwise
    assert h100[ComputeTier.bounded_relaxation]["backend"] == h100[ComputeTier.single_point]["backend"] == "nvalchemi+ase"
    monkeypatch.delenv("KILN_TIER_SETTINGS")
    monkeypatch.chdir(root)
    assert load_tier_settings() == gb10                                                     # default unchanged
