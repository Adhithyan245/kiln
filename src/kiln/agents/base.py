"""Base class every agent subclasses: the specialists, the single agent (C1) and the planner (C3)."""
from __future__ import annotations

from abc import ABC, abstractmethod

from kiln.board import Board
from kiln.budget import Budget
from kiln.schemas import AgentName, Item

__all__ = ["Agent"]


class Agent(ABC):
    name: AgentName

    @abstractmethod
    def step(self, item: Item, board: Board, budget: Budget) -> None:
        """One coordination round for one item.

        Read what's on the board, answer needs this agent can fulfil, post new needs and
        artifacts, and charge every tool call, token and compute unit to the budget.
        The runner calls step() once per agent per round, up to RunConfig.coordination_rounds.
        """
