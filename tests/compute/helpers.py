"""Shared test helpers. Lives in an importable module so spawned processes can use it."""
from __future__ import annotations

from pathlib import Path

from kiln.budget import Budget
from kiln.compute.backends import StubBackend
from kiln.compute.cache import ResultCache
from kiln.compute.client import ComputeClient
from kiln.schemas import ComputeTier, Item, RunConfig

# Test-only prices and settings. Real values are frozen from profiling (protocol OPEN-02/03).
TEST_PRICES = {
    "cached_lookup": 0.1,
    "single_point": 1.0,
    "bounded_relaxation": 4.0,
    "decomposition_reeval": 2.0,
}
TEST_SETTINGS = {
    ComputeTier.cached_lookup: {"source": "materials_project"},
    ComputeTier.single_point: {"model": "stub"},
    ComputeTier.bounded_relaxation: {
        "model": "stub", "fmax_ev_per_a": 0.05, "stress_tol_ev_per_a3": 0.001, "max_steps": 200,
    },
    ComputeTier.decomposition_reeval: {"model": "stub"},
}


def make_config(run_id: str = "test-run", max_units: float = 10.0) -> RunConfig:
    return RunConfig(
        run_id=run_id, condition="C4", seed=0, model="stub",
        max_compute_units_per_item=max_units, tier_prices=dict(TEST_PRICES),
    )


def make_item(item_id: str = "PG-dev-0001") -> Item:
    # Made-up development item for tests; no label or ledger data.
    return Item(
        item_id=item_id, source="precursor_genome", precursor_a="CaCO3", precursor_b="TiO2",
        temperature_c=900.0, split="dev",
    )


def make_client(run_dir: Path, cache_dir: Path, backend: StubBackend | None = None,
                config: RunConfig | None = None) -> ComputeClient:
    config = config or make_config(run_id=run_dir.name)
    return ComputeClient(run_dir, config, backend or StubBackend(), ResultCache(cache_dir), TEST_SETTINGS)


def request_many(run_dir: str, cache_dir: str, n: int, barrier, results) -> None:
    """Child process: wait for every racer, then log n requests and report their ids."""
    client = make_client(Path(run_dir), Path(cache_dir))
    budget = Budget(make_config(run_id=Path(run_dir).name, max_units=100.0))
    barrier.wait()
    ids = [
        client.request(make_item(), "thermo", ComputeTier.single_point, "race test",
                       {"formula": f"X{i}"}, budget).request_id
        for i in range(n)
    ]
    results.put(ids)
