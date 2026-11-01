"""Shared test helpers. Lives in an importable module so spawned processes can use it."""
from __future__ import annotations

from pathlib import Path

from kiln.board import Board
from kiln.schemas import Artifact, Item, Need


def make_item(item_id: str = "PG-dev-0001") -> Item:
    # Made-up development item for tests; no label or ledger data.
    return Item(
        item_id=item_id,
        source="precursor_genome",
        precursor_a="CaCO3",
        precursor_b="TiO2",
        temperature_c=900.0,
        dwell_h=4.0,
        melting_point_a_c=1339.0,
        melting_point_b_c=1843.0,
        split="dev",
    )


def make_need(board: Board, item_id: str = "PG-dev-0001") -> Need:
    return Need(
        need_id=board.new_id("need"),
        run_id=board.run_id,
        item_id=item_id,
        type="firm_up_energy",
        from_agent="kinetics",
        payload={"formula": "CaTiO3", "current_dE_ev_per_atom": -0.04},
    )


def make_artifact(board: Board, item_id: str = "PG-dev-0001", **kw) -> Artifact:
    return Artifact(
        artifact_id=board.new_id("thermo"),
        run_id=board.run_id,
        item_id=item_id,
        agent="thermo",
        type="reaction_report",
        values={"dE_ev_per_atom": -0.05},
        **kw,
    )


def race_claim(run_dir: str, need_id: str, agent: str, barrier, results) -> None:
    """Child process: wait until every racer is ready, then try to claim the same need."""
    board = Board(Path(run_dir))
    barrier.wait()
    results.put((agent, board.claim(need_id, agent)))
