"""UI-only adapters for cached run artifacts. No labels, model calls or scoring.

    adapt_trail(artifacts, candidate, provenance=None) -> dict
    make_your_call(pairs, root) -> list[dict]
    load_workspace(root) -> dict

Current JSONL runs and the supplied plan's legacy candidate exports are supported.
Risk values must be recorded by the producer; this module never invents a risk mapping.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import re
from datetime import datetime
from pathlib import Path


RISK_WORDS = {"red": "High risk", "amber": "Watch", "green": "Go", "inconclusive": "Inconclusive"}
PREDICTION_KEYS = ("run_id", "condition", "seed", "item_id", "category", "p_react", "cause", "fix", "evidence",
                   "review_flags", "needs_review", "disagreements", "applicability_notes", "cost", "risk", "risk_before",
                   "mlip_disagreement", "precursor_a", "precursor_b", "temperature_c", "dwell_h", "split")
ARTIFACT_KEYS = ("artifact_id", "agent", "type", "summary", "values", "claims", "cites", "fulfills_need",
                 "compute_requests", "rationale", "verifier", "verifier_notes", "created_at")
REQUEST_KEYS = ("request_id", "agent", "tier", "reason", "inputs", "settings", "status", "compute_units",
               "gpu_seconds", "p_react_before", "p_react_after", "category_before", "category_after",
               "changed_prediction", "created_at", "cache_key")
RESULT_KEYS = ("dE_ev_per_atom", "dE_mp_ev_per_atom", "dE_mlip_minus_mp_ev_per_atom", "products", "source",
               "model", "backend", "competitor_e_hull_ev_per_atom", "competitor_formula", "n_not_converged", "error",
               "mp_products", "reactants", "n_structures", "max_steps_used", "n_finished_by_ase")


def read_json(path: Path, default=None):
    return json.loads(path.read_text(encoding="utf-8-sig")) if path.is_file() else default


def read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [row for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()
            if isinstance(row := json.loads(line), dict)]


def _timestamp(value) -> float:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError, OverflowError):
        return float("inf")


def adapt_trail(artifacts: list[dict], candidate: dict, provenance: list[str] | None = None) -> dict:
    """The component and cards consume the same list: explicit provenance, then timestamps.

    Missing timestamps retain input order. Last append of each id is its verifier's final stamp.
    """
    latest = {}
    for index, artifact in enumerate(artifacts):
        if not isinstance(artifact, dict):
            continue
        key = artifact.get("artifact_id") or f"unidentified-{index}"
        latest[key] = {key_: artifact.get(key_) for key_ in ARTIFACT_KEYS} | {"artifact_id": key}
    order = {str(key): i for i, key in enumerate(provenance or [])}
    arranged = sorted(latest.values(), key=lambda a: (order.get(a["artifact_id"], len(order)), _timestamp(a.get("created_at"))))
    for artifact in arranged:
        if artifact.get("verifier") not in ("accepted", "rejected", "pending", "inconclusive"):
            artifact["verifier"] = "inconclusive"
        if not artifact.get("summary"):
            claims = artifact.get("claims") or []
            artifact["summary"] = next((c.get("statement") for c in claims if isinstance(c, dict) and c.get("statement")), None) or artifact.get("rationale") or "Recorded evidence"
    after = candidate.get("risk") if candidate.get("risk") in RISK_WORDS else None
    before = candidate.get("risk_before") if candidate.get("risk_before") in RISK_WORDS else None
    if before == after or not any(a.get("fulfills_need") and a["verifier"] == "accepted" for a in arranged):
        before = None
    return {"artifacts": arranged, "risk_before": before, "risk_after": after, "replayed": True}


def scoring_gate(root: Path) -> bool:
    """The supplied plan's explicit release gate. It is not independent receipt verification."""
    digest = root / "protocol" / "predictions.sha256"
    comparison = root / "results" / "comparison.json"
    if not digest.is_file() or not comparison.is_file():
        return False
    try:
        return bool(re.fullmatch(r"[0-9a-fA-F]{64}", digest.read_text().strip())) and isinstance(read_json(comparison), dict)
    except (OSError, ValueError):
        return False


