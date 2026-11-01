"""UI contract checks use synthetic records, never experiment labels."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
from app import data
from app.components.evidence_strip import render_evidence_strip


def artifacts():
    return [{"artifact_id": f"a{i}", "agent": f"Agent {i}", "summary": f"Finding {i}",
             "verifier": "rejected" if i == 2 else "accepted",
             "fulfills_need": "need-1" if i == 3 else None} for i in range(4)]


def test_strip_has_one_link_per_artifact_in_card_order():
    page = render_evidence_strip(artifacts(), "amber", "red", prefix="item")
    assert page.count('class="strip-segment"') == 4
    assert page.count('data-status="accepted"') == 3
    assert 'data-status="rejected"' in page
    assert 'dropped from verdict' in page
    assert [page.index(f'href="#item-artifact-{i}"') for i in range(4)] == sorted(
        page.index(f'href="#item-artifact-{i}"') for i in range(4))
    assert 'Changed because' in page
    assert 'Replayed from cached runs.' in page


def test_risk_change_requires_different_known_risks_and_accepted_need():
    for before, after in [(None, "red"), ("red", "red"), ("amber", None)]:
        assert 'Changed because' not in render_evidence_strip(artifacts(), before, after)
    rows = artifacts()
    rows[3]["verifier"] = "rejected"
    assert 'Changed because' not in render_evidence_strip(rows, "amber", "red")


def test_strip_escapes_untrusted_text():
    rows = artifacts()
    rows[0]["summary"] = '<script>alert(1)</script>'
    page = render_evidence_strip(rows, None, None)
    assert '<script>' not in page
    assert '&lt;script&gt;' in page


def test_adapter_uses_provenance_and_final_verifier_stamp():
    rows = artifacts()
    rows.append(rows[0] | {"verifier": "rejected"})
    trail = data.adapt_trail(rows, {"risk": "red", "risk_before": "amber"}, ["a3", "a1", "a0", "a2"])
    assert [a["artifact_id"] for a in trail["artifacts"]] == ["a3", "a1", "a0", "a2"]
    assert trail["artifacts"][2]["verifier"] == "rejected"
    assert trail["risk_before"] == "amber"


def test_heldout_pair_gate_requires_hash_and_comparison(tmp_path):
    pair = {"id": "synthetic-test", "precursors": ["A", "B"], "split": "heldout",
            "real_reacts": True, "kiln_reacts": False}
    assert data.make_your_call([pair], tmp_path) == []
    (tmp_path / "protocol").mkdir()
    (tmp_path / "protocol" / "predictions.sha256").write_text("a" * 64)
    assert data.make_your_call([pair], tmp_path) == []
    (tmp_path / "results").mkdir()
    (tmp_path / "results" / "comparison.json").write_text('{}')
    assert data.make_your_call([pair], tmp_path)[0]["label"] == "Held-out pair · scored"


def test_development_fallback_and_no_unreleased_file_read(tmp_path, monkeypatch):
    pair = {"id": "synthetic-test", "precursors": ["A", "B"], "split": "dev",
            "real_reacts": True, "kiln_reacts": False}
    export = tmp_path / "results" / "app"
    export.mkdir(parents=True)
    (export / "development_pairs.json").write_text(json.dumps([pair]))
    original = data.read_json
    def guarded(path, default=None):
        assert path.name != "scored_pairs.json"
        return original(path, default)
    monkeypatch.setattr(data, "read_json", guarded)
    workspace = data.load_workspace(tmp_path)
    assert workspace["call_pairs"][0]["label"] == "Development pair"
    assert not workspace["scoring_released"]


def test_no_risk_is_invented_from_category():
    trail = data.adapt_trail(artifacts(), {"category": "unreacted", "p_react": 0.1})
    assert trail["risk_after"] is None
    assert trail["risk_before"] is None


def test_strip_includes_step_scrubber_and_verifier_tallies():
    page = render_evidence_strip(artifacts(), "amber", "red", prefix="item")
    assert 'class="button button-ghost step-prev"' in page
    assert 'class="button button-ghost step-next"' in page
    assert '3 accepted' in page
    assert '1 rejected' in page


def test_telemetry_and_precursor_reference_loading(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "precursor_props.csv").write_text(
        '"formula","decomposes_at_c","decomposition_product","decomposition_source","volatile_above_c","volatility_source","melting_point_c","melting_point_source","melting_point_source_url","melting_point_semantics","melting_point_semantics_source","melting_point_semantics_note"\n'
        '"CaCO3","770","CaO","src","unknown","unknown","825.0","Lange","https://example.org","possible_decomposition_or_dehydration","src2","decomposes"\n',
        encoding="utf-8",
    )
    rows = data.load_precursors(tmp_path)
    assert len(rows) == 1
    assert rows[0]["formula"] == "CaCO3"
    assert rows[0]["melting_point_c"] == 825.0
    assert rows[0]["tammann_c"] == 459.0
    assert rows[0]["decomposition_product"] == "CaO"
