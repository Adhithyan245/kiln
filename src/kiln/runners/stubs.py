"""STAND-INS for teammates' pieces that aren't on dev yet. Never used for experiment runs.

Each one copies the interface in docs/interfaces.md so the runner can be wired and tested
now, and the real piece replaces it without changing the runner:

    StubCompute      -> kiln.compute.client           (CJ)
    StubThermo/Kinetics/Precursor -> kiln.agents.*    (Annamayya)
    stub_tool_values -> kiln.tools.tammann/precursors (Annamayya)
    stub_flags       -> kiln.review.flags             (Annamayya)
    StubScorer       -> kiln.scoring.score.ScoringEngine (Hemanath; needs frozen rules, OPEN-05)

Every number a stand-in produces is fake and marked: compute results carry "stub": True
and settings {"backend": "stub"}, and run configs record that stubs were used.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Sequence

from filelock import FileLock

from kiln.agents.base import Agent
from kiln.board import Board
from kiln.budget import Budget
from kiln.schemas import (
    AgentName, Artifact, Category, Claim, ComputeRequest, ComputeStatus, ComputeTier, Cost, Item,
    Need, Prediction, ReviewFlag, ReviewReason, RunConfig,
)

STUB_TIER_PRICES = {
    ComputeTier.cached_lookup.value: 0.5,
    ComputeTier.single_point.value: 1.0,
    ComputeTier.bounded_relaxation.value: 4.0,
    ComputeTier.decomposition_reeval.value: 2.0,
}
BORDERLINE_DE = 0.05  # |dE| below this (eV/atom) counts as a borderline driving force in the stubs


def _unit(*parts: Any) -> float:
    """Deterministic pseudo-random number in [0, 1) from the inputs."""
    digest = hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()
    return int(digest[:12], 16) / 16**12


# ---------- compute (CJ) ----------

class StubCompute:
    """Same contract as kiln.compute.client.request: charge first (even on cache hits),
    then serve from cache or 'compute', then append to runs/<run_id>/compute_requests.jsonl."""

    backend = "stub"

    def __init__(self, run_dir: str | Path, tier_prices: dict[str, float] | None = None) -> None:
        self.run_dir = Path(run_dir)
        self.run_id = self.run_dir.name
        self.log_path = self.run_dir / "compute_requests.jsonl"
        self.prices = tier_prices or STUB_TIER_PRICES
        self._lock = FileLock(str(self.run_dir / ".compute.lock"))

    def request(self, item: Item, agent: AgentName, tier: ComputeTier, reason: str,
                inputs: dict[str, Any], budget: Budget) -> ComputeRequest:
        tier = ComputeTier(tier)
        units = self.prices[tier.value]
        budget.charge_compute(units)  # raises BudgetExceeded before anything runs
        settings = {"backend": self.backend, "model": "stub"}
        cache_key = hashlib.sha256(json.dumps([tier.value, inputs, settings], sort_keys=True).encode()).hexdigest()
        with self._lock:
            log = self._read()
            cached = any(r.cache_key == cache_key for r in log)
            req = ComputeRequest(
                request_id=f"{self.run_id}:compute:{len(log) + 1}", run_id=self.run_id, item_id=item.item_id,
                agent=agent, tier=tier, reason=reason, inputs=inputs, settings=settings, cache_key=cache_key,
                status=ComputeStatus.cached if cached else ComputeStatus.ok,
                result={"dE_ev_per_atom": self._energy(tier, inputs), "stub": True},
                compute_units=units, gpu_seconds=0.0,
            )
            with self.log_path.open("a", encoding="utf-8") as f:
                f.write(req.model_dump_json() + "\n")
        return req

    @staticmethod
    def _energy(tier: ComputeTier, inputs: dict[str, Any]) -> float:
        base = -0.12 + 0.2 * _unit("dE", inputs.get("formula"), inputs.get("species"))
        shift = {ComputeTier.cached_lookup: 0.0, ComputeTier.single_point: -0.01,
                 ComputeTier.bounded_relaxation: -0.015, ComputeTier.decomposition_reeval: 0.02}[tier]
        return round(base + shift, 4)

    def _read(self) -> list[ComputeRequest]:
        if not self.log_path.exists():
            return []
        return [ComputeRequest.model_validate_json(line) for line in self.log_path.read_text(encoding="utf-8").splitlines() if line.strip()]


# ---------- tools (Annamayya) ----------

def stub_tammann_c(melting_point_c: float | None) -> float | None:
    """Two-thirds of the melting point, taken in kelvin, returned in °C."""
    if melting_point_c is None:
        return None
    return round((melting_point_c + 273.15) * 2 / 3 - 273.15, 1)


def stub_tool_values(item: Item) -> dict[str, float | None]:
    """What the verifier recomputes for the item. Decomposition and volatility are unknown
    until Annamayya's cited property table lands."""
    return {
        "tammann_a_c": stub_tammann_c(item.melting_point_a_c),
        "tammann_b_c": stub_tammann_c(item.melting_point_b_c),
    }


