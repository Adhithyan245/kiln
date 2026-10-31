"""Budgeted thermodynamic evidence from the shared compute service."""

from __future__ import annotations

import math

from kiln.agents.base import Agent
from kiln.board import Board
from kiln.budget import Budget
from kiln.compute import client
from kiln.schemas import Artifact, Claim, ComputeStatus, ComputeTier, Item


class Thermo(Agent):
    name = "thermo"

    def __init__(self, compute=None, *, energy_margin_ev_per_atom: float | None = None,
                 disagreement_threshold_ev_per_atom: float | None = None) -> None:
        for value in (energy_margin_ev_per_atom, disagreement_threshold_ev_per_atom):
            if value is not None and (isinstance(value, bool) or not math.isfinite(value) or value < 0):
                raise ValueError("Escalation thresholds must be finite and nonnegative")
        self.compute = compute or client
        self.energy_margin = energy_margin_ev_per_atom
        self.disagreement_threshold = disagreement_threshold_ev_per_atom

    def step(self, item: Item, board: Board, budget: Budget) -> None:
        previous = [a for a in board.artifacts(item.item_id) if a.agent == self.name]
        needs = board.open_needs(item.item_id, ("firm_up_energy", "reaction_energy"))
        need = needs[0] if needs else None
        inputs = {"precursor_a": item.precursor_a, "precursor_b": item.precursor_b}
        if need is not None:
            if need.type == "firm_up_energy" and self.energy_margin is None:
                return
            if need.type == "reaction_energy":
                species = need.payload.get("species")
                if not isinstance(species, list) or len(species) != 2 or not all(isinstance(s, str) and s for s in species):
                    return
                inputs = {"precursor_a": species[0], "precursor_b": species[1]}
                tier = ComputeTier.cached_lookup
                reason = "A specialist requested the reaction energy for these species."
            else:
                tier = ComputeTier.single_point
                reason = "Kinetics requested improved evidence for a borderline energy."
            if not board.claim(need.need_id, self.name):
                return
        elif previous:
            accepted = [a for a in board.accepted_artifacts(item.item_id) if a.agent == self.name]
            if not accepted:
                return
            last = accepted[-1]
            energy = last.values.get("dE_ev_per_atom")
            delta = last.values.get("dE_mlip_minus_mp_ev_per_atom")
            borderline = self.energy_margin is not None and isinstance(energy, (float, int)) and abs(energy) <= self.energy_margin
            conflict = self.disagreement_threshold is not None and isinstance(delta, (float, int)) and abs(delta) > self.disagreement_threshold
            if last.values.get("compute_tier") == "cached_lookup" and borderline and not any(
                    a.values.get("compute_tier") == "single_point" for a in previous):
                tier = ComputeTier.single_point
                reason = "The cached reaction energy is within the configured borderline margin."
            elif last.values.get("compute_tier") == "single_point" and (borderline or conflict) and not any(
                    a.values.get("compute_tier") == "bounded_relaxation" for a in previous):
                tier = ComputeTier.bounded_relaxation
                reason = "The single-point estimate remains borderline or conflicts with cached energy."
            else:
                return
        else:
            tier = ComputeTier.cached_lookup
            reason = "Start with the cached thermodynamic reaction estimate."
        start = budget.spent
        try:
            budget.charge_tool_call()
            request = self.compute.request(item, self.name, tier, reason, inputs, budget)
        except Exception:
            if need is not None:
                board.decline(need.need_id, self.name)
            raise
        values = {"compute_tier": tier.value}
        if request.status in (ComputeStatus.ok, ComputeStatus.cached):
            for key in ("dE_ev_per_atom", "dE_mlip_minus_mp_ev_per_atom"):
                if request.result.get(key) is not None:
                    values[key] = request.result[key]
        spent = budget.spent
        cost = spent.model_copy(update={"tool_calls": spent.tool_calls-start.tool_calls,
            "compute_units": spent.compute_units-start.compute_units,
            "gpu_seconds": request.gpu_seconds, "tokens_in": 0, "tokens_out": 0, "usd": 0})
        artifact = Artifact(artifact_id=board.new_id(self.name), run_id=board.run_id,
            item_id=item.item_id, agent=self.name, type="reaction_report", values=values,
            claims=[Claim(cause="thermodynamic_evidence", statement="A reaction-energy estimate is available.",
                          evidence=["values.dE_ev_per_atom"],
                          falsified_if="The cited computation does not reproduce the reported reaction energy.")]
                   if "dE_ev_per_atom" in values else [],
            compute_requests=[request.request_id], fulfills_need=need.need_id if need else None,
            rationale=reason, cost=cost)
        board.post_artifact(artifact)
        if need is not None:
            board.fulfill(need.need_id, artifact.artifact_id)
