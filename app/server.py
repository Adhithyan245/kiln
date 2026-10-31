"""Read-only Kiln evidence viewer for recorded runs; no label access."""

from __future__ import annotations

import html
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(os.environ.get("KILN_ROOT", Path(__file__).resolve().parents[1]))


def load_predictions() -> list[dict]:
    predictions = []
    for path in sorted((ROOT / "runs").glob("*/predictions.jsonl")):
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                if line.strip():
                    data = json.loads(line)
                    if isinstance(data, dict):
                        data["_run_dir"] = path.parent.name
                        predictions.append(data)
    return sorted(predictions, key=lambda p: not bool(p.get("needs_review")))


def render() -> str:
    cards = []
    for row in load_predictions():
        def esc(value: object) -> str:
            return html.escape(str(value))
        details = {k: row.get(k) for k in ("category", "p_react", "cause", "evidence", "compute_requests",
            "review_flags", "disagreements", "applicability_notes", "cost")}
        run_dir = ROOT / "runs" / row["_run_dir"]
        artifact_paths = sorted((run_dir / "board").rglob("artifacts.jsonl"))
        for title, paths in (("artifacts", artifact_paths),
                             ("calculation_log", [run_dir / "compute_requests.jsonl"])):
            records = {}
            for path in paths:
                if path.is_file():
                    with path.open(encoding="utf-8") as stream:
                        for line in stream:
                            if not line.strip():
                                continue
                            record = json.loads(line)
                            if record.get("item_id") == row.get("item_id"):
                                key = record.get("artifact_id") or record.get("request_id")
                                if key:
                                    records[key] = record
            details[title] = list(records.values())
        cards.append(f"<article><h2>{esc(row.get('item_id', 'unknown'))}</h2>"
                     f"<strong>{'Needs review' if row.get('needs_review') else 'No review flag'}</strong>"
                     f"<pre>{esc(json.dumps(details, indent=2, ensure_ascii=False))}</pre></article>")
    content = ''.join(cards) or '<p>No recorded predictions are available yet.</p>'
    return ("<!doctype html><html><head><meta charset='utf-8'><title>Kiln Triage</title>"
            "<style>body{font:16px system-ui;margin:3rem auto;max-width:900px;padding:0 1rem}"
            "article{border:1px solid #bbb;border-radius:8px;padding:1rem;margin:1rem 0}"
            "pre{white-space:pre-wrap;overflow-wrap:anywhere}</style></head><body>"
            "<h1>Kiln Triage</h1><p>Retrospective evaluation on public data. Flags indicate evidence requiring review.</p>"
            + content + "</body></html>")


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path != "/":
            self.send_error(404)
            return
        try:
            body = render().encode("utf-8")
        except (OSError, ValueError):
            self.send_error(500, "Could not read recorded predictions")
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("PORT", "8080"))), Handler).serve_forever()
