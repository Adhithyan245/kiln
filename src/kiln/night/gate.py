"""Label gates for the night runner.

`labels_absent` is the preflight for Night 2: labels must not be on the run host before the
prediction hash is posted. `receipt_ok` lets a `requires_receipt` step run only when the receipt
file records the sha256 of the predictions manifest and every file the manifest lists still has
its recorded hash.

This is a local gate, not proof of posting. `kiln.scoring.evaluate.evaluate` separately demands
an independent `verify_posted_hash` check (protocol H3, OPEN-16) before it loads any label.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

__all__ = ["labels_absent", "receipt_ok", "sha256_file"]


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def labels_absent(repo_root: Path) -> bool:
    return not (repo_root / "labels").exists()


def receipt_ok(repo_root: Path, receipt: str, manifest: str) -> tuple[bool, str]:
    receipt_path, manifest_path = repo_root / receipt, repo_root / manifest
    if not manifest_path.exists():
        return False, f"no manifest at {manifest}"
    if not receipt_path.exists():
        return False, f"no receipt at {receipt}"
    digest = sha256_file(manifest_path)
    posted = set()
    for line in receipt_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                posted.add(json.loads(line).get("sha256"))
            except ValueError:
                return False, "receipt file is not valid JSON Lines"
    if digest not in posted:
        return False, "manifest sha256 not found in receipt"
    try:
        files: dict[str, str] = json.loads(manifest_path.read_text(encoding="utf-8"))["files"]
    except (ValueError, KeyError):
        return False, "manifest has no files table"
    for rel, expected in files.items():
        path = repo_root / rel
        if not path.exists() or sha256_file(path) != expected:
            return False, f"predictions changed since hashing: {rel}"
    return True, "receipt matches manifest"
