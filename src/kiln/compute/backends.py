"""Backends that actually run a tier. The client never trusts them to report failure politely.

`StubBackend` is deterministic and offline, for tests and for wiring agents before the GB10
service is up. Its numbers are placeholders and must never reach an experiment run.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Protocol

from kiln.schemas import ComputeStatus, ComputeTier

__all__ = ["Backend", "BackendResult", "StubBackend"]

Result = dict[str, float | str | bool | None]


@dataclass(frozen=True)
class BackendResult:
    status: ComputeStatus          # ok, not_converged or failed (never cached: that is the client's call)
    result: Result = field(default_factory=dict)
    gpu_seconds: float = 0.0


class Backend(Protocol):
    name: str

    def run(self, tier: ComputeTier, inputs: dict[str, Any], settings: dict[str, Any]) -> BackendResult: ...

    def healthy(self) -> bool: ...


class StubBackend:
    """Deterministic fake energies derived from a hash of the request.

    `forced` maps a tier to the status every request of that tier returns, to exercise the
    not_converged and failed paths. `calls` counts real runs, so tests can see cache hits.
    """

    name = "stub"

    def __init__(self, forced: dict[ComputeTier, ComputeStatus] | None = None) -> None:
        self.forced = dict(forced or {})
        self.calls = 0

    def run(self, tier: ComputeTier, inputs: dict[str, Any], settings: dict[str, Any]) -> BackendResult:
        self.calls += 1
        status = self.forced.get(tier, ComputeStatus.ok)
        if status == ComputeStatus.failed:
            return BackendResult(status, {"error": "stub: forced failure"})
        digest = hashlib.sha256(repr((tier.value, sorted(inputs.items()))).encode()).digest()
        # Placeholder in [-0.2, 0) eV/atom; not physics.
        dE = -0.2 * (int.from_bytes(digest[:4], "big") / 2**32) - 1e-6
        result: Result = {"dE_ev_per_atom": round(dE, 6), "model": "stub"}
        if status == ComputeStatus.not_converged:
            result["converged"] = False
        return BackendResult(status, result, gpu_seconds=0.0)

    def healthy(self) -> bool:
        return True
