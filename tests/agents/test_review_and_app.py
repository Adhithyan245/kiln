"""Review flags and evidence presentation on synthetic outputs."""

import importlib.util
import json
from pathlib import Path

from kiln.review import flags
from kiln.schemas import Artifact, ComputeRequest, ComputeStatus, ComputeTier, Item, ReviewReason, VerifierStatus


def test_missing_failed_and_energy_conflict():
    item = Item(item_id="example", source="alab_demo", precursor_a="A", precursor_b="B", temperature_c=500, split="dev")
    a = Artifact(artifact_id="run:thermo:1", run_id="run", item_id="example", agent="thermo", type="reaction_report",
                 values={"dE_mlip_minus_mp_ev_per_atom": 0.2}, verifier=VerifierStatus.accepted)
    request = ComputeRequest(request_id="run:compute:1", run_id="run", item_id="example", agent="thermo",
        tier=ComputeTier.single_point, reason="synthetic", inputs={}, settings={}, cache_key="synthetic", status=ComputeStatus.failed)
    reasons = {f.reason for f in flags(item, [a], [request], disagreement_threshold=0.1)}
    assert reasons == {ReviewReason.missing_evidence, ReviewReason.failed_computation, ReviewReason.conflict}


def test_explicit_applicability_warning_is_preserved():
    item = Item(item_id="example", source="alab_demo", precursor_a="A", precursor_b="B", temperature_c=500, split="dev")
    a = Artifact(artifact_id="run:thermo:1", run_id="run", item_id="example", agent="thermo", type="reaction_report",
                 values={"outside_applicability": True}, verifier=VerifierStatus.accepted)
    assert any(f.reason == ReviewReason.outside_applicability for f in flags(item, [a], []))


def test_app_escapes_output_and_sorts_flags(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("kiln_demo_app", Path(__file__).parents[2] / "app" / "server.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    out = tmp_path / "runs" / "example"
    out.mkdir(parents=True)
    rows = [{"item_id": "ordinary", "needs_review": False},
            {"item_id": "<script>", "needs_review": True}]
    (out / "predictions.jsonl").write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    page = module.render()
    payload = page.split('<script type="application/json" id="kiln-data">', 1)[1].split('</script>', 1)[0]
    assert "<script>" not in payload
    assert "\\u003cscript\\u003e" in payload
    assert [row["item_id"] for row in json.loads(payload)] == ["<script>", "ordinary"]
