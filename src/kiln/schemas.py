"""Shared data models for Kiln. Every module imports from here.

Change this file only after telling the team, and update docs/interfaces.md in the same commit.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


def now() -> datetime:
    return datetime.now(timezone.utc)


# ---------- Inputs ----------

class Item(BaseModel):
    """One precursor pair at one furnace condition. Agents may see this and nothing else about the experiment."""
    item_id: str                       # e.g. "PG-0123" (Precursor Genome) or "AL-CaTiO3-a+b" (A-Lab demo)
    source: Literal["precursor_genome", "alab_demo"]
    precursor_a: str                   # reduced formula, e.g. "Li2CO3"
    precursor_b: str
    temperature_c: float               # furnace setpoint, °C
    dwell_h: float | None = None
    melting_point_a_c: float | None = None
    melting_point_b_c: float | None = None
    split: Literal["dev", "heldout"]


class Category(str, Enum):
    unreacted = "unreacted"
    transformed = "transformed"        # a precursor changed on its own but didn't react with the other
    partially_reacted = "partially_reacted"
    completely_reacted = "completely_reacted"


class Label(BaseModel):
    """LOCKED. Lives only in labels/. Only src/kiln/scoring/evaluate.py may load it."""
    item_id: str
    category: Category
    reacted: bool                      # partially or completely reacted


# ---------- Need board ----------

AgentName = Literal["thermo", "kinetics", "precursor", "single", "planner"]

NeedType = Literal[
    "firm_up_energy",          # Kinetics -> Thermo: a borderline driving force needs better evidence
    "decomposition_products",  # Thermo/Kinetics -> Precursor: what a precursor becomes at T
    "reaction_energy",         # Precursor/Kinetics -> Thermo: recompute a reaction with given species
]


class Claim(BaseModel):
    cause: str                         # e.g. "kinetically_limited", "no_driving_force", "decomposes_only", "volatile"
    statement: str                     # one plain-language sentence
    evidence: list[str]                # artifact ids and/or "values.<key>" references
    falsified_if: str                  # required: the result that would prove this wrong


class Cost(BaseModel):
    tool_calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    compute_units: float = 0.0         # charged at the frozen tier price, even on cache hits
    gpu_seconds: float = 0.0           # measured, for reporting only
    usd: float = 0.0                   # experiment API spend (Gemini), tracked per item


# ---------- Compute service ----------

class ComputeTier(str, Enum):
    cached_lookup = "cached_lookup"                    # Materials Project energies/stability for a chemical system
    single_point = "single_point"                      # one ALCHEMI (MACE) energy for a given structure
    bounded_relaxation = "bounded_relaxation"          # variable-cell relaxation, force + stress criteria, step cap
    decomposition_reeval = "decomposition_reeval"      # reaction energy recomputed with decomposition products


class ComputeStatus(str, Enum):
    ok = "ok"
    cached = "cached"                  # served from cache, still charged
    not_converged = "not_converged"    # raises a review flag
    failed = "failed"                  # raises a review flag


class ComputeRequest(BaseModel):
    """One logged request to the compute service. Written to runs/<run_id>/compute_requests.jsonl."""
    request_id: str                    # "<run_id>:compute:<seq>"
    run_id: str
    item_id: str
    agent: AgentName
    tier: ComputeTier
    reason: str                        # one sentence: why this evidence is worth its cost
    inputs: dict[str, Any]             # formula(s), structure ids, species
    settings: dict[str, Any]           # model, fmax, stress tolerance, max steps, etc.
    cache_key: str                     # hash of (tier, inputs, settings)
    status: ComputeStatus = ComputeStatus.ok
    result: dict[str, float | str | bool | None] = Field(default_factory=dict)
    compute_units: float = 0.0
    gpu_seconds: float = 0.0
    p_react_before: float | None = None   # provisional score from the fixed scoring functions
    p_react_after: float | None = None
    category_before: str | None = None
    category_after: str | None = None
    changed_prediction: bool | None = None
    moved_toward_label: bool | None = None  # filled ONLY after unblinding, by the evaluator
    created_at: datetime = Field(default_factory=now)


class VerifierStatus(str, Enum):
    pending = "pending"
    accepted = "accepted"
    rejected = "rejected"
    inconclusive = "inconclusive"


class Artifact(BaseModel):
    artifact_id: str                   # "<run_id>:<agent>:<seq>"
    run_id: str
    item_id: str
    agent: AgentName
    type: Literal["reaction_report", "kinetics_report", "precursor_report"]
    values: dict[str, float | str | bool | None]   # numbers carry units in the key, e.g. "dE_ev_per_atom", "tammann_a_c"
    claims: list[Claim] = Field(default_factory=list)
    cites: list[str] = Field(default_factory=list) # artifact ids this one depends on
    fulfills_need: str | None = None
    compute_requests: list[str] = Field(default_factory=list)  # request ids this artifact used
    rationale: str = ""                # LLM's explanation of what it chose to compute (no numbers decided here)
    cost: Cost = Field(default_factory=Cost)
    created_at: datetime = Field(default_factory=now)
    verifier: VerifierStatus = VerifierStatus.pending
    verifier_notes: str = ""


class Need(BaseModel):
    need_id: str                       # "<run_id>:need:<seq>"
    run_id: str
    item_id: str
    type: NeedType
    from_agent: AgentName
    payload: dict[str, Any]            # e.g. {"formula": "Li2TiO3"} or {"species": ["Li2O", "TiO2"]}
    status: Literal["open", "claimed", "fulfilled", "declined"] = "open"
    claimed_by: AgentName | None = None
    fulfilled_by: str | None = None    # artifact_id
    created_at: datetime = Field(default_factory=now)


# ---------- Review flags ----------

class ReviewReason(str, Enum):
    missing_evidence = "missing_evidence"          # budget ran out before a key check, or a property is unknown
    failed_computation = "failed_computation"      # non-converged or errored request
    conflict = "conflict"                          # specialists disagree, or MLIP vs Materials Project beyond threshold
    outside_applicability = "outside_applicability"


class ReviewFlag(BaseModel):
    reason: ReviewReason
    detail: str
    evidence: list[str] = Field(default_factory=list)


# ---------- Outputs ----------

ConditionId = Literal["B0", "B0-T", "B1", "C1", "C2", "C3", "C4", "N1", "N2"]
# C3 (central planner) is a core comparator, not optional.


class Prediction(BaseModel):
    """Produced only by src/kiln/scoring/score.py from verifier-accepted artifacts."""
    run_id: str
    condition: ConditionId
    seed: int
    item_id: str
    p_react: float                     # single score used for AUROC
    category: Category
    cause: str
    fix: str
    evidence: list[str]                # accepted artifact ids used
    compute_requests: list[str] = Field(default_factory=list)
    disagreements: list[str] = Field(default_factory=list)   # plain-language specialist disagreements
    needs_review: bool = False
    review_flags: list[ReviewFlag] = Field(default_factory=list)
    applicability_notes: list[str] = Field(default_factory=list)
    cost: Cost


class RunConfig(BaseModel):
    run_id: str
    condition: ConditionId
    seed: int
    model: str                         # e.g. "gemini-flash" or the Claude model id used
    max_tool_calls_per_item: int = 12
    max_tokens_per_item: int = 40000
    max_compute_units_per_item: float = 10.0   # the ONE primary locked budget; final value set from profiling
    tier_prices: dict[str, float] = Field(default_factory=dict)  # frozen in the protocol at code freeze
    coordination_rounds: int = 3
