"""Local, cached-only Kiln UI. Standard library; no live compute or label access."""
from __future__ import annotations

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

APP_DIR = Path(__file__).resolve().parent
if str(APP_DIR.parent) not in sys.path:
    sys.path.insert(0, str(APP_DIR.parent))
from app import data, lab
from app.components.evidence_strip import render_evidence_strip

ROOT = Path(os.environ.get("KILN_ROOT", APP_DIR.parent))
TEMPLATE = APP_DIR / "index.html"
_CACHE_LOCK = threading.RLock()
_DATA_CACHE: dict[tuple, tuple[tuple, object]] = {}


def _signature(paths: tuple[Path, ...]) -> tuple:
    """Cheap metadata signature; large JSONL files are parsed only after a change."""
    entries = []
    for base in paths:
        if base.is_file():
            try:
                stat = base.stat()
                entries.append((str(base), stat.st_mtime_ns, stat.st_size))
            except OSError:
                entries.append((str(base), None, None))
        elif base.is_dir():
            for path in sorted(base.rglob("*")):
                if not path.is_file():
                    continue
                try:
                    stat = path.stat()
                    entries.append((str(path), stat.st_mtime_ns, stat.st_size))
                except OSError:
                    entries.append((str(path), None, None))
    return tuple(entries)


def _cached(key: str, paths: tuple[Path, ...], loader):
    signature = _signature(paths)
    cache_key = (key, str(ROOT.resolve()))
    with _CACHE_LOCK:
        cached = _DATA_CACHE.get(cache_key)
        if cached and cached[0] == signature:
            return cached[1]
        value = loader()
        _DATA_CACHE[cache_key] = (signature, value)
        return value


def _data_paths() -> tuple[Path, ...]:
    paths = tuple(ROOT / name for name in ("runs", "runs-h100", "runs-h100-cut", "results", "results-h100-cut", "protocol", "data/precursor_props.csv"))
    items = os.environ.get("KILN_ITEMS")
    return paths + ((Path(items),) if items else ())


def _lab_paths() -> tuple[Path, ...]:
    """Only watch summary files; loading a pair reads that item's evidence on demand."""
    paths = []
    for folder in ("runs-h100-cut", "runs-h100", "runs"):
        base = ROOT / folder
        for run in sorted(base.glob("*")):
            if run.is_dir():
                paths.extend(run / name for name in ("predictions.jsonl", "config.json", "compute_requests.jsonl"))
    item_path = os.environ.get("KILN_ITEMS")
    if item_path:
        paths.append(Path(item_path))
    return tuple(paths)


def load_predictions() -> list[dict]:
    return _cached("predictions", _data_paths(), lambda: data.load_records(ROOT, []))


def load_provenance() -> dict:
    return _cached("provenance", _data_paths(), lambda: data.load_provenance(ROOT))


def workspace() -> dict:
    result = dict(_cached("workspace", _data_paths(), lambda: data.load_workspace(ROOT)))
    for row in result["records"]:
        row["strip_html"] = render_evidence_strip(row["artifacts"], row["risk_before"], row["risk_after"],
                                                  replayed=True, prefix=row["key"])
    for row in result.get("dryrun_records", []):
        row["strip_html"] = render_evidence_strip(row["artifacts"], row["risk_before"], row["risk_after"],
                                                  replayed=True, prefix=row["key"])
    for idx, pair in enumerate(result.get("call_pairs", [])):
        if pair.get("artifacts"):
            pair["strip_html"] = render_evidence_strip(
                pair["artifacts"],
                None,
                "green" if pair.get("kiln_reacts") else "red",
                replayed=True,
                prefix=f"call-{idx}",
            )
    return result



def _embedded(value) -> str:
    return json.dumps(value, ensure_ascii=True, allow_nan=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def render() -> str:
    state = workspace()
    records = state.pop("records")
    return TEMPLATE.read_text(encoding="utf-8").replace("__KILN_DATA__", _embedded(records)).replace("__KILN_STATE__", _embedded(state))


class Handler(BaseHTTPRequestHandler):
    def send_json(self, value, status=200):
        body = _embedded(value).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if urlsplit(self.path).path != "/api/triage":
            self.send_json({"error": "Not found"}, 404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 16384:
                raise ValueError("Invalid body size")
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise ValueError("JSON object required")
            status, result = lab.triage(ROOT, body, _cached("lab-records", _lab_paths(), lambda: lab.records(ROOT)))
            self.send_json(result, status)
        except (ValueError, TypeError):
            self.send_json({"error": "Invalid request or unavailable item export"}, 400)

    def do_GET(self) -> None:
        route = urlsplit(self.path).path
        assets = {"/assets/app.css": (APP_DIR / "assets" / "app.css", "text/css; charset=utf-8"),
                  "/assets/app.js": (APP_DIR / "assets" / "app.js", "text/javascript; charset=utf-8"),
                  "/assets/lab.css": (APP_DIR / "assets" / "lab.css", "text/css; charset=utf-8"),
                  "/assets/lab.js": (APP_DIR / "assets" / "lab.js", "text/javascript; charset=utf-8")}
        try:
            if route == "/api/status":
                self.send_json({"live": False})
                return
            elif route == "/api/pairs":
                rows = _cached("lab-records", _lab_paths(), lambda: lab.records(ROOT))
                self.send_json(lab.pairs(rows))
                return
            elif route == "/api/compute":
                rows = _cached("lab-records", _lab_paths(), lambda: lab.records(ROOT))
                self.send_json(lab.compute(ROOT, rows))
                return
            elif route == "/api/catalogue":
                self.send_json(_cached("catalogue", (ROOT / "data" / "precursor_props.csv",),
                                        lambda: [{"formula": p["formula"]} for p in data.load_precursors(ROOT)]))
                return
            elif route in ("/", "/index.html"):
                body, content_type = (APP_DIR / "lab.html").read_bytes(), "text/html; charset=utf-8"
            elif route == "/evidence":
                body, content_type = render().encode("utf-8"), "text/html; charset=utf-8"
            elif route in assets:
                path, content_type = assets[route]
                body = path.read_bytes()
            elif route == "/amendments":
                path = ROOT / "protocol" / "amendments.md"
                if not path.is_file():
                    self.send_error(404, "Amendment file is not available in this checkout")
                    return
                body, content_type = path.read_bytes(), "text/plain; charset=utf-8"
            else:
                self.send_error(404)
                return
        except (OSError, ValueError, TypeError):
            self.send_error(500, "Recorded files could not be loaded. Check the local run export.")
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    # Public hosting requires a deliberate reverse proxy and access controls.
    ThreadingHTTPServer((os.environ.get("KILN_HOST", "127.0.0.1"), int(os.environ.get("PORT", "8080"))), Handler).serve_forever()
