"""The viewer exposes recorded evidence without copying evaluation-only fields."""
import importlib.util
import json
from pathlib import Path


def test_viewer_limits_fields_and_escapes_embedded_json(tmp_path):
    spec = importlib.util.spec_from_file_location("kiln_viewer", Path(__file__).parents[1] / "app" / "server.py")
    viewer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(viewer)
    viewer.ROOT = tmp_path
    run = tmp_path / "runs" / "run1"
    run.mkdir(parents=True)
    (run / "predictions.jsonl").write_text(json.dumps({"item_id": "</script><script>bad()</script>",
        "run_id": "run1", "needs_review": True, "category": "unreacted"}) + "\n", encoding="utf-8")
    (run / "config.json").write_text(json.dumps({"stubs_used": True, "stub_parts": ["scorer"]}), encoding="utf-8")
    (run / "compute_requests.jsonl").write_text(json.dumps({"item_id": "</script><script>bad()</script>",
        "request_id": "r1", "tier": "cached_lookup", "moved_toward_label": "PRIVATE_LABEL_MARKER"}) + "\n", encoding="utf-8")
    page = viewer.render()
    assert "PRIVATE_LABEL_MARKER" not in page
    assert "</script><script>bad()" not in page
    assert "\\u003c/script\\u003e" in page
    assert '"stubs_used": true' in page


def test_viewer_hides_stub_compute_runs_and_labels_machines(tmp_path):
    spec = importlib.util.spec_from_file_location("kiln_viewer_stub", Path(__file__).parents[1] / "app" / "server.py")
    viewer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(viewer)
    viewer.ROOT = tmp_path
    for folder, run, model in (("runs", "fake", "stub"), ("runs-h100", "real", "medium-mpa-0")):
        d = tmp_path / folder / run
        d.mkdir(parents=True)
        (d / "predictions.jsonl").write_text(json.dumps({"item_id": f"PG_{run}", "run_id": run}) + "\n", encoding="utf-8")
        (d / "compute_requests.jsonl").write_text(json.dumps({"item_id": f"PG_{run}", "request_id": "r1",
            "tier": "single_point", "result": {"model": model}}) + "\n", encoding="utf-8")
    rows = viewer.load_predictions()
    assert [r["item_id"] for r in rows] == ["PG_real"]           # the stub-backend run is never shown
    assert rows[0]["source_label"] == "H100 (ALCHEMI Toolkit)"


def test_empty_viewer_renders(tmp_path):
    spec = importlib.util.spec_from_file_location("kiln_viewer_empty", Path(__file__).parents[1] / "app" / "server.py")
    viewer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(viewer)
    viewer.ROOT = tmp_path
    assert 'id="kiln-data">[]</script>' in viewer.render()
