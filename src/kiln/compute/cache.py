"""Content-addressed store of successful compute results.

One JSON file per key under <root>/<key[:2]>/<key>.json. Writes go to a temporary file in the
same folder and are renamed into place, so a crash never leaves a half-written entry. Only `ok`
results are stored; failed and non-converged results are logged by the client, never cached.
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
        path = self._path(key)
        if not path.exists():
            return None
        entry: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return entry["result"]

    def put(self, key: str, result: Result, *, tier: str, settings: dict[str, Any]) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        entry = {"key": key, "tier": tier, "settings": settings, "result": result}
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
