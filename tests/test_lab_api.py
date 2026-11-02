"""Lab preview tests use synthetic temporary records, never evaluation labels."""
import json
import sys
import threading
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from http.server import ThreadingHTTPServer

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
from app import lab, server


def row(source="H100 (ALCHEMI Toolkit)", condition="C4", reqs=None):
    return {"source_label": source, "source_kind": "h100", "run_id": "test", "item_id": "synthetic",
            "condition": condition, "seed": 1, "precursor_a": "A", "precursor_b": "B",
            "requests": reqs or [], "artifacts": [], "category": "unreacted"}


def test_compute_uses_prices_and_separates_machines(tmp_path):
    protocol = tmp_path / "protocol"
    protocol.mkdir()
    (protocol / "frozen_settings.json").write_text(json.dumps({"tier_prices": {
        "cached_lookup": 2, "single_point": 3, "bounded_relaxation": 4, "decomposition_reeval": 5}}))
    requests = [{"request_id": "r", "tier": "single_point", "status": "ok", "compute_units": 3, "gpu_seconds": 10}]
    output = lab.compute(tmp_path, [row(reqs=requests), row(source="GB10 rerun", reqs=requests)])
    assert output["full_check_units"] == 14
    assert len(output["by_condition"]) == 2
    assert output["totals"]["compute_units"] == 6
    assert output["saved_vs_full_check"] == 22
    assert output["by_condition"][0]["single_point_pct"] == 100


def test_reuse_estimates_only_matching_timed_original():
    reqs = [{"cache_key": "x", "status": "ok", "gpu_seconds": 10, "source_label": "H100", "tier": "single_point"},
            {"cache_key": "x", "status": "cached", "source_label": "H100", "tier": "single_point"},
            {"cache_key": "x", "status": "cached", "source_label": "GB10", "tier": "single_point"},
            {"cache_key": "missing", "status": "cached", "source_label": "H100", "tier": "single_point"}]
    result = lab.reuse_info(reqs)
    assert result["reuses"] == 3
    assert result["unmatched_reuses"] == 2
    assert result["estimated_gpu_seconds_avoided"] == 10


def test_replay_refuses_live_missing_and_unknown_pairs(tmp_path):
    rows = [row()]
    assert lab.triage(tmp_path, {"live": True}, rows)[0] == 409
    assert lab.triage(tmp_path, {}, rows)[0] == 400
    assert lab.triage(tmp_path, {"precursor_a": "A", "precursor_b": "C"}, rows)[0] == 404
    status, output = lab.triage(tmp_path, {"precursor_a": "B", "precursor_b": "A", "condition": "C4", "seed": 1}, rows)
    assert status == 200
    assert output["mode"] == "replay"
    assert output["prediction"]["category"] == "unreacted"


def test_replay_preserves_selected_machine_when_run_names_match(tmp_path):
    h100 = row()
    gb10 = row(source="GB10 rerun")
    gb10["source_kind"] = "gb10"
    gb10["category"] = "transformed"
    status, output = lab.triage(tmp_path, {"precursor_a": " b ", "precursor_b": "a", "condition": "C4",
        "seed": 1, "run_id": "test", "source_label": "GB10 rerun"}, [h100, gb10])
    assert status == 200
    assert output["source_label"] == "GB10 rerun"
    assert output["prediction"]["category"] == "transformed"


def test_gb10_stub_run_excluded_and_cache_key_preserved(tmp_path):
    for name, model in [("real", "mace"), ("fake", "stub")]:
        path = tmp_path / "runs" / name
        path.mkdir(parents=True)
        (path / "predictions.jsonl").write_text(json.dumps({"item_id": "i", "condition": "C4", "seed": 1}))
        (path / "compute_requests.jsonl").write_text(json.dumps({"item_id": "i", "cache_key": "cache", "request_id": name,
            "inputs": {"precursor_a": "A", "precursor_b": "B"}, "result": {"model": model}}))
    rows = lab.records(tmp_path)
    assert len(rows) == 1
    assert rows[0]["requests"][0]["cache_key"] == "cache"
    assert lab.pairs(rows)[0]["precursor_a"] == "A"


def test_missing_prices_and_costs_do_not_invent_savings(tmp_path):
    output = lab.compute(tmp_path, [row(reqs=[{"tier": "single_point", "status": "ok"}])])
    assert output["full_check_units"] is None
    assert output["saved_vs_full_check"] is None
    assert output["by_condition"][0]["mean_compute_units"] is None


