"""Local, cached-only Kiln UI. Standard library; no live compute or label access."""
from __future__ import annotations

import json
import os
import tempfile
import time
import re
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
_RECIPE_LOCK = threading.Lock()   # one recipe search at a time: each reads large cache files
RECIPE_FORMULA = re.compile(r"[A-Za-z][A-Za-z0-9().]{0,39}")
# Systems fetched on demand from the Materials Project (needs MP_API_KEY on the host), kept for the
# life of the server in a writable temporary directory.
LIVE_MP_DIR = Path(os.environ.get("KILN_LIVE_MP_DIR", Path(tempfile.gettempdir()) / "kiln-mp-live"))
LIVE_FETCH_LIMIT, LIVE_FETCH_SECONDS = 40, 60.0


def _recipe_cache() -> Path | None:
    """The full Materials Project cache when the MACE check is enabled (it needs structures),
    else the committed energies-only `data/mp-energies`, which covers the extended precursor pool,
    else a local energies-only copy."""
    full = (ROOT / "cache" / "mp",) if os.environ.get("KILN_RECIPE_CHECK") == "1" else ()
    for path in (*full, ROOT / "data" / "mp-energies", ROOT / "cache" / "mp", ROOT / "cache" / "mp-energies"):
        if path.is_dir():
            return path
    return None


_RECIPE_MODEL: dict | None = None


def _fetch_missing(target: str, table: Path, cache_dir: Path) -> dict:
    """Fetch the Materials Project systems this target's pairs need and no cache has, within a
    count and time budget. Without MP_API_KEY nothing is fetched and those pairs show as
    'No Materials Project data'."""
    from kiln import recipe
    if LIVE_MP_DIR not in recipe.FALLBACK_DIRS:
        recipe.FALLBACK_DIRS.append(LIVE_MP_DIR)
    missing = recipe.missing_systems(target, recipe._formulas(table), cache_dir)
    key = os.environ.get("MP_API_KEY")
    fetched, failed, start = 0, 0, time.monotonic()
    if key:
        for chemsys in missing[:LIVE_FETCH_LIMIT]:
            if time.monotonic() - start > LIVE_FETCH_SECONDS:
                break
            try:
                recipe.fetch_energies(chemsys, LIVE_MP_DIR, key, timeout=20)
                fetched += 1
            except Exception as exc:   # network or API error: the pair stays unscreened
                failed += 1
                print(f"Materials Project fetch failed for {chemsys}: {type(exc).__name__}", flush=True)
    return {"fetched": fetched, "failed": failed, "missing": len(missing) - fetched}


