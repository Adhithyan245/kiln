from __future__ import annotations

import json
import multiprocessing as mp
from pathlib import Path

import pytest

from kiln.budget import Budget, BudgetExceeded
from kiln.compute import client as client_module
from kiln.compute.accounting import MissingPrice
from kiln.compute.backends import BackendResult, StubBackend
from kiln.compute.cache import ResultCache
from kiln.compute.client import ComputeClient
from kiln.schemas import (
    Artifact, Claim, ComputeRequest, ComputeStatus, ComputeTier, Cost, RunConfig, VerifierStatus,
)
from kiln.verifier import verify

from tests.compute.helpers import (
    TEST_SETTINGS, make_client, make_config, make_item, request_many,
)

INPUTS = {"formula": "CaTiO3"}


@pytest.fixture
def paths(tmp_path: Path) -> tuple[Path, Path]:
    return tmp_path / "runs" / "test-run", tmp_path / "cache"


def read_log(run_dir: Path) -> list[dict]:
    return [json.loads(line) for line in (run_dir / "compute_requests.jsonl").read_text().splitlines()]


def ask(client: ComputeClient, budget: Budget, tier=ComputeTier.single_point, inputs=INPUTS):
    return client.request(make_item(), "thermo", tier, "Borderline driving force needs a refined energy.", inputs, budget)


def test_ok_request_is_charged_logged_and_cached(paths) -> None:
    run_dir, cache_dir = paths
    client, budget = make_client(run_dir, cache_dir), Budget(make_config())
    req = ask(client, budget)
    assert req.status == ComputeStatus.ok
    assert req.compute_units == 1.0 and budget.spent.compute_units == 1.0
    assert req.request_id == "test-run:compute:1"
    assert "dE_ev_per_atom" in req.result
    assert req.p_react_before is None and req.p_react_after is None
    assert ResultCache(cache_dir).get(req.cache_key) == req.result
    assert [r["request_id"] for r in read_log(run_dir)] == [req.request_id]


def test_a_change_to_the_tier_code_invalidates_the_cache(paths) -> None:
    run_dir, cache_dir = paths
    client, budget = make_client(run_dir, cache_dir), Budget(make_config())
    first = ask(client, budget)
    assert ask(client, budget).status == ComputeStatus.cached
    client.code_version = "tiers-fixed-tonight"            # as if tiers.py had changed
    again = ask(client, budget)
    assert again.status == ComputeStatus.ok and again.cache_key != first.cache_key
    assert "_code_version" not in again.settings           # the backend sees the settings unchanged


def test_code_version_follows_the_tier_source() -> None:
    assert client_module.code_version() == client_module.code_version()
    assert len(client_module.code_version()) == 16


def test_cache_hit_is_charged_full_price(paths) -> None:
    run_dir, cache_dir = paths
    backend = StubBackend()
    client, budget = make_client(run_dir, cache_dir, backend), Budget(make_config())
    first, second = ask(client, budget), ask(client, budget)
    assert backend.calls == 1
    assert second.status == ComputeStatus.cached
    assert second.result == first.result
    assert second.compute_units == 1.0 and second.gpu_seconds == 0.0
    assert budget.spent.compute_units == 2.0


