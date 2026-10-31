"""Sourced individual-precursor evidence and decomposition requests."""

from __future__ import annotations

from kiln.agents.base import Agent, llm_choose
from kiln.board import Board
from kiln.budget import Budget
from kiln.compute import client
from kiln.schemas import Artifact, ComputeStatus, ComputeTier, Cost, Item, RunConfig
from kiln.tools.precursors import props


class Precursor(Agent):
    name = "precursor"

    def __init__(self, compute=None, *, config: RunConfig) -> None:
        if not isinstance(config, RunConfig):
            raise TypeError("A RunConfig is required for model selection")
        self.compute = compute or client
        self.config = config

    def step(self, item: Item, board: Board, budget: Budget) -> None:
        if self.config.run_id != board.run_id:
            raise ValueError("Agent config does not match the board run")
        for need in board.open_needs(item.item_id, ("decomposition_products",)):
            formula = need.payload.get("formula")
            if formula not in (item.precursor_a, item.precursor_b):
                continue
            before = budget.spent
            choice = llm_choose(["answer_need", "skip"], f"Rule recommends answering the precursor-property need for {formula}.",
                                budget, self.config, system="Choose an action; never supply numerical evidence.")
            if not choice:
                raise ValueError("Precursor model returned no valid action")
            action = choice[0]
            if not board.claim(need.need_id, self.name):
                continue
            if action == "skip":
                board.decline(need.need_id, self.name)
                spent = budget.spent
                board.post_artifact(Artifact(artifact_id=board.new_id(self.name), run_id=board.run_id,
                    item_id=item.item_id, agent=self.name, type="precursor_report", values={"precursor_need_decision": "skip"},
                    rationale="Rule recommended answer_need; model chose skip.",
                    cost=Cost(tokens_in=spent.tokens_in-before.tokens_in, tokens_out=spent.tokens_out-before.tokens_out,
                              usd=spent.usd-before.usd)))
                continue
            try:
                budget.charge_tool_call()
                p = props(formula)
                values = {"decomposition_product": p.decomposition_product,
                          "decomposition_source": p.decomposition_source}
                if p.decomposes_at_c is not None:
                    values["decomposes_at_c"] = p.decomposes_at_c
                spent = budget.spent
                artifact = Artifact(artifact_id=board.new_id(self.name), run_id=board.run_id,
                    item_id=item.item_id, agent=self.name, type="precursor_report", values=values,
                    fulfills_need=need.need_id, cost=Cost(tool_calls=1, tokens_in=spent.tokens_in-before.tokens_in,
                    tokens_out=spent.tokens_out-before.tokens_out, usd=spent.usd-before.usd),
                    rationale="Rule recommended answer_need; model chose answer_need. Return sourced evidence or unknown.")
                board.post_artifact(artifact)
                board.fulfill(need.need_id, artifact.artifact_id)
            except Exception:
                board.decline(need.need_id, self.name)
                raise
        if any(a.agent == self.name and a.fulfills_need is None for a in board.artifacts(item.item_id)):
            return
        start = budget.spent
        chosen = llm_choose(["gather_properties", "skip"],
            f"Rule recommends gathering properties for {item.precursor_a} and {item.precursor_b}.", budget, self.config,
            system="Choose an action; never supply numerical evidence.")
        if not chosen:
            raise ValueError("Precursor model returned no valid action")
        if chosen[0] == "skip":
            spent = budget.spent
            board.post_artifact(Artifact(artifact_id=board.new_id(self.name), run_id=board.run_id,
                item_id=item.item_id, agent=self.name, type="precursor_report", values={"precursor_check": "skipped"},
                rationale="Rule recommended gather_properties; model chose skip.",
                cost=Cost(tokens_in=spent.tokens_in-start.tokens_in, tokens_out=spent.tokens_out-start.tokens_out,
                          usd=spent.usd-start.usd)))
            return
        values = {}
        properties = {}
        for side, formula in (("a", item.precursor_a), ("b", item.precursor_b)):
            budget.charge_tool_call()
            p = props(formula)
            properties[formula] = {"decomposes_at_c": p.decomposes_at_c, "decomposition_product": p.decomposition_product}
            values[f"precursor_{side}_formula"] = formula
            values[f"precursor_{side}_product"] = p.decomposition_product
            values[f"precursor_{side}_source"] = p.decomposition_source
            values[f"precursor_{side}_decomposition_known"] = p.decomposes_at_c is not None
        requests = []
        eligible = any(p["decomposes_at_c"] is not None and p["decomposition_product"] is not None for p in properties.values())
        reached = any(p["decomposes_at_c"] is not None and p["decomposition_product"] is not None
                      and item.temperature_c >= p["decomposes_at_c"] for p in properties.values())
        recommended = "decomposition_reeval" if reached else "skip"
        action = "skip"
        if eligible:
            options = [recommended, "skip" if reached else "decomposition_reeval"]
            chosen = llm_choose(options, f"Rule recommends {recommended}; furnace temperature {item.temperature_c} C. "
                f"Sourced precursor reference values: {properties}. Conditions may differ; remaining budget: {budget.remaining()}.",
                budget, self.config, system="Choose an action; never supply numerical evidence.")
            if not chosen:
                raise ValueError("Precursor model returned no valid action")
            action = chosen[0]
        if action == "decomposition_reeval":
            budget.charge_tool_call()
            req = self.compute.request(item, self.name, ComputeTier.decomposition_reeval,
                f"Rule recommended {recommended}; model chose {action}; source conditions may differ.",
                {"precursor_a": item.precursor_a, "precursor_b": item.precursor_b,
                 "temperature_c": item.temperature_c, "properties": properties}, budget)
            requests.append(req)
            # The source's conditions are not established for this experiment.
            # The request is a conditional estimate, not a confirmed transformation.
            values["decomposition_conditions_unverified"] = True
            if req.status in (ComputeStatus.ok, ComputeStatus.cached) and req.result.get("dE_ev_per_atom") is not None:
                values["dE_ev_per_atom"] = req.result["dE_ev_per_atom"]
        spent = budget.spent
        cost = spent.model_copy(update={"tool_calls": spent.tool_calls-start.tool_calls,
            "compute_units": spent.compute_units-start.compute_units,
            "gpu_seconds": sum(r.gpu_seconds for r in requests), "tokens_in": spent.tokens_in-start.tokens_in,
            "tokens_out": spent.tokens_out-start.tokens_out, "usd": spent.usd-start.usd})
        board.post_artifact(Artifact(artifact_id=board.new_id(self.name), run_id=board.run_id,
            item_id=item.item_id, agent=self.name, type="precursor_report", values=values,
            compute_requests=[r.request_id for r in requests], cost=cost,
            rationale=f"Rule recommended {recommended}; model chose {action}. Source conditions may differ."))
