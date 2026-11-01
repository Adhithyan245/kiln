"""Read-only Kiln evidence viewer for recorded predictions; never reads labels."""
from __future__ import annotations

import json
import os
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(os.environ.get("KILN_ROOT", Path(__file__).resolve().parents[1]))
TEMPLATE = Path(__file__).with_name("index.html")


def _jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8") as stream:
        return [value for line in stream if line.strip()
                if isinstance(value := json.loads(line), dict)]


def load_predictions() -> list[dict]:
    """Load run outputs once per run, keeping only agent-visible and prediction fields."""
    predictions = []
    paths = list((ROOT / "runs").glob("*/predictions.jsonl"))
    paths += list((ROOT / "results" / "gb10").glob("dryrun_*/*/predictions.jsonl"))
    for path in sorted(paths):
        run_dir = path.parent
        config_path = run_dir / "config.json"
        config = json.loads(config_path.read_text(encoding="utf-8")) if config_path.is_file() else {}
        artifacts: dict[str, dict[str, dict]] = defaultdict(dict)
        requests: dict[str, dict[str, dict]] = defaultdict(dict)
        for artifact_path in sorted((run_dir / "board").rglob("artifacts.jsonl")):
            for artifact in _jsonl(artifact_path):
                if artifact.get("item_id") and artifact.get("artifact_id"):
                    artifacts[artifact["item_id"]][artifact["artifact_id"]] = {
                        key: artifact.get(key) for key in ("artifact_id", "agent", "type", "values", "rationale", "verifier", "verifier_notes")}
        for request in _jsonl(run_dir / "compute_requests.jsonl"):
            if request.get("item_id") and request.get("request_id"):
                requests[request["item_id"]][request["request_id"]] = {
                    key: request.get(key) for key in ("request_id", "agent", "tier", "reason", "inputs", "status", "compute_units", "gpu_seconds")}
        for prediction in _jsonl(path):
            item_id = prediction.get("item_id")
            if not item_id:
                continue
            row = {key: prediction.get(key) for key in ("run_id", "condition", "seed", "item_id", "category", "p_react", "cause", "fix", "evidence", "review_flags", "needs_review", "disagreements", "applicability_notes", "cost")}
            row["run_id"] = row["run_id"] or run_dir.name
            row["source_label"] = "Development dry run" if "dryrun_" in run_dir.parent.name else "Recorded run"
            row["artifacts"] = list(artifacts[item_id].values())
            row["requests"] = list(requests[item_id].values())
            row["stubs_used"] = config.get("stubs_used")
            row["stub_parts"] = config.get("stub_parts", [])
            predictions.append(row)
    return sorted(predictions, key=lambda p: not bool(p.get("needs_review")))


def render() -> str:
    payload = json.dumps(load_predictions(), ensure_ascii=True).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return TEMPLATE.read_text(encoding="utf-8").replace("__KILN_DATA__", payload)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path not in ("/", "/index.html"):
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
