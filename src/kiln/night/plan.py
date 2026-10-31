"""Night plans: a TOML file of steps that form a DAG.

Every step must be idempotent: the runner reruns a step whose done-marker is missing or stale,
and a retry reruns it from the start. Steps that loop over items should skip items whose output
already exists (the compute cache and per-run predictions make that cheap).

Caps are deliberately not defaulted (protocol OPEN-02); a real run refuses to start without them.
"""
from __future__ import annotations

import hashlib
import json
import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator

__all__ = ["Caps", "Gate", "Plan", "PlanError", "Retry", "Step", "load_plan"]


class PlanError(Exception):
    """A plan file that cannot be run: bad TOML, unknown dependency, cycle, missing caps."""


class Caps(BaseModel):
    max_tokens: int | None = None
    max_usd: float | None = None
    max_gpu_hours: float | None = None

    def complete(self) -> bool:
        return None not in (self.max_tokens, self.max_usd, self.max_gpu_hours)


class Retry(BaseModel):
    base_s: float = 30.0
    factor: float = 2.0
    jitter: float = 0.25          # each delay is stretched by up to this fraction, at random
    max_delay_s: float = 900.0


class Gate(BaseModel):
    """Files that decide whether a `requires_receipt` step may run."""
    receipt: str = "protocol/posts.jsonl"
    manifest: str = "protocol/predictions.manifest.json"


class Step(BaseModel):
    name: str
    cmd: list[str] = Field(min_length=1)      # argv; "python" means this interpreter; ${VAR} is expanded
    depends_on: list[str] = Field(default_factory=list)
    timeout_s: float = 3600.0
    retries: int = Field(default=2, ge=0)      # extra attempts after the first
    env: list[str] = Field(default_factory=list)          # names of required env vars, never values
    on_missing_env: Literal["fail", "skip"] = "fail"
    requires_receipt: bool = False
    always: bool = False                      # runs at the end even after failure or stop
    note: str = ""

    def spec_hash(self) -> str:
        canonical = json.dumps(self.model_dump(exclude={"note"}), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()


class Plan(BaseModel):
    name: str
    labels_must_be_absent: bool = False
    heartbeat_s: float = 1800.0
    cap_check_s: float = 60.0
    stop_grace_s: float = 120.0
    caps: Caps = Field(default_factory=Caps)
    retry: Retry = Field(default_factory=Retry)
    gate: Gate = Field(default_factory=Gate)
    steps: list[Step] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_dag(self) -> Plan:
        names = [s.name for s in self.steps]
        if len(set(names)) != len(names):
            raise ValueError("duplicate step names")
        known = set(names)
        for s in self.steps:
            unknown = set(s.depends_on) - known
            if unknown:
                raise ValueError(f"step {s.name!r} depends on unknown {sorted(unknown)}")
            if s.always and s.depends_on:
                raise ValueError(f"always-step {s.name!r} cannot have dependencies")
        self.order()  # raises on cycles
        return self

    def step(self, name: str) -> Step:
        return next(s for s in self.steps if s.name == name)

    def order(self) -> list[Step]:
        """Main steps in dependency order (file order breaks ties); always-steps excluded."""
        done: list[str] = []
        pending = [s for s in self.steps if not s.always]
        while pending:
            ready = [s for s in pending if all(d in done for d in s.depends_on)]
            if not ready:
                raise ValueError(f"dependency cycle among {[s.name for s in pending]}")
            done.append(ready[0].name)
            pending.remove(ready[0])
        return [self.step(n) for n in done]

    def finally_steps(self) -> list[Step]:
        return [s for s in self.steps if s.always]


def load_plan(path: str | Path) -> Plan:
    try:
        data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
        return Plan.model_validate(data)
    except (OSError, tomllib.TOMLDecodeError, ValueError) as exc:
        raise PlanError(f"{path}: {exc}") from exc