def _recipe_model() -> dict:
    """The extended precursor table and the learned ranker fitted on it, when both are present;
    otherwise the study's 46-precursor table ranked by driving force."""
    global _RECIPE_MODEL
    if _RECIPE_MODEL is None:
        from kiln import recipe_rank
        table = ROOT / "data" / "precursor_props_extended.csv"
        ranker = recipe_rank.Ranker.load()
        _RECIPE_MODEL = {"table": table, "ranker": ranker} if table.is_file() and ranker else {}
    return _RECIPE_MODEL


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
    item_path = os.environ.get("KILN_ITEMS") or lab.conditions_path(ROOT)
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
        route = urlsplit(self.path).path
        if route == "/api/recipe":
            self.recipe()
            return
        if route == "/api/whatif":
            self.whatif()
            return
        if route != "/api/triage":
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

    def whatif(self) -> None:
        """One recorded prediction rescored by the frozen rules at another furnace temperature."""
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 1024:
                raise ValueError
            body = json.loads(self.rfile.read(length))
            run_id, item_id = str(body["run_id"]), str(body["item_id"])
            temperature = float(body["temperature_c"])
        except Exception:
            self.send_json({"error": "Choose a recorded run and enter a furnace temperature."}, 400)
            return
        from app import whatif
        rows = _cached("lab-records", _lab_paths(), lambda: lab.records(ROOT))
        row = next((r for r in rows if r.get("run_id") == run_id and r.get("item_id") == item_id), None)
        if row is None:
            self.send_json({"error": "That recorded run was not found."}, 404)
            return
        conditions = _cached("conditions", _lab_paths(), lambda: lab.conditions(ROOT)).get(item_id)
        try:
            status, result = whatif.whatif(row, conditions, temperature)
        except Exception:
            self.send_json({"error": "The what-if could not be computed on this server."}, 500)
            return
        self.send_json(result, status)

    def recipe(self) -> None:
        """Rank precursor pairs for a target (kiln.recipe). The MACE check is off unless the host
        enables it with KILN_RECIPE_CHECK=1, because it can take minutes on a CPU."""
        hint = "Enter a formula such as BaTiO3 and a temperature from 100 to 2000 °C"
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 1024:
                raise ValueError(hint)
            body = json.loads(self.rfile.read(length))
            typed = str(body.get("target", "")).strip()
            temperature = float(body.get("temperature_c"))
            if not RECIPE_FORMULA.fullmatch(typed) or not 100 <= temperature <= 2000:
                raise ValueError(hint)
            from pymatgen.core import Composition
            from kiln import recipe as _recipe
            target = _recipe.normalize_formula(typed)
            if not Composition(target).valid:
                raise ValueError(hint)
        except Exception:
            self.send_json({"error": hint}, 400)
            return
        cache_dir = _recipe_cache()
        if cache_dir is None:
            self.send_json({"error": "The Materials Project cache is not on this server, so recipes cannot be screened."}, 503)
            return
        from kiln import recipe
        from pymatgen.core import Composition
        # The MACE check needs crystal structures, which only the full cache has.
        enabled = os.environ.get("KILN_RECIPE_CHECK") == "1" and cache_dir == ROOT / "cache" / "mp"
        check = bool(body.get("check")) and enabled
        settings = None
        if check:
            from kiln.compute.profile import load_tier_settings
            from kiln.schemas import ComputeTier
            settings = {**load_tier_settings()[ComputeTier.single_point],
                        "device": os.environ.get("KILN_RECIPE_DEVICE", "cpu")}
        # The full cache covers only the study's 46 precursors, so it keeps their table and order.
        model = {} if cache_dir == ROOT / "cache" / "mp" else _recipe_model()
        fetch = {"fetched": 0, "missing": 0, "available": bool(os.environ.get("MP_API_KEY"))}
        try:
            with _RECIPE_LOCK:
                if cache_dir != ROOT / "cache" / "mp":
                    fetch.update(_fetch_missing(target, model.get("table", recipe.DEFAULT_TABLE), cache_dir))
                result = recipe.find(target, temperature, n_check=3 if check else 0,
                                     cache_dir=cache_dir, settings=settings, **model)
        except Exception:
            self.send_json({"error": "The recipe search failed on this server. Check the server log."}, 500)
            return
        ranker = model.get("ranker")
        ranking = {"method": "learned" if ranker else "driving_force",
                   "n_precursors": len(recipe._formulas(model.get("table", recipe.DEFAULT_TABLE))),
                   "summary": ranker.meta.get("summary", "") if ranker else ""}
        why = ""
        if not result.candidates:
            pool = {Composition(f).reduced_formula for f in recipe._formulas(model.get("table", recipe.DEFAULT_TABLE))}
            cations = [e.symbol for e in Composition(target).elements if e.symbol not in ("O", "C", "H", "N")]
            if Composition(target).reduced_formula in pool:
                why = f"{target} is itself one of Kiln's precursors, so it is bought rather than made from a pair."
            elif len(cations) < 2:
                why = (f"{target} has only one element besides O, C, H and N, so it comes from a single precursor "
                       "(for example by decomposing a salt), and the finder only tries pairs.")
        self.send_json({**result.to_dict(), "check_available": enabled, "ranking": ranking,
                        "typed": typed, "materials_project": fetch, "why_none": why})

    def do_GET(self) -> None:
        route = urlsplit(self.path).path
        assets = {"/assets/app.css": (APP_DIR / "assets" / "app.css", "text/css; charset=utf-8"),
                  "/assets/app.js": (APP_DIR / "assets" / "app.js", "text/javascript; charset=utf-8"),
                  "/assets/lab.css": (APP_DIR / "assets" / "lab.css", "text/css; charset=utf-8"),
                  "/assets/lab.js": (APP_DIR / "assets" / "lab.js", "text/javascript; charset=utf-8")}
        try:
            if route == "/api/status":
                cache = _recipe_cache()
                self.send_json({"live": False, "recipe": cache is not None,
                                "recipe_check": os.environ.get("KILN_RECIPE_CHECK") == "1"
                                and cache == ROOT / "cache" / "mp"})
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