def make_your_call(pairs: list[dict], root: Path) -> list[dict]:
    """Release explicit scored outcomes only, with development fallback and no score derivation."""
    released = scoring_gate(root)
    result = []
    for pair in pairs:
        if not isinstance(pair, dict) or pair.get("split") not in ("dev", "heldout"):
            continue
        if pair["split"] == "heldout" and not released:
            continue
        if not isinstance(pair.get("real_reacts"), bool) or not isinstance(pair.get("kiln_reacts"), bool):
            continue
        if not isinstance(pair.get("precursors"), list) or len(pair["precursors"]) != 2 or not pair.get("id"):
            continue
        view = {k: pair.get(k) for k in ("id", "precursors", "temp_c", "hours", "kiln_reacts", "kiln_cause", "real_reacts", "split")}
        view["label"] = "Held-out pair · scored" if pair["split"] == "heldout" else "Development pair"
        view["artifacts"] = adapt_trail(pair.get("artifacts", []), pair)["artifacts"]
        result.append(view)
    heldout = [p for p in result if p["split"] == "heldout"]
    return heldout if released and heldout else [p for p in result if p["split"] == "dev"]


def _stub(config: dict, requests: list[dict]) -> bool:
    return bool(config.get("stubs_used") or config.get("stub_parts")) or any(
        (r.get("result") or {}).get("model") == "stub" or (r.get("result") or {}).get("stub") is True
        or (r.get("settings") or {}).get("backend") == "stub" for r in requests)


def _extract_telemetry(row: dict) -> dict:
    """Summarize verified numeric values from accepted artifacts and requests for visual gauges."""
    accepted = [a for a in (row.get("artifacts") or []) if a.get("verifier") == "accepted"]
    dE = None
    dE_mp = None
    dE_diff = None
    tammann_a = None
    tammann_b = None
    decomp_info = None
    products = None
    for a in accepted:
        vals = a.get("values") or {}
        if not isinstance(vals, dict):
            continue
        if isinstance(vals.get("dE_ev_per_atom"), (int, float)) and math.isfinite(vals["dE_ev_per_atom"]):
            dE = float(vals["dE_ev_per_atom"])
        if isinstance(vals.get("dE_mlip_minus_mp_ev_per_atom"), (int, float)) and math.isfinite(vals["dE_mlip_minus_mp_ev_per_atom"]):
            dE_diff = float(vals["dE_mlip_minus_mp_ev_per_atom"])
        if isinstance(vals.get("tammann_a_c"), (int, float)) and math.isfinite(vals["tammann_a_c"]):
            tammann_a = float(vals["tammann_a_c"])
        if isinstance(vals.get("tammann_b_c"), (int, float)) and math.isfinite(vals["tammann_b_c"]):
            tammann_b = float(vals["tammann_b_c"])
        if vals.get("precursor_a_product") or vals.get("precursor_b_product"):
            parts = []
            if vals.get("precursor_a_product") and vals.get("precursor_a_product") != "unknown":
                parts.append(f"{vals.get('precursor_a_formula', 'A')} → {vals['precursor_a_product']}")
            if vals.get("precursor_b_product") and vals.get("precursor_b_product") != "unknown":
                parts.append(f"{vals.get('precursor_b_formula', 'B')} → {vals['precursor_b_product']}")
            if parts:
                decomp_info = " · ".join(parts)
    for req in (row.get("requests") or []):
        res = req.get("result") or {}
        if isinstance(res.get("dE_mp_ev_per_atom"), (int, float)) and math.isfinite(res["dE_mp_ev_per_atom"]):
            dE_mp = float(res["dE_mp_ev_per_atom"])
        if res.get("products"):
            products = str(res["products"])
    cost = row.get("cost") if isinstance(row.get("cost"), dict) else {}
    units = cost.get("compute_units")
    if not isinstance(units, (int, float)):
        units = sum(q["compute_units"] for q in (row.get("requests") or []) if isinstance(q.get("compute_units"), (int, float)))
    gpu_s = cost.get("gpu_seconds")
    if not isinstance(gpu_s, (int, float)):
        gpu_s = sum(q["gpu_seconds"] for q in (row.get("requests") or []) if isinstance(q.get("gpu_seconds"), (int, float)))
    tiers = [str(q.get("tier")) for q in (row.get("requests") or []) if q.get("tier")]
    fulfilled_needs = sum(1 for a in accepted if a.get("fulfills_need"))
    return {
        "dE_ev_per_atom": dE,
        "dE_mp_ev_per_atom": dE_mp,
        "dE_mlip_minus_mp_ev_per_atom": dE_diff,
        "tammann_a_c": tammann_a,
        "tammann_b_c": tammann_b,
        "decomp_summary": decomp_info,
        "products": products,
        "compute_units": round(float(units), 3) if isinstance(units, (int, float)) else 0.0,
        "gpu_seconds": round(float(gpu_s), 3) if isinstance(gpu_s, (int, float)) else 0.0,
        "tiers": tiers,
        "fulfilled_needs": fulfilled_needs,
    }


