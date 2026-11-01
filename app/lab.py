"""Read-only laboratory replay API and transparent compute summaries."""
from __future__ import annotations

import math
import os
from collections import defaultdict
from pathlib import Path
from app import data
from app.invalid_runs import invalid_gb10


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def records(root: Path) -> list[dict]:
    """Load lightweight summaries; read individual evidence only when replayed."""
    rows = []
    cut_paths = sorted((root / "runs-h100-cut").glob("*/predictions.jsonl"))
    # The preregistered 301-pair cut is the adopted result. Do not pool it
    # with the partial full run or the secondary GB10 replication.
    sources = [("runs-h100-cut", "H100 (adopted 301-pair result)", "h100_cut")] if cut_paths else [
        ("runs-h100", "H100 (ALCHEMI Toolkit)", "h100"), ("runs", "GB10 rerun", "gb10")]
    for folder, source, kind in sources:
      for path in sorted((root / folder).glob("*/predictions.jsonl")):
        try:
            if kind == "gb10" and ("invalid" in path.parent.name.lower() or invalid_gb10(path)):
                continue
            config = data.read_json(path.parent / "config.json", {})
            requests = data.read_jsonl(path.parent / "compute_requests.jsonl")
            if data._stub(config, requests):
                continue
            by_item = defaultdict(list)
            for request in requests:
                by_item[request.get("item_id")].append(request)
            for prediction in data.read_jsonl(path):
                item = prediction.get("item_id")
                if item:
                    row = data._view(prediction, [], by_item[item], source, path.parent.name, config)
                    row["source_kind"] = kind
                    row["_run_dir"] = str(path.parent)
                    rows.append(row)
        except (OSError, ValueError, TypeError, AttributeError):
            continue
    item_path = os.environ.get("KILN_ITEMS")
    if item_path:
        path = Path(item_path)
        # This input must be the label-free item export, never the raw ledger.
        if "labels" in [s.lower() for s in path.resolve().parts] or "ledger" in path.name.lower():
            raise ValueError("KILN_ITEMS must be a label-free item export")
        items = {i.get("item_id"): i for i in data.read_jsonl(path)}
        for row in rows:
            for key in ("precursor_a", "precursor_b", "temperature_c", "dwell_h"):
                if row.get(key) is None:
                    row[key] = items.get(row["item_id"], {}).get(key)
    return rows


def _item_artifacts(row: dict) -> list[dict]:
    """Load and deduplicate only the selected item's recorded artifacts."""
    item = str(row.get("item_id") or "")
    if not item or Path(item).name != item or not row.get("_run_dir"):
        return row.get("artifacts") or []
    board = Path(row["_run_dir"]) / "board"
    files = list((board / item).rglob("artifacts.jsonl"))
    if (board / "artifacts.jsonl").is_file():
        files.append(board / "artifacts.jsonl")
    artifacts = [a for path in sorted(files) for a in data.read_jsonl(path) if a.get("item_id") == item]
    return data.adapt_trail(artifacts, row)["artifacts"]


def pairs(rows: list[dict]) -> list[dict]:
    grouped = {}
    for row in rows:
        if not row.get("precursor_a") or not row.get("precursor_b"):
            continue
        key = (row["item_id"], row["precursor_a"], row["precursor_b"])
        item = grouped.setdefault(key, {k: row.get(k) for k in ("item_id", "precursor_a", "precursor_b", "temperature_c", "dwell_h")} | {"runs": []})
        item["runs"].append({"condition": row["condition"], "seed": row["seed"], "source": row["source_label"], "run_id": row["run_id"]})
    return list(grouped.values())


def requests(rows):
    seen = set()
    output = []
    for row in rows:
        for i, request in enumerate(row["requests"]):
            key = (row["source_label"], row["run_id"], request.get("request_id") or (row["item_id"], i))
            if key not in seen:
                seen.add(key)
                output.append(request | {"source_label": row["source_label"], "condition": row["condition"], "seed": row["seed"]})
    return output


def reuse_info(all_requests: list[dict], subset: list[dict] | None = None) -> dict:
    fresh = {}
    for request in sorted(all_requests, key=lambda r: str(r.get("created_at") or "")):
        key = (request.get("source_label"), request.get("cache_key"))
        seconds = request.get("gpu_seconds")
        if key[1] and request.get("status") in ("ok", "not_converged", "failed") and finite(seconds) and seconds > 0:
            fresh.setdefault(key, seconds)
    by_tier = defaultdict(lambda: {"reuses": 0, "estimated_gpu_seconds_avoided": 0.0, "unmatched_reuses": 0})
    details = []
    for request in all_requests if subset is None else subset:
        if request.get("status") != "cached":
            continue
        seconds = fresh.get((request.get("source_label"), request.get("cache_key")))
        group = by_tier[request.get("tier") or "unknown"]
        group["reuses"] += 1
        group["estimated_gpu_seconds_avoided"] += seconds or 0
        group["unmatched_reuses"] += seconds is None
        details.append({"request_id": request.get("request_id"), "fresh_gpu_seconds": seconds})
    return {"reuses": len(details), "estimated_gpu_seconds_avoided": sum(g["estimated_gpu_seconds_avoided"] for g in by_tier.values()),
            "unmatched_reuses": sum(g["unmatched_reuses"] for g in by_tier.values()), "by_tier": dict(by_tier), "requests": details,
            "method": "Estimated from the earliest timed original calculation with the same cache key and machine. Unmatched reuses contribute no seconds."}


