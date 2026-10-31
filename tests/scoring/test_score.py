"""Synthetic evidence tests; no experimental outcomes are used."""
import pytest

from kiln.schemas import Artifact, ComputeRequest, Item, ReviewFlag, VerifierStatus
from kiln.scoring.score import ScoringConfigurationError, provisional, score


@pytest.fixture
def item():
    return Item(item_id="synthetic", source="alab_demo", precursor_a="A", precursor_b="B", temperature_c=500, split="dev")


@pytest.fixture
def artifact(item):
    return Artifact(artifact_id="run:thermo:1", run_id="run", item_id=item.item_id,
                    agent="thermo", type="reaction_report", values={"dE_ev_per_atom": -0.1},
                    verifier=VerifierStatus.accepted)


def test_both_entry_points_fail_closed_without_frozen_rules(item, artifact):
    # Round-trip synthetic input through the shared schema before scoring.
    accepted = [Artifact.model_validate_json(artifact.model_dump_json())]
    flags = [ReviewFlag(reason="missing_evidence", detail="synthetic missing input")]
    with pytest.raises(ScoringConfigurationError, match="frozen rules"):
        provisional(item, accepted)
    with pytest.raises(ScoringConfigurationError, match="run context"):
        score(item, accepted, [], flags)


@pytest.mark.parametrize("status", [VerifierStatus.pending, VerifierStatus.rejected, VerifierStatus.inconclusive])
def test_rejects_unaccepted_artifacts(item, artifact, status):
    artifact.verifier = status
    with pytest.raises(ValueError, match="not verifier-accepted"):
        provisional(item, [artifact])


def test_rejects_wrong_item_and_duplicate_artifacts(item, artifact):
    with pytest.raises(ValueError, match="duplicate artifact"):
        score(item, [artifact, artifact], [], [])
    artifact.item_id = "other"
    with pytest.raises(ValueError, match="another item"):
        provisional(item, [artifact])


def test_rejects_wrong_item_and_duplicate_requests(item):
    request = ComputeRequest(request_id="r", run_id="run", item_id="other", agent="thermo",
                             tier="cached_lookup", reason="synthetic", inputs={}, settings={}, cache_key="key")
    with pytest.raises(ValueError, match="another item"):
        score(item, [], [request], [])
    request.item_id = item.item_id
    with pytest.raises(ValueError, match="duplicate request"):
        score(item, [], [request, request], [])