def _view(candidate: dict, artifacts: list[dict], requests: list[dict], source: str, run_id: str,
          config: dict | None = None, provenance: list[str] | None = None) -> dict:
    row = {k: candidate.get(k) for k in PREDICTION_KEYS}
    cfg = (config or {}).get("run_config", {})
    row["item_id"] = candidate.get("item_id") or candidate.get("id") or "Unnamed record"
    row["run_id"] = candidate.get("run_id") or run_id
    row["condition"] = row.get("condition") or cfg.get("condition")
    row["seed"] = row["seed"] if row.get("seed") is not None else cfg.get("seed")
    row["split"] = candidate.get("split") or cfg.get("split")
    row["key"] = hashlib.sha256(f'{source}/{run_id}/{row["item_id"]}'.encode()).hexdigest()[:20]
    row["source_label"] = source
    row["source_kind"] = "h100" if source.startswith("H100") else ("dryrun" if "dry run" in source.lower() else "legacy")
    row["stubs_used"] = False
    row["requests"] = []
    for request in requests:
        view = {k: request.get(k) for k in REQUEST_KEYS}
        view["result"] = {k: v for k, v in (request.get("result") or {}).items() if k in RESULT_KEYS}
        row["requests"].append(view)
        inputs = request.get("inputs") or {}
        for key in ("precursor_a", "precursor_b", "temperature_c", "dwell_h"):
            if row.get(key) is None and inputs.get(key) is not None:
                row[key] = inputs[key]
    row.update(adapt_trail(artifacts, row, provenance))
    row["risk"] = row["risk_after"]
    row["models_disagree"] = row.get("mlip_disagreement") is True or any(
        f.get("reason") == "conflict" and "energy" in str(f.get("detail", "")).lower()
        for f in (row.get("review_flags") or []) if isinstance(f, dict))
    row["has_need_change"] = bool(row["risk_before"] and row["risk_after"] and row["risk_before"] != row["risk_after"])
    row["telemetry"] = _extract_telemetry(row)
    return row



def load_records(root: Path, warnings: list[str]) -> list[dict]:
    records = []
    for prediction_path in sorted((root / "runs-h100").glob("*/predictions.jsonl")):
        run = prediction_path.parent
        try:
            config = read_json(run / "config.json", {})
            requests = read_jsonl(run / "compute_requests.jsonl")
            if _stub(config, requests):
                warnings.append(f"Excluded stand-in run: {run.name}.")
                continue
            artifacts = []
            for path in sorted((run / "board").rglob("artifacts.jsonl")):
                artifacts.extend(read_jsonl(path))
            for prediction in read_jsonl(prediction_path):
                item = prediction.get("item_id")
                if item:
                    records.append(_view(prediction, [a for a in artifacts if a.get("item_id") == item],
                        [r for r in requests if r.get("item_id") == item], "H100 (ALCHEMI Toolkit)", run.name, config))
        except (OSError, ValueError, TypeError, AttributeError):
            warnings.append(f"Could not load {run.name}; its files may be incomplete.")
    # Original app contract in the supplied plan; never scans labels or the ledger.
    for path in sorted((root / "runs").glob("*/*/candidates.json")):
        try:
            candidates = read_json(path, [])
            candidates = candidates.get("candidates", []) if isinstance(candidates, dict) else candidates
            provenance = read_json(path.parent / "provenance.json", {})
            order = provenance.get("artifact_order", []) if isinstance(provenance, dict) else provenance
            artifacts = []
            for artifact_path in sorted((path.parent / "artifacts").glob("*.json")):
                value = read_json(artifact_path, {})
                artifacts.extend(value if isinstance(value, list) else [value])
            if _stub(read_json(path.parent / "config.json", {}), []):
                continue
            for candidate in candidates:
                key = candidate.get("item_id") or candidate.get("id")
                chosen = [a for a in artifacts if a.get("item_id", a.get("candidate_id")) == key]
                records.append(_view(candidate, chosen, [], "Recorded legacy run", str(path.parent.relative_to(root)), provenance=order))
        except (OSError, ValueError, TypeError, AttributeError):
            warnings.append(f"Could not load legacy candidates in {path.parent.name}.")
    return sorted(records, key=lambda r: (not bool(r.get("needs_review")), str(r.get("item_id")), str(r.get("condition")), str(r.get("seed"))))


