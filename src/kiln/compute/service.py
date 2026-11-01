"""Compute service on the GPU host: one HTTP endpoint in front of the tiers, one GPU job at a time.

    POST /run      {"tier": ..., "inputs": {...}, "settings": {...}} -> {"status", "result", "gpu_seconds"}
    GET  /healthz  -> {"ok": bool, "backend": name}

It binds to 127.0.0.1 by default; reach it through an SSH tunnel. If KILN_COMPUTE_TOKEN is set,
every request must send "Authorization: Bearer <token>". It does no charging or logging: the
client does both before and after calling it, so the budget can't be bypassed from here.

    python -m kiln.compute.service --port 8765 --cache-dir cache/mp
"""
from __future__ import annotations

import os

os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")  # before torch loads (AGENTS.md rule 6)

import argparse
import hmac
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from kiln.compute.backends import Backend
from kiln.schemas import ComputeStatus, ComputeTier

__all__ = ["make_server", "main"]

MAX_BODY_BYTES = 1 << 20


def make_server(backend: Backend, host: str = "127.0.0.1", port: int = 8765,
                token: str | None = None) -> ThreadingHTTPServer:
    gpu = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, body: dict[str, Any]) -> None:
            data = json.dumps(body, allow_nan=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _authorized(self) -> bool:
            if token is None:
                return True
            sent = self.headers.get("Authorization", "")
            return hmac.compare_digest(sent.encode(), f"Bearer {token}".encode())

        def do_GET(self) -> None:
            if not self._authorized():
                return self._send(401, {"error": "unauthorized"})
            if self.path != "/healthz":
                return self._send(404, {"error": "not found"})
            try:
                ok = bool(backend.healthy())
            except Exception:
                ok = False
            self._send(200, {"ok": ok, "backend": backend.name})

        def do_POST(self) -> None:
            if not self._authorized():
                return self._send(401, {"error": "unauthorized"})
            if self.path != "/run":
                return self._send(404, {"error": "not found"})
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > MAX_BODY_BYTES:
                return self._send(400, {"error": "bad body size"})
            try:
                body = json.loads(self.rfile.read(length))
                tier = ComputeTier(body["tier"])
                inputs, settings = dict(body["inputs"]), dict(body["settings"])
            except (ValueError, KeyError, TypeError) as exc:
                return self._send(400, {"error": f"bad request: {exc}"})
            with gpu:
                try:
                    out = backend.run(tier, inputs, settings)
                    reply = {"status": out.status.value, "result": out.result, "gpu_seconds": out.gpu_seconds}
                except Exception as exc:  # reported as failed; the client logs it
                    reply = {"status": ComputeStatus.failed.value,
                             "result": {"error": f"{type(exc).__name__}: {exc}"}, "gpu_seconds": 0.0}
            self._send(200, reply)

        def log_message(self, fmt: str, *args: Any) -> None:
            sys.stderr.write(f"[compute] {self.address_string()} {fmt % args}\n")

    return ThreadingHTTPServer((host, port), Handler)


def main(argv: list[str] | None = None) -> int:
    from kiln.compute.tiers import LocalBackend

    parser = argparse.ArgumentParser(prog="python -m kiln.compute.service")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--cache-dir", type=Path, default=Path("cache") / "mp")
    args = parser.parse_args(argv)

    token = os.environ.get("KILN_COMPUTE_TOKEN") or None
    if token is None and args.host not in ("127.0.0.1", "localhost", "::1"):
        parser.error("set KILN_COMPUTE_TOKEN before binding to a non-loopback address")
    server = make_server(LocalBackend(args.cache_dir), args.host, args.port, token)
    print(f"compute service on {args.host}:{server.server_port} (auth {'on' if token else 'off'})", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
