"""Need board: the only channel agents use to coordinate.

Files (append-only JSON Lines, per docs/interfaces.md):
    runs/<run_id>/board/artifacts.jsonl
    runs/<run_id>/board/needs.jsonl

Nothing is ever rewritten. A change to an artifact or need (a claim, a fulfilment,
a verifier verdict) is appended as a new full record with the same id; the latest
record for an id is its current state, and earlier lines remain as the history.
Every write and every read-modify-write happens under one file lock, so several
processes can share a board and claim() has exactly one winner.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, TypeVar

from filelock import FileLock
from pydantic import BaseModel

from kiln.schemas import AgentName, Artifact, Need, NeedType, VerifierStatus

__all__ = ["Board", "BoardError"]

M = TypeVar("M", bound=BaseModel)


class BoardError(Exception):
    """An operation that the board's state doesn't allow (unknown id, wrong status)."""


class Board:
    def __init__(self, run_dir: str | Path, name: str = "board") -> None:
        """name="board" is the shared board; C2 gives each isolated specialist its own name."""
        self.run_dir = Path(run_dir)
        self.run_id = self.run_dir.name
        self.dir = self.run_dir / name
        self.dir.mkdir(parents=True, exist_ok=True)
        self.artifacts_path = self.dir / "artifacts.jsonl"
        self.needs_path = self.dir / "needs.jsonl"
        self._counters_path = self.dir / "counters.json"
        self._lock = FileLock(str(self.dir / ".lock"))

    # ---------- ids ----------

    def new_id(self, kind: str) -> str:
        """Next id of the form "<run_id>:<kind>:<seq>", unique across processes.

        Use kind="need" for needs and the agent name for artifacts.
        """
        with self._lock:
            counters = json.loads(self._counters_path.read_text()) if self._counters_path.exists() else {}
            seq = counters.get(kind, 0) + 1
            counters[kind] = seq
            self._counters_path.write_text(json.dumps(counters))
        return f"{self.run_id}:{kind}:{seq}"

    # ---------- artifacts ----------

    def post_artifact(self, a: Artifact) -> None:
        """Post a new artifact, or a new state of an existing one (e.g. the verifier's verdict)."""
        self._check_run(a.run_id)
        with self._lock:
            self._append(self.artifacts_path, a)

    def artifacts(self, item_id: str | None = None) -> list[Artifact]:
        """Current state of every artifact, optionally for one item, in posting order."""
        with self._lock:
            current = self._latest(self.artifacts_path, Artifact, "artifact_id")
        return [a for a in current.values() if item_id is None or a.item_id == item_id]

    def get_artifact(self, artifact_id: str) -> Artifact:
        with self._lock:
            current = self._latest(self.artifacts_path, Artifact, "artifact_id")
        if artifact_id not in current:
            raise BoardError(f"unknown artifact {artifact_id}")
        return current[artifact_id]

    def accepted_artifacts(self, item_id: str) -> list[Artifact]:
        return [a for a in self.artifacts(item_id) if a.verifier == VerifierStatus.accepted]

    # ---------- needs ----------

    def post_need(self, n: Need) -> None:
        self._check_run(n.run_id)
        if n.status != "open":
            raise BoardError(f"new need {n.need_id} must be open, not {n.status}")
        with self._lock:
            if n.need_id in self._latest(self.needs_path, Need, "need_id"):
                raise BoardError(f"need {n.need_id} already exists")
            self._append(self.needs_path, n)

    def needs(self, item_id: str | None = None) -> list[Need]:
        """Current state of every need, optionally for one item, in posting order."""
        with self._lock:
            current = self._latest(self.needs_path, Need, "need_id")
        return [n for n in current.values() if item_id is None or n.item_id == item_id]

    def get_need(self, need_id: str) -> Need:
        with self._lock:
            current = self._latest(self.needs_path, Need, "need_id")
        if need_id not in current:
            raise BoardError(f"unknown need {need_id}")
        return current[need_id]

    def open_needs(self, item_id: str, types: Iterable[NeedType] | None = None) -> list[Need]:
        wanted = set(types) if types is not None else None
        return [
            n for n in self.needs(item_id)
            if n.status == "open" and (wanted is None or n.type in wanted)
        ]

    def claim(self, need_id: str, agent: AgentName) -> bool:
        """Claim an open need. Exactly one caller wins, even across processes."""
        with self._lock:
            n = self._latest(self.needs_path, Need, "need_id").get(need_id)
            if n is None:
                raise BoardError(f"unknown need {need_id}")
            if n.status != "open":
                return False
            self._append(self.needs_path, n.model_copy(update={"status": "claimed", "claimed_by": agent}))
            return True

    def fulfill(self, need_id: str, artifact_id: str) -> None:
        """Mark a claimed need fulfilled by an artifact already on the board."""
        with self._lock:
            n = self._latest(self.needs_path, Need, "need_id").get(need_id)
            if n is None:
                raise BoardError(f"unknown need {need_id}")
            if n.status != "claimed":
                raise BoardError(f"need {need_id} is {n.status}; only a claimed need can be fulfilled")
            if artifact_id not in self._latest(self.artifacts_path, Artifact, "artifact_id"):
                raise BoardError(f"unknown artifact {artifact_id}")
            self._append(self.needs_path, n.model_copy(update={"status": "fulfilled", "fulfilled_by": artifact_id}))

    def decline(self, need_id: str, agent: AgentName) -> None:
        """The claimant gives a claimed need up as declined (e.g. the budget can't cover it)."""
        with self._lock:
            n = self._latest(self.needs_path, Need, "need_id").get(need_id)
            if n is None:
                raise BoardError(f"unknown need {need_id}")
            if n.status != "claimed" or n.claimed_by != agent:
                raise BoardError(f"need {need_id} is not claimed by {agent}")
            self._append(self.needs_path, n.model_copy(update={"status": "declined"}))

    # ---------- internals (call with the lock held) ----------

    def _check_run(self, run_id: str) -> None:
        if run_id != self.run_id:
            raise BoardError(f"record is for run {run_id}, but this board is run {self.run_id}")

    @staticmethod
    def _append(path: Path, record: BaseModel) -> None:
        with path.open("a", encoding="utf-8") as f:
            f.write(record.model_dump_json() + "\n")

    @staticmethod
    def _latest(path: Path, model: type[M], key: str) -> dict[str, M]:
        current: dict[str, M] = {}
        if not path.exists():
            return current
        with path.open(encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    record = model.model_validate_json(line)
                    current[getattr(record, key)] = record
        return current