def load_provenance(root: Path) -> dict:
    result = {"protocol_sha256": None, "prediction_sha256": None, "prediction_posted_at": None}
    path = root / "protocol" / "amendments.md"
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("| SHA-256 of `git cat-file blob"):
                found = re.search(r"\| `([0-9a-f ]+)`", line)
                value = found.group(1).replace(" ", "") if found else ""
                if len(value) == 64:
                    result["protocol_sha256"] = value
                break
    manifest = root / "protocol" / "predictions-h100.manifest.json"
    if manifest.is_file():
        result["prediction_sha256"] = hashlib.sha256(manifest.read_bytes()).hexdigest()
        for receipt in read_jsonl(root / "protocol" / "posts-h100.jsonl"):
            if receipt.get("sha256") == result["prediction_sha256"]:
                result["prediction_posted_at"] = receipt.get("message_timestamp") or receipt.get("recorded_at")
    return result


def load_evaluations(root: Path, records: list[dict], warnings: list[str]) -> list[dict]:
    """Aggregate evaluator outputs must match the H100 prediction bytes; no lab labels loaded."""
    reports = []
    for run_id in sorted({r["run_id"] for r in records if r["source_kind"] == "h100"}):
        if Path(run_id).name != run_id:
            continue
        pred_path = root / "runs-h100" / run_id / "predictions.jsonl"
        for report_path in (root / "results" / run_id / "evaluation.json", root / "results" / "h100" / run_id / "evaluation.json"):
            try:
                report = read_json(report_path)
                if not report or report.get("invalid") is True:
                    continue
                meta = report.get("run") or {}
                if report.get("prediction_sha256") != hashlib.sha256(pred_path.read_bytes()).hexdigest():
                    warnings.append(f"Evaluation for {run_id} does not match the loaded predictions; not displayed.")
                    continue
                if "runs-h100/" not in str(meta.get("run_dir", "")).replace("\\", "/"):
                    continue
                sample = next(r for r in records if r["run_id"] == run_id)
                metrics = {k: v for k, v in (report.get("metrics") or {}).items()
                           if k in ("auroc", "brier", "coverage", "four_class_accuracy", "n", "n_scored")
                           and (v is None or isinstance(v, (int, float)) and math.isfinite(v))}
                reports.append({"run_id": run_id, "condition": sample["condition"], "seed": sample["seed"], "metrics": metrics,
                                "verification": meta.get("verification"), "prediction_sha256": report["prediction_sha256"]})
                break
            except (OSError, ValueError, TypeError, AttributeError):
                warnings.append(f"Could not read the evaluation for {run_id}.")
    return reports


def load_precursors(root: Path) -> list[dict]:
    """Load the cited precursor property table with Tammann temperatures (2/3 T_m in K -> °C)."""
    path = root / "data" / "precursor_props.csv"
    if not path.is_file():
        return []
    rows = []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for item in csv.DictReader(handle):
                formula = (item.get("formula") or "").strip()
                if not formula:
                    continue
                mp_raw = (item.get("melting_point_c") or "").strip()
                decomp_raw = (item.get("decomposes_at_c") or "").strip()
                mp_c = float(mp_raw) if mp_raw and mp_raw != "unknown" else None
                decomp_c = float(decomp_raw) if decomp_raw and decomp_raw != "unknown" else None
                tammann_c = round((2.0 / 3.0) * (mp_c + 273.15) - 273.15, 1) if mp_c is not None else None
                prod = (item.get("decomposition_product") or "").strip()
                sem = (item.get("melting_point_semantics") or "as_reported").strip()
                note = (item.get("melting_point_semantics_note") or "").strip()
                rows.append({
                    "formula": formula,
                    "melting_point_c": mp_c,
                    "tammann_c": tammann_c,
                    "decomposes_at_c": decomp_c,
                    "decomposition_product": prod if prod != "unknown" else None,
                    "melting_point_source": (item.get("melting_point_source") or "").strip(),
                    "melting_point_source_url": (item.get("melting_point_source_url") or "").strip(),
                    "melting_point_semantics": sem if sem != "unknown" else "as_reported",
                    "melting_point_semantics_source": (item.get("melting_point_semantics_source") or "").strip(),
                    "melting_point_semantics_note": note if note != "unknown" else None,
                })
    except (OSError, ValueError):
        return []
    return rows


