"""Run one condition x seed x split: the only code path for C1-C4 (docs/plans/cj-kiln-v2.md §3).

The condition changes only which agents run and whether needs are delivered:

    C1 single    SingleAgent (every specialist skill, every tier)  one board   needs suppressed
    C2 isolated  thermo, kinetics, precursor                       own boards  needs suppressed
    C3 planner   Planner + the specialists as callees              one board   needs go to the planner
    C4 Kiln      thermo, kinetics, precursor                       one board   needs delivered

Everything else is shared, so the comparison is fair: the item list (sorted), one Budget per
item drawn on by every agent in the condition (the planner's tokens included), the compute
client and cache (cache hits charged), the verifier, the review flags and the scorer.

Every artifact is verified before it is written. A need is fulfilled only by an accepted
artifact; otherwise it goes back to open. When the budget runs out the item stops, what was
accepted is scored, and a missing_evidence flag says why. No item is skipped.

Outputs in runs/<run_id>/: config.json, board/<item>/attempt-<n>/, compute_requests.jsonl,
needs_suppressed.jsonl, verifier.log, predictions.jsonl (one line per item) and cost.json
(item id -> Cost, read by the night runner's spend caps). Re-running resumes: items already in
predictions.jsonl are skipped, and an interrupted item gets a fresh attempt folder.

    python -m kiln.runners.conditions --split dev --condition C4 --seed 0 --model offline \\
        --stubs --items-file ~/kiln-items.jsonl --limit 5
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from kiln.agents.base import PRICES_USD_PER_MTOK, Agent
from kiln.board import Board
from kiln.budget import Budget, BudgetExceeded
from kiln.schemas import (
    Artifact, ComputeRequest, Cost, Item, Need, Prediction, ReviewFlag, ReviewReason, RunConfig, VerifierStatus,
)
from kiln.verifier import verify

__all__ = ["CONDITIONS", "Components", "VerifyingBoard", "main", "run", "run_id_for", "stub_components"]

CONDITIONS = ("C1", "C2", "C3", "C4")
SEEDS = (0, 1, 2)
AGENT_ORDER = ("precursor", "thermo", "kinetics")   # fixed by the protocol, never shuffled by seed


class Compute(Protocol):
    def request(self, item: Item, agent: Any, tier: Any, reason: str, inputs: dict[str, Any],
                budget: Budget) -> ComputeRequest: ...


class Scorer(Protocol):
    def score(self, item: Item, accepted: Sequence[Artifact], requests: Sequence[ComputeRequest],
              flags: Sequence[ReviewFlag], *, cost: Cost) -> Prediction: ...


@dataclass(frozen=True)
class Components:
    """The pieces each condition shares. `stubs` is recorded in config.json and in every prediction."""
    compute: Callable[[Path, RunConfig], Compute]
    specialists: Callable[[Compute, RunConfig], list[Agent]]
    tool_values: Callable[[Item], Mapping[str, float | str | bool | None]]
    flags: Callable[[Item, Sequence[Artifact], Sequence[ComputeRequest]], list[ReviewFlag]]
    scorer: Callable[[RunConfig], Scorer]
    stubs: bool


def stub_components() -> Components:
    """Adhi's stand-ins (kiln.runners.stubs). Fake numbers, for wiring and dry runs only."""
    from kiln.runners import stubs

    return Components(
        compute=lambda run_dir, cfg: stubs.StubCompute(run_dir, cfg.tier_prices or None),
        specialists=lambda compute, cfg: stubs.stub_specialists(compute),  # type: ignore[arg-type]
        tool_values=stubs.stub_tool_values,
        flags=stubs.stub_flags,
        scorer=stubs.StubScorer,
        stubs=True,
    )


def real_components() -> Components:
    missing = [m for m in ("kiln.agents.thermo", "kiln.agents.kinetics", "kiln.agents.precursor",
                           "kiln.tools.tammann", "kiln.review") if not _importable(m)]
    if missing:
        raise SystemExit(f"real components not on this branch yet: {', '.join(missing)}. "
                         "Use --stubs for a dry run; stub results are never experiment results.")
    raise SystemExit("real components are importable but not wired into the runner yet")  # CJ: wire on arrival


def run_id_for(condition: str, model: str, seed: int, split: str) -> str:
    return f"{condition}-{re.sub(r'[^A-Za-z0-9.]+', '-', model)}-s{seed}-{split}"


# ---------- the verifying board ----------

