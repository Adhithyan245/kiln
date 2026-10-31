from __future__ import annotations

import multiprocessing as mp

import pytest

from kiln.board import Board, BoardError
from kiln.schemas import VerifierStatus

from tests.board.helpers import make_artifact, make_need, race_claim


@pytest.fixture
def board(tmp_path):
    return Board(tmp_path / "runs" / "run-test")


def test_files_live_under_run_board_dir(board, tmp_path):
    board.post_need(make_need(board))
    board.post_artifact(make_artifact(board))
    base = tmp_path / "runs" / "run-test" / "board"
    assert (base / "needs.jsonl").exists()
    assert (base / "artifacts.jsonl").exists()
    assert board.run_id == "run-test"


def test_ids_are_sequential_per_kind(board):
    assert board.new_id("need") == "run-test:need:1"
    assert board.new_id("need") == "run-test:need:2"
    assert board.new_id("thermo") == "run-test:thermo:1"


def test_need_lifecycle_open_claimed_fulfilled(board):
    n = make_need(board)
    board.post_need(n)
    assert [x.need_id for x in board.open_needs(n.item_id, ["firm_up_energy"])] == [n.need_id]
    assert board.open_needs(n.item_id, ["reaction_energy"]) == []

    assert board.claim(n.need_id, "thermo") is True
    assert board.claim(n.need_id, "planner") is False
    assert board.open_needs(n.item_id) == []
    assert board.get_need(n.need_id).claimed_by == "thermo"

    a = make_artifact(board, fulfills_need=n.need_id)
    board.post_artifact(a)
    board.fulfill(n.need_id, a.artifact_id)
    done = board.get_need(n.need_id)
    assert done.status == "fulfilled" and done.fulfilled_by == a.artifact_id


def test_files_are_append_only(board):
    n = make_need(board)
    board.post_need(n)
    board.claim(n.need_id, "thermo")
    a = make_artifact(board)
    board.post_artifact(a)
    board.fulfill(n.need_id, a.artifact_id)
    lines = board.needs_path.read_text().splitlines()
    assert len(lines) == 3  # open, claimed, fulfilled: history is kept
    assert [line.count('"status":"open"') for line in lines] == [1, 0, 0]


def test_fulfill_requires_claim_and_known_artifact(board):
    n = make_need(board)
    board.post_need(n)
    a = make_artifact(board)
    board.post_artifact(a)
    with pytest.raises(BoardError):
        board.fulfill(n.need_id, a.artifact_id)  # not claimed yet
    board.claim(n.need_id, "thermo")
    with pytest.raises(BoardError):
        board.fulfill(n.need_id, "run-test:thermo:999")


def test_decline_only_by_claimant(board):
    n = make_need(board)
    board.post_need(n)
    board.claim(n.need_id, "thermo")
    with pytest.raises(BoardError):
        board.decline(n.need_id, "precursor")
    board.decline(n.need_id, "thermo")
    assert board.get_need(n.need_id).status == "declined"


def test_unknown_and_duplicate_needs_rejected(board):
    with pytest.raises(BoardError):
        board.claim("run-test:need:404", "thermo")
    n = make_need(board)
    board.post_need(n)
    with pytest.raises(BoardError):
        board.post_need(n)


def test_records_from_another_run_rejected(board):
    n = make_need(board).model_copy(update={"run_id": "other-run"})
    with pytest.raises(BoardError):
        board.post_need(n)


def test_accepted_artifacts_follow_latest_verdict(board):
    a = make_artifact(board)
    b = make_artifact(board)
    board.post_artifact(a)
    board.post_artifact(b)
    assert board.accepted_artifacts(a.item_id) == []

    board.post_artifact(a.model_copy(update={"verifier": VerifierStatus.accepted}))
    board.post_artifact(b.model_copy(update={"verifier": VerifierStatus.rejected}))
    assert [x.artifact_id for x in board.accepted_artifacts(a.item_id)] == [a.artifact_id]
    assert board.accepted_artifacts("PG-dev-other") == []


@pytest.mark.parametrize("racers", [2, 8])
def test_concurrent_claim_has_exactly_one_winner(tmp_path, racers):
    board = Board(tmp_path / "runs" / "run-race")
    n = make_need(board)
    board.post_need(n)

    ctx = mp.get_context("spawn")  # same behaviour on Windows and Linux
    barrier = ctx.Barrier(racers)
    results = ctx.Queue()
    names = ["thermo", "kinetics", "precursor", "single", "planner"]
    procs = [
        ctx.Process(target=race_claim, args=(str(board.run_dir), n.need_id, names[i % len(names)], barrier, results))
        for i in range(racers)
    ]
    for p in procs:
        p.start()
    outcomes = [results.get(timeout=60) for _ in procs]
    for p in procs:
        p.join(timeout=60)
        assert p.exitcode == 0

    winners = [agent for agent, won in outcomes if won]
    assert len(winners) == 1
    final = board.get_need(n.need_id)
    assert final.status == "claimed" and final.claimed_by == winners[0]
    # exactly one claim record was written after the open record
    assert len(board.needs_path.read_text().splitlines()) == 2