def load_frozen_settings(root: Path) -> dict:
    """Expose frozen tier prices and budget caps for UI telemetry bars."""
    raw = read_json(root / "protocol" / "frozen_settings.json", {})
    if not isinstance(raw, dict):
        return {}
    return {
        "tier_prices": raw.get("tier_prices") or {"cached_lookup": 0.1, "decomposition_reeval": 0.2, "single_point": 1.0, "bounded_relaxation": 30.0},
        "max_compute_units_per_item": raw.get("max_compute_units_per_item", 32.0),
        "max_tool_calls_per_item": raw.get("max_tool_calls_per_item", 12),
        "max_tokens_per_item": raw.get("max_tokens_per_item", 40000),
        "energy_margin_ev_per_atom": raw.get("energy_margin_ev_per_atom", 0.05),
        "disagreement_threshold_ev_per_atom": raw.get("disagreement_threshold_ev_per_atom", 0.05),
    }


def load_dryrun_records(root: Path) -> list[dict]:
    """Load real-compute development dry-run items from results/gb10/dryrun_e89d25a (excluding any stub item)."""
    dryrun_root = root / "results" / "gb10" / "dryrun_e89d25a"
    if not dryrun_root.is_dir():
        return []
    records = []
    for prediction_path in sorted(dryrun_root.glob("*/predictions.jsonl")):
        run = prediction_path.parent
        try:
            config = read_json(run / "config.json", {})
            if bool(config.get("stubs_used") or config.get("stub_parts")):
                continue
            requests = read_jsonl(run / "compute_requests.jsonl")
            artifacts = []
            for path in sorted((run / "board").rglob("artifacts.jsonl")):
                artifacts.extend(read_jsonl(path))
            for prediction in read_jsonl(prediction_path):
                item = prediction.get("item_id")
                if not item:
                    continue
                item_reqs = [r for r in requests if r.get("item_id") == item]
                if _stub({}, item_reqs):
                    continue
                item_arts = [a for a in artifacts if a.get("item_id") == item]
                records.append(_view(prediction, item_arts, item_reqs, "Development dry run (real compute)", run.name, config))
        except (OSError, ValueError, TypeError, AttributeError):
            continue
    return sorted(records, key=lambda r: (not bool(r.get("needs_review")), str(r.get("item_id")), str(r.get("condition")), str(r.get("seed"))))


def load_workspace(root: Path) -> dict:
    warnings = []
    records = load_records(root, warnings)
    gate = scoring_gate(root)
    pairs = []
    # These are explicit UI exports, never raw label files. Missing exports leave the exercise empty.
    for name in (["development_pairs.json", "scored_pairs.json"] if gate else ["development_pairs.json"]):
        try:
            rows = read_json(root / "results" / "app" / name, [])
            pairs.extend(rows if isinstance(rows, list) else [])
        except (OSError, ValueError):
            warnings.append(f"Could not load the published {name} export.")
    try:
        provenance = load_provenance(root)
    except (OSError, ValueError):
        provenance = {}
        warnings.append("Provenance files are incomplete.")
    return {
        "records": records,
        "dryrun_records": load_dryrun_records(root),
        "precursors": load_precursors(root),
        "frozen_settings": load_frozen_settings(root),
        "provenance": provenance,
        "evaluations": load_evaluations(root, records, warnings),
        "call_pairs": make_your_call(pairs, root),
        "scoring_released": gate,
        "warnings": warnings,
    }