class VerifyingBoard(Board):
    """A Board that runs the verifier on every new artifact before writing it, fulfils needs
    only with accepted artifacts, and (when needs are off) logs needs instead of posting them."""

    def __init__(self, run_dir: Path, name: str, *, item: Item, config: RunConfig, budget: Budget,
                 requests: Callable[[], list[ComputeRequest]],
                 tool_values: Mapping[str, float | str | bool | None], needs_enabled: bool) -> None:
        super().__init__(run_dir, name)
        self.item, self.config, self.budget = item, config, budget
        self._requests, self.tool_values, self.needs_enabled = requests, tool_values, needs_enabled
        self.suppressed: list[Need] = []

    def post_artifact(self, a: Artifact) -> None:
        if a.verifier == VerifierStatus.pending:
            status, notes = verify(a, self, requests=self._requests(), config=self.config,
                                   item_cost=self.budget.spent, tool_values=self.tool_values)
            a = a.model_copy(update={"verifier": status, "verifier_notes": notes})
            if status != VerifierStatus.accepted:  # still written below (rule 9), and logged here
                _append_jsonl(self.run_dir / "verifier.log", {"artifact_id": a.artifact_id, "agent": a.agent,
                                                               "status": status.value, "notes": notes})
        super().post_artifact(a)

    def fulfill(self, need_id: str, artifact_id: str) -> None:
        if self.get_artifact(artifact_id).verifier == VerifierStatus.accepted:
            super().fulfill(need_id, artifact_id)
            return
        with self._lock:  # not accepted: the need goes back to open for another round
            n = self._latest(self.needs_path, Need, "need_id")[need_id]
            self._append(self.needs_path, n.model_copy(update={"status": "open", "claimed_by": None}))

    def post_need(self, n: Need) -> None:
        if self.needs_enabled:
            super().post_need(n)
            return
        self._check_run(n.run_id)
        self.suppressed.append(n)
        _append_jsonl(self.run_dir / "needs_suppressed.jsonl",
                      {"event": "need_suppressed", "condition": self.config.condition, "need": n.model_dump(mode="json")})


# ---------- one item ----------

def _boards(cfg: RunConfig, run_dir: Path, item: Item, attempt: int, budget: Budget,
            requests: Callable[[], list[ComputeRequest]], tool_values: Mapping[str, Any],
            names: Sequence[str]) -> dict[str, VerifyingBoard]:
    base = f"board/{_safe(item.item_id)}/attempt-{attempt}"
    make = lambda name, needs: VerifyingBoard(run_dir, name, item=item, config=cfg, budget=budget,  # noqa: E731
                                              requests=requests, tool_values=tool_values, needs_enabled=needs)
    if cfg.condition == "C2":
        return {name: make(f"{base}/{name}", False) for name in names}
    shared = make(base, cfg.condition == "C4")
    return {name: shared for name in names}


def _agents(cfg: RunConfig, compute: Compute, components: Components) -> list[Agent]:
    specialists = sorted(components.specialists(compute, cfg), key=lambda a: AGENT_ORDER.index(a.name))
    if cfg.condition == "C1":
        from kiln.agents.single import SingleAgent

        return [SingleAgent(specialists, cfg)]
    if cfg.condition == "C3":
        from kiln.agents.planner import Planner

        return [Planner(specialists, cfg)]
    return specialists


def run_item(cfg: RunConfig, run_dir: Path, item: Item, compute: Compute, components: Components) -> Prediction:
    budget = Budget(cfg)
    log_path = run_dir / "compute_requests.jsonl"
    before = {r.request_id for r in _read_requests(log_path) if r.item_id == item.item_id}

    def requests() -> list[ComputeRequest]:
        return [r for r in _read_requests(log_path) if r.item_id == item.item_id and r.request_id not in before]

    attempt = 1 + sum(1 for p in (run_dir / "board" / _safe(item.item_id)).glob("attempt-*"))
    agents = _agents(cfg, compute, components)
    boards = _boards(cfg, run_dir, item, attempt, budget, requests, components.tool_values(item),
                     [a.name for a in agents])
    unique = list({id(b): b for b in boards.values()}.values())
    flags: list[ReviewFlag] = []

    def size() -> int:
        return sum(len(b.artifacts(item.item_id)) + len(b.needs(item.item_id)) + len(b.suppressed) for b in unique)

    try:
        for _ in range(cfg.coordination_rounds):
            start = size()
            for agent in agents:
                agent.step(item, boards[agent.name], budget)
            if size() == start:   # nothing new this round: stop early
                break
    except BudgetExceeded as exc:
        flags.append(ReviewFlag(reason=ReviewReason.missing_evidence,
                                detail=f"Budget exhausted ({exc.resource}); scored what was accepted."))

    accepted = [a for b in unique for a in b.accepted_artifacts(item.item_id)]
    reqs = requests()
    flags += components.flags(item, accepted, reqs)
    for b in unique:
        for n in b.needs(item.item_id):
            if n.status != "fulfilled":
                flags.append(ReviewFlag(reason=ReviewReason.missing_evidence,
                                        detail=f"Need {n.type} from {n.from_agent} ended {n.status}.", evidence=[n.need_id]))
    cost = budget.spent.model_copy(update={"gpu_seconds": sum(r.gpu_seconds for r in reqs)})
    prediction = components.scorer(cfg).score(item, accepted, reqs, flags, cost=cost)
    if components.stubs:
        prediction = prediction.model_copy(update={
            "applicability_notes": [*prediction.applicability_notes, "STUB components: not an experiment result."]})
    return prediction


# ---------- one run ----------

