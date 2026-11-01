"""Content-addressed store of compute results.

One JSON file per key under <root>/<key[:2]>/<key>.json. Writes go to a temporary file in the
same folder and are renamed into place, so a crash never leaves a half-written entry. `ok` results
are reused as `cached` evidence. Not-converged results are stored with that status so parallel runs
don't repeat the same failing relaxation; they are served as not_converged, never as evidence.
Failed results are never stored.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

__all__ = ["ResultCache"]

Result = dict[str, float | str | bool | None]


class ResultCache:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def _path(self, key: str) -> Path:
        if len(key) != 64 or any(c not in "0123456789abcdef" for c in key):
            raise ValueError(f"not a cache key: {key!r}")
        return self.root / key[:2] / f"{key}.json"

    def get(self, key: str) -> Result | None:
        """The stored `ok` result, or None (also for a stored not-converged entry)."""
        entry = self._entry(key)
        return entry["result"] if entry is not None and entry.get("status", "ok") == "ok" else None

    def get_not_converged(self, key: str) -> Result | None:
        """The stored result of a calculation that did not converge, or None. It is never usable
        evidence; it only saves recomputing the same failing relaxation in another run."""
        entry = self._entry(key)
        return entry["result"] if entry is not None and entry.get("status") == "not_converged" else None

    def _entry(self, key: str) -> dict[str, Any] | None:
        path = self._path(key)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def put(self, key: str, result: Result, *, tier: str, settings: dict[str, Any], status: str = "ok") -> None:
        if status not in ("ok", "not_converged"):
            raise ValueError(f"only ok and not_converged results are cached, not {status!r}")
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        entry = {"key": key, "tier": tier, "settings": settings, "result": result, "status": status}
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(entry, f, sort_keys=True, allow_nan=False)
            try:
                os.replace(tmp, path)
            except PermissionError:
                # Windows refuses to replace a file another process has open. Two writers of
                # one key both hold a valid `ok` result for it, so the first one wins.
                if not path.exists():
                    raise
                Path(tmp).unlink(missing_ok=True)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