# ---------- specialists (Annamayya) ----------

def _product(item: Item) -> str:
    return f"{item.precursor_a}+{item.precursor_b}"


class StubThermo(Agent):
    name = "thermo"

    def __init__(self, compute: StubCompute) -> None:
        self.compute = compute

    def step(self, item: Item, board: Board, budget: Budget) -> None:
        for need in board.open_needs(item.item_id, ["firm_up_energy", "reaction_energy"]):
            if board.claim(need.need_id, self.name):
                tier = ComputeTier.single_point
                self._report(item, board, budget, tier, f"Answer {need.type} from {need.from_agent} with a {tier.value}.", need.need_id)
        if not any(a.agent == self.name for a in board.artifacts(item.item_id)):
            self._report(item, board, budget, ComputeTier.cached_lookup, "Cheapest evidence first: cached energies.", None)

    def _report(self, item: Item, board: Board, budget: Budget, tier: ComputeTier, reason: str, need_id: str | None) -> None:
        budget.charge_tool_call()
        req = self.compute.request(item, self.name, tier, reason, {"formula": _product(item)}, budget)
        dE = req.result["dE_ev_per_atom"]
        a = Artifact(
            artifact_id=board.new_id(self.name), run_id=board.run_id, item_id=item.item_id, agent=self.name,
            type="reaction_report", values={"dE_ev_per_atom": dE},
            claims=[Claim(cause="no_driving_force" if dE >= 0 else "driving_force",
                          statement=f"Stub {tier.value} reaction energy is {dE} eV/atom.",
                          evidence=["values.dE_ev_per_atom"],
                          falsified_if="A higher-tier calculation gives the opposite sign of dE.")],
            fulfills_need=need_id, compute_requests=[req.request_id], rationale=f"STUB: {reason}",
            cost=Cost(tool_calls=1, compute_units=req.compute_units),
        )
        board.post_artifact(a)
        if need_id:
            board.fulfill(need_id, a.artifact_id)


class StubKinetics(Agent):
    name = "kinetics"

    def step(self, item: Item, board: Board, budget: Budget) -> None:
        mine = [a for a in board.artifacts(item.item_id) if a.agent == self.name]
        if not mine:
            budget.charge_tool_call()
            tv = stub_tool_values(item)
            claims = []
            known = [t for t in tv.values() if t is not None]
            if known and item.temperature_c < min(known):
                claims.append(Claim(
                    cause="kinetically_limited", statement="Furnace is below both Tammann temperatures.",
                    evidence=[f"values.{k}" for k, v in tv.items() if v is not None],
                    falsified_if="The pair is observed to react at this temperature."))
            board.post_artifact(Artifact(
                artifact_id=board.new_id(self.name), run_id=board.run_id, item_id=item.item_id, agent=self.name,
                type="kinetics_report", values=dict(tv), claims=claims,
                rationale="STUB: Tammann check for both precursors.", cost=Cost(tool_calls=1)))
        asked = any(n.from_agent == self.name and n.type == "firm_up_energy" for n in board.needs(item.item_id))
        borderline = [a for a in board.accepted_artifacts(item.item_id)
                      if a.type == "reaction_report" and abs(float(a.values.get("dE_ev_per_atom", 1))) < BORDERLINE_DE]
        if borderline and not asked:
            budget.charge_tool_call()
            board.post_need(Need(
                need_id=board.new_id("need"), run_id=board.run_id, item_id=item.item_id, type="firm_up_energy",
                from_agent=self.name,
                payload={"formula": _product(item), "current_dE_ev_per_atom": borderline[-1].values["dE_ev_per_atom"]}))


