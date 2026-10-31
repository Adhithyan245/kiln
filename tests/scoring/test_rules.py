"""Rule-set configuration tests. Every number and text here is an arbitrary
synthetic value chosen to exercise the code, not a proposed scoring rule."""
import pytest
from pydantic import ValidationError

from kiln.schemas import Category, ReviewReason
from kiln.scoring.rules import (
    CategoryRule,
    Condition,
    EvidenceSource,
    Feature,
    LinearScore,
    Outcome,
    ScoringRules,
    Term,
)

SOURCE = EvidenceSource(agent="thermo", artifact_type="reaction_report", value_key="dE_ev_per_atom")
OUTCOME = Outcome(category=Category.unreacted, cause="synthetic cause", fix="synthetic fix")


def feature(name="x", **overrides):
    fields = {"name": name, "sources": (SOURCE,), "on_multiple": "require_equal", "fallback": None}
    return Feature(**(fields | overrides))


def rules(**overrides):
    fields = {
        "features": (feature(),),
        "p_react": LinearScore(intercept=0.0, terms=(Term(feature="x", weight=1.0),), link="logistic"),
        "category_rules": (CategoryRule(when=(Condition(subject="p_react", op="ge", threshold=0.5),),
                                        outcome=OUTCOME),),
        "otherwise": OUTCOME,
        "disagreement_flag_reasons": (ReviewReason.conflict,),
        "applicability_flag_reasons": (),
    }
    return ScoringRules(**(fields | overrides))


@pytest.mark.parametrize("model", [EvidenceSource, Feature, Term, LinearScore, Condition, Outcome,
                                   CategoryRule, ScoringRules])
def test_every_field_is_required(model):
    # No weight, threshold, mapping, fallback or outcome has a built-in default.
    assert all(field.is_required() for field in model.model_fields.values())


def test_rules_are_immutable_and_reject_unknown_fields():
    built = rules()
    with pytest.raises(ValidationError):
        built.otherwise = OUTCOME
    with pytest.raises(ValidationError):
        built.p_react.terms[0].weight = 2.0
    with pytest.raises(ValidationError, match="Extra inputs"):
        Term(feature="x", weight=1.0, note="x")


@pytest.mark.parametrize("weight", [float("nan"), float("inf"), True, "1.0"])
def test_numbers_must_be_finite_real_numbers(weight):
    with pytest.raises(ValidationError):
        Term(feature="x", weight=weight)


def test_source_must_be_a_documented_numeric_key_and_known_type():
    with pytest.raises(ValidationError, match="numeric value key"):
        EvidenceSource(agent="thermo", artifact_type="reaction_report", value_key="dE")
    with pytest.raises(ValidationError, match="numeric value key"):
        EvidenceSource(agent="precursor", artifact_type="precursor_report", value_key="decomposition_product")
    with pytest.raises(ValidationError, match="artifact type"):
        EvidenceSource(agent="thermo", artifact_type="report", value_key="dE_ev_per_atom")
    with pytest.raises(ValidationError):
        EvidenceSource(agent="oracle", artifact_type="reaction_report", value_key="dE_ev_per_atom")


def test_feature_needs_unique_sources_and_valid_name():
    with pytest.raises(ValidationError):
        feature(sources=())
    with pytest.raises(ValidationError, match="twice"):
        feature(sources=(SOURCE, SOURCE))
    with pytest.raises(ValidationError):
        feature(name="not a name")


def test_text_and_conditions_cannot_be_empty():
    with pytest.raises(ValidationError, match="blank"):
        Outcome(category=Category.unreacted, cause=" ", fix="synthetic fix")
    with pytest.raises(ValidationError):
        CategoryRule(when=(), outcome=OUTCOME)


def test_references_must_resolve():
    with pytest.raises(ValidationError, match="unique"):
        rules(features=(feature(), feature()))
    with pytest.raises(ValidationError, match="reserved"):
        rules(features=(feature(), feature("p_react")))
    with pytest.raises(ValidationError, match="undefined feature"):
        rules(p_react=LinearScore(intercept=0.0, terms=(Term(feature="y", weight=1.0),), link="clip"))
    with pytest.raises(ValidationError, match="at most one term"):
        rules(p_react=LinearScore(intercept=0.0, terms=(Term(feature="x", weight=1.0),) * 2, link="clip"))
    with pytest.raises(ValidationError, match="undefined subject"):
        rules(category_rules=(CategoryRule(when=(Condition(subject="y", op="lt", threshold=0.0),),
                                           outcome=OUTCOME),))
    with pytest.raises(ValidationError, match="twice"):
        rules(applicability_flag_reasons=(ReviewReason.conflict, ReviewReason.conflict))


def test_digest_identifies_the_rule_set():
    built = rules()
    assert len(built.digest()) == 64
    assert rules().digest() == built.digest()
    assert ScoringRules.model_validate_json(built.model_dump_json()).digest() == built.digest()
    # 1 and 1.0 are the same configured number.
    integer = rules(p_react=LinearScore(intercept=0, terms=(Term(feature="x", weight=1),), link="logistic"))
    assert integer.digest() == built.digest()
    changed = [
        rules(p_react=LinearScore(intercept=0.0, terms=(Term(feature="x", weight=1.5),), link="logistic")),
        rules(p_react=LinearScore(intercept=0.0, terms=(Term(feature="x", weight=1.0),), link="clip")),
        rules(features=(feature(fallback=0.0),)),
        rules(otherwise=Outcome(category=Category.unreacted, cause="other", fix="synthetic fix")),
        rules(disagreement_flag_reasons=()),
    ]
    assert len({other.digest() for other in changed} | {built.digest()}) == len(changed) + 1


def test_digest_refuses_an_unvalidated_instance():
    # model_copy(update=...) and model_construct() skip validation.
    built = rules()
    for bad in (built.model_copy(update={"otherwise": "not an outcome"}),
                built.model_copy(update={"features": [feature()]}),
                built.model_copy(update={"p_react": built.p_react.model_copy(update={"link": "probit"})}),
                ScoringRules.model_construct(features=built.features)):
        with pytest.raises(ValidationError):
            bad.digest()


def test_unvalidated_parts_are_validated_again_when_nested():
    with pytest.raises(ValidationError, match="finite"):
        LinearScore(intercept=0.0, terms=(Term.model_construct(feature="x", weight=float("nan")),), link="logistic")
    with pytest.raises(ValidationError, match="blank"):
        rules(otherwise=Outcome.model_construct(category=Category.unreacted, cause=" ", fix="synthetic fix"))
