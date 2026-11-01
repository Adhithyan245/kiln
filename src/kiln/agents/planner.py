"""C3: a central planner that decides which specialist runs, and when.

Specialists don't talk to each other: their needs are suppressed by the runner and shown to the
planner instead, which decides who acts on them. Each round one LLM call (llm_choose) orders the
specialists to run; its tokens come out of the same per-item budget as everyone else's.
"""
from __future__ import annotations

from collections.abc import Sequence

from kiln.agents.base import Agent, llm_choose
from kiln.agents.single import describe
from kiln.board import Board
from kiln.budget import Budget
from kiln.schemas import Item, RunConfig

__all__ = ["Planner"]

SYSTEM = ("You coordinate three specialists (precursor, thermo, kinetics) deciding whether two solid "
          "precursors react at a furnace temperature. Choose who works next; you never supply numbers.")


class Planner(Agent):
    name = "planner"

    def __init__(self, specialists: Sequence[Agent], config: RunConfig) -> None:
        self.specialists = {s.name: s for s in specialists}
        self.config = config

    def step(self, item: Item, board: Board, budget: Budget) -> None:
        suppressed = getattr(board, "suppressed", [])
        pending = [f"{n.from_agent} asks for {n.type} {n.payload}" for n in suppressed if n.item_id == item.item_id]
        for name in llm_choose(list(self.specialists), describe(item, board, pending), budget, self.config,
                               system=SYSTEM):
            self.specialists[name].step(item, board, budget)