class StubPrecursor(Agent):
    name = "precursor"

    def step(self, item: Item, board: Board, budget: Budget) -> None:
        if any(a.agent == self.name for a in board.artifacts(item.item_id)):
            return
        budget.charge_tool_call()
        board.post_artifact(Artifact(
            artifact_id=board.new_id(self.name), run_id=board.run_id, item_id=item.item_id, agent=self.name,
            type="precursor_report", values={},
            rationale="STUB: no cited property table yet, so decomposition and volatility are unknown.",
            cost=Cost(tool_calls=1)))


def stub_specialists(compute: StubCompute) -> list[Agent]:
    return [StubThermo(compute), StubKinetics(), StubPrecursor()]


# ---------- review flags (Annamayya) ----------

def stub_flags(item: Item, accepted: Sequence[Artifact], requests: Sequence[ComputeRequest]) -> list[ReviewFlag]:
    flags = [
        ReviewFlag(reason=ReviewReason.failed_computation, detail=f"{r.tier.value} request {r.status.value}", evidence=[r.request_id])
        for r in requests if r.status in (ComputeStatus.failed, ComputeStatus.not_converged)
    ]
    if not any(a.type == "precursor_report" and "decomposes_at_c" in a.values for a in accepted):
        flags.append(ReviewFlag(reason=ReviewReason.missing_evidence, detail="Precursor decomposition properties unknown."))
    if not any(a.type == "reaction_report" for a in accepted):
        flags.append(ReviewFlag(reason=ReviewReason.missing_evidence, detail="No accepted reaction energy."))
    return flags


# ---------- scoring (Hemanath) ----------

class StubScorer:
    """Same methods as ScoringEngine. A fixed formula, not the protocol's frozen rules."""

    def __init__(self, config: RunConfig) -> None:
        self.config = config

    def provisional(self, item: Item, accepted: Sequence[Artifact]) -> tuple[float, Category]:
        energies = [a for a in accepted if a.type == "reaction_report" and "dE_ev_per_atom" in a.values]
        dE = float(max(energies, key=lambda a: a.created_at).values["dE_ev_per_atom"]) if energies else 0.0
        tammann = [float(v) for a in accepted if a.type == "kinetics_report"
                   for k, v in a.values.items() if k.startswith("tammann") and isinstance(v, (int, float))]
        margin = item.temperature_c - max(tammann) if tammann else 0.0
        p = 1 / (1 + math.exp(40 * dE)) * (1 / (1 + math.exp(-margin / 100)))
        p = round(min(max(p * 2, 0.0), 1.0), 4)  # margin 0 halves p; rescale so p spans [0, 1]
        if p >= 0.75:
            return p, Category.completely_reacted
        if p >= 0.5:
            return p, Category.partially_reacted
        return p, Category.unreacted

    def score(self, item: Item, accepted: Sequence[Artifact], requests: Sequence[ComputeRequest],
              flags: Sequence[ReviewFlag], *, cost: Cost) -> Prediction:
        p, category = self.provisional(item, accepted)
        causes = [c.cause for a in accepted for c in a.claims]
        cause = "kinetically_limited" if "kinetically_limited" in causes else (
            "no_driving_force" if "no_driving_force" in causes else ("reacts" if p >= 0.5 else "unclear"))
        return Prediction(
            run_id=self.config.run_id, condition=self.config.condition, seed=self.config.seed, item_id=item.item_id,
            p_react=p, category=category, cause=cause, fix="STUB: no fix rules yet.",
            evidence=[a.artifact_id for a in accepted],
            compute_requests=sorted({r for a in accepted for r in a.compute_requests}),
            needs_review=bool(flags), review_flags=list(flags),
            applicability_notes=["STUB scorer: not the frozen protocol rules."], cost=cost,
        )