def run(cfg: RunConfig, items: Sequence[Item], components: Components, runs_dir: Path = Path("runs"),
        progress: Callable[[str], None] = print) -> Path:
    run_dir = Path(runs_dir) / cfg.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    _write_config(run_dir, cfg, components, len(items))
    pred_path, cost_path = run_dir / "predictions.jsonl", run_dir / "cost.json"
    done = {json.loads(line)["item_id"] for line in _lines(pred_path)}
    costs: dict[str, Any] = json.loads(cost_path.read_text(encoding="utf-8")) if cost_path.exists() else {}
    compute = components.compute(run_dir, cfg)
    todo = [i for i in sorted(items, key=lambda i: i.item_id) if i.item_id not in done]
    for n, item in enumerate(todo, 1):
        prediction = run_item(cfg, run_dir, item, compute, components)
        _append_jsonl(pred_path, prediction.model_dump(mode="json"))
        costs[item.item_id] = prediction.cost.model_dump()
        _atomic_write(cost_path, json.dumps(costs, indent=1))
        progress(f"[{n}/{len(todo)}] {cfg.run_id} {item.item_id}: p={prediction.p_react} {prediction.category.value} "
                 f"flags={len(prediction.review_flags)} units={prediction.cost.compute_units}")
    return run_dir


def _write_config(run_dir: Path, cfg: RunConfig, components: Components, n_items: int) -> None:
    record = {"run_config": cfg.model_dump(), "stubs_used": components.stubs, "git_sha": _git_sha(),
              "llm_prices_usd_per_mtok": {k: list(v) for k, v in PRICES_USD_PER_MTOK.items()},
              "agent_order": list(AGENT_ORDER), "n_items": n_items}
    path = run_dir / "config.json"
    if path.exists():  # resuming: the run's settings must not change underneath it
        old = json.loads(path.read_text(encoding="utf-8"))
        if old["run_config"] != record["run_config"] or old["stubs_used"] != record["stubs_used"]:
            raise SystemExit(f"{path} has different settings; use a new run id instead of resuming")
        return
    _atomic_write(path, json.dumps(record, indent=2))


# ---------- helpers ----------

def _read_requests(path: Path) -> list[ComputeRequest]:
    return [ComputeRequest.model_validate_json(line) for line in _lines(path)]


def _lines(path: Path) -> list[str]:
    return [l for l in path.read_text(encoding="utf-8").splitlines() if l.strip()] if path.exists() else []


def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _safe(item_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", item_id)


def _importable(module: str) -> bool:
    import importlib.util

    try:
        return importlib.util.find_spec(module) is not None
    except ModuleNotFoundError:
        return False


def _git_sha() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10,
                              check=True).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _load_items(split: str, items_file: Path | None) -> list[Item]:
    from kiln.compute.profile import _items

    return _items(split, items_file)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m kiln.runners.conditions")
    parser.add_argument("--split", choices=["dev", "heldout"], required=True)
    parser.add_argument("--condition", choices=CONDITIONS, action="append")
    parser.add_argument("--all-conditions", action="store_true")
    parser.add_argument("--seed", type=int, action="append")
    parser.add_argument("--all-seeds", action="store_true")
    parser.add_argument("--model", required=True, help="exact model id, recorded in every run; no default")
    parser.add_argument("--items-file", type=Path, help="agent-visible items (JSON Lines) instead of the ledger")
    parser.add_argument("--limit", type=int, help="first N items in sorted order (dry runs)")
    parser.add_argument("--tier-prices", type=Path, help="JSON with a tier_prices mapping (the frozen price list)")
    parser.add_argument("--budget", type=Path, help="JSON with max_tool_calls_per_item, max_tokens_per_item, "
                                                    "max_compute_units_per_item (the frozen caps)")
    parser.add_argument("--stubs", action="store_true", help="use the stand-ins; results are marked and never "
                                                             "experiment results")
    parser.add_argument("--runs-dir", type=Path, default=Path("runs"))
    args = parser.parse_args(argv)

    conditions = list(CONDITIONS) if args.all_conditions else (args.condition or parser.error("give --condition or --all-conditions"))
    seeds = list(SEEDS) if args.all_seeds else (args.seed or parser.error("give --seed or --all-seeds"))
    components = stub_components() if args.stubs else real_components()
    items = _load_items(args.split, args.items_file)
    items = sorted(items, key=lambda i: i.item_id)[: args.limit] if args.limit else items
    extra: dict[str, Any] = {}
    if args.tier_prices:
        extra["tier_prices"] = json.loads(args.tier_prices.read_text(encoding="utf-8"))["tier_prices"]
    if args.budget:
        extra.update(json.loads(args.budget.read_text(encoding="utf-8")))
    # One seed of every condition first, so a partial night is still a valid comparison (plan R2).
    for seed in seeds:
        for condition in conditions:
            cfg = RunConfig(run_id=run_id_for(condition, args.model, seed, args.split), condition=condition,
                            seed=seed, model=args.model, **extra)
            run(cfg, items, components, args.runs_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
