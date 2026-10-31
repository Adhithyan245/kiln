"""Synthetic integration checks; no laboratory outcome data is used."""

import json
import importlib.util
from pathlib import Path
from types import SimpleNamespace

from kiln.agents.kinetics import Kinetics
from kiln.agents.precursor import Precursor
import kiln.agents.precursor as precursor_module
import kiln.agents.thermo as thermo_module
import kiln.agents.kinetics as kinetics_module
from kiln.agents.thermo import Thermo
from kiln.board import Board
from kiln.budget import Budget
from kiln.compute.backends import StubBackend
from kiln.compute.cache import ResultCache
from kiln.compute.client import ComputeClient, use
from kiln.review import flags
from kiln.schemas import Category, ComputeRequest, ComputeTier, Item, RunConfig, VerifierStatus
from kiln.scoring.rules import EvidenceSource, Feature, LinearScore, Outcome, ScoringRules, Term
from kiln.scoring.score import ScoringEngine
from kiln.verifier import verify
from kiln.tools.tammann import item_tool_values
from kiln.runners.conditions import Components, run_item
from kiln.runners.stubs import StubCompute, StubScorer


def test_specialists_share_verified_synthetic_evidence(tmp_path):
    run = tmp_path / "synthetic"
    config = RunConfig(run_id="synthetic", condition="C4", seed=1, model="offline",
        tier_prices={"cached_lookup": 1.0, "single_point": 1.0, "decomposition_reeval": 1.0})
    budget = Budget(config)
    board = Board(run)
    service = ComputeClient(run, config, StubBackend(), ResultCache(tmp_path / "cache"),
        {ComputeTier.cached_lookup: {}, ComputeTier.single_point: {}, ComputeTier.decomposition_reeval: {}})
    use(service)
    item = Item(item_id="example", source="alab_demo", precursor_a="CaCO3", precursor_b="TiO2",
        temperature_c=900, melting_point_a_c=825, melting_point_b_c=1843, split="dev")
    try:
        thermo = Thermo(config=config, energy_margin_ev_per_atom=1.0)
        kinetics_agent = Kinetics(config=config, energy_margin_ev_per_atom=1.0)
        thermo.step(item, board, budget)
        Precursor(config=config).step(item, board, budget)
        kinetics_agent.step(item, board, budget)
        requests = [ComputeRequest.model_validate_json(line) for line in service.log_path.read_text().splitlines()]
        artifacts = board.artifacts(item.item_id)
        assert {a.agent for a in artifacts} == {"thermo", "precursor", "kinetics"}
        kinetics = next(a for a in artifacts if a.agent == "kinetics")
        assert kinetics.values["melting_a_semantics"] == "possible_decomposition_or_dehydration"
        assert kinetics.values["tammann_a_c"] is not None
        tool_values = {key: value for key, value in kinetics.values.items() if key.startswith("tammann_")}
        for artifact in artifacts:
            status, notes = verify(artifact, board, requests=requests, config=config,
                item_cost=budget.spent, tool_values=tool_values)
            assert status == VerifierStatus.accepted, notes
            board.post_artifact(artifact.model_copy(update={"verifier": status, "verifier_notes": notes}))
        flagged = flags(item, board.accepted_artifacts(item.item_id), requests)
        assert any("decomposition or dehydration" in flag.detail for flag in flagged)
        # CaCO3's temperature is known and TiO2 is a stable oxide, so nothing is missing (proposal).
        assert not any("decomposition temperature is unknown" in flag.detail for flag in flagged)
        # This arbitrary configuration exists only to exercise the scorer; it is not the experiment protocol.
        outcome = Outcome(category=Category.unreacted, cause="synthetic", fix="synthetic")
        scoring_rules = ScoringRules(features=(Feature(name="x", sources=(EvidenceSource(agent="thermo",
            artifact_type="reaction_report", value_key="dE_ev_per_atom"),), on_multiple="require_equal", fallback=None),),
            p_react=LinearScore(intercept=0.0, terms=(Term(feature="x", weight=1.0),), link="logistic"),
            category_rules=(), otherwise=outcome, disagreement_flag_reasons=(), applicability_flag_reasons=())
        engine = ScoringEngine(scoring_rules, config, verify_frozen_rules=lambda digest: True)
        prediction = engine.score(item, board.accepted_artifacts(item.item_id), requests, flagged,
                                  cost=budget.spent, gpu_seconds_from_log=True)
        assert prediction.item_id == item.item_id and prediction.needs_review
        (run / "predictions.jsonl").write_text(prediction.model_dump_json() + "\n", encoding="utf-8")
        spec = importlib.util.spec_from_file_location("kiln_demo", Path(__file__).parents[2] / "app" / "server.py")
        viewer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(viewer)
        # Mirror the app's expected runs/<run_id> hierarchy using a temporary test root.
        viewer.ROOT = tmp_path
        (tmp_path / "runs").mkdir()
        run.rename(tmp_path / "runs" / "synthetic")
        assert "example" in viewer.render()
        (tmp_path / "runs" / "synthetic").rename(run)
        kinetics_agent.step(item, board, budget)
        assert len(board.open_needs(item.item_id, ("firm_up_energy",))) == 1
        thermo.step(item, board, budget)
        assert any(n.type == "firm_up_energy" and n.status == "fulfilled" for n in board.needs(item.item_id))
        assert len(service.log_path.read_text().splitlines()) == 3
    finally:
        use(None)


