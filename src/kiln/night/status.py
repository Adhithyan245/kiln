"""One screen of night status, from the files the night already writes.

    python -m kiln.night status src/kiln/night/plans/night2.toml [--runs-dir runs]

Per run: predictions against items, crashed and finalized items, compute backend (STUB is shouted),
tokens, dollars and GPU-seconds. Then spend against the plan's caps, each step's state, and the last
alerts. Reads only; never touches a running night.
"""
from __future__ import annotations

import json
from pathlib import Path

from kiln.night.plan import Plan
from kiln.night.spend import breach, read_spend

__all__ = ["status_lines"]


def _count(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open(encoding="utf-8") as f:
        return sum(1 for line in f if line.strip())


def _gpu_seconds(path: Path) -> float:
    if not path.exists():
        return 0.0
    with path.open(encoding="utf-8") as f:
        return sum(float(json.loads(line).get("gpu_seconds", 0.0)) for line in f if line.strip())


def status_lines(plan: Plan, runs_dir: Path, state_dir: Path, alerts: int = 5) -> list[str]:
    lines = [f"night {plan.name!r}: runs in {runs_dir}"]
    runs = sorted(p.parent for p in runs_dir.glob("*/config.json"))
    for run in runs:
        config = json.loads((run / "config.json").read_text(encoding="utf-8"))
        backend = config.get("compute_backend") or "unrecorded"
        warn = "  <-- STUB COMPUTE: fake energies" if backend == "stub" or "compute" in config.get("stub_parts", []) else ""
        costs = json.loads((run / "cost.json").read_text(encoding="utf-8")) if (run / "cost.json").exists() else {}
        tokens = sum(c.get("tokens_in", 0) + c.get("tokens_out", 0) for c in costs.values())
        usd = sum(c.get("usd", 0.0) for c in costs.values())
        lines.append(f"  {run.name}: {_count(run / 'predictions.jsonl')}/{config.get('n_items', '?')} predicted, "
                     f"{_count(run / 'failed_items.jsonl')} crashed, {_count(run / 'finalized_items.jsonl')} finalized; "
                     f"backend {backend}; {tokens} tokens, ${usd:.2f}, "
                     f"{_gpu_seconds(run / 'compute_requests.jsonl') / 3600:.2f} GPU-h{warn}")
    if not runs:
        lines.append("  (no runs yet)")
    spend = read_spend(runs_dir)
    why = breach(spend, plan.caps)
    lines.append(f"spend: {spend.summary(plan.caps)}" + (f"  <-- {why}" if why else ""))
    state = state_dir / "state.json"
    if state.exists():
        data = json.loads(state.read_text(encoding="utf-8"))
        steps = ", ".join(f"{k}={v}" for k, v in data.get("steps", {}).items())
        lines.append(f"steps: {steps or '(none yet)'}" + (f"; stopped: {data['stopped']}" if data.get("stopped") else ""))
    else:
        lines.append("steps: no state yet (night not started here)")
    log = state_dir / "alerts.log"
    if log.exists():
        lines.append("last alerts:")
        lines += [f"  {line}" for line in log.read_text(encoding="utf-8").splitlines()[-alerts:]]
    return lines
