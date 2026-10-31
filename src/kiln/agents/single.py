"""C1: one agent with every specialist skill and every compute tier.

Each round one LLM call (llm_choose) picks which skills to use and in what order, from a fixed
menu; the skills are the specialists' own implementations, so C1 has exactly the tools and tiers
the collective has. Every number still comes from the skills' code (AGENTS.md rule 7). There is
no need board traffic in C1: the runner suppresses needs and logs them.
"""
from __future__ import annotations

from collections.abc import Sequence

from kiln.agents.base import Agent, llm_choose
from kiln.board import Board
from kiln.budget import Budget
from kiln.schemas import Item, RunConfig

__all__ = ["SingleAgent", "describe"]

SYSTEM = ("You decide what evidence to gather about whether two solid precursors react at a furnace "
          "temperature. Each action runs a fixed tool; you never supply numbers.")


def describe(item: Item, board: Board, pending: Sequence[str] = ()) -> str:
    """What the LLM may see: the item and the accepted evidence so far. Never labels."""
    lines = [f"Precursors {item.precursor_a} + {item.precursor_b} at {item.temperature_c} °C"
             + (f" for {item.dwell_h} h" if item.dwell_h is not None else "") + "."]
    for a in board.accepted_artifacts(item.item_id):
        causes = ", ".join(c.cause for c in a.claims) or "no claim"
        lines.append(f"- accepted {a.type} from {a.agent}: {causes}")
    lines += [f"- request: {p}" for p in pending]
    return "\n".join(lines)


class SingleAgent(Agent):
    name = "single"

    def __init__(self, skills: Sequence[Agent], config: RunConfig) -> None:
        self.skills = {s.name: s for s in skills}
        self.config = config

    def step(self, item: Item, board: Board, budget: Budget) -> None:
        for name in llm_choose(list(self.skills), describe(item, board), budget, self.config, system=SYSTEM):
            self.skills[name].step(item, board, budget)
