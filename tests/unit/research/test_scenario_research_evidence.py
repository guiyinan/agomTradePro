"""Unit coverage for PIT analogy, path evidence, and review intents in R7."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

import pytest

from apps.research.domain.scenario_probability_contracts import (
    ResearchEvidenceStatus,
    ScenarioProbabilityResearchPolicy,
    ScenarioResearchScope,
)
from apps.research.domain.scenario_research_evidence import (
    ConditionalProbabilityEvidence,
    HistoricalAnalogyCandidateEvidence,
    HistoricalAnalogyStudyEvidence,
    MultiPeriodShockEvidence,
    PointInTimeFeatureValue,
    PointInTimeManifestFeature,
    PointInTimeManifestReference,
    ScenarioPathStudyEvidence,
    TransitionProbabilityEvidence,
    assess_historical_analogy,
    assess_scenario_path_evidence,
)
from apps.research.domain.scenario_review_intent import build_review_reminder_intent
from tests.unit.research.scenario_review_reminder_factories import make_observation

NOW = datetime(2026, 8, 5, 12, tzinfo=UTC)
SET_REVISION = UUID("00000000-0000-0000-0000-000000000100")
REVISION_A = UUID("00000000-0000-0000-0000-000000000001")
REVISION_B = UUID("00000000-0000-0000-0000-000000000002")


def _scope() -> ScenarioResearchScope:
    return ScenarioResearchScope.create(
        scope_version="scenario-scope.v1",
        scenario_set_revision_id=SET_REVISION,
        scenario_revision_ids=(REVISION_A, REVISION_B),
        forecast_horizon=timedelta(days=1),
        censoring_rule_version="scenario-censoring.v1",
        path_horizon_periods=2,
        path_initial_state_revision_ids=(REVISION_A, REVISION_B),
    )


def _policy() -> ScenarioProbabilityResearchPolicy:
    return ScenarioProbabilityResearchPolicy.create(
        policy_version="scenario-calibration-policy.v1",
        activated_at=NOW - timedelta(days=30),
        valid_until=NOW + timedelta(days=30),
        sample_window_start=NOW - timedelta(days=365),
        sample_window_end=NOW,
        forecast_horizon=timedelta(days=1),
        censoring_lag=timedelta(days=7),
        censoring_rule_version="scenario-censoring.v1",
        minimum_forecasts_per_revision=2,
        minimum_resolved_outcomes_per_revision=2,
        minimum_outcome_coverage=Decimal("0.80"),
        minimum_binary_class_observations=1,
        minimum_multiclass_groups=2,
        minimum_multiclass_class_observations=1,
        maximum_outcome_evidence_age=timedelta(days=365),
        calibration_bin_edges=(Decimal("0"), Decimal("0.5"), Decimal("1")),
        probability_sum_tolerance=Decimal("0.000001"),
        minimum_historical_analogies=2,
        minimum_path_probability_observations=10,
        path_horizon_periods=2,
        require_all_path_initial_states=True,
        maximum_research_evidence_age=timedelta(days=90),
        invalidation_review_delay=timedelta(days=2),
        approved_by="research-owner",
    )


def _manifest(
    *,
    manifest_id: str,
    as_of: datetime,
    digest_character: str,
    features: tuple[PointInTimeManifestFeature, ...] = (),
) -> PointInTimeManifestReference:
    return PointInTimeManifestReference.create(
        manifest_id=manifest_id,
        manifest_version="pit-manifest.v1",
        as_of=as_of,
        manifest_hash=digest_character * 64,
        features=features,
    )


def _candidate(candidate_id: str, *, year: int) -> HistoricalAnalogyCandidateEvidence:
    as_of = datetime(year, 1, 31, tzinfo=UTC)
    available_at = datetime(year, 1, 20, tzinfo=UTC)
    vintage_at = datetime(year, 1, 21, tzinfo=UTC)
    return HistoricalAnalogyCandidateEvidence.create(
        candidate_id=candidate_id,
        candidate_version="historical-candidate.v1",
        window_start=datetime(year, 1, 1, tzinfo=UTC),
        window_end=datetime(year, 1, 30, tzinfo=UTC),
        decision_cutoff=as_of,
        allowed_release_lag=timedelta(days=1),
        pit_manifest=_manifest(
            manifest_id=f"pit-{candidate_id}",
            as_of=as_of,
            digest_character="a" if year == 2020 else "b",
            features=(
                PointInTimeManifestFeature(
                    feature_key="growth_zscore",
                    source_version="macro-vintage.v1",
                    available_at=available_at,
                    vintage_at=vintage_at,
                    content_hash=("1" if year == 2020 else "2") * 64,
                ),
            ),
        ),
        feature_definition_version="analogy-features.v1",
        features=(
            PointInTimeFeatureValue(
                feature_key="growth_zscore",
                value=Decimal("-1.2"),
                unit="zscore",
                source_version="macro-vintage.v1",
                available_at=available_at,
                vintage_at=vintage_at,
            ),
        ),
        similarity_score=Decimal("0.82"),
        evidence_refs=(f"pit://{candidate_id}",),
    )


def _analogy_study() -> HistoricalAnalogyStudyEvidence:
    return HistoricalAnalogyStudyEvidence.create(
        study_version="historical-analogy-study.v1",
        scope=_scope(),
        query_manifest=_manifest(
            manifest_id="pit-query",
            as_of=NOW - timedelta(days=1),
            digest_character="c",
        ),
        feature_definition_version="analogy-features.v1",
        candidates=(
            _candidate("covid-window", year=2020),
            _candidate("tightening-window", year=2022),
        ),
        generated_at=NOW - timedelta(hours=1),
        valid_until=NOW + timedelta(days=10),
        evidence_refs=("research://analogy-run-v1",),
    )


def _path_study(
    *,
    observation_count: int = 20,
    valid_until: datetime | None = None,
) -> ScenarioPathStudyEvidence:
    return ScenarioPathStudyEvidence.create(
        study_version="scenario-path-study.v1",
        scope=_scope(),
        pit_manifest=_manifest(
            manifest_id="pit-path",
            as_of=NOW - timedelta(days=2),
            digest_character="d",
        ),
        shocks=(
            MultiPeriodShockEvidence(
                period_index=1,
                scenario_revision_id=REVISION_A,
                period_start=NOW - timedelta(days=10),
                period_end=NOW - timedelta(days=9),
                shock_key="growth",
                magnitude=Decimal("-0.5"),
                unit="zscore",
                source_version="shock-spec.v1",
            ),
            MultiPeriodShockEvidence(
                period_index=2,
                scenario_revision_id=REVISION_B,
                period_start=NOW - timedelta(days=8),
                period_end=NOW - timedelta(days=7),
                shock_key="inflation",
                magnitude=Decimal("0.7"),
                unit="zscore",
                source_version="shock-spec.v1",
            ),
        ),
        conditional_probabilities=(
            ConditionalProbabilityEvidence(
                condition_key="growth_down",
                target_scenario_revision_id=REVISION_A,
                probability=Decimal("0.60"),
                observation_count=observation_count,
                source_version="path-study.v1",
                sample_definition_version="path-sample.v1",
                pit_manifest_id="pit-path",
                pit_manifest_version="pit-manifest.v1",
                pit_manifest_hash="d" * 64,
                period_index=1,
            ),
            ConditionalProbabilityEvidence(
                condition_key="growth_down",
                target_scenario_revision_id=REVISION_B,
                probability=Decimal("0.40"),
                observation_count=observation_count,
                source_version="path-study.v1",
                sample_definition_version="path-sample.v1",
                pit_manifest_id="pit-path",
                pit_manifest_version="pit-manifest.v1",
                pit_manifest_hash="d" * 64,
                period_index=1,
            ),
            ConditionalProbabilityEvidence(
                condition_key="growth_down",
                target_scenario_revision_id=REVISION_A,
                probability=Decimal("0.60"),
                observation_count=observation_count,
                source_version="path-study.v1",
                sample_definition_version="path-sample.v1",
                pit_manifest_id="pit-path",
                pit_manifest_version="pit-manifest.v1",
                pit_manifest_hash="d" * 64,
                period_index=2,
            ),
            ConditionalProbabilityEvidence(
                condition_key="growth_down",
                target_scenario_revision_id=REVISION_B,
                probability=Decimal("0.40"),
                observation_count=observation_count,
                source_version="path-study.v1",
                sample_definition_version="path-sample.v1",
                pit_manifest_id="pit-path",
                pit_manifest_version="pit-manifest.v1",
                pit_manifest_hash="d" * 64,
                period_index=2,
            ),
        ),
        transition_probabilities=(
            TransitionProbabilityEvidence(
                REVISION_A,
                REVISION_A,
                1,
                Decimal("0.70"),
                observation_count,
                "path-study.v1",
                "path-sample.v1",
                "pit-path",
                "pit-manifest.v1",
                "d" * 64,
            ),
            TransitionProbabilityEvidence(
                REVISION_A,
                REVISION_B,
                1,
                Decimal("0.30"),
                observation_count,
                "path-study.v1",
                "path-sample.v1",
                "pit-path",
                "pit-manifest.v1",
                "d" * 64,
            ),
            TransitionProbabilityEvidence(
                REVISION_B,
                REVISION_A,
                1,
                Decimal("0.40"),
                observation_count,
                "path-study.v1",
                "path-sample.v1",
                "pit-path",
                "pit-manifest.v1",
                "d" * 64,
            ),
            TransitionProbabilityEvidence(
                REVISION_B,
                REVISION_B,
                1,
                Decimal("0.60"),
                observation_count,
                "path-study.v1",
                "path-sample.v1",
                "pit-path",
                "pit-manifest.v1",
                "d" * 64,
            ),
            TransitionProbabilityEvidence(
                REVISION_A,
                REVISION_A,
                2,
                Decimal("0.70"),
                observation_count,
                "path-study.v1",
                "path-sample.v1",
                "pit-path",
                "pit-manifest.v1",
                "d" * 64,
            ),
            TransitionProbabilityEvidence(
                REVISION_A,
                REVISION_B,
                2,
                Decimal("0.30"),
                observation_count,
                "path-study.v1",
                "path-sample.v1",
                "pit-path",
                "pit-manifest.v1",
                "d" * 64,
            ),
            TransitionProbabilityEvidence(
                REVISION_B,
                REVISION_A,
                2,
                Decimal("0.40"),
                observation_count,
                "path-study.v1",
                "path-sample.v1",
                "pit-path",
                "pit-manifest.v1",
                "d" * 64,
            ),
            TransitionProbabilityEvidence(
                REVISION_B,
                REVISION_B,
                2,
                Decimal("0.60"),
                observation_count,
                "path-study.v1",
                "path-sample.v1",
                "pit-path",
                "pit-manifest.v1",
                "d" * 64,
            ),
        ),
        generated_at=NOW - timedelta(hours=2),
        valid_until=valid_until or NOW + timedelta(days=10),
        evidence_refs=("research://path-run-v1",),
        probability_sum_tolerance=Decimal("0.000001"),
    )


def test_historical_analogy_requires_each_candidates_own_pit_manifest() -> None:
    assessment = assess_historical_analogy(
        scope=_scope(),
        policy=_policy(),
        evidence=_analogy_study(),
        evaluated_at=NOW,
    )

    assert assessment.status is ResearchEvidenceStatus.AVAILABLE
    assert assessment.candidate_count == 2
    assert assessment.probability_estimate is None
    assert assessment.research_only is True
    assert len(assessment.content_hash) == 64


def test_historical_analogy_rejects_late_manifest_backfill() -> None:
    manifest = _manifest(
        manifest_id="pit-history",
        as_of=datetime(2020, 1, 31, tzinfo=UTC),
        digest_character="e",
    )
    with pytest.raises(ValueError, match="exact decision cutoff"):
        HistoricalAnalogyCandidateEvidence.create(
            candidate_id="lookahead",
            candidate_version="historical-candidate.v1",
            window_start=datetime(2020, 1, 1, tzinfo=UTC),
            window_end=datetime(2020, 1, 30, tzinfo=UTC),
            decision_cutoff=datetime(2020, 1, 30, tzinfo=UTC),
            allowed_release_lag=timedelta(0),
            pit_manifest=manifest,
            feature_definition_version="analogy-features.v1",
            features=(
                PointInTimeFeatureValue(
                    feature_key="growth_zscore",
                    value=Decimal("-1"),
                    unit="zscore",
                    source_version="current-revision",
                    available_at=datetime(2020, 1, 30, tzinfo=UTC),
                    vintage_at=datetime(2020, 1, 30, tzinfo=UTC),
                ),
            ),
            similarity_score=Decimal("0.8"),
            evidence_refs=("pit://lookahead",),
        )


def test_historical_analogy_rejects_manifest_vintage_mismatch() -> None:
    cutoff = datetime(2020, 1, 31, tzinfo=UTC)
    manifest = _manifest(
        manifest_id="pit-history-exact",
        as_of=cutoff,
        digest_character="e",
        features=(
            PointInTimeManifestFeature(
                "growth_zscore",
                "macro-vintage.v1",
                datetime(2020, 1, 20, tzinfo=UTC),
                datetime(2020, 1, 21, tzinfo=UTC),
                "e" * 64,
            ),
        ),
    )
    with pytest.raises(ValueError, match="does not match its PIT manifest entry"):
        HistoricalAnalogyCandidateEvidence.create(
            candidate_id="vintage-mismatch",
            candidate_version="historical-candidate.v1",
            window_start=datetime(2020, 1, 1, tzinfo=UTC),
            window_end=datetime(2020, 1, 30, tzinfo=UTC),
            decision_cutoff=cutoff,
            allowed_release_lag=timedelta(days=1),
            pit_manifest=manifest,
            feature_definition_version="analogy-features.v1",
            features=(
                PointInTimeFeatureValue(
                    "growth_zscore",
                    Decimal("-1"),
                    "zscore",
                    "macro-vintage.v1",
                    datetime(2020, 1, 20, tzinfo=UTC),
                    datetime(2020, 1, 22, tzinfo=UTC),
                ),
            ),
            similarity_score=Decimal("0.8"),
            evidence_refs=("pit://vintage-mismatch",),
        )


def test_missing_or_expired_analogy_evidence_fails_closed() -> None:
    missing = assess_historical_analogy(
        scope=_scope(),
        policy=_policy(),
        evidence=None,
        evaluated_at=NOW,
    )
    assert missing.status is ResearchEvidenceStatus.INSUFFICIENT_EVIDENCE
    assert missing.probability_estimate is None

    expired_study = HistoricalAnalogyStudyEvidence.create(
        study_version="historical-analogy-study.v1",
        scope=_scope(),
        query_manifest=_manifest(
            manifest_id="pit-old-query",
            as_of=NOW - timedelta(days=100),
            digest_character="f",
        ),
        feature_definition_version="analogy-features.v1",
        candidates=(
            _candidate("covid-window", year=2020),
            _candidate("tightening-window", year=2022),
        ),
        generated_at=NOW - timedelta(days=95),
        valid_until=NOW - timedelta(days=1),
        evidence_refs=("research://expired-analogy",),
    )
    expired = assess_historical_analogy(
        scope=_scope(),
        policy=_policy(),
        evidence=expired_study,
        evaluated_at=NOW,
    )
    assert expired.status is ResearchEvidenceStatus.BLOCKED
    assert any("expired" in blocker.reason_code for blocker in expired.blockers)


def test_path_and_transition_probabilities_remain_research_only_evidence() -> None:
    evidence = _path_study()
    assessment = assess_scenario_path_evidence(
        scope=_scope(),
        policy=_policy(),
        evidence=evidence,
        evaluated_at=NOW,
    )

    assert evidence.research_only is True
    assert evidence.must_not_use_for_decision is True
    assert assessment.status is ResearchEvidenceStatus.AVAILABLE
    assert assessment.research_only is True


def test_path_probability_support_and_distribution_are_fail_closed() -> None:
    low_support = assess_scenario_path_evidence(
        scope=_scope(),
        policy=_policy(),
        evidence=_path_study(observation_count=5),
        evaluated_at=NOW,
    )
    assert low_support.status is ResearchEvidenceStatus.INSUFFICIENT_EVIDENCE
    assert low_support.evidence_hash is not None

    with pytest.raises(ValueError, match="probabilities must sum to one"):
        ScenarioPathStudyEvidence.create(
            study_version="scenario-path-study.v1",
            scope=_scope(),
            pit_manifest=_manifest(
                manifest_id="pit-invalid-path",
                as_of=NOW - timedelta(days=2),
                digest_character="1",
            ),
            shocks=_path_study().shocks,
            conditional_probabilities=tuple(
                ConditionalProbabilityEvidence(
                    item.condition_key,
                    item.target_scenario_revision_id,
                    (
                        Decimal("0.50")
                        if item.target_scenario_revision_id == REVISION_A
                        else Decimal("0.40")
                    ),
                    item.observation_count,
                    item.source_version,
                    item.sample_definition_version,
                    "pit-invalid-path",
                    item.pit_manifest_version,
                    "1" * 64,
                    item.period_index,
                )
                for item in _path_study().conditional_probabilities
            ),
            transition_probabilities=tuple(
                TransitionProbabilityEvidence(
                    item.from_scenario_revision_id,
                    item.to_scenario_revision_id,
                    item.horizon_periods,
                    item.probability,
                    item.observation_count,
                    item.source_version,
                    item.sample_definition_version,
                    "pit-invalid-path",
                    item.pit_manifest_version,
                    "1" * 64,
                )
                for item in _path_study().transition_probabilities
            ),
            generated_at=NOW - timedelta(hours=1),
            valid_until=NOW + timedelta(days=1),
            evidence_refs=("research://invalid-path",),
            probability_sum_tolerance=Decimal("0.000001"),
        )


def test_path_rejects_out_of_scope_shock_and_mixed_distribution_provenance() -> None:
    valid = _path_study()
    outsider = UUID("00000000-0000-0000-0000-000000000999")
    with pytest.raises(ValueError, match="outside scenario scope"):
        ScenarioPathStudyEvidence.create(
            study_version="scenario-path-study.v1",
            scope=_scope(),
            pit_manifest=valid.pit_manifest,
            shocks=(
                MultiPeriodShockEvidence(
                    1,
                    outsider,
                    NOW - timedelta(days=10),
                    NOW - timedelta(days=9),
                    "growth",
                    Decimal("-0.5"),
                    "zscore",
                    "shock-spec.v1",
                ),
                valid.shocks[1],
            ),
            conditional_probabilities=valid.conditional_probabilities,
            transition_probabilities=valid.transition_probabilities,
            generated_at=NOW - timedelta(hours=2),
            valid_until=NOW + timedelta(days=1),
            evidence_refs=("research://out-of-scope",),
            probability_sum_tolerance=Decimal("0.000001"),
        )

    mixed = (
        valid.conditional_probabilities[0],
        ConditionalProbabilityEvidence(
            "growth_down",
            REVISION_B,
            Decimal("0.40"),
            21,
            "path-study.v1",
            "path-sample.v1",
            "pit-path",
            "pit-manifest.v1",
            "d" * 64,
            1,
        ),
    )
    with pytest.raises(ValueError, match="share exact sample and PIT provenance"):
        ScenarioPathStudyEvidence.create(
            study_version="scenario-path-study.v1",
            scope=_scope(),
            pit_manifest=valid.pit_manifest,
            shocks=valid.shocks,
            conditional_probabilities=mixed,
            transition_probabilities=valid.transition_probabilities,
            generated_at=NOW - timedelta(hours=2),
            valid_until=NOW + timedelta(days=1),
            evidence_refs=("research://mixed-provenance",),
            probability_sum_tolerance=Decimal("0.000001"),
        )


def test_invalidation_creates_deterministic_review_intent_without_dispatch() -> None:
    observation = make_observation()
    assert observation.invalidation is not None
    first = build_review_reminder_intent(
        observation=observation,
        policy=_policy(),
        evaluated_at=NOW,
    )
    second = build_review_reminder_intent(
        observation=observation,
        policy=_policy(),
        evaluated_at=(NOW + timedelta(hours=3)).astimezone(timezone(timedelta(hours=8))),
    )

    assert first.intent_id == second.intent_id
    assert first.content_hash == second.content_hash
    assert first.forecast_entry_id == observation.entry_id
    assert first.forecast_observation_hash == observation.content_hash
    assert first.dispatch_requested is False
    assert first.created_at == observation.invalidation.invalidated_at
    assert first.review_due_at == (observation.invalidation.invalidated_at + timedelta(days=2))
    assert len(first.content_hash) == 64
