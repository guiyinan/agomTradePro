"""Reject altered PIT chronology and unsafe research-evidence publication."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from apps.research.domain.scenario_probability_contracts import ResearchEvidenceStatus
from apps.research.domain.scenario_research_evidence import (
    assess_historical_analogy,
    assess_scenario_path_evidence,
)
from tests.unit.research.test_scenario_research_evidence import (
    NOW,
    _analogy_study,
    _candidate,
    _path_study,
    _policy,
    _scope,
)


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("allowed_release_lag", timedelta(days=-1), "cannot be negative"),
        ("allowed_release_lag", timedelta(0), "exceeds allowed release lag"),
        ("features", (), "requires PIT features"),
        ("content_hash", "f" * 64, "content_hash mismatch"),
    ],
)
def test_analogy_candidate_rejects_invalid_frozen_inputs(
    field: str, value: object, reason: str
) -> None:
    candidate = _candidate("historical-window", year=2020)
    with pytest.raises(ValueError, match=reason):
        replace(candidate, **{field: value})


def test_analogy_candidate_enforces_window_and_exact_feature_membership() -> None:
    candidate = _candidate("historical-window", year=2020)
    with pytest.raises(ValueError, match="window_end must follow"):
        replace(candidate, window_end=candidate.window_start)
    with pytest.raises(ValueError, match="cutoff cannot precede"):
        replace(candidate, decision_cutoff=candidate.window_start)
    with pytest.raises(ValueError, match="duplicate features"):
        replace(candidate, features=candidate.features * 2)
    with pytest.raises(ValueError, match="exactly cover candidate features"):
        replace(candidate, features=(replace(candidate.features[0], feature_key="other"),))


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("valid_until", NOW - timedelta(days=1), "valid_until must follow"),
        ("generated_at", NOW - timedelta(days=2), "query manifest cannot be future"),
        ("feature_definition_version", "unbound.v2", "feature version mismatch"),
        ("research_only", False, "must remain research-only"),
        ("must_not_use_for_decision", False, "must remain research-only"),
        ("content_hash", "f" * 64, "content_hash mismatch"),
    ],
)
def test_analogy_study_rejects_unsafe_or_substituted_projection(
    field: str, value: object, reason: str
) -> None:
    with pytest.raises(ValueError, match=reason):
        replace(_analogy_study(), **{field: value})


def test_analogy_study_rejects_duplicate_and_nonhistorical_candidates() -> None:
    study = _analogy_study()
    with pytest.raises(ValueError, match="duplicate candidates"):
        replace(study, candidates=(study.candidates[0],) * 2)
    with pytest.raises(ValueError, match="must predate query"):
        replace(study, query_manifest=study.candidates[0].pit_manifest)


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("scenario_revision_ids", (), "unique scenario revisions"),
        ("generated_at", NOW - timedelta(days=3), "PIT manifest cannot be future"),
        ("valid_until", NOW - timedelta(days=1), "valid_until must follow"),
        ("shocks", (), "at least one period shock"),
        ("research_only", False, "must remain research-only"),
        ("must_not_use_for_decision", False, "must remain research-only"),
        ("content_hash", "f" * 64, "content_hash mismatch"),
    ],
)
def test_path_study_rejects_missing_scope_and_unsafe_publication(
    field: str, value: object, reason: str
) -> None:
    with pytest.raises(ValueError, match=reason):
        replace(_path_study(), **{field: value})


def test_path_shock_and_probability_evidence_require_positive_periods() -> None:
    study = _path_study()
    for invalid in (0, True):
        with pytest.raises(ValueError, match="period_index must be a positive integer"):
            replace(study.shocks[0], period_index=invalid)
        with pytest.raises(ValueError, match="conditional period_index must be positive"):
            replace(study.conditional_probabilities[0], period_index=invalid)
        with pytest.raises(ValueError, match="horizon_periods must be positive"):
            replace(study.transition_probabilities[0], horizon_periods=invalid)
    with pytest.raises(ValueError, match="period_end must follow"):
        replace(study.shocks[0], period_end=study.shocks[0].period_start)
    with pytest.raises(ValueError, match="contiguous period indices"):
        replace(study, shocks=(replace(study.shocks[0], period_index=3),))
    with pytest.raises(ValueError, match="shock horizon does not match"):
        replace(study, shocks=(study.shocks[0],))
    overlapping = replace(study.shocks[1], period_start=study.shocks[0].period_start)
    with pytest.raises(ValueError, match="periods cannot overlap"):
        replace(study, shocks=(study.shocks[0], overlapping))


@pytest.mark.parametrize("path", [False, True], ids=["analogy", "path"])
def test_inactive_policy_remains_blocked_when_evidence_is_missing(path: bool) -> None:
    evaluator = assess_scenario_path_evidence if path else assess_historical_analogy
    assessment = evaluator(
        scope=_scope(),
        policy=_policy(),
        evidence=None,
        evaluated_at=NOW + timedelta(days=31),
    )
    assert assessment.status is ResearchEvidenceStatus.BLOCKED
    assert {item.reason_code for item in assessment.blockers} == {
        "scenario_research.policy.inactive",
        "scenario_path.evidence.missing" if path else "historical_analogy.evidence.missing",
    }
    assert assessment.evidence_hash is None
    assert assessment.research_only and assessment.must_not_use_for_decision


@pytest.mark.parametrize("path", [False, True], ids=["analogy", "path"])
def test_assessment_rejects_relabeling_missing_evidence_as_available(path: bool) -> None:
    evaluator = assess_scenario_path_evidence if path else assess_historical_analogy
    missing = evaluator(scope=_scope(), policy=_policy(), evidence=None, evaluated_at=NOW)
    assert missing.status is ResearchEvidenceStatus.INSUFFICIENT_EVIDENCE
    with pytest.raises(ValueError, match="available .* requires unblocked evidence"):
        replace(missing, status=ResearchEvidenceStatus.AVAILABLE)
    with pytest.raises(ValueError, match="unavailable .* requires blockers"):
        replace(missing, blockers=())
    with pytest.raises(ValueError, match="must remain research-only"):
        replace(missing, research_only=False)
    with pytest.raises(ValueError, match="content_hash mismatch"):
        replace(missing, content_hash="f" * 64)


def test_analogy_assessment_never_publishes_probability_or_negative_count() -> None:
    assessment = assess_historical_analogy(
        scope=_scope(), policy=_policy(), evidence=_analogy_study(), evaluated_at=NOW
    )
    assert assessment.status is ResearchEvidenceStatus.AVAILABLE
    assert assessment.probability_estimate is None
    with pytest.raises(ValueError, match="cannot publish a probability"):
        replace(assessment, probability_estimate=Decimal("0.8"))
    with pytest.raises(ValueError, match="candidate_count cannot be negative"):
        replace(assessment, candidate_count=-1)
