"""Immutable configuration for the deterministic scoring engine.

This module defines the shape of a scoring rule set, not its contents. It holds
no weights, thresholds, category boundaries, evidence mappings, fallback values
or freeze status, and nothing here defaults to a scientific choice: every such
value is a required input. Choosing the real rule set is protocol OPEN-05.
Whether a given rule set is the frozen one is decided outside this module, by
the verifier passed to ``kiln.scoring.score.ScoringEngine``.
"""
from __future__ import annotations

import hashlib
import json
from typing import Annotated, Literal, get_args

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from kiln.schemas import AgentName, Artifact, Category, ReviewReason

# The numeric value keys listed in docs/interfaces.md ("Value keys"). The other
# documented key, decomposition_product, names a phase and is not a number.
NUMERIC_VALUE_KEYS = frozenset({
    "dE_ev_per_atom", "dE_mlip_minus_mp_ev_per_atom", "tammann_a_c", "tammann_b_c",
    "decomposes_at_c", "volatile_above_c",
})
ARTIFACT_TYPES = frozenset(get_args(Artifact.model_fields["type"].annotation))
# Reserved condition subject: the score itself rather than a feature.
P_REACT = "p_react"


def _not_blank(text: str) -> str:
    if not text.strip():
        raise ValueError("must not be blank")
    return text


Name = Annotated[str, Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")]
Text = Annotated[str, AfterValidator(_not_blank)]


class _Frozen(BaseModel):
    # Strict: no bool-as-number or string coercion. Python input needs tuples
    # and enum members; load a JSON rule file with model_validate_json.
    # model_construct() and model_copy(update=...) skip validation, so an
    # existing instance is validated again, into a new copy, whenever it is
    # passed back in; a subclass instance comes back as the base class.
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid", allow_inf_nan=False,
                              revalidate_instances="always")


class EvidenceSource(_Frozen):
    """A value key in verifier-accepted artifacts of one agent and type."""
    agent: AgentName
    artifact_type: str
    value_key: str

    @model_validator(mode="after")
    def _documented(self) -> EvidenceSource:
        if self.artifact_type not in ARTIFACT_TYPES:
            raise ValueError(f"unknown artifact type: {self.artifact_type!r}")
        if self.value_key not in NUMERIC_VALUE_KEYS:
            raise ValueError(f"not a documented numeric value key: {self.value_key!r}")
        return self


class Feature(_Frozen):
    """A number read only from verifier-accepted artifact values.

    ``sources`` are tried in order and the first with any non-null value wins.
    Several accepted artifacts for that source must agree: ``require_equal``
    compares them all, ``latest_created`` compares those with the latest
    ``created_at``. When no source has a value, ``fallback`` is used and the
    prediction gets a missing-evidence flag; ``None`` makes scoring fail.
    """
    name: Name
    sources: tuple[EvidenceSource, ...] = Field(min_length=1)
    on_multiple: Literal["require_equal", "latest_created"]
    fallback: float | None

    @model_validator(mode="after")
    def _unique_sources(self) -> Feature:
        if len(set(self.sources)) != len(self.sources):
            raise ValueError(f"feature {self.name!r} lists a source twice")
        return self


class Term(_Frozen):
    feature: Name
    weight: float


class LinearScore(_Frozen):
    """``p_react = link(intercept + sum(weight * feature))``.

    ``logistic`` is ``1 / (1 + exp(-z))``; ``clip`` is ``min(1, max(0, z))``.
    """
    intercept: float
    terms: tuple[Term, ...]
    link: Literal["logistic", "clip"]


class Condition(_Frozen):
    """``subject op threshold``, where subject is ``p_react`` or a feature name."""
    subject: Name
    op: Literal["lt", "le", "gt", "ge"]
    threshold: float


class Outcome(_Frozen):
    category: Category
    cause: Text
    fix: Text


class CategoryRule(_Frozen):
    """Applies ``outcome`` when every condition holds."""
    when: tuple[Condition, ...] = Field(min_length=1)
    outcome: Outcome


class ScoringRules(_Frozen):
    """A complete rule set. Category rules are checked in order; the first match
    wins and ``otherwise`` applies when none matches. The details of review flags
    with the listed reasons are copied to ``disagreements`` and
    ``applicability_notes``."""
    features: tuple[Feature, ...]
    p_react: LinearScore
    category_rules: tuple[CategoryRule, ...]
    otherwise: Outcome
    disagreement_flag_reasons: tuple[ReviewReason, ...]
    applicability_flag_reasons: tuple[ReviewReason, ...]

    @model_validator(mode="after")
    def _consistent(self) -> ScoringRules:
        names = [feature.name for feature in self.features]
        if len(set(names)) != len(names):
            raise ValueError("feature names must be unique")
        if P_REACT in names:
            raise ValueError(f"{P_REACT!r} is reserved and cannot name a feature")
        terms = [term.feature for term in self.p_react.terms]
        if len(set(terms)) != len(terms):
            raise ValueError("each feature may appear in at most one term")
        for name in terms:
            if name not in names:
                raise ValueError(f"term uses undefined feature {name!r}")
        for rule in self.category_rules:
            for condition in rule.when:
                if condition.subject != P_REACT and condition.subject not in names:
                    raise ValueError(f"condition uses undefined subject {condition.subject!r}")
        for field in ("disagreement_flag_reasons", "applicability_flag_reasons"):
            reasons = getattr(self, field)
            if len(set(reasons)) != len(reasons):
                raise ValueError(f"{field} lists a reason twice")
        return self

    def digest(self) -> str:
        """SHA-256 of the canonical JSON form; equal rule sets share a digest.

        The instance is validated first, so an unvalidated one (built with
        model_construct or model_copy(update=...)) raises instead of hashing.
        """
        valid = ScoringRules.model_validate(self)
        canonical = json.dumps(valid.model_dump(mode="json"), sort_keys=True,
                               separators=(",", ":"), ensure_ascii=True, allow_nan=False)
        return hashlib.sha256(canonical.encode("ascii")).hexdigest()
