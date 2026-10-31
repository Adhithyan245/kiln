"""Temperature evidence and requests for uncertain reaction energies."""

from __future__ import annotations

import math

from kiln.agents.base import Agent, llm_choose
from kiln.board import Board
from kiln.budget import Budget
from kiln.schemas import Artifact, Claim, Cost, Item, Need, RunConfig
from kiln.tools.precursors import props
from kiln.tools.tammann import checked_tammann_c


class Kinetics(Agent):
    name = "kinetics"

    def __init__(self, *, config: RunConfig, energy_margin_ev_per_atom: float | None = None) -> None:
        if not isinstance(config, RunConfig):
            raise TypeError("A RunConfig is required for model selection")
        if energy_margin_ev_per_atom is not None and (isinstance(energy_margin_ev_per_atom, bool)
                or not math.isfinite(energy_margin_ev_per_atom) or energy_margin_ev_per_atom < 0):
            raise ValueError("Energy margin must be finite and nonnegative")
        self.energy_margin = energy_margin_ev_per_atom
        self.config = config

    def step(self, item: Item, board: Board, budget: Budget) -> None:
        if self.config.run_id != board.run_id:
            raise ValueError("Agent config does not match the board run")
        prior = board.artifacts(item.item_id)
        if not any(a.agent == self.name for a in prior):
            before = budget.spent
            selected = llm_choose(["gather_temperature", "skip"],
                f"Kinetics for {item.precursor_a} and {item.precursor_b} at {item.temperature_c} C. "
                "Rule recommends gathering reported temperature evidence.", budget, self.config,
                system="Choose an action; never supply numerical evidence.")
            if not selected:
                raise ValueError("Kinetics model returned no valid action")
            if selected[0] == "skip":
                spent = budget.spent
                board.post_artifact(Artifact(artifact_id=board.new_id(self.name), run_id=board.run_id,
                    item_id=item.item_id, agent=self.name, type="kinetics_report", values={"temperature_check": "skipped"},
                    rationale="Rule recommended temperature evidence; model chose skip.",
                    cost=Cost(tokens_in=spent.tokens_in-before.tokens_in, tokens_out=spent.tokens_out-before.tokens_out,
                              usd=spent.usd-before.usd)))
                return
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
                claims=claims, rationale="Rule recommended temperature evidence; model chose gather_temperature. Check source cautions.",
                cost=Cost(tool_calls=spent.tool_calls-before.tool_calls, tokens_in=spent.tokens_in-before.tokens_in,
                          tokens_out=spent.tokens_out-before.tokens_out, usd=spent.usd-before.usd)))
        if self.energy_margin is None:
            return
        if any(a.agent == self.name and a.values.get("kinetics_energy_decision") for a in board.artifacts(item.item_id)):
            return
        for a in board.accepted_artifacts(item.item_id):
            value = a.values.get("dE_ev_per_atom")
            if a.agent == "thermo" and isinstance(value, (float, int)) and not isinstance(value, bool):
                before = budget.spent
                recommended = "firm_up_energy" if abs(value) <= self.energy_margin else "skip"
                options = [recommended, "skip" if recommended != "skip" else "firm_up_energy"]
                chosen = llm_choose(options, f"Rule recommends {recommended}; energy is {value} eV/atom. "
                    f"Remaining budget: {budget.remaining()}.", budget, self.config,
                    system="Choose an action; never supply numerical evidence.")
                if not chosen:
                    raise ValueError("Kinetics model returned no valid action")
                action = chosen[0]
                spent = budget.spent
                board.post_artifact(Artifact(artifact_id=board.new_id(self.name), run_id=board.run_id,
                    item_id=item.item_id, agent=self.name, type="kinetics_report",
                    values={"kinetics_energy_decision": action}, cites=[a.artifact_id],
                    rationale=f"Rule recommended {recommended}; model chose {action}.",
                    cost=Cost(tokens_in=spent.tokens_in-before.tokens_in, tokens_out=spent.tokens_out-before.tokens_out,
                              usd=spent.usd-before.usd)))
                if action == "firm_up_energy" and not any(n.type == "firm_up_energy" and n.from_agent == self.name for n in board.needs(item.item_id)):
                    board.post_need(Need(need_id=board.new_id("need"), run_id=board.run_id,
                        item_id=item.item_id, type="firm_up_energy", from_agent=self.name,
                        payload={"current_dE_ev_per_atom": value,
                                 "reason": f"Rule recommended {recommended}; model chose {action}."}))
                break