def test_precursor_escalates_only_with_sourced_threshold(tmp_path, monkeypatch):
    run = tmp_path / "synthetic"
    config = RunConfig(run_id="synthetic", condition="C4", seed=1, model="offline",
        tier_prices={"decomposition_reeval": 1.0})
    budget = Budget(config)
    board = Board(run)
    service = ComputeClient(run, config, StubBackend(), ResultCache(tmp_path / "cache"),
        {ComputeTier.decomposition_reeval: {}})
    monkeypatch.setattr(precursor_module, "props", lambda f: SimpleNamespace(
        decomposes_at_c=400.0 if f == "A" else None,
        decomposition_product="Product" if f == "A" else None,
        decomposition_source="synthetic source" if f == "A" else None))
    item = Item(item_id="example", source="alab_demo", precursor_a="A", precursor_b="B",
        temperature_c=500, split="dev")
    use(service)
    try:
        Precursor(config=config).step(item, board, budget)
        records = [ComputeRequest.model_validate_json(line) for line in service.log_path.read_text().splitlines()]
        assert [record.tier for record in records] == [ComputeTier.decomposition_reeval]
        assert board.artifacts(item.item_id)[0].compute_requests == [records[0].request_id]
    finally:
        use(None)


def test_real_specialists_work_with_verifying_runner_and_stub_compute(tmp_path):
    run = tmp_path / "synthetic"
    run.mkdir()
    config = RunConfig(run_id="synthetic", condition="C4", seed=1, model="offline",
        tier_prices={"cached_lookup": 1.0, "single_point": 1.0, "decomposition_reeval": 1.0})
    compute = StubCompute(run, config.tier_prices)
    components = Components(compute=lambda path, cfg: compute,
        specialists=lambda c, cfg: [Precursor(c), Thermo(c), Kinetics()],
        tool_values=item_tool_values, flags=flags, scorer=StubScorer, stubs=True)
    item = Item(item_id="example", source="alab_demo", precursor_a="CaCO3", precursor_b="TiO2",
                temperature_c=900, melting_point_a_c=825, melting_point_b_c=1843, split="dev")
    prediction = run_item(config, run, item, compute, components)
    assert prediction.item_id == "example"
    assert "STUB components" in prediction.applicability_notes[-1]
    assert prediction.needs_review


def test_model_skip_overrides_recommendation_and_charges_tokens(tmp_path, monkeypatch):
    run = tmp_path / "synthetic"
    run.mkdir()
    cfg = RunConfig(run_id="synthetic", condition="C4", seed=1, model="offline")
    budget = Budget(cfg)
    board = Board(run)
    calls = []

    def choose(options, context, actual_budget, config, **kwargs):
        calls.append((options, config.model))
        actual_budget.charge_tokens(2, 1)
        return ["skip"]

    for module in (thermo_module, kinetics_module, precursor_module):
        monkeypatch.setattr(module, "llm_choose", choose)
    item = Item(item_id="example", source="alab_demo", precursor_a="CaCO3", precursor_b="TiO2",
                temperature_c=900, split="dev")
    for agent in (Thermo(config=cfg), Kinetics(config=cfg), Precursor(config=cfg)):
        agent.step(item, board, budget)
    artifacts = board.artifacts(item.item_id)
    assert len(calls) == 3 and all(model == "offline" for _, model in calls)
    assert budget.spent.tokens_in == 6 and budget.spent.tokens_out == 3
    assert len(artifacts) == 3 and all("model chose skip" in a.rationale for a in artifacts)
    assert all(not a.compute_requests for a in artifacts)
    accepted = [a.model_copy(update={"verifier": VerifierStatus.accepted}) for a in artifacts]
    assert any(f.reason.value == "missing_evidence" for f in flags(item, accepted, []))


def test_model_can_request_recheck_despite_rule_recommending_skip(tmp_path, monkeypatch):
    run = tmp_path / "synthetic"
    run.mkdir()
    cfg = RunConfig(run_id="synthetic", condition="C4", seed=1, model="offline",
                    tier_prices={"decomposition_reeval": 1.0})
    budget = Budget(cfg)
    board = Board(run)
    service = StubCompute(run, cfg.tier_prices)
    monkeypatch.setattr(precursor_module, "props", lambda formula: SimpleNamespace(
        decomposes_at_c=900.0 if formula == "A" else None,
        decomposition_product="Product" if formula == "A" else None,
        decomposition_source="synthetic source" if formula == "A" else None))

    def choose(options, context, actual_budget, config, **kwargs):
        actual_budget.charge_tokens(2, 1)
        return ["decomposition_reeval" if "decomposition_reeval" in options else options[0]]

    monkeypatch.setattr(precursor_module, "llm_choose", choose)
    item = Item(item_id="example", source="alab_demo", precursor_a="A", precursor_b="B",
                temperature_c=500, split="dev")
    Precursor(service, config=cfg).step(item, board, budget)
    request = ComputeRequest.model_validate_json(service.log_path.read_text().strip())
    assert request.tier == ComputeTier.decomposition_reeval
    assert "Rule recommended skip; model chose decomposition_reeval" in request.reason
    assert budget.spent.tokens_in == 4 and budget.spent.tokens_out == 2
