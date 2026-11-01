"""Score one frozen run locally, after an independent posted-hash check.

    python -m kiln.scoring --run-dir runs/<run_id> --labels <path> --receipt protocol/posts.jsonl
        [--manifest protocol/predictions.manifest.json] [--items-file ~/kiln-items.jsonl | --ledger PATH]
        [--split heldout] [--verify discord|manual] [--out results/<run_id>/evaluation.json]

The gate is ``kiln.scoring.evaluate.evaluate``'s own: it hashes ``<run-dir>/predictions.jsonl``
and calls ``verify_posted_hash(digest)``; labels are read only if that returns the literal True.
This command supplies ``PostedHashVerifier``, which returns True only when all of these hold:

1. the predictions manifest lists ``<run-dir>/predictions.jsonl`` with exactly that digest;
2. the local receipt (``protocol/posts.jsonl``) has a record for the manifest's sha256. The
   receipt is used only to find the posted message; it is never accepted as proof;
3. an independent confirmer that reads the posting channel itself returns the literal True:
   - ``discord`` (default): fetches the posted message from Discord with
     ``GET <KILN_PREREG_WEBHOOK>/messages/<message_id>`` and requires the same message id, the
     manifest sha256 in its content, no edit since posting, and a posting time not in the future.
     The webhook URL is read from the environment and never printed;
   - ``manual``: the operator pastes the sha256 shown in the posted message (read from the
     channel, not from the receipt); the digest is not displayed before the answer.

The posting channel and its receipt proof are OPEN-16; these confirmers are proposals for it.
Labels are read only by ``kiln.scoring.evaluate.read_labels_jsonl``, passed to ``evaluate`` as its
``load_labels`` callback, so no label-reading code lives outside evaluate.py (AGENTS.md rule 1).
Writes the evaluation JSON and a Markdown table next to it, and prints the table.
Exit codes: 0 scored, 2 locked (labels not read), 1 any other failure.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.request
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from kiln.schemas import ComputeRequest, Item
from kiln.scoring.evaluate import EvaluationLockedError, evaluate, read_labels_jsonl

__all__ = ["PostedHashVerifier", "discord_confirm", "main", "manual_confirm", "render_table"]

# (manifest sha256, receipt record) -> literal True only when the post is independently confirmed.
Confirm = Callable[[str, Mapping[str, Any]], bool]
WEBHOOK_ENV = "KILN_PREREG_WEBHOOK"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class PostedHashVerifier:
    """``verify_posted_hash`` for ``evaluate``; see the module docstring for the three checks.

    ``reason`` says why the last call did not return True (no secrets, no label data).
    """

    def __init__(self, repo_root: Path, predictions: Path, manifest: Path, receipt: Path, confirm: Confirm):
        self.repo_root, self.predictions, self.manifest, self.receipt = repo_root, predictions, manifest, receipt
        self.confirm = confirm
        self.reason = "not run"
        self.manifest_sha256: str | None = None
        self.message_id: str | None = None

    def __call__(self, digest: str) -> bool:
        try:
            files = json.loads(self.manifest.read_text(encoding="utf-8"))["files"]
        except (OSError, ValueError, KeyError, TypeError):
            self.reason = f"no readable files table in manifest {self.manifest}"
            return False
        try:
            key = self.predictions.resolve().relative_to(self.repo_root.resolve()).as_posix()
        except ValueError:
            self.reason = "predictions file is not under the repo root, so the manifest cannot list it"
            return False
        if not isinstance(files, dict) or files.get(key) != digest:
            self.reason = f"manifest does not list {key} with the sha256 of the file being scored"
            return False
        manifest_sha = _sha256(self.manifest)
        self.manifest_sha256 = manifest_sha
        try:
            lines = self.receipt.read_text(encoding="utf-8").splitlines()
            records = [r for r in (json.loads(line) for line in lines if line.strip())
                       if isinstance(r, dict) and r.get("sha256") == manifest_sha]
        except (OSError, ValueError):
            self.reason = f"receipt {self.receipt} is missing or not valid JSON Lines"
            return False
        if not records:
            self.reason = "no receipt record for the manifest sha256, so there is no posted message to check"
            return False
        for record in records:
            if self.confirm(manifest_sha, record) is True:
                self.message_id = record.get("message_id")
                self.reason = "confirmed"
                return True
        self.reason = "the posting channel did not independently confirm the manifest sha256"
        return False


def _discord_fetch(webhook_url: str) -> Callable[[str], dict[str, Any]]:
    base = webhook_url.split("?", 1)[0].rstrip("/")

    def fetch(message_id: str) -> dict[str, Any]:
        request = urllib.request.Request(f"{base}/messages/{message_id}", headers={"User-Agent": "kiln-score/1"})
        with urllib.request.urlopen(request, timeout=15) as response:  # noqa: S310 (URL from env)
            return json.loads(response.read())
    return fetch


def discord_confirm(
    fetch: Callable[[str], Mapping[str, Any]] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> Confirm:
    """Confirm by re-reading the posted message from Discord, never from the local receipt."""

    def confirm(manifest_sha: str, record: Mapping[str, Any]) -> bool:
        message_id = record.get("message_id")
        if not isinstance(message_id, str) or not message_id.isdigit():
            return False
        getter = fetch
        if getter is None:
            url = (os.environ if environ is None else environ).get(WEBHOOK_ENV)
            if not url:
                raise RuntimeError(f"{WEBHOOK_ENV} is not set; cannot read the posted message")
            getter = _discord_fetch(url)
        message = getter(message_id)
        content = message.get("content")
        if str(message.get("id")) != message_id or not isinstance(content, str):
            return False
        if f"sha256 {manifest_sha}" not in content or message.get("edited_timestamp") is not None:
            return False
        posted = datetime.fromisoformat(str(message.get("timestamp")))
        return posted.tzinfo is not None and posted <= now()
    return confirm


def _ask_tty(prompt: str) -> str:
    if not sys.stdin.isatty():
        raise RuntimeError("manual verification needs an interactive terminal")
    return input(prompt)


def manual_confirm(ask: Callable[[str], str] = _ask_tty) -> Confirm:
    """Confirm by the operator pasting the sha256 they read in the posted message itself."""

    def confirm(manifest_sha: str, record: Mapping[str, Any]) -> bool:
        answer = ask(f"Open the posted message (id {record.get('message_id')}) in the posting channel, not the "
                     "local receipt, and paste the sha256 it shows: ")
        return answer.strip().lower() == manifest_sha
    return confirm


def _read_jsonl(path: Path, model: type[BaseModel], what: str) -> list[Any]:
    rows = []
    with path.open(encoding="utf-8") as stream:
        for number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                rows.append(model.model_validate_json(line))
            except ValidationError as exc:
                # Pydantic quotes the input; report field names only and drop the chained error.
                names = ", ".join(sorted({".".join(map(str, e["loc"])) or e["type"] for e in exc.errors()}))
                raise ValueError(f"{what} line {number} failed {model.__name__} validation for {names}") from None
    return rows


def _json_default(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"cannot serialize {type(value).__name__}")


def _fmt(value: Any, digits: int = 3) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def render_table(result: Mapping[str, Any]) -> str:
    """Short Markdown summary of an evaluation result (the JSON is the full record)."""
    m, run = result["metrics"], result["run"]
    lines = [
        f"## Kiln evaluation: {run['run_id']}",
        "",
        f"Split {result['split']}, source {result['source']}, n = {m['n']}. "
        f"Predictions sha256 `{result['prediction_sha256']}`; manifest sha256 `{run['manifest_sha256']}` "
        f"confirmed as posted by `{run['verification']}` (message {run['message_id']}).",
        "",
        "| Metric (all pairs, flagged included) | Value |",
        "|---|---|",
        f"| AUROC (reacted vs not) | {_fmt(m['auroc'])} |",
        f"| Brier | {_fmt(m['brier'])} |",
        f"| Four-class accuracy | {_fmt(m['four_class_accuracy'])} |",
        f"| Four-class macro-F1 | {_fmt(m['four_class_macro_f1'])} |",
        f"| Coverage (unflagged share) | {_fmt(m['coverage'])} |",
        f"| Flagged accuracy (n = {m['flagged_n']}) | {_fmt(m['flagged_accuracy'])} |",
        f"| Unflagged accuracy (n = {m['unflagged_n']}) | {_fmt(m['unflagged_accuracy'])} |",
        "",
        "| Class | Support | Predicted | F1 |",
        "|---|---|---|---|",
        *(f"| {c['category']} | {c['support']} | {c['predicted']} | {_fmt(c['f1'])} |" for c in m["four_class_f1"]),
        "",
        "| Compute tier | Requests | Compute units | GPU-seconds | Moved toward label (known) |",
        "|---|---|---|---|---|",
        *(f"| {t['tier']} | {t['requests']} | {_fmt(t['compute_units'], 2)} | {_fmt(t['gpu_seconds'], 1)} | "
          f"{t['moved_toward_label']} ({t['movement_known']}) |" for t in result["compute_by_tier"]),
    ]
    total = result["compute_total"]
    lines.append(f"| **total** | {total['requests']} | {_fmt(total['compute_units'], 2)} | "
                 f"{_fmt(total['gpu_seconds'], 1)} | {total['moved_toward_label']} ({total['movement_known']}) |")
    hard = result["hard_subset"]
    lines += [
        "",
        f"- Hard subset: {'reported in the JSON' if hard.get('available') else hard.get('reason')}",
        f"- Bootstrap intervals: {result['bootstrap']['reason']}",
        f"- Correct changes: {result['correct_changes']['reason']}",
        "- Review flags are flags, not calibrated probabilities or validated failure causes.",
    ]
    return "\n".join(lines) + "\n"


def _redact(text: str, environ: Mapping[str, str]) -> str:
    secret = environ.get(WEBHOOK_ENV)
    if not secret:
        return text
    base = secret.split("?", 1)[0].rstrip("/")
    for value in (secret, base, base.rsplit("/", 1)[-1]):   # full URL, URL without query, the token
        if value:
            text = text.replace(value, f"<{WEBHOOK_ENV}>")
    return text


def main(
    argv: list[str] | None = None,
    *,
    confirm: Confirm | None = None,
    environ: Mapping[str, str] | None = None,
) -> int:
    env = os.environ if environ is None else environ
    p = argparse.ArgumentParser(prog="python -m kiln.scoring", description="Score one frozen run after an "
                                "independent posted-hash check (labels are read only after it passes).")
    p.add_argument("--run-dir", type=Path, required=True, help="runs/<run_id> holding predictions.jsonl")
    p.add_argument("--labels", type=Path, required=True, help="JSON Lines of Label; read only after the gate")
    p.add_argument("--receipt", type=Path, default=Path("protocol/posts.jsonl"))
    p.add_argument("--manifest", type=Path, default=Path("protocol/predictions.manifest.json"))
    p.add_argument("--repo-root", type=Path, default=Path("."), help="root the manifest paths are relative to")
    source = p.add_mutually_exclusive_group()
    source.add_argument("--items-file", type=Path, help="JSON Lines of Item (agent-visible fields)")
    source.add_argument("--ledger", type=Path, help="Precursor Genome ledger (default: kiln.data.DEFAULT_LEDGER)")
    p.add_argument("--split", choices=("dev", "heldout"), default="heldout")
    p.add_argument("--verify", choices=("discord", "manual"), default="discord")
    p.add_argument("--out", type=Path, help="evaluation JSON (default results/<run_id>/evaluation.json)")
    args = p.parse_args(argv)

    root = args.repo_root
    resolve = lambda path: path if path.is_absolute() else root / path  # noqa: E731
    run_dir = resolve(args.run_dir)
    run_id = run_dir.name
    out = resolve(args.out or Path("results") / run_id / "evaluation.json")
    if confirm is None:
        confirm = discord_confirm(environ=env) if args.verify == "discord" else manual_confirm()
    verifier = PostedHashVerifier(root, run_dir / "predictions.jsonl", resolve(args.manifest),
                                  resolve(args.receipt), confirm)
    labels_path = args.labels
    try:
        if args.items_file:
            items = [i for i in _read_jsonl(args.items_file, Item, "items") if i.split == args.split]
        else:
            from kiln.data import DEFAULT_LEDGER, load_items
            items = load_items(args.split, args.ledger or DEFAULT_LEDGER)
        log = run_dir / "compute_requests.jsonl"
        requests = _read_jsonl(log, ComputeRequest, "compute_requests") if log.exists() else []
        result = evaluate(run_dir / "predictions.jsonl", items, lambda: read_labels_jsonl(labels_path),
                          verify_posted_hash=verifier, compute_requests=requests)
    except EvaluationLockedError as exc:
        cause = exc.__cause__
        detail = f"{type(cause).__name__}: {cause}" if cause is not None else verifier.reason
        print(_redact(f"Scoring locked, labels not read: {exc}. {detail}", env), file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 (report and exit nonzero; messages name fields, not label values)
        print(_redact(f"Scoring failed: {type(exc).__name__}: {exc}", env), file=sys.stderr)
        return 1
    result = {
        "run": {"run_id": run_id, "run_dir": args.run_dir.as_posix(), "manifest_sha256": verifier.manifest_sha256,
                "verification": args.verify, "message_id": verifier.message_id},
        **result,
    }
    table = render_table(result)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, default=_json_default, indent=2, sort_keys=True, allow_nan=False) + "\n",
                   encoding="utf-8")
    out.with_suffix(".md").write_text(table, encoding="utf-8")
    print(table)
    print(f"Wrote {out} and {out.with_suffix('.md')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