def test_cache_is_shared_across_runs(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    backend = StubBackend()
    a = make_client(tmp_path / "runs" / "run-a", cache_dir, backend)
    b = make_client(tmp_path / "runs" / "run-b", cache_dir, backend)
    ask(a, Budget(make_config("run-a")))
    hit = ask(b, Budget(make_config("run-b")))
    assert hit.status == ComputeStatus.cached and backend.calls == 1


@pytest.mark.parametrize("status", [ComputeStatus.not_converged, ComputeStatus.failed])
def test_failures_are_charged_logged_never_cached(paths, status) -> None:
    run_dir, cache_dir = paths
    backend = StubBackend(forced={ComputeTier.bounded_relaxation: status})
    client, budget = make_client(run_dir, cache_dir, backend), Budget(make_config())
    first = ask(client, budget, tier=ComputeTier.bounded_relaxation)
    second = ask(client, budget, tier=ComputeTier.bounded_relaxation)
    assert first.status == second.status == status
    assert backend.calls == 2
    assert ResultCache(cache_dir).get(first.cache_key) is None
    assert budget.spent.compute_units == 8.0
    assert [r["status"] for r in read_log(run_dir)] == [status.value, status.value]


class RaisingBackend:
    name = "raising"

    def run(self, tier, inputs, settings):
        raise RuntimeError("GPU fell over")

    def healthy(self):
        raise RuntimeError("unreachable")


class LyingBackend:
    name = "lying"

    def run(self, tier, inputs, settings):
        return BackendResult(ComputeStatus.cached, {"dE_ev_per_atom": -0.1})

    def healthy(self):
        return True


def test_backend_exception_is_logged_as_failed(paths) -> None:
    run_dir, cache_dir = paths
    config = make_config()
    client = ComputeClient(run_dir, config, RaisingBackend(), ResultCache(cache_dir), TEST_SETTINGS)
    budget = Budget(config)
    req = ask(client, budget)
    assert req.status == ComputeStatus.failed
    assert "GPU fell over" in str(req.result["error"])
    assert budget.spent.compute_units == 1.0
    assert client.healthy() is False


def test_backend_cannot_claim_cached(paths) -> None:
    run_dir, cache_dir = paths
    config = make_config()
    client = ComputeClient(run_dir, config, LyingBackend(), ResultCache(cache_dir), TEST_SETTINGS)
    req = ask(client, Budget(config))
    assert req.status == ComputeStatus.failed
    assert ResultCache(cache_dir).get(req.cache_key) is None


def test_refused_charge_spends_and_logs_nothing(paths) -> None:
    run_dir, cache_dir = paths
    backend = StubBackend()
    client, budget = make_client(run_dir, cache_dir, backend), Budget(make_config(max_units=3.0))
    with pytest.raises(BudgetExceeded):
        ask(client, budget, tier=ComputeTier.bounded_relaxation)
    assert backend.calls == 0
    assert budget.spent.compute_units == 0.0
    assert not (run_dir / "compute_requests.jsonl").exists()


def test_invalid_requests_are_not_charged(paths) -> None:
    run_dir, cache_dir = paths
    client, budget = make_client(run_dir, cache_dir), Budget(make_config())
    with pytest.raises(ValueError):
        client.request(make_item(), "thermo", ComputeTier.single_point, "  ", INPUTS, budget)
    with pytest.raises(TypeError):
        ask(client, budget, inputs={"formula": object()})
    assert budget.spent.compute_units == 0.0


def test_missing_price_is_not_charged(paths) -> None:
    run_dir, cache_dir = paths
    config = RunConfig(run_id="test-run", condition="C4", seed=0, model="stub")
    client = make_client(run_dir, cache_dir, config=config)
    budget = Budget(config)
    with pytest.raises(MissingPrice):
        ask(client, budget)
    assert budget.spent.compute_units == 0.0


def test_relaxation_requires_force_stress_and_step_cap(paths) -> None:
    run_dir, cache_dir = paths
    settings = dict(TEST_SETTINGS)
    settings[ComputeTier.bounded_relaxation] = {"model": "stub", "fmax_ev_per_a": 0.05, "max_steps": 200}
    with pytest.raises(ValueError, match="stress_tol_ev_per_a3"):
        ComputeClient(run_dir, make_config(), StubBackend(), ResultCache(cache_dir), settings)


def test_run_dir_must_match_run_id(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        make_client(tmp_path / "other-run", tmp_path / "cache", config=make_config("test-run"))


class EmptyBoard:
    def accepted_artifacts(self, item_id: str) -> list[Artifact]:
        return []


def test_charges_match_log_so_verifier_accepts(paths) -> None:
    run_dir, cache_dir = paths
    config = make_config()
    client = make_client(run_dir, cache_dir, StubBackend(forced={ComputeTier.bounded_relaxation: ComputeStatus.failed}))
    budget = Budget(config)
    lookup = ask(client, budget, tier=ComputeTier.cached_lookup)
    failed = ask(client, budget, tier=ComputeTier.bounded_relaxation)
    artifact = Artifact(
        artifact_id="test-run:thermo:1", run_id="test-run", item_id=make_item().item_id,
        agent="thermo", type="reaction_report",
        values={"dE_ev_per_atom": lookup.result["dE_ev_per_atom"]},
        claims=[Claim(cause="no_driving_force", statement="Stub statement.",
                      evidence=["values.dE_ev_per_atom"], falsified_if="A refined energy below the threshold.")],
        compute_requests=[lookup.request_id, failed.request_id],
        cost=Cost(compute_units=lookup.compute_units + failed.compute_units),
    )
    requests = [ComputeRequest.model_validate(d) for d in read_log(run_dir)]
    status, notes = verify(artifact, EmptyBoard(), requests=requests, config=config,
                           item_cost=budget.spent, tool_values={})
    assert status == VerifierStatus.accepted, notes


def test_module_level_api(paths) -> None:
    run_dir, cache_dir = paths
    client_module.use(None)
    assert client_module.healthy() is False
    with pytest.raises(RuntimeError):
        client_module.request(make_item(), "thermo", ComputeTier.single_point, "r", INPUTS, Budget(make_config()))
    client_module.use(make_client(run_dir, cache_dir))
    try:
        assert client_module.healthy() is True
        req = client_module.request(make_item(), "kinetics", ComputeTier.single_point, "r", INPUTS, Budget(make_config()))
        assert req.agent == "kinetics"
    finally:
        client_module.use(None)


def test_concurrent_processes_get_unique_sequential_ids(paths) -> None:
    run_dir, cache_dir = paths
    ctx = mp.get_context("spawn")
    procs_n, per_proc = 3, 5
    barrier, results = ctx.Barrier(procs_n), ctx.Queue()
    procs = [ctx.Process(target=request_many, args=(str(run_dir), str(cache_dir), per_proc, barrier, results))
             for _ in range(procs_n)]
    for p in procs:
        p.start()
    ids = [i for _ in procs for i in results.get(timeout=60)]
    for p in procs:
        p.join(timeout=60)
        assert p.exitcode == 0
    total = procs_n * per_proc
    assert sorted(ids) == sorted(f"test-run:compute:{n}" for n in range(1, total + 1))
    assert len(read_log(run_dir)) == total
