"""Temperature what-if: the frozen scoring rules re-applied to one recorded run's evidence.

The rules turn accepted evidence into (p_react, category); the furnace temperature enters only
through furnace-minus-Tammann features. So rescoring the same accepted artifacts with another
temperature is exactly what Kiln would have concluded from that evidence at that temperature.
It is checked first: rescoring at the recorded temperature must reproduce the recorded prediction,
or no what-if is given. Evidence the agents gathered at the recorded temperature is reused as it
is (for example a precursor's decomposition), which is what the caveat in the response says.
No agents, no GPU, no labels.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

MIN_C, MAX_C = 100.0, 2000.0


def _attempt(path: Path) -> int:
    m = re.search(r"attempt-(\d+)", str(path))
    return int(m.group(1)) if m else 0


def accepted_evidence(run_dir: Path, item_id: str, evidence_ids: list[str]) -> list:
    """The prediction's accepted artifacts, latest attempt winning. C4 keeps one board per item,
    C2 one per agent (attempt-N/<agent>/artifacts.jsonl); both are read."""
    from kiln.schemas import Artifact

    board = Path(run_dir) / "board" / item_id
    latest = {}
    for path in sorted(board.rglob("artifacts.jsonl"), key=lambda p: (_attempt(p), str(p))):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                a = Artifact(**json.loads(line))
                latest[a.artifact_id] = a
    wanted = set(evidence_ids)
    return [a for a in latest.values() if a.verifier == "accepted" and a.artifact_id in wanted]


def whatif(row: dict, conditions: dict, temperature_c: float) -> tuple[int, dict]:
    """(status, body) for one recorded prediction rescored at `temperature_c`."""
    from kiln.schemas import Item
    from kiln.scoring.score import provisional

    if not MIN_C <= temperature_c <= MAX_C:
        return 400, {"error": f"Enter a furnace temperature from {MIN_C:g} to {MAX_C:g} °C"}
    if not conditions or conditions.get("temperature_c") is None:
        return 409, {"error": "This pair's recorded furnace conditions are not available on this server."}
    pred_path = Path(row["_run_dir"]) / "predictions.jsonl"
    prediction = next((json.loads(l) for l in pred_path.read_text(encoding="utf-8").splitlines()
                       if l.strip() and json.loads(l).get("item_id") == row["item_id"]), None)
    if prediction is None:
        return 404, {"error": "Recorded prediction not found."}
    accepted = accepted_evidence(Path(row["_run_dir"]), row["item_id"], prediction.get("evidence") or [])
    fields = set(Item.model_fields)
    item = Item(**{k: v for k, v in conditions.items() if k in fields})
    p0, c0 = provisional(item, accepted)
    if abs(p0 - prediction["p_react"]) > 1e-9 or c0.value != prediction["category"]:
        return 409, {"error": "The recorded prediction could not be reproduced from its evidence, so no what-if is given."}
    p1, c1 = provisional(item.model_copy(update={"temperature_c": float(temperature_c)}), accepted)
    return 200, {
        "item_id": row["item_id"], "run_id": row["run_id"],
        "recorded": {"temperature_c": item.temperature_c, "p_react": p0, "category": c0.value},
        "whatif": {"temperature_c": float(temperature_c), "p_react": p1, "category": c1.value},
        "category_changed": c1 != c0,
        "note": ("Kiln's frozen scoring rules re-applied to this run's recorded evidence at the new "
                 "temperature. The evidence itself (energies, decomposition reports) is reused from "
                 "the recorded run, so this is a what-if, not a new run or a laboratory result."),
    }
