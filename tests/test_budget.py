from __future__ import annotations

import threading

import pytest

from kiln.budget import Budget, BudgetExceeded
from kiln.schemas import RunConfig


def make_budget(**limits) -> Budget:
    return Budget(RunConfig(run_id="run-b", condition="C1", seed=0, model="none", **limits))


def test_limits_come_from_run_config():
    b = make_budget(max_tool_calls_per_item=3, max_tokens_per_item=100, max_compute_units_per_item=5.0)
    assert b.remaining() == {"tool_calls": 3, "tokens": 100, "compute_units": 5.0}


def test_tool_calls_refused_past_limit_without_charging():
    b = make_budget(max_tool_calls_per_item=2)
    b.charge_tool_call()
    b.charge_tool_call()
    with pytest.raises(BudgetExceeded) as e:
        b.charge_tool_call()
    assert e.value.resource == "tool_calls"
    assert b.spent.tool_calls == 2


def test_compute_refused_past_limit_without_charging():
    b = make_budget(max_compute_units_per_item=5.0)
    b.charge_compute(3.0)
    with pytest.raises(BudgetExceeded) as e:
        b.charge_compute(2.5)
    assert e.value.resource == "compute_units" and e.value.remaining == pytest.approx(2.0)
    assert b.spent.compute_units == pytest.approx(3.0)
    b.charge_compute(2.0)  # exactly reaching the limit is allowed
    assert b.remaining()["compute_units"] == pytest.approx(0.0)


def test_tokens_are_recorded_then_raise_when_over():
    b = make_budget(max_tokens_per_item=100)
    b.charge_tokens(40, 20)
    with pytest.raises(BudgetExceeded) as e:
        b.charge_tokens(30, 20)
    assert e.value.resource == "tokens"
    # the LLM call already happened, so its tokens stay on the bill
    assert (b.spent.tokens_in, b.spent.tokens_out) == (70, 40)
    assert b.remaining()["tokens"] == -10


def test_negative_charges_rejected():
    b = make_budget()
    with pytest.raises(ValueError):
        b.charge_compute(-1.0)
    with pytest.raises(ValueError):
        b.charge_tokens(-1, 0)


def test_spent_is_a_copy():
    b = make_budget()
    b.charge_tool_call()
    snapshot = b.spent
    snapshot.tool_calls = 99
    assert b.spent.tool_calls == 1


def test_item_cost_is_the_cumulative_cost_for_the_verifier():
    b = make_budget()
    b.charge_tool_call()
    b.charge_compute(1.5)
    b.charge_tokens(10, 5)
    assert b.item_cost == b.spent
    b.item_cost.tool_calls = 99   # a copy: the verifier can't change what was charged
    assert b.spent.tool_calls == 1


def test_thread_safe_charging_never_overspends():
    b = make_budget(max_compute_units_per_item=10.0)
    refused = []

    def worker():
        for _ in range(10):
            try:
                b.charge_compute(1.0)
            except BudgetExceeded:
                refused.append(1)

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert b.spent.compute_units == pytest.approx(10.0)
    assert len(refused) == 40
