from __future__ import annotations

import json
from pathlib import Path

import pytest

from kiln.agents.base import Agent
from kiln.compute.profile import write_items_file
from kiln.runners import stubs
from kiln.runners.conditions import Components, main, run, run_id_for, stub_components
from kiln.schemas import Artifact, Claim, ComputeStatus, Cost, Item, RunConfig

# Made-up development items; no ledger or label data.
ITEMS = [Item(item_id=f"T-{n}", source="precursor_genome", precursor_a=a, precursor_b="TiO2", temperature_c=t,
              melting_point_a_c=m, melting_point_b_c=1843.0, split="dev")
         for n, (a, t, m) in enumerate([("CaO", 1100, 2613.0), ("Li2CO3", 700, 723.0), ("BaO", 900, 1923.0)])]


def cfg(condition: str, **kw) -> RunConfig:
    return RunConfig(run_id=run_id_for(condition, "offline", 0, "dev"), condition=condition, seed=0,
                     model="offline", **kw)


def go(tmp_path: Path, condition: str, items=ITEMS, components: Components | None = None, **kw) -> Path:
    return run(cfg(condition, **kw), items, components or stub_components(), tmp_path, progress=lambda _: None)


def jsonl(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


@pytest.mark.parametrize("condition", ["C1", "C2", "C3", "C4"])
def test_every_condition_predicts_every_item_and_marks_stubs(tmp_path: Path, condition: str) -> None:
    run_dir = go(tmp_path, condition)
    preds = jsonl(run_dir / "predictions.jsonl")
    assert [p["item_id"] for p in preds] == ["T-0", "T-1", "T-2"]
    assert all(p["condition"] == condition and "STUB components" in p["applicability_notes"][-1] for p in preds)
    config = json.loads((run_dir / "config.json").read_text())
    assert config["stubs_used"] is True and config["agent_order"] == ["precursor", "thermo", "kinetics"]
    assert set(json.loads((run_dir / "cost.json").read_text())) == {"T-0", "T-1", "T-2"}


def test_caps_are_identical_across_conditions(tmp_path: Path) -> None:
    caps = {json.dumps({k: v for k, v in json.loads((go(tmp_path, c) / "config.json").read_text())["run_config"].items()
                        if k.startswith("max_") or k in ("tier_prices", "coordination_rounds")}) for c in
            ["C1", "C2", "C3", "C4"]}
    assert len(caps) == 1


def test_c4_needs_are_fulfilled_across_agents_and_change_the_score(tmp_path: Path) -> None:
    c4 = {p["item_id"]: p for p in jsonl(go(tmp_path, "C4") / "predictions.jsonl")}
    c2 = {p["item_id"]: p for p in jsonl(go(tmp_path, "C2") / "predictions.jsonl")}
    needs = [n for p in (tmp_path / cfg("C4").run_id).glob("board/**/needs.jsonl") for n in jsonl(p)]
    fulfilled = [n for n in needs if n["status"] == "fulfilled"]
    assert fulfilled and all(n["from_agent"] == "kinetics" and n["claimed_by"] == "thermo" for n in fulfilled)
    assert c4["T-0"]["p_react"] != c2["T-0"]["p_react"]          # the fulfilled need moved the verdict


def test_c2_isolates_specialists_and_delivers_no_needs(tmp_path: Path) -> None:
    run_dir = go(tmp_path, "C2")
    boards = sorted(p.parent.name for p in run_dir.glob("board/T-0/attempt-1/*/artifacts.jsonl"))
    assert boards == ["kinetics", "precursor", "thermo"]
    assert not list(run_dir.glob("board/**/needs.jsonl"))


@pytest.mark.parametrize("condition", ["C1", "C3"])
def test_c1_and_c3_suppress_needs_and_charge_their_own_tokens(tmp_path: Path, condition: str) -> None:
    run_dir = go(tmp_path, condition)
    assert all(r["event"] == "need_suppressed" for r in jsonl(run_dir / "needs_suppressed.jsonl"))
    assert jsonl(run_dir / "needs_suppressed.jsonl")
    assert not list(run_dir.glob("board/**/needs.jsonl"))
    assert all(p["cost"]["tokens_in"] > 0 for p in jsonl(run_dir / "predictions.jsonl"))


def test_cache_hits_are_charged(tmp_path: Path) -> None:
    twin = ITEMS[0].model_copy(update={"item_id": "T-0b"})   # same pair: the second lookup is a cache hit
    run_dir = go(tmp_path, "C2", items=[ITEMS[0], twin])
    cached = [r for r in jsonl(run_dir / "compute_requests.jsonl") if r["status"] == ComputeStatus.cached.value]
    assert cached and all(r["compute_units"] == stubs.STUB_TIER_PRICES[r["tier"]] for r in cached)


def test_running_out_of_budget_still_scores_the_item(tmp_path: Path) -> None:
    preds = jsonl(go(tmp_path, "C4", max_compute_units_per_item=0.5) / "predictions.jsonl")
    assert len(preds) == 3
    t0 = next(p for p in preds if p["item_id"] == "T-0")
    assert any("Budget exhausted" in f["detail"] for f in t0["review_flags"]) and t0["needs_review"]


def test_resume_skips_done_items_and_retries_an_interrupted_one(tmp_path: Path) -> None:
    run_dir = go(tmp_path, "C4")
    go(tmp_path, "C4")
    assert len(jsonl(run_dir / "predictions.jsonl")) == 3
    lines = (run_dir / "predictions.jsonl").read_text().splitlines()
    (run_dir / "predictions.jsonl").write_text("\n".join(lines[:-1]) + "\n")   # T-2 was interrupted
    go(tmp_path, "C4")
    assert [p["item_id"] for p in jsonl(run_dir / "predictions.jsonl")] == ["T-0", "T-1", "T-2"]
    assert (run_dir / "board" / "T-2" / "attempt-2").is_dir()
    with pytest.raises(SystemExit, match="different settings"):
        go(tmp_path, "C4", max_tool_calls_per_item=99)


class Fabricator(Agent):
    """Posts an energy no compute request produced: the verifier must reject it."""
    name = "thermo"

    def step(self, item, board, budget) -> None:
        if not board.artifacts(item.item_id):
            budget.charge_tool_call()
            board.post_artifact(Artifact(
                artifact_id=board.new_id("thermo"), run_id=board.run_id, item_id=item.item_id, agent="thermo",
                type="reaction_report", values={"dE_ev_per_atom": -0.5},
                claims=[Claim(cause="driving_force", statement="Made up.", evidence=["values.dE_ev_per_atom"],
                              falsified_if="Anything.")], cost=Cost(tool_calls=1)))


def test_unverified_numbers_are_rejected_logged_and_not_scored(tmp_path: Path) -> None:
    base = stub_components()
    components = Components(compute=base.compute, specialists=lambda compute, c: [Fabricator()],
                            tool_values=base.tool_values, flags=base.flags, scorer=base.scorer, stub_parts=base.stub_parts)
    run_dir = go(tmp_path, "C4", items=ITEMS[:1], components=components)
    assert jsonl(run_dir / "verifier.log")[0]["status"] in ("rejected", "inconclusive")
    assert jsonl(run_dir / "predictions.jsonl")[0]["evidence"] == []


def test_cli_runs_one_seed_of_every_condition_and_requires_a_model(tmp_path: Path) -> None:
    items_file = tmp_path / "items.jsonl"
    write_items_file(items_file, ITEMS)
    assert main(["--split", "dev", "--all-conditions", "--seed", "0", "--model", "offline", "--stubs",
                 "--items-file", str(items_file), "--limit", "2", "--runs-dir", str(tmp_path / "runs")]) == 0
    assert sorted(p.name for p in (tmp_path / "runs").iterdir()) == [run_id_for(c, "offline", 0, "dev") for c in
                                                                      ["C1", "C2", "C3", "C4"]]
    with pytest.raises(SystemExit):
        main(["--split", "dev", "--all-conditions", "--seed", "0", "--stubs"])
    with pytest.raises(SystemExit, match="need --frozen"):
        main(["--split", "dev", "--condition", "C1", "--seed", "0", "--model", "offline",
              "--items-file", str(items_file)])
    with pytest.raises(SystemExit, match="not found"):
        main(["--split", "dev", "--condition", "C1", "--seed", "0", "--model", "offline",
              "--items-file", str(items_file), "--frozen", str(tmp_path / "missing.json")])
    partial = tmp_path / "partial.json"
    partial.write_text(json.dumps({"tier_prices": stubs.STUB_TIER_PRICES}))
    with pytest.raises(SystemExit, match="missing"):
        main(["--split", "dev", "--condition", "C1", "--seed", "0", "--model", "offline",
              "--items-file", str(items_file), "--frozen", str(partial)])


class Crasher(Agent):
    name = "thermo"

    def step(self, item, board, budget) -> None:
        if item.item_id != "T-1":
            raise RuntimeError("provider down")


def test_a_failing_item_is_logged_and_the_run_continues_then_stops_on_a_streak(tmp_path: Path) -> None:
    base = stub_components()
    one_bad = Components(compute=base.compute, specialists=lambda compute, c: [Crasher()], tool_values=base.tool_values,
                         flags=base.flags, scorer=base.scorer, stub_parts=base.stub_parts)
    run_dir = go(tmp_path, "C4", items=ITEMS[:2], components=one_bad)   # T-0 fails, T-1 predicts
    assert [f["item_id"] for f in jsonl(run_dir / "failed_items.jsonl")] == ["T-0"]
    assert [p["item_id"] for p in jsonl(run_dir / "predictions.jsonl")] == ["T-1"]
    many = [ITEMS[0].model_copy(update={"item_id": f"T-0{n}"}) for n in range(5)]
    with pytest.raises(SystemExit, match="in a row"):
        go(tmp_path / "streak", "C4", items=many, components=one_bad)


def test_real_components_wire_annamayyas_agents_with_the_frozen_thresholds() -> None:
    from kiln.runners.conditions import real_components

    comp = real_components({"energy_margin_ev_per_atom": 0.05, "disagreement_threshold_ev_per_atom": 0.05})
    assert comp.stub_parts == ("scorer",)
    agents = comp.specialists(object(), cfg("C4"))
    assert sorted(a.name for a in agents) == ["kinetics", "precursor", "thermo"]
    assert all(getattr(a, "energy_margin", 0.05) == 0.05 for a in agents)
