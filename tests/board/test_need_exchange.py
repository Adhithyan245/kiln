"""Two dummy agents exchange one firm_up_energy need through the board (Task 1)."""
from __future__ import annotations

from kiln.agents.base import Agent
from kiln.board import Board
from kiln.budget import Budget
from kiln.schemas import Artifact, Claim, Item, Need, RunConfig

from tests.board.helpers import make_item


class DummyKinetics(Agent):
    """Posts one firm_up_energy need, then reads the answer once it's fulfilled."""
    name = "kinetics"

    def __init__(self) -> None:
        self.need_id: str | None = None
        self.answer: Artifact | None = None

    def step(self, item: Item, board: Board, budget: Budget) -> None:
        if self.need_id is None:
            budget.charge_tool_call()
            self.need_id = board.new_id("need")
            board.post_need(Need(
                need_id=self.need_id, run_id=board.run_id, item_id=item.item_id,
                type="firm_up_energy", from_agent=self.name,
                payload={"formula": "CaTiO3", "current_dE_ev_per_atom": -0.04},
            ))
            return
        need = board.get_need(self.need_id)
        if need.status == "fulfilled" and self.answer is None:
            self.answer = board.get_artifact(need.fulfilled_by)


class DummyThermo(Agent):
    """Claims open firm_up_energy needs and answers each with a fixed stub artifact."""
    name = "thermo"

    def step(self, item: Item, board: Board, budget: Budget) -> None:
        for need in board.open_needs(item.item_id, ["firm_up_energy"]):
            if not board.claim(need.need_id, self.name):
                continue
            budget.charge_tool_call()
            budget.charge_compute(2.0)  # stand-in for a compute-service request
            a = Artifact(
                artifact_id=board.new_id(self.name), run_id=board.run_id, item_id=item.item_id,
                agent=self.name, type="reaction_report",
                values={"dE_ev_per_atom": -0.06},
                claims=[Claim(
                    cause="driving_force_firmed_up",
                    statement="Stub: driving force confirmed for the test.",
                    evidence=["values.dE_ev_per_atom"],
                    falsified_if="A higher-tier calculation gives dE >= 0.",
                )],
                fulfills_need=need.need_id,
                rationale="Dummy agent for the Task 1 board test.",
            )
            board.post_artifact(a)
            board.fulfill(need.need_id, a.artifact_id)


def test_two_dummy_agents_exchange_one_need(tmp_path):
    board = Board(tmp_path / "runs" / "run-dummy")
    budget = Budget(RunConfig(run_id="run-dummy", condition="C4", seed=0, model="none"))
    item = make_item()
    kinetics, thermo = DummyKinetics(), DummyThermo()

    for _ in range(3):  # coordination rounds
        for agent in (kinetics, thermo):
            agent.step(item, board, budget)

    need = board.get_need(kinetics.need_id)
    assert need.status == "fulfilled" and need.claimed_by == "thermo"
    assert kinetics.answer is not None
    assert kinetics.answer.fulfills_need == need.need_id
    assert kinetics.answer.values["dE_ev_per_atom"] == -0.06
    assert len(board.needs(item.item_id)) == 1  # exactly one need was exchanged
    assert budget.spent.tool_calls == 2 and budget.spent.compute_units == 2.0
