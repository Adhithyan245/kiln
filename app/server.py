"""Kiln triage app: replay recorded Night 2 runs step by step, or run one pair live.

Replay needs only the standard library. Live mode (KILN_LIVE=1 with GEMINI_API_KEY and
KILN_COMPUTE_BACKEND=local) imports kiln lazily and runs one item through the real agents and compute.
Never reads labels, and never serves a run whose compute log contains a stub result.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
import uuid
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(os.environ.get("KILN_ROOT", Path(__file__).resolve().parents[1]))
TEMPLATE = Path(__file__).with_name("index.html")

# Real Night 2 runs only, adopted result first: the H100 run scored on 301 common items (runs-h100-cut/),
# the full H100 run when it lands (runs-h100/), then the GB10 rerun (runs/). Development dry runs are not
# shown: they used the stub compute backend.
RUN_SOURCES = {"runs-h100-cut": "H100 (ALCHEMI Toolkit)", "runs-h100": "H100 (ALCHEMI Toolkit)",
               "runs": "GB10 (DGX Spark)"}
PREDICTION_KEYS = ("run_id", "condition", "seed", "item_id", "category", "p_react", "cause", "fix", "evidence",
                   "review_flags", "needs_review", "disagreements", "applicability_notes", "cost")
ARTIFACT_KEYS = ("artifact_id", "agent", "type", "values", "rationale", "verifier", "verifier_notes", "created_at")
REQUEST_KEYS = ("request_id", "agent", "tier", "reason", "inputs", "status", "compute_units", "gpu_seconds", "created_at")
RESULT_KEYS = ("dE_ev_per_atom", "dE_mp_ev_per_atom", "dE_mlip_minus_mp_ev_per_atom", "products", "mp_products",
               "reactants", "competitor_formula", "competitor_e_hull_ev_per_atom", "model", "backend", "source",
               "n_structures", "max_steps_used", "n_not_converged", "n_finished_by_ase", "error")
SUMMARY_KEYS = ("item_id", "run_id", "condition", "seed", "category", "p_react", "needs_review")


def _jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8") as stream:
        return [value for line in stream if line.strip()
                if isinstance(value := json.loads(line), dict)]


def _uses_stub_compute(run_dir: Path) -> bool:
    """A run whose compute results came from the stub backend has fake energies: never show it."""
    return any((request.get("result") or {}).get("model") == "stub"
               for request in _jsonl(run_dir / "compute_requests.jsonl"))


def _request_view(request: dict) -> dict:
    view = {key: request.get(key) for key in REQUEST_KEYS}
    result = request.get("result") or {}
    view["result"] = {key: result[key] for key in RESULT_KEYS if key in result}
    return view


def _items_index() -> dict[str, dict]:
    """Agent-visible item fields (temperature, dwell) from an items file, if the server has one."""
    for path in (os.environ.get("KILN_ITEMS"), ROOT / "kiln-items.jsonl", Path.home() / "kiln-items.jsonl"):
        if path and Path(path).is_file():
            return {row["item_id"]: row for row in _jsonl(Path(path)) if row.get("item_id")}
    return {}


def _runs() -> list[tuple[Path, dict, str]]:
    out = []
    for folder, label in RUN_SOURCES.items():
        for predictions in sorted((ROOT / folder).glob("*/predictions.jsonl")):
            run_dir = predictions.parent
            if _uses_stub_compute(run_dir):
                continue
            config_path = run_dir / "config.json"
            config = json.loads(config_path.read_text(encoding="utf-8")) if config_path.is_file() else {}
            out.append((run_dir, config, label))
    return out


def _artifacts(run_dir: Path, item_id: str) -> list[dict]:
    rows: dict[str, dict] = {}
    for path in sorted((run_dir / "board" / item_id).rglob("artifacts.jsonl")):
        for artifact in _jsonl(path):
            if artifact.get("artifact_id"):
                rows[artifact["artifact_id"]] = {key: artifact.get(key) for key in ARTIFACT_KEYS}
    return sorted(rows.values(), key=lambda a: str(a.get("created_at") or ""))


def load_predictions() -> list[dict]:
    """Every recorded prediction with its evidence and compute trail (stub-backend runs excluded)."""
    predictions = []
    for run_dir, config, label in _runs():
        requests: dict[str, list[dict]] = defaultdict(list)
        for request in _jsonl(run_dir / "compute_requests.jsonl"):
            if request.get("item_id") and request.get("request_id"):
                requests[request["item_id"]].append(_request_view(request))
        for prediction in _jsonl(run_dir / "predictions.jsonl"):
            item_id = prediction.get("item_id")
            if not item_id:
                continue
            row = {key: prediction.get(key) for key in PREDICTION_KEYS}
            row["run_id"] = row["run_id"] or run_dir.name
            row["source_label"] = label
            row["artifacts"] = _artifacts(run_dir, item_id)
            row["requests"] = requests[item_id]
            row["stubs_used"] = config.get("stubs_used")
            row["stub_parts"] = config.get("stub_parts", [])
            predictions.append(row)
    return sorted(predictions, key=lambda p: not bool(p.get("needs_review")))


def list_pairs() -> list[dict]:
    """One entry per recorded item: the pair, its conditions, and which runs recorded it."""
    meta = _items_index()
    pairs: dict[str, dict] = {}
    for run_dir, config, label in _runs():
        run_config = config.get("run_config") or {}
        names = {}
        for request in _jsonl(run_dir / "compute_requests.jsonl"):
            inputs = request.get("inputs") or {}
            if request.get("item_id") and inputs.get("precursor_a") and request["item_id"] not in names:
                names[request["item_id"]] = (inputs["precursor_a"], inputs["precursor_b"])
        for prediction in _jsonl(run_dir / "predictions.jsonl"):
            item_id = prediction.get("item_id")
            if not item_id:
                continue
            item = meta.get(item_id, {})
            a, b = (item.get("precursor_a"), item.get("precursor_b")) if item else names.get(item_id, (None, None))
            entry = pairs.setdefault(item_id, {"item_id": item_id, "precursor_a": a, "precursor_b": b,
                                               "temperature_c": item.get("temperature_c"),
                                               "dwell_h": item.get("dwell_h"), "runs": []})
            entry["runs"].append({"condition": prediction.get("condition") or run_config.get("condition"),
                                  "seed": prediction.get("seed", run_config.get("seed")), "source": label})
    return sorted((p for p in pairs.values() if p["precursor_a"]), key=lambda p: (p["precursor_a"], p["precursor_b"]))


def _same_pair(entry: dict, a: str, b: str) -> bool:
    got = {str(entry.get("precursor_a", "")).lower(), str(entry.get("precursor_b", "")).lower()}
    return got == {a.strip().lower(), b.strip().lower()}


def replay(request: dict) -> tuple[int, dict]:
    a, b = str(request.get("precursor_a") or ""), str(request.get("precursor_b") or "")
    if not a or not b:
        return 400, {"error": "Enter both precursors."}
    entry = next((p for p in list_pairs() if _same_pair(p, a, b)), None)
    if entry is None:
        return 404, {"error": f"{a} + {b} is not in the recorded runs.", "live_available": live_enabled()}
    condition, seed = request.get("condition") or "C4", request.get("seed")
    for run_dir, config, label in _runs():
        run_config = config.get("run_config") or {}
        if run_config.get("condition") != condition or (seed not in (None, "") and str(run_config.get("seed")) != str(seed)):
            continue
        prediction = next((p for p in _jsonl(run_dir / "predictions.jsonl") if p.get("item_id") == entry["item_id"]), None)
        if prediction is None:
            continue
        row = {key: prediction.get(key) for key in PREDICTION_KEYS}
        row["run_id"] = row["run_id"] or run_dir.name
        requests = [_request_view(r) for r in _jsonl(run_dir / "compute_requests.jsonl") if r.get("item_id") == entry["item_id"]]
        return 200, {"mode": "replay", "item": {k: entry[k] for k in ("item_id", "precursor_a", "precursor_b", "temperature_c", "dwell_h")},
                     "source_label": label, "prediction": row, "artifacts": _artifacts(run_dir, entry["item_id"]),
                     "requests": requests}
    return 404, {"error": f"{a} + {b} has no recorded {condition} run" + (f" for seed {seed}." if seed not in (None, "") else "."),
                 "available": entry["runs"]}


# ---------- live mode ----------

JOBS: dict[str, dict] = {}


def live_enabled() -> bool:
    return (os.environ.get("KILN_LIVE") == "1" and bool(os.environ.get("GEMINI_API_KEY"))
            and os.environ.get("KILN_COMPUTE_BACKEND") == "local")


def start_live(request: dict) -> tuple[int, dict]:
    if not live_enabled():
        return 403, {"error": "Live mode is off on this server. Replay a recorded pair instead."}
    from kiln.runners.conditions import AGENT_SETTINGS, CAP_KEYS, _read_frozen, real_components  # noqa: PLC0415
    from kiln.schemas import Item, RunConfig  # noqa: PLC0415
    from kiln.tools.precursors import props  # noqa: PLC0415

    a, b = str(request.get("precursor_a") or "").strip(), str(request.get("precursor_b") or "").strip()
    try:
        temperature = float(request.get("temperature_c"))
        dwell = float(request["dwell_h"]) if request.get("dwell_h") not in (None, "") else None
        melting = [props(f).melting_point_c for f in (a, b)]
    except (TypeError, ValueError, KeyError) as exc:
        return 400, {"error": f"Cannot run this pair: {exc}"}
    frozen = _read_frozen(ROOT / "protocol" / "frozen_settings.json")
    job = uuid.uuid4().hex[:12]
    run_dir = Path(tempfile.mkdtemp(prefix=f"kiln-live-{job}-"))
    cfg = RunConfig(run_id=f"live-{job}", condition=request.get("condition") or "C4", seed=int(request.get("seed") or 0),
                    model="gemini-3.8-flash", **{k: frozen[k] for k in ("tier_prices", *CAP_KEYS)})
    item = Item(item_id=f"LIVE-{job}", source="precursor_genome", precursor_a=a, precursor_b=b, temperature_c=temperature,
                dwell_h=dwell, melting_point_a_c=melting[0], melting_point_b_c=melting[1], split="dev")
    JOBS[job] = {"status": "running", "run_dir": run_dir, "item": item.model_dump(mode="json"), "prediction": None, "error": None}

    def work() -> None:
        from kiln.runners.conditions import run_item  # noqa: PLC0415
        try:
            components = real_components({k: frozen.get(k) for k in AGENT_SETTINGS})
            prediction = run_item(cfg, run_dir, item, components.compute(run_dir, cfg), components)
            JOBS[job].update(status="done", prediction={k: prediction.model_dump(mode="json").get(k) for k in PREDICTION_KEYS})
        except Exception as exc:  # reported to the page, never hidden
            JOBS[job].update(status="error", error=f"{type(exc).__name__}: {exc}"[:400])

    threading.Thread(target=work, daemon=True).start()
    return 202, {"mode": "live", "job": job}


def live_status(job: str) -> tuple[int, dict]:
    state = JOBS.get(job)
    if state is None:
        return 404, {"error": "Unknown job."}
    run_dir, item_id = state["run_dir"], state["item"]["item_id"]
    return 200, {"mode": "live", "status": state["status"], "error": state["error"], "item": state["item"],
                 "source_label": "Live run", "prediction": state["prediction"], "artifacts": _artifacts(run_dir, item_id),
                 "requests": [_request_view(r) for r in _jsonl(run_dir / "compute_requests.jsonl")]}


# ---------- page and HTTP ----------

def _embed(value: object) -> str:
    return json.dumps(value, ensure_ascii=True).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def render() -> str:
    """The page, with a light summary of the recorded predictions embedded (no evidence payloads)."""
    rows = []
    for row in load_predictions():
        summary = {key: row.get(key) for key in SUMMARY_KEYS}
        summary.update(source_label=row["source_label"], stubs_used=row["stubs_used"], stub_parts=row["stub_parts"])
        rows.append(summary)
    return TEMPLATE.read_text(encoding="utf-8").replace("__KILN_DATA__", _embed(rows))


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, kind: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, value: dict | list) -> None:
        self._send(code, _embed(value).encode("utf-8"), "application/json")

    def do_GET(self) -> None:
        try:
            if self.path in ("/", "/index.html"):
                self._send(200, render().encode("utf-8"), "text/html; charset=utf-8")
            elif self.path == "/api/pairs":
                self._json(200, list_pairs())
            elif self.path == "/api/status":
                self._json(200, {"live": live_enabled()})
            elif self.path.startswith("/api/triage/"):
                self._json(*live_status(self.path.rsplit("/", 1)[-1]))
            else:
                self.send_error(404)
        except (OSError, ValueError):
            self.send_error(500, "Could not read recorded runs")

    def do_POST(self) -> None:
        if self.path != "/api/triage":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            request = json.loads(self.rfile.read(min(length, 65536)) or b"{}")
            if not isinstance(request, dict):
                raise ValueError("expected a JSON object")
        except ValueError:
            self._json(400, {"error": "Send a JSON object."})
            return
        self._json(*(start_live(request) if request.get("live") else replay(request)))

    def log_message(self, fmt: str, *args) -> None:  # quieter console
        return


if __name__ == "__main__":
    if live_enabled():
        os.chdir(ROOT)   # the compute client's cache and tier settings use repo-relative paths
    ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("PORT", "8080"))), Handler).serve_forever()