def totals(reqs):
    return {"requests": len(reqs), "compute_units": sum(r["compute_units"] for r in reqs if finite(r.get("compute_units"))),
            "gpu_seconds": sum(r["gpu_seconds"] for r in reqs if finite(r.get("gpu_seconds"))),
            "missing_units": sum(not finite(r.get("compute_units")) for r in reqs),
            "missing_gpu_seconds": sum(not finite(r.get("gpu_seconds")) for r in reqs)}


def compute(root: Path, rows: list[dict]) -> dict:
    reqs = requests(rows)
    raw = data.read_json(root / "protocol" / "frozen_settings.json", {})
    prices = {k: v for k, v in raw.get("tier_prices", {}).items() if finite(v)}
    full = sum(prices.values()) if all(k in prices for k in ("cached_lookup", "single_point", "bounded_relaxation", "decomposition_reeval")) else None
    all_totals = totals(reqs)
    tiers = []
    for tier in sorted({r.get("tier") or "unknown" for r in reqs}):
        group = totals([r for r in reqs if (r.get("tier") or "unknown") == tier])
        group.update(tier=tier, unit_share=group["compute_units"] / all_totals["compute_units"] if all_totals["compute_units"] and not all_totals["missing_units"] else None,
                     gpu_share=group["gpu_seconds"] / all_totals["gpu_seconds"] if all_totals["gpu_seconds"] and not all_totals["missing_gpu_seconds"] else None)
        tiers.append(group)
    conditions = []
    for source, condition in sorted({(r["source_label"], str(r["condition"])) for r in rows}):
        group_rows = [r for r in rows if r["source_label"] == source and str(r["condition"]) == condition]
        group_reqs = [r for r in reqs if r["source_label"] == source and str(r["condition"]) == condition]
        group = totals(group_reqs)
        group.update(source_label=source, condition=condition, predictions=len(group_rows),
                     mean_compute_units=group["compute_units"] / len(group_rows) if group_reqs and all(r["requests"] for r in group_rows) and not group["missing_units"] else None,
                     single_point_pct=100 * sum(any(q.get("tier") == "single_point" for q in r["requests"]) for r in group_rows) / len(group_rows),
                     relaxation_pct=100 * sum(any(q.get("tier") == "bounded_relaxation" for q in r["requests"]) for r in group_rows) / len(group_rows),
                     cached_pct=100 * sum(q.get("status") == "cached" for q in group_reqs) / len(group_reqs) if group_reqs else None)
        conditions.append(group)
    toolkit = [r for r in reqs if (r.get("result") or {}).get("backend") == "nvalchemi+ase"]
    toolkit_stats = {"requests": len(toolkit)}
    for field in ("n_structures", "n_finished_by_ase"):
        values = [r["result"].get(field) for r in toolkit]
        toolkit_stats[field] = sum(values) if values and all(finite(v) for v in values) else None
    benchmark = data.read_json(root / "results" / "gb10" / "toolkit_hybrid_check.json", {})
    bench = {"n_structures": benchmark.get("n_structures"), "hybrid": benchmark.get("runs", {}).get("nvalchemi+ase"),
             "ase": benchmark.get("runs", {}).get("ase"), "energy_difference_mev_per_atom": benchmark.get("hybrid_vs_ase_max_mev_per_atom")}
    lookup_only = sum(bool(r["requests"]) and all(q.get("tier") == "cached_lookup" for q in r["requests"]) for r in rows)
    return {"by_condition": conditions, "by_tier": tiers, "totals": all_totals, "reuse": reuse_info(reqs), "toolkit": toolkit_stats,
            "benchmark": bench, "tier_prices": prices, "full_check_units": full, "predictions": len(rows),
            "lookup_only_pct": 100 * lookup_only / len(rows) if rows else None,
            "saved_vs_full_check": full * len(rows) - all_totals["compute_units"] if rows and all(r["requests"] for r in rows) and full is not None and not all_totals["missing_units"] else None}


def triage(root: Path, body: dict, rows: list[dict]) -> tuple[int, dict]:
    if body.get("live"):
        return 409, {"error": "Live mode is off on this server"}
    if not body.get("precursor_a") or not body.get("precursor_b"):
        return 400, {"error": "Choose two precursors"}
    choices = [r for r in rows if sorted([str(r.get("precursor_a") or "").strip().casefold(), str(r.get("precursor_b") or "").strip().casefold()]) == sorted([str(body["precursor_a"]).strip().casefold(), str(body["precursor_b"]).strip().casefold()])]
    for key in ("condition", "seed", "run_id", "item_id", "source_label"):
        if body.get(key) is not None:
            choices = [r for r in choices if str(r.get(key)) == str(body[key])]
    if not choices:
        return 404, {"error": "No recorded assessment for this selection. Live mode is off on this server.", "available": pairs(rows)}
    row = sorted(choices, key=lambda r: (r["source_kind"] not in ("h100", "h100_cut"), r["run_id"]))[0]
    artifacts = _item_artifacts(row)
    subset = [r | {"source_label": row["source_label"]} for r in row["requests"]]
    return 200, {"mode": "replay", "item": {k: row.get(k) for k in ("item_id", "precursor_a", "precursor_b", "temperature_c", "dwell_h")},
                 "source_label": row["source_label"], "prediction": {k: row.get(k) for k in data.PREDICTION_KEYS},
                 "artifacts": artifacts, "requests": row["requests"], "reuse": reuse_info(requests(rows), subset)}
