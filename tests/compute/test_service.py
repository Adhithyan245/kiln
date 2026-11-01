from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator

import pytest

from kiln.compute.backends import HttpBackend, StubBackend, backend_from_env
from kiln.compute.service import make_server
from kiln.schemas import ComputeStatus, ComputeTier


class Boom(StubBackend):
    def run(self, tier, inputs, settings):
        raise RuntimeError("CUDA out of memory")


def serve(backend, token=None) -> Iterator[str]:
    server = make_server(backend, "127.0.0.1", 0, token)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture
def url() -> Iterator[str]:
    yield from serve(StubBackend(forced={ComputeTier.bounded_relaxation: ComputeStatus.not_converged}))


def test_round_trip_matches_local_stub(url: str) -> None:
    remote = HttpBackend(url).run(ComputeTier.single_point, {"formula": "CaTiO3"}, {"model": "stub"})
    local = StubBackend().run(ComputeTier.single_point, {"formula": "CaTiO3"}, {"model": "stub"})
    assert remote == local


def test_statuses_pass_through(url: str) -> None:
    out = HttpBackend(url).run(ComputeTier.bounded_relaxation, {"formula": "CaTiO3"}, {})
    assert out.status == ComputeStatus.not_converged


def test_health(url: str) -> None:
    assert HttpBackend(url).healthy() is True
    assert HttpBackend("http://127.0.0.1:9").healthy() is False


def test_backend_exception_comes_back_as_failed() -> None:
    for base in serve(Boom()):
        out = HttpBackend(base).run(ComputeTier.single_point, {}, {})
        assert out.status == ComputeStatus.failed and "CUDA out of memory" in str(out.result["error"])


def test_token_is_required_when_set() -> None:
    for base in serve(StubBackend(), token="s3cret"):
        with pytest.raises(urllib.error.HTTPError) as err:
            HttpBackend(base).run(ComputeTier.single_point, {}, {})
        assert err.value.code == 401
        assert HttpBackend(base, token="wrong").healthy() is False
        assert HttpBackend(base, token="s3cret").healthy() is True


def test_bad_tier_is_rejected(url: str) -> None:
    req = urllib.request.Request(url + "/run", data=json.dumps({"tier": "md_nvt", "inputs": {}, "settings": {}}).encode(),
                                 method="POST")
    with pytest.raises(urllib.error.HTTPError) as err:
        urllib.request.urlopen(req, timeout=5)
    assert err.value.code == 400


def test_backend_from_env(monkeypatch) -> None:
    monkeypatch.delenv("KILN_COMPUTE_BACKEND", raising=False)
    assert isinstance(backend_from_env(), StubBackend)
    monkeypatch.setenv("KILN_COMPUTE_BACKEND", "http")
    monkeypatch.delenv("KILN_COMPUTE_URL", raising=False)
    with pytest.raises(RuntimeError):
        backend_from_env()
    monkeypatch.setenv("KILN_COMPUTE_URL", "http://127.0.0.1:8765")
    assert isinstance(backend_from_env(), HttpBackend)
