"""Task 5: totals, reconciliation, allocation table and replay on made-up run folders."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from kiln.compute.accounting import (
    allocation_row, allocation_table, category_flip, load_run, main, pair_totals, reconcile, replay_changes,
    to_markdown,
)
from kiln.schemas import (
    Artifact, Category, ComputeRequest, ComputeStatus, ComputeTier, Cost, Item, Prediction, RunConfig,
    VerifierStatus,
)

T0 = datetime(2026, 10, 31, 12, tzinfo=timezone.utc)


def _request(run_id: str, n: int, item: str, tier: ComputeTier, units: float,
             status: ComputeStatus = ComputeStatus.ok, **kw) -> ComputeRequest:
    return ComputeRequest(request_id=f"{run_id}:compute:{n}", run_id=run_id, item_id=item, agent="thermo",
                          tier=tier, reason="test", inputs={}, settings={}, cache_key=f"k{n}", status=status,
                          compute_units=units, gpu_seconds=units * 2, **kw)


def _prediction(run_id: str, condition: str, item: str, units: float) -> Prediction:
    return Prediction(run_id=run_id, condition=condition, seed=0, item_id=item, p_react=0.5,
                      category=Category.unreacted, cause="test", fix="", evidence=[], cost=Cost(compute_units=units))


def make_run(root: Path, run_id: str, condition: str, requests: list[ComputeRequest],
             predictions: list[Prediction], artifacts: list[Artifact] = ()) -> Path:
    d = root / run_id
    (d / "board").mkdir(parents=True)
    cfg = RunConfig(run_id=run_id, condition=condition, seed=0, model="offline", max_compute_units_per_item=10.0)
    (d / "config.json").write_text(cfg.model_dump_json())
    (d / "compute_requests.jsonl").write_text("".join(r.model_dump_json() + "\n" for r in requests))
    (d / "predictions.jsonl").write_text("".join(p.model_dump_json() + "\n" for p in predictions))
    (d / "board" / "artifacts.jsonl").write_text("".join(a.model_dump_json() + "\n" for a in artifacts))
    return d


def c4_run(root: Path) -> Path:
    r = "C4-s0"
    reqs = [_request(r, 1, "A", ComputeTier.cached_lookup, 0.1),
            _request(r, 2, "A", ComputeTier.single_point, 1.0),
            _request(r, 3, "A", ComputeTier.bounded_relaxation, 6.0, ComputeStatus.not_converged),
            _request(r, 4, "B", ComputeTier.cached_lookup, 0.1, ComputeStatus.cached),
            _request(r, 5, "B", ComputeTier.single_point, 1.0, ComputeStatus.failed)]
    preds = [_prediction(r, "C4", "A", 7.1), _prediction(r, "C4", "B", 1.1), _prediction(r, "C4", "C", 0.0)]
    return make_run(root, r, "C4", reqs, preds)


def test_pair_totals(tmp_path: Path) -> None:
    t = pair_totals(load_run(c4_run(tmp_path)))
    assert t["A"]["compute_units"] == pytest.approx(7.1) and t["A"]["requests"] == 3
    assert t["A"]["by_tier"]["bounded_relaxation"] == 1
    assert t["B"]["compute_units"] == pytest.approx(1.1)
    assert t["C"]["requests"] == 0                      # an item that spent nothing still appears


def test_reconcile_is_exact_when_log_matches(tmp_path: Path) -> None:
    assert reconcile(load_run(c4_run(tmp_path))) == []


def test_reconcile_reports_every_mismatch(tmp_path: Path) -> None:
    r = "C1-s0"
    reqs = [_request(r, 1, "A", ComputeTier.single_point, 1.0), _request(r, 2, "Z", ComputeTier.single_point, 1.0)]
    run = load_run(make_run(tmp_path, r, "C1", reqs, [_prediction(r, "C1", "A", 2.0)]))
    problems = reconcile(run)
    assert any("A: prediction charged 2.0" in p for p in problems)
    assert any("Z: 1 compute requests but no prediction" in p for p in problems)


def test_failed_cached_and_not_converged_are_counted_and_charged(tmp_path: Path) -> None:
    row = allocation_row(load_run(c4_run(tmp_path)))
    assert row["requests"] == 5 and row["failed"] == 1 and row["not_converged"] == 1
    assert row["cache_hit_share"] == pytest.approx(0.2)
    assert row["compute_units_total"] == pytest.approx(8.2)
    assert row["requests_by_tier"] == {"cached_lookup": 2, "single_point": 2, "bounded_relaxation": 1,
                                       "decomposition_reeval": 0}
    assert row["units_per_pair_median"] == pytest.approx(1.1)
    assert row["budget_share_mean"] == pytest.approx(8.2 / 3 / 10.0)
    assert row["reconciliation_problems"] == []


def test_changed_and_moved_are_unknown_until_logged(tmp_path: Path) -> None:
    row = allocation_row(load_run(c4_run(tmp_path)))
    assert row["changed_prediction_known"] == 0 and row["changed_prediction_share"] is None
    assert row["moved_toward_label_known"] == 0 and row["moved_toward_label_share_of_changed"] is None


def test_moved_toward_label_uses_evaluator_values_after_unblinding(tmp_path: Path) -> None:
    r = "C4-s1"
    reqs = [_request(r, 1, "A", ComputeTier.single_point, 1.0, changed_prediction=True, moved_toward_label=True),
            _request(r, 2, "A", ComputeTier.single_point, 1.0, changed_prediction=True, moved_toward_label=False),
            _request(r, 3, "A", ComputeTier.single_point, 1.0, changed_prediction=False, moved_toward_label=False)]
    row = allocation_row(load_run(make_run(tmp_path, r, "C4", reqs, [_prediction(r, "C4", "A", 3.0)])))
    assert row["changed_prediction_share"] == pytest.approx(2 / 3)
    assert row["changed_per_unit"] == pytest.approx(2 / 3)
    assert row["moved_toward_label_share_of_changed"] == pytest.approx(0.5)


def test_table_sorts_conditions_and_renders_markdown(tmp_path: Path) -> None:
    c4 = load_run(c4_run(tmp_path))
    r = "C1-s0"
    c1 = load_run(make_run(tmp_path, r, "C1", [_request(r, 1, "A", ComputeTier.single_point, 1.0)],
                           [_prediction(r, "C1", "A", 1.0)]))
    rows = allocation_table([c4, c1])
    assert [row["condition"] for row in rows] == ["C1", "C4"]
    md = to_markdown(rows)
    assert md.splitlines()[0].startswith("| condition | seed | items")
    assert "| C4 | 0 | 3 |" in md and "n/a" in md


def test_replay_finds_the_request_that_changed_the_prediction(tmp_path: Path) -> None:
    r = "C4-s2"
    item = Item(item_id="A", source="precursor_genome", precursor_a="CaCO3", precursor_b="TiO2",
                temperature_c=900.0, split="dev")

    def artifact(n: int, reqs: list[str], dE: float, status=VerifierStatus.accepted) -> Artifact:
        return Artifact(artifact_id=f"{r}:thermo:{n}", run_id=r, item_id="A", agent="thermo", type="reaction_report",
                        values={"dE_ev_per_atom": dE}, compute_requests=reqs, verifier=status,
                        created_at=T0 + timedelta(minutes=n))

    reqs = [_request(r, i, "A", ComputeTier.single_point, 1.0) for i in (1, 2, 3)]
    arts = [artifact(1, [f"{r}:compute:1"], 0.01),                                # no reaction: unreacted
            artifact(2, [f"{r}:compute:2"], -0.10),                               # favourable: flips
            artifact(3, [f"{r}:compute:3"], -0.20, VerifierStatus.rejected)]      # never accepted
    run = load_run(make_run(tmp_path, r, "C4", reqs, [_prediction(r, "C4", "A", 3.0)], arts))

    def provisional(it: Item, accepted: list[Artifact]) -> tuple[float, Category]:  # a stand-in fixed rule
        dE = accepted[-1].values["dE_ev_per_atom"] if accepted else 0.0
        return (0.8, Category.completely_reacted) if dE < 0 else (0.2, Category.unreacted)

    changes = replay_changes(run, {"A": item}, provisional, category_flip)
    assert changes[f"{r}:compute:1"]["changed"] is False
    assert changes[f"{r}:compute:2"]["changed"] is True
    assert changes[f"{r}:compute:2"]["before"][1] == Category.unreacted
    assert changes[f"{r}:compute:3"]["changed"] is False          # cited only by a rejected artifact
    row = allocation_row(run, changes)
    assert row["changed_source"] == "replay" and row["changed_prediction_share"] == pytest.approx(1 / 3)


def test_command_writes_json_and_markdown_and_fails_on_mismatch(tmp_path: Path) -> None:
    out = tmp_path / "results" / "compute_allocation.json"
    assert main([str(c4_run(tmp_path)), "--out", str(out)]) == 0
    assert json.loads(out.read_text())[0]["condition"] == "C4"
    assert out.with_suffix(".md").exists()
    r = "C2-s0"
    bad = make_run(tmp_path, r, "C2", [_request(r, 1, "A", ComputeTier.single_point, 1.0)],
                   [_prediction(r, "C2", "A", 5.0)])
    assert main([str(bad), "--out", str(tmp_path / "bad.json")]) == 1
