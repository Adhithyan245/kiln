"""Backends that actually run a tier. The client never trusts them to report failure politely.

`StubBackend` is deterministic and offline, for tests and for wiring agents before the GB10
service is up. Its numbers are placeholders and must never reach an experiment run.
`HttpBackend` talks to kiln.compute.service; `tiers.LocalBackend` runs the tiers in-process.
"""
from __future__ import annotations

import hashlib
import json
import os
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Protocol

from kiln.schemas import ComputeStatus, ComputeTier

__all__ = ["Backend", "BackendResult", "StubBackend", "HttpBackend", "backend_from_env"]

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


class HttpBackend:
    """Calls kiln.compute.service over HTTP (usually through an SSH tunnel to the GB10 or Brev).

    Network errors and timeouts raise; the client logs them as `failed`.
    """

    name = "http"

    def __init__(self, url: str, token: str | None = None, timeout_s: float = 1800.0) -> None:
        self.url = url.rstrip("/")
        self.token = token
        self.timeout_s = timeout_s

    def _call(self, method: str, path: str, body: dict[str, Any] | None, timeout: float) -> dict[str, Any]:
        data = json.dumps(body, allow_nan=False).encode() if body is not None else None
        req = urllib.request.Request(self.url + path, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())

    def run(self, tier: ComputeTier, inputs: dict[str, Any], settings: dict[str, Any]) -> BackendResult:
        reply = self._call("POST", "/run", {"tier": tier.value, "inputs": inputs, "settings": settings},
                           self.timeout_s)
        return BackendResult(ComputeStatus(reply["status"]), dict(reply["result"]),
                             float(reply.get("gpu_seconds", 0.0)))

    def healthy(self) -> bool:
        try:
            return bool(self._call("GET", "/healthz", None, 10.0).get("ok"))
        except (OSError, ValueError):
            return False


def backend_from_env() -> Backend:
    """KILN_COMPUTE_BACKEND = stub | local | http (http reads KILN_COMPUTE_URL, KILN_COMPUTE_TOKEN)."""
    kind = os.environ.get("KILN_COMPUTE_BACKEND", "stub")
    if kind == "stub":
        return StubBackend()
    if kind == "local":
        from kiln.compute.tiers import LocalBackend  # needs pymatgen/ASE (and MACE for MLIP tiers)

        return LocalBackend()
    if kind == "http":
        url = os.environ.get("KILN_COMPUTE_URL")
        if not url:
            raise RuntimeError("KILN_COMPUTE_BACKEND=http needs KILN_COMPUTE_URL")
        return HttpBackend(url, os.environ.get("KILN_COMPUTE_TOKEN") or None)
    raise RuntimeError(f"unknown KILN_COMPUTE_BACKEND {kind!r}")
