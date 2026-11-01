"""Budgeted thermodynamic evidence from the shared compute service."""

from __future__ import annotations

import math

from kiln.agents.base import Agent, llm_call, llm_choose
from kiln.board import Board
from kiln.budget import Budget
from kiln.compute import client
from kiln.schemas import Artifact, Claim, ComputeStatus, ComputeTier, Cost, Item, RunConfig

HULL_WINDOW_EV_PER_ATOM = 0.1
# Materials Project returns "no product below the join" as 0 or as float noise (about 1e-15 on 110 of
# 635 development pairs); both are zero for the escalation rule.
ZERO_DE_EV_PER_ATOM = 1e-6


def is_zero_energy(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and abs(value) <= ZERO_DE_EV_PER_ATOM


class Thermo(Agent):
    name = "thermo"

    def __init__(self, compute=None, *, config: RunConfig | None = None, energy_margin_ev_per_atom: float | None = None,
                 disagreement_threshold_ev_per_atom: float | None = None) -> None:
        if config is not None and not isinstance(config, RunConfig):
            raise TypeError("config must be a RunConfig")
        for value in (energy_margin_ev_per_atom, disagreement_threshold_ev_per_atom):
            if value is not None and (isinstance(value, bool) or not math.isfinite(value) or value < 0):
                raise ValueError("Escalation thresholds must be finite and nonnegative")
        self.compute = compute or client
        self.config = config
        self.energy_margin = energy_margin_ev_per_atom
        self.disagreement_threshold = disagreement_threshold_ev_per_atom

    def step(self, item: Item, board: Board, budget: Budget) -> None:
        board_config = getattr(board, "config", None)
        config = self.config or board_config
        if not isinstance(config, RunConfig):
            raise TypeError("A RunConfig is required for model selection")
        if config.run_id != board.run_id or (board_config is not None and config != board_config):
            raise ValueError("Agent config does not match the board run")
        start = budget.spent
        previous = [a for a in board.artifacts(item.item_id) if a.agent == self.name]
        needs = board.open_needs(item.item_id, ("firm_up_energy", "reaction_energy"))
        need = needs[0] if needs else None
        inputs = {"precursor_a": item.precursor_a, "precursor_b": item.precursor_b}
        zero_without_other_trigger = False
        observed = [{"tier": a.values.get("compute_tier"), "dE_ev_per_atom": a.values.get("dE_ev_per_atom"),
                     "dE_mlip_minus_mp_ev_per_atom": a.values.get("dE_mlip_minus_mp_ev_per_atom"),
                     "competitor_e_hull_ev_per_atom": a.values.get("competitor_e_hull_ev_per_atom")}
                    for a in board.accepted_artifacts(item.item_id) if a.agent == self.name]
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
        elif previous:
            accepted = [a for a in board.accepted_artifacts(item.item_id) if a.agent == self.name]
            if not accepted:
                return
            last = accepted[-1]
            energy = last.values.get("dE_ev_per_atom")
            delta = last.values.get("dE_mlip_minus_mp_ev_per_atom")
            borderline = (self.energy_margin is not None and isinstance(energy, (float, int))
                          and not isinstance(energy, bool) and ZERO_DE_EV_PER_ATOM < abs(energy) <= self.energy_margin)
            conflict = self.disagreement_threshold is not None and isinstance(delta, (float, int)) and abs(delta) > self.disagreement_threshold
            # The competitor is supplied by the accepted lookup, not the MLIP tier.
            hull = next((a.values.get("competitor_e_hull_ev_per_atom") for a in reversed(accepted)
                         if a.values.get("compute_tier") == "cached_lookup"
                         and a.values.get("competitor_e_hull_ev_per_atom") is not None), None)
            near_hull = (isinstance(hull, (int, float)) and not isinstance(hull, bool)
                         and 0 < hull <= HULL_WINDOW_EV_PER_ATOM)
            zero_without_other_trigger = is_zero_energy(energy) and not near_hull and not conflict
            if last.values.get("compute_tier") == "cached_lookup" and (borderline or near_hull) and not any(
                    a.values.get("compute_tier") == "single_point" for a in previous):
                tier = ComputeTier.single_point
                reason = "The cached reaction energy is borderline or an off-hull competitor is near the hull."
            elif last.values.get("compute_tier") == "single_point" and (borderline or near_hull or conflict) and not any(
                    a.values.get("compute_tier") == "bounded_relaxation" for a in previous):
                tier = ComputeTier.bounded_relaxation
                reason = "Evidence remains borderline, a competitor is near the hull, or energy methods conflict."
            else:
                if last.values.get("compute_tier") == "cached_lookup" and self.energy_margin is not None:
                    tier = ComputeTier.single_point
                    reason = "The rule does not recommend escalation; the model may request a second estimate."
                elif last.values.get("compute_tier") == "single_point" and self.energy_margin is not None:
                    tier = ComputeTier.bounded_relaxation
                    reason = "The rule does not recommend escalation; the model may request a relaxation."
                else:
                    return
        else:
            tier = ComputeTier.cached_lookup
            reason = "Start with the cached thermodynamic reaction estimate."
        recommended = "skip" if reason.startswith("The rule does not recommend") else tier.value
        options = [recommended, "skip" if recommended != "skip" else tier.value]
        if recommended == "skip" and zero_without_other_trigger:
            # OPEN-07: a zero alone never recommends escalation, but the model may still escalate for
            # another reason, within budget; the override below logs its explanation.
            reason += (" The cached reaction energy is zero (no product below the join in this calculation);"
                       " that alone does not recommend escalation and does not show the powders cannot react.")
        context = (f"Thermo for {item.precursor_a} and {item.precursor_b} at {item.temperature_c} C. "
                   f"Accepted evidence: {observed}. Rule recommendation: {recommended}. {reason} "
                   f"Remaining budget: {budget.remaining()}.")
        chosen = llm_choose(options, context, budget, config, system="Choose an action; do not supply numerical values.")
        if not chosen:
            raise ValueError("Thermo model returned no valid action")
        action = chosen[0]
        reason = f"Rule recommended {recommended}; model chose {action}. {reason}"
        if action != recommended:
            # This is a separate, budgeted call: it is the model's post-hoc explanation,
            # not a verbatim record of its internal decision-making.
            if config.model == "offline":
                explanation = "Offline test model selected an alternative action."
            else:
                reply = llm_call(
                    f"{context}\nThe recommended action was {recommended}; you selected {action}. "
                    "In one sentence, explain that choice. Do not invent evidence.",
                    budget, config, system="Explain the selected action using only the supplied context.",
                )
                explanation = reply.text.strip()
                if not explanation:
                    raise ValueError("Thermo model returned no override explanation")
            reason += f" Model explanation (post-hoc): {explanation}"
        if need is not None and not board.claim(need.need_id, self.name):
            return
        if action == "skip":
            if need is not None:
                board.decline(need.need_id, self.name)
            spent = budget.spent
            board.post_artifact(Artifact(artifact_id=board.new_id(self.name), run_id=board.run_id,
                item_id=item.item_id, agent=self.name, type="reaction_report", values={"compute_tier": "skipped"},
                rationale=reason, cost=Cost(tokens_in=spent.tokens_in-start.tokens_in,
                tokens_out=spent.tokens_out-start.tokens_out, usd=spent.usd-start.usd)))
            return
        try:
            budget.charge_tool_call()
            request = self.compute.request(item, self.name, tier, reason, inputs, budget)
        except Exception:
            if need is not None:
                board.decline(need.need_id, self.name)
            raise
        values = {"compute_tier": tier.value}
        if request.status in (ComputeStatus.ok, ComputeStatus.cached):
            for key in ("dE_ev_per_atom", "dE_mlip_minus_mp_ev_per_atom", "competitor_e_hull_ev_per_atom"):
                if key == "competitor_e_hull_ev_per_atom" and request.result.get("competitor_e_hull_status") != "ok":
                    continue
                if request.result.get(key) is not None:
                    values[key] = request.result[key]
        spent = budget.spent
        cost = spent.model_copy(update={"tool_calls": spent.tool_calls-start.tool_calls,
            "compute_units": spent.compute_units-start.compute_units,
            "gpu_seconds": request.gpu_seconds, "tokens_in": spent.tokens_in-start.tokens_in,
            "tokens_out": spent.tokens_out-start.tokens_out, "usd": spent.usd-start.usd})
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
