"""Prediction manifest and hash posting (protocol §10, H2; interfaces "Run folders").

`manifest` hashes every runs/<run_id>/predictions.jsonl, writes runs/<run_id>/prediction.sha256
and one manifest listing them all. `post` sends the manifest's sha256 to KILN_PREREG_WEBHOOK and
appends a receipt line; it is idempotent (a digest already in the receipt is not reposted).

A receipt is a local record, not proof: the channel and its independent check are OPEN-16, and
`kiln.scoring.evaluate` still requires its own `verify_posted_hash`.

    python -m kiln.night.prereg manifest [--runs-dir runs] [--out protocol/predictions.manifest.json]
    python -m kiln.night.prereg post [--manifest ...] [--receipt protocol/posts.jsonl]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from kiln.night.alerts import post_json
from kiln.night.gate import sha256_file

__all__ = ["build_manifest", "post_manifest"]


def build_manifest(repo_root: Path, runs_dir: str, out: str) -> str:
    files: dict[str, str] = {}
    for pred in sorted((repo_root / runs_dir).glob("*/predictions.jsonl")):
        digest = sha256_file(pred)
        (pred.parent / "prediction.sha256").write_text(digest + "\n", encoding="utf-8")
        files[pred.relative_to(repo_root).as_posix()] = digest
    if not files:
        raise SystemExit(f"no predictions.jsonl under {runs_dir}")
    out_path = repo_root / out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({"files": files}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return sha256_file(out_path)


def _commit(repo_root: Path) -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_root, capture_output=True,
                              text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def post_manifest(
    repo_root: Path,
    manifest: str,
    receipt: str,
    poster: Callable[[str], bytes] | None = None,
) -> dict:
    digest = sha256_file(repo_root / manifest)
    receipt_path = repo_root / receipt
    if receipt_path.exists():
        for line in receipt_path.read_text(encoding="utf-8").splitlines():
            if line.strip() and json.loads(line).get("sha256") == digest:
                return json.loads(line)
    if poster is None:
        url = os.environ.get("KILN_PREREG_WEBHOOK")
        if not url:
            raise SystemExit("KILN_PREREG_WEBHOOK is not set; nothing posted")
        # ?wait=true makes Discord return the created message (id, timestamp) for the receipt.
        poster = lambda content: post_json(url + ("&" if "?" in url else "?") + "wait=true", {"content": content})
    commit = _commit(repo_root)
    body = poster(f"Kiln predictions manifest sha256 {digest} (commit {commit})")
    try:
        message = json.loads(body or b"{}")
    except ValueError:
        message = {}
    record = {
        "sha256": digest,
        "manifest": manifest,
        "commit": commit,
        "message_id": message.get("id"),
        "message_timestamp": message.get("timestamp"),
        "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    with receipt_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, sort_keys=True) + "\n")
    return record


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m kiln.night.prereg")
    p.add_argument("--repo-root", default=".")
    sub = p.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("manifest")
    m.add_argument("--runs-dir", default="runs")
    m.add_argument("--out", default="protocol/predictions.manifest.json")
    q = sub.add_parser("post")
    q.add_argument("--manifest", default="protocol/predictions.manifest.json")
    q.add_argument("--receipt", default="protocol/posts.jsonl")
    args = p.parse_args(argv)
    root = Path(args.repo_root)
    if args.cmd == "manifest":
        print(build_manifest(root, args.runs_dir, args.out))
    else:
        print(json.dumps(post_manifest(root, args.manifest, args.receipt)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
