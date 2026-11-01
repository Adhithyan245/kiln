"""Per-item budget: tool calls, tokens and compute units, identical for every condition.

Every agent and the compute client charge through one Budget per item. Tool calls and
compute are charged *before* the work runs: a charge that would go over the limit is
refused (nothing is spent) and raises BudgetExceeded. Tokens are only known after an
LLM call returns, so they are always recorded (the spend really happened) and then
BudgetExceeded is raised if the total is over the limit.
"""
from __future__ import annotations

import threading

from kiln.schemas import Cost, RunConfig

__all__ = ["Budget", "BudgetExceeded"]


class BudgetExceeded(Exception):
    def __init__(self, resource: str, requested: float, remaining: float) -> None:
        self.resource = resource
        self.requested = requested
        self.remaining = remaining
        super().__init__(f"budget exceeded: {resource} requested {requested}, remaining {remaining}")


class Budget:
    def __init__(self, config: RunConfig) -> None:
        self.max_tool_calls = config.max_tool_calls_per_item
        self.max_tokens = config.max_tokens_per_item
        self.max_compute_units = config.max_compute_units_per_item
        self._spent = Cost()
        self._lock = threading.Lock()

    def charge_tool_call(self) -> None:
        with self._lock:
            left = self.max_tool_calls - self._spent.tool_calls
            if left < 1:
                raise BudgetExceeded("tool_calls", 1, left)
            self._spent.tool_calls += 1

    def charge_tokens(self, tokens_in: int, tokens_out: int) -> None:
        if tokens_in < 0 or tokens_out < 0:
            raise ValueError("token counts must be non-negative")
        with self._lock:
            self._spent.tokens_in += tokens_in
            self._spent.tokens_out += tokens_out
            used = self._spent.tokens_in + self._spent.tokens_out
            if used > self.max_tokens:
                raise BudgetExceeded("tokens", tokens_in + tokens_out, self.max_tokens - (used - tokens_in - tokens_out))

    def charge_compute(self, units: float) -> None:
        if units < 0:
            raise ValueError("compute units must be non-negative")
        with self._lock:
            left = self.max_compute_units - self._spent.compute_units
            if units > left + 1e-9:
                raise BudgetExceeded("compute_units", units, left)
            self._spent.compute_units += units

    def record_usd(self, usd: float) -> None:
        """Experiment API spend for this item. Recorded for reporting, not capped."""
        if usd < 0:
            raise ValueError("usd must be non-negative")
        with self._lock:
            self._spent.usd += usd

    def remaining(self) -> dict[str, float]:
        with self._lock:
            return {
                "tool_calls": self.max_tool_calls - self._spent.tool_calls,
                "tokens": self.max_tokens - self._spent.tokens_in - self._spent.tokens_out,
                "compute_units": self.max_compute_units - self._spent.compute_units,
            }

    @property
    def spent(self) -> Cost:
        """A copy of everything charged so far, for Prediction.cost and cost.json."""
        with self._lock:
            return self._spent.model_copy()

    @property
    def item_cost(self) -> Cost:
        """The item's cumulative cost so far: what `kiln.verifier.verify` takes as `item_cost` (OPEN-24).
        Read it while no compute request for the item is in flight."""
        return self.spent