def test_http_routes_assets_and_traversal(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "ROOT", tmp_path)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{httpd.server_port}"
    try:
        with urlopen(url) as response:
            assert b"Select your chemicals" in response.read()
        with urlopen(url + "/api/status") as response:
            assert json.load(response)["live"] is False
        with urlopen(url + "/assets/lab.js") as response:
            assert response.status == 200
        for path in ("/assets/../server.py", "/assets/%2e%2e/server.py", "/labels/test.json"):
            try:
                urlopen(url + path)
                assert False, "Private path must not be served"
            except HTTPError as error:
                assert error.code == 404
        try:
            urlopen(Request(url + "/api/triage", data=b'{}', headers={"Content-Type": "application/json"}))
            assert False, "Missing precursors must fail"
        except HTTPError as error:
            assert error.code == 400
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join()


def test_http_recorded_pair_and_failure_flow(tmp_path, monkeypatch):
    """Synthetic files exercise the same HTTP contract consumed by the lab UI."""
    monkeypatch.setattr(server, "ROOT", tmp_path)
    run = tmp_path / "runs-h100" / "fixture"
    board = run / "board" / "test-item" / "attempt-1"
    board.mkdir(parents=True)
    prediction = {"item_id": "test-item", "run_id": "fixture", "condition": "C4", "seed": 1,
                  "category": "partially_reacted", "p_react": 0.3, "cause": "Synthetic reason", "needs_review": True}
    requests = [{"item_id": "test-item", "request_id": "r1", "tier": "cached_lookup", "status": "ok",
                 "compute_units": 0.1, "gpu_seconds": 0, "inputs": {"precursor_a": "A", "precursor_b": "B"},
                 "result": {"dE_mp_ev_per_atom": -0.02, "source": "fixture"}},
                {"item_id": "test-item", "request_id": "r2", "tier": "single_point", "status": "failed",
                 "compute_units": 1, "gpu_seconds": 5, "result": {"error": "Synthetic failure"}}]
    artifact = {"item_id": "test-item", "artifact_id": "art-1", "agent": "Thermo", "verifier": "accepted",
                "values": {"dE_ev_per_atom": -0.02}, "rationale": "Synthetic explanation"}
    (run / "predictions.jsonl").write_text(json.dumps(prediction), encoding="utf-8")
    (run / "compute_requests.jsonl").write_text("\n".join(map(json.dumps, requests)), encoding="utf-8")
    (board / "artifacts.jsonl").write_text(json.dumps(artifact), encoding="utf-8")
    items = tmp_path / "items.jsonl"
    items.write_text(json.dumps({"item_id": "test-item", "temperature_c": 700, "dwell_h": 3}), encoding="utf-8")
    monkeypatch.setenv("KILN_ITEMS", str(items))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{httpd.server_port}"
    try:
        with urlopen(url + "/api/pairs") as response:
            pair = json.load(response)[0]
        assert (pair["precursor_a"], pair["precursor_b"], pair["temperature_c"]) == ("A", "B", 700)
        body = {"precursor_a": "A", "precursor_b": "B", "condition": "C4", "seed": 1,
                "run_id": "fixture", "source_label": pair["runs"][0]["source"]}
        request = Request(url + "/api/triage", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        with urlopen(request) as response:
            replay = json.load(response)
        assert replay["prediction"]["category"] == "partially_reacted"
        assert replay["artifacts"][0]["rationale"] == "Synthetic explanation"
        assert replay["requests"][1]["result"]["error"] == "Synthetic failure"
        with urlopen(url + "/api/compute") as response:
            compute = json.load(response)
        assert abs(compute["totals"]["compute_units"] - 1.1) < 1e-9
        assert compute["totals"]["gpu_seconds"] == 5
        assert compute["by_condition"][0]["single_point_pct"] == 100
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join()


def test_recipe_route_validates_and_screens(tmp_path, monkeypatch):
    pytest.importorskip("pymatgen")
    from kiln.tools import mp
    from tests.tools.mp_fixtures import ca_ti_o_entries

    monkeypatch.setattr(server, "ROOT", tmp_path)
    monkeypatch.delenv("KILN_RECIPE_CHECK", raising=False)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{httpd.server_port}/api/recipe"

    def post(body):
        return urlopen(Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}))

    try:
        for bad in ({"target": "not a formula", "temperature_c": 900}, {"target": "BaTiO3", "temperature_c": 5000},
                    {"target": "BaTiO3"}):
            try:
                post(bad)
                assert False, "Invalid recipe input must fail"
            except HTTPError as error:
                assert error.code == 400
        try:
            post({"target": "CaTiO3", "temperature_c": 1000})
            assert False, "No cache: the server must say so, not guess"
        except HTTPError as error:
            assert error.code == 503
        (tmp_path / "cache" / "mp").mkdir(parents=True)
        mp._write_entries(tmp_path / "cache" / "mp" / "Ca-O-Ti.json", ca_ti_o_entries())
        with post({"target": "CaTiO3", "temperature_c": 1000, "check": True}) as response:
            result = json.load(response)
        assert result["target"] == "CaTiO3" and result["n_checked"] == 0 and result["check_available"] is False
        assert all(c["precursor_a"] != c["precursor_b"] for c in result["candidates"])
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join()
