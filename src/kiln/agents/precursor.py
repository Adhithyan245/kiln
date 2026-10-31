"""Sourced individual-precursor evidence and decomposition requests."""

from __future__ import annotations

from kiln.agents.base import Agent
from kiln.board import Board
from kiln.budget import Budget
from kiln.compute import client
from kiln.schemas import Artifact, ComputeStatus, ComputeTier, Cost, Item
from kiln.tools.precursors import props


class Precursor(Agent):
    name = "precursor"

    def __init__(self, compute=None) -> None:
        self.compute = compute or client

    def step(self, item: Item, board: Board, budget: Budget) -> None:
        for need in board.open_needs(item.item_id, ("decomposition_products",)):
            formula = need.payload.get("formula")
            if formula not in (item.precursor_a, item.precursor_b) or not board.claim(need.need_id, self.name):
                continue
            try:
                budget.charge_tool_call()
                p = props(formula)
                values = {"decomposition_product": p.decomposition_product,
                          "decomposition_source": p.decomposition_source}
                if p.decomposes_at_c is not None:
                    values["decomposes_at_c"] = p.decomposes_at_c
                artifact = Artifact(artifact_id=board.new_id(self.name), run_id=board.run_id,
                    item_id=item.item_id, agent=self.name, type="precursor_report", values=values,
                    fulfills_need=need.need_id, cost=Cost(tool_calls=1),
                    rationale="Return sourced decomposition information or an explicit unknown.")
                board.post_artifact(artifact)
                board.fulfill(need.need_id, artifact.artifact_id)
            except Exception:
                board.decline(need.need_id, self.name)
                raise
        if any(a.agent == self.name and a.fulfills_need is None for a in board.artifacts(item.item_id)):
            return
        start = budget.spent
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
        if any(p["decomposes_at_c"] is not None and p["decomposition_product"] is not None
               and item.temperature_c >= p["decomposes_at_c"] for p in properties.values()):
            budget.charge_tool_call()
            req = self.compute.request(item, self.name, ComputeTier.decomposition_reeval,
                "A sourced precursor decomposition threshold is reached.",
                {"precursor_a": item.precursor_a, "precursor_b": item.precursor_b,
                 "temperature_c": item.temperature_c, "properties": properties}, budget)
            requests.append(req)
            if req.status in (ComputeStatus.ok, ComputeStatus.cached) and req.result.get("dE_ev_per_atom") is not None:
                values["dE_ev_per_atom"] = req.result["dE_ev_per_atom"]
        spent = budget.spent
        cost = spent.model_copy(update={"tool_calls": spent.tool_calls-start.tool_calls,
            "compute_units": spent.compute_units-start.compute_units,
            "gpu_seconds": sum(r.gpu_seconds for r in requests), "tokens_in": 0, "tokens_out": 0, "usd": 0})
        board.post_artifact(Artifact(artifact_id=board.new_id(self.name), run_id=board.run_id,
            item_id=item.item_id, agent=self.name, type="precursor_report", values=values,
            compute_requests=[r.request_id for r in requests], cost=cost,
            rationale="Report only sourced precursor data; unknown thresholds remain unknown."))
