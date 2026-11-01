"""The one door to compute (docs/interfaces.md step 4).

Order inside request(), fixed:
    1. validate the request (non-empty reason, JSON-able inputs, tier settings present);
    2. charge the frozen tier price to the item budget; BudgetExceeded means nothing was spent,
       nothing runs and nothing is logged;
    3. serve from the cache (status `cached`, still charged, 0 GPU-seconds) or run the backend;
    4. cache the result only if it is `ok`;
    5. append the ComputeRequest to runs/<run_id>/compute_requests.jsonl.
Steps 3-5 always log exactly one record per charge, so the item's charged compute units equal
the log total, which the verifier checks. A backend that raises or returns an unknown status is
logged as `failed` with the error text (AGENTS.md rule 9).

The caller fills p_react_before / p_react_after from score.provisional.
"""
from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from filelock import FileLock

from kiln.budget import Budget
from kiln.compute.accounting import cache_key, price
from kiln.compute.backends import Backend, BackendResult
from kiln.compute.cache import ResultCache
from kiln.schemas import AgentName, ComputeRequest, ComputeStatus, ComputeTier, Item, RunConfig

__all__ = ["ComputeClient", "use", "request", "healthy", "RELAXATION_SETTINGS"]

# Variable-cell relaxation must stop on force AND stress, with a hard step cap (AGENTS.md).
RELAXATION_SETTINGS = frozenset({"fmax_ev_per_a", "stress_tol_ev_per_a3", "max_steps"})

_BACKEND_STATUSES = frozenset({ComputeStatus.ok, ComputeStatus.not_converged, ComputeStatus.failed})

# The physics code a cached result depends on. Its hash goes into every cache key, so a result
# computed by older tier code is never served after that code changes (the settings alone don't
# capture a code fix). The backend still receives the settings unchanged.
_TIER_CODE = ("compute/tiers.py", "compute/convergence.py", "compute/energy_reference.py",
              "compute/decomposition.py", "tools/mp.py")


def code_version() -> str:
    import hashlib

    root = Path(__file__).resolve().parents[1]
    digest = hashlib.sha256()
    for rel in _TIER_CODE:
        path = root / rel
        digest.update(rel.encode() + b"\0" + (path.read_bytes() if path.exists() else b"missing") + b"\0")
    return digest.hexdigest()[:16]


class ComputeClient:
    def __init__(
        self,
        run_dir: str | Path,
        config: RunConfig,
        backend: Backend,
        cache: ResultCache,
        tier_settings: Mapping[ComputeTier, Mapping[str, Any]],
    ) -> None:
        self.run_dir = Path(run_dir)
        self.run_id = self.run_dir.name
        if self.run_id != config.run_id:
            raise ValueError(f"run_dir name {self.run_id!r} does not match config.run_id {config.run_id!r}")
        relax = tier_settings.get(ComputeTier.bounded_relaxation)
        if relax is not None and not RELAXATION_SETTINGS <= relax.keys():
            missing = sorted(RELAXATION_SETTINGS - relax.keys())
            raise ValueError(f"bounded_relaxation settings missing {missing}")
        self.config = config
        self.backend = backend
        self.cache = cache
        self.tier_settings = {tier: dict(s) for tier, s in tier_settings.items()}
        self.code_version = code_version()
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = self.run_dir / "compute_requests.jsonl"
        self._lock = FileLock(str(self.run_dir / ".compute_requests.lock"))

    def request(
        self,
        item: Item,
        agent: AgentName,
        tier: ComputeTier,
        reason: str,
        inputs: dict[str, Any],
        budget: Budget,
    ) -> ComputeRequest:
        if not reason.strip():
            raise ValueError("every compute request needs a one-sentence reason")
        if tier not in self.tier_settings:
            raise ValueError(f"no settings configured for tier {tier.value!r}")
        settings = dict(self.tier_settings[tier])
        key = cache_key(tier, inputs, {**settings, "_code_version": self.code_version})  # raises on non-JSON inputs
        units = price(self.config, tier)

        budget.charge_compute(units)

        # One calculation per key at a time across processes (--parallel runs): a second request for
        # the same key waits, then is served from the cache instead of computing it again.
        lock_dir = Path(self.cache.root) / ".locks"
        lock_dir.mkdir(parents=True, exist_ok=True)
        with FileLock(str(lock_dir / f"{key}.lock")):
            cached = self.cache.get(key)
            stuck = None if cached is not None else self.cache.get_not_converged(key)
            if cached is not None:
                outcome = BackendResult(ComputeStatus.cached, cached, gpu_seconds=0.0)
            elif stuck is not None:  # same code, inputs and settings already failed to converge: say so again
                outcome = BackendResult(ComputeStatus.not_converged, {**stuck, "from_cache": True}, gpu_seconds=0.0)
            else:
                outcome = self._run(tier, inputs, settings)
                if outcome.status in (ComputeStatus.ok, ComputeStatus.not_converged):
                    self.cache.put(key, outcome.result, tier=tier.value, settings=settings,
                                   status=outcome.status.value)

        return self._log(
            item_id=item.item_id,
            agent=agent,
            tier=tier,
            reason=reason,
            inputs=inputs,
            settings=settings,
            cache_key=key,
            status=outcome.status,
            result=outcome.result,
            compute_units=units,
            gpu_seconds=outcome.gpu_seconds,
        )

    def healthy(self) -> bool:
        try:
            return bool(self.backend.healthy())
        except Exception:
            return False

    def _run(self, tier: ComputeTier, inputs: dict[str, Any], settings: dict[str, Any]) -> BackendResult:
        try:
            outcome = self.backend.run(tier, inputs, settings)
        except Exception as exc:  # logged as failed, never hidden
            return BackendResult(ComputeStatus.failed, {"error": f"{type(exc).__name__}: {exc}"})
        if outcome.status not in _BACKEND_STATUSES:
            return BackendResult(
                ComputeStatus.failed,
                {"error": f"backend {self.backend.name!r} returned status {outcome.status!r}"},
                outcome.gpu_seconds,
            )
        return outcome

    def _log(self, **fields: Any) -> ComputeRequest:
        with self._lock:
            seq = 1
            if self.log_path.exists():
                with self.log_path.open("r", encoding="utf-8") as f:
                    seq += sum(1 for line in f if line.strip())
            record = ComputeRequest(
                request_id=f"{self.run_id}:compute:{seq}",
                run_id=self.run_id,
                **fields,
            )
            with self.log_path.open("a", encoding="utf-8") as f:
                f.write(record.model_dump_json() + "\n")
                f.flush()
        return record


# ---------- module-level API from docs/interfaces.md ----------

_client: ComputeClient | None = None


def use(client: ComputeClient | None) -> None:
    """Set the client the module-level request()/healthy() go through (the runner does this per run)."""
    global _client
    _client = client


def _current() -> ComputeClient:
    if _client is None:
        raise RuntimeError("no compute client configured; call kiln.compute.client.use(...) first")
    return _client


def request(
    item: Item,
    agent: AgentName,
    tier: ComputeTier,
    reason: str,
    inputs: dict[str, Any],
    budget: Budget,
) -> ComputeRequest:
    return _current().request(item, agent, tier, reason, inputs, budget)


def healthy() -> bool:
    return _client is not None and _client.healthy()
