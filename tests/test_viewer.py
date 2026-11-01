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


def _app(tmp_path, name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).parents[1] / "app" / "server.py")
    app = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(app)
    app.ROOT = tmp_path
    return app


def _write_run(root, folder, run, condition, seed, model, item="PG_0001", pair=("CaCO3", "TiO2")):
    d = root / folder / run
    (d / "board" / item / "attempt-1").mkdir(parents=True)
    (d / "config.json").write_text(json.dumps({"run_config": {"condition": condition, "seed": seed}, "stubs_used": False}), encoding="utf-8")
    (d / "predictions.jsonl").write_text(json.dumps({"item_id": item, "run_id": run, "condition": condition, "seed": seed,
        "category": "unreacted", "p_react": 0.2, "needs_review": True, "cost": {"compute_units": 1.1}}) + "\n", encoding="utf-8")
    requests = [{"item_id": item, "request_id": f"{run}:1", "agent": "thermo", "tier": "cached_lookup", "status": "ok",
                 "inputs": {"precursor_a": pair[0], "precursor_b": pair[1]}, "created_at": "2026-11-01T10:00:00Z",
                 "result": {"dE_ev_per_atom": -0.03, "source": "materials_project", "moved_toward_label": "SECRET"}},
                {"item_id": item, "request_id": f"{run}:2", "agent": "thermo", "tier": "single_point", "status": "ok",
                 "inputs": {"precursor_a": pair[0], "precursor_b": pair[1]}, "created_at": "2026-11-01T10:00:05Z",
                 "result": {"dE_ev_per_atom": -0.04, "dE_mp_ev_per_atom": -0.03, "model": model}}]
    (d / "compute_requests.jsonl").write_text("\n".join(json.dumps(r) for r in requests) + "\n", encoding="utf-8")
    (d / "board" / item / "attempt-1" / "artifacts.jsonl").write_text(json.dumps({"artifact_id": "a1", "item_id": item,
        "agent": "thermo", "type": "reaction_report", "rationale": "Rule recommended single_point; model chose single_point.",
        "verifier": "accepted", "created_at": "2026-11-01T10:00:06Z"}) + "\n", encoding="utf-8")


def test_pairs_list_recorded_items_and_skip_stub_runs(tmp_path):
    app = _app(tmp_path, "kiln_app_pairs")
    _write_run(tmp_path, "runs-h100", "C4-s0", "C4", 0, "medium-mpa-0")
    _write_run(tmp_path, "runs", "C4-s0", "C4", 0, "stub", item="PG_0002", pair=("BaCO3", "SiO2"))
    (tmp_path / "kiln-items.jsonl").write_text(json.dumps({"item_id": "PG_0001", "precursor_a": "CaCO3", "precursor_b": "TiO2",
        "temperature_c": 900, "dwell_h": 4}) + "\n", encoding="utf-8")
    pairs = app.list_pairs()
    assert [(p["precursor_a"], p["precursor_b"], p["temperature_c"]) for p in pairs] == [("CaCO3", "TiO2", 900)]
    assert pairs[0]["runs"] == [{"condition": "C4", "seed": 0, "source": "H100 (ALCHEMI Toolkit)"}]


def test_replay_returns_the_recorded_run_in_either_order_and_hides_labels(tmp_path):
    app = _app(tmp_path, "kiln_app_replay")
    _write_run(tmp_path, "runs-h100", "C4-s0", "C4", 0, "medium-mpa-0")
    code, body = app.replay({"precursor_a": "tio2", "precursor_b": "CaCO3", "condition": "C4", "seed": "0"})
    assert code == 200 and body["mode"] == "replay" and body["prediction"]["category"] == "unreacted"
    assert [r["tier"] for r in body["requests"]] == ["cached_lookup", "single_point"]
    assert body["requests"][1]["result"] == {"dE_ev_per_atom": -0.04, "dE_mp_ev_per_atom": -0.03, "model": "medium-mpa-0"}
    assert "moved_toward_label" not in json.dumps(body)
    assert body["artifacts"][0]["rationale"].startswith("Rule recommended")


def test_replay_refuses_stub_runs_unknown_pairs_and_missing_conditions(tmp_path):
    app = _app(tmp_path, "kiln_app_refuse")
    _write_run(tmp_path, "runs", "C4-s0", "C4", 0, "stub")
    assert app.replay({"precursor_a": "CaCO3", "precursor_b": "TiO2"})[0] == 404       # stub run is never served
    _write_run(tmp_path, "runs-h100", "C4-s0", "C4", 0, "medium-mpa-0")
    code, body = app.replay({"precursor_a": "CaCO3", "precursor_b": "TiO2", "condition": "C1"})
    assert code == 404 and body["available"] == [{"condition": "C4", "seed": 0, "source": "H100 (ALCHEMI Toolkit)"}]
    code, body = app.replay({"precursor_a": "Li2CO3", "precursor_b": "NiO"})
    assert code == 404 and "not in the recorded runs" in body["error"]
    assert app.replay({"precursor_a": "", "precursor_b": "NiO"})[0] == 400


def test_live_mode_refuses_unless_the_server_enables_it(tmp_path, monkeypatch):
    app = _app(tmp_path, "kiln_app_live")
    for name in ("KILN_LIVE", "GEMINI_API_KEY", "KILN_COMPUTE_BACKEND"):
        monkeypatch.delenv(name, raising=False)
    assert app.live_enabled() is False
    code, body = app.start_live({"precursor_a": "CaCO3", "precursor_b": "TiO2", "temperature_c": 900})
    assert code == 403 and "Live mode is off" in body["error"]
    monkeypatch.setenv("KILN_LIVE", "1"); monkeypatch.setenv("GEMINI_API_KEY", "x")
    monkeypatch.setenv("KILN_COMPUTE_BACKEND", "stub")              # a stub backend never counts as live
    assert app.live_enabled() is False
    assert app.live_status("nope")[0] == 404
