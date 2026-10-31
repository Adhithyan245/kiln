"""Temperature evidence and requests for uncertain reaction energies."""

from __future__ import annotations

import math

from kiln.agents.base import Agent
from kiln.board import Board
from kiln.budget import Budget
from kiln.schemas import Artifact, Claim, Cost, Item, Need
from kiln.tools.precursors import props
from kiln.tools.tammann import checked_tammann_c


class Kinetics(Agent):
    name = "kinetics"

    def __init__(self, *, energy_margin_ev_per_atom: float | None = None) -> None:
        if energy_margin_ev_per_atom is not None and (isinstance(energy_margin_ev_per_atom, bool)
                or not math.isfinite(energy_margin_ev_per_atom) or energy_margin_ev_per_atom < 0):
            raise ValueError("Energy margin must be finite and nonnegative")
        self.energy_margin = energy_margin_ev_per_atom

    def step(self, item: Item, board: Board, budget: Budget) -> None:
        prior = board.artifacts(item.item_id)
        if not any(a.agent == self.name for a in prior):
            before = budget.spent
            values = {}
            for side, formula, fallback in (("a", item.precursor_a, item.melting_point_a_c),
                                            ("b", item.precursor_b, item.melting_point_b_c)):
                budget.charge_tool_call()
                p = props(formula)
                melting = p.melting_point_c if p.melting_point_c is not None else fallback
                result, status = checked_tammann_c(melting, semantics=p.melting_point_semantics or "as_reported")
                values[f"tammann_{side}_c"] = result
                values[f"melting_{side}_semantics"] = status
                values[f"melting_{side}_source"] = p.melting_point_source_url
            spent = budget.spent
            claims = [Claim(cause="temperature_evidence", statement=f"A Tammann estimate is available for precursor {side}.",
                            evidence=[f"values.tammann_{side}_c"],
                            falsified_if="Recomputing the conversion from the reported melting point gives a different value.")
                      for side in ("a", "b") if values[f"tammann_{side}_c"] is not None]
            board.post_artifact(Artifact(artifact_id=board.new_id(self.name), run_id=board.run_id,
                item_id=item.item_id, agent=self.name, type="kinetics_report", values=values,
                claims=claims, rationale="Reported temperatures are estimates; check source cautions.",
                cost=Cost(tool_calls=spent.tool_calls-before.tool_calls)))
        if self.energy_margin is None:
            return
        for a in board.accepted_artifacts(item.item_id):
            value = a.values.get("dE_ev_per_atom")
            if a.agent == "thermo" and isinstance(value, (float, int)) and abs(value) <= self.energy_margin:
                if not any(n.type == "firm_up_energy" and n.from_agent == self.name for n in board.needs(item.item_id)):
                    board.post_need(Need(need_id=board.new_id("need"), run_id=board.run_id,
                        item_id=item.item_id, type="firm_up_energy", from_agent=self.name,
                        payload={"current_dE_ev_per_atom": value}))
                break
