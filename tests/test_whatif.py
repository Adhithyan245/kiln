"""Temperature what-if on the committed H100 runs: label-free conditions plus recorded evidence."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))
from app import lab, whatif  # noqa: E402

RUN = "C4-gemini-3.8-flash-s0-heldout"
pytest.importorskip("pydantic")
pytestmark = pytest.mark.skipif(not (ROOT / "runs-h100-cut" / RUN).is_dir() or lab.conditions_path(ROOT) is None,
                                reason="committed H100 cut runs or held-out conditions not in this checkout")


def _row(item_id):
    return {"run_id": RUN, "item_id": item_id, "_run_dir": str(ROOT / "runs-h100-cut" / RUN)}


def _recorded(item_id):
    lines = (ROOT / "runs-h100-cut" / RUN / "predictions.jsonl").read_text(encoding="utf-8").splitlines()
    return next(json.loads(l) for l in lines if json.loads(l)["item_id"] == item_id)


def test_conditions_are_label_free_and_cover_the_held_out_set():
    rows = [json.loads(l) for l in lab.conditions_path(ROOT).read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 346 and {r["split"] for r in rows} == {"heldout"}
    allowed = {"item_id", "source", "precursor_a", "precursor_b", "temperature_c", "dwell_h",
               "melting_point_a_c", "melting_point_b_c", "split"}
    assert all(set(r) == allowed for r in rows)   # no category, reacted or any outcome field


def test_recorded_temperature_reproduces_the_recorded_prediction():
    item = "PG_0113"
    cond = lab.conditions(ROOT)[item]
    status, body = whatif.whatif(_row(item), cond, cond["temperature_c"])
    rec = _recorded(item)
    assert status == 200
    assert body["whatif"]["p_react"] == pytest.approx(rec["p_react"])
    assert body["whatif"]["category"] == rec["category"] and body["category_changed"] is False


def test_hotter_furnace_moves_the_score_up_through_the_tammann_terms():
    item = "PG_0113"   # recorded below precursor B's Tammann temperature: partially_reacted
    cond = lab.conditions(ROOT)[item]
    status, body = whatif.whatif(_row(item), cond, 1200.0)
    assert status == 200 and _recorded(item)["category"] == "partially_reacted"
    assert body["whatif"]["p_react"] > body["recorded"]["p_react"]
    assert body["whatif"]["category"] != "partially_reacted" and body["category_changed"] is True


def test_out_of_range_and_missing_conditions_are_refused():
    cond = lab.conditions(ROOT)["PG_0113"]
    assert whatif.whatif(_row("PG_0113"), cond, 5000.0)[0] == 400
    assert whatif.whatif(_row("PG_0113"), None, 900.0)[0] == 409
