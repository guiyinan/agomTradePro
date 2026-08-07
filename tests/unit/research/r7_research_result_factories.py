"""Deterministic typed evidence for R7 result persistence tests."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID

from apps.research.application.r7_research_result_persistence import (
    materialize_persisted_r7_research_result,
)
from apps.research.domain.r7_research_result_persistence import (
    PersistedR7ResearchResult,
    R7ResearchEvidenceGraph,
)
from apps.research.domain.r7_sample_policy import PersistedR7SamplePolicy
from apps.research.domain.scenario_probability_contracts import (
    ForecastLedgerOutcomeObservation,
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
)
from apps.signal.domain.forecast_scenario_evidence import ScenarioForecastBinding
from tests.unit.research.r7_sample_policy_factories import (
    ACTIVATED_AT,
    RECORDED_AT,
    REVISION_A,
    REVISION_B,
    make_authorization,
    make_draft,
)

EVALUATED_AT = ACTIVATED_AT
RESULT_RECORDED_AT = EVALUATED_AT + timedelta(minutes=5)


def make_policy_record() -> PersistedR7SamplePolicy:
    """Materialize one already-approved, active persisted policy record."""

    draft = make_draft()
    return PersistedR7SamplePolicy.create(
        policy_id=draft.policy_id,
        policy_version=draft.policy_version,
        scope=draft.scope,
        policy_definition=draft.policy_definition,
        authorization=make_authorization(draft),
        recorded_at=RECORDED_AT,
    )


def make_forecast_observations() -> tuple[ForecastLedgerOutcomeObservation, ...]:
    """Create one complete but intentionally small two-class forecast group."""

    policy_record = make_policy_record()
    published_at = datetime.fromisoformat("2025-01-01T00:00:00+00:00")
    horizon_end = published_at + policy_record.scope.forecast_horizon

    def observation(
        *,
        entry_id: str,
        revision_id: UUID,
        probability: str,
        realized: bool,
    ) -> ForecastLedgerOutcomeObservation:
        return ForecastLedgerOutcomeObservation.create(
            observation_version="r7-forecast-observation.v1",
            entry_id=entry_id,
            forecast_group_id="r7-forecast-group:1",
            binding=ScenarioForecastBinding.from_values(
                scenario_revision_id=revision_id,
                scenario_set_revision_id=policy_record.scope.scenario_set_revision_id,
                subjective_probability=probability,
                subjective_probability_source_version="committee-probability.v1",
            ),
            pit_manifest_id="pit-forecast-group:1",
            pit_manifest_version="pit-manifest.v1",
            pit_manifest_hash=hashlib.sha256(b"pit-forecast-group:1").hexdigest(),
            censoring_rule_version=policy_record.scope.censoring_rule_version,
            published_at=published_at,
            horizon_end=horizon_end,
            scenario_realized=realized,
            outcome_recorded_at=horizon_end + timedelta(hours=1),
            outcome_evidence_valid_until=EVALUATED_AT + timedelta(days=1),
        )

    return (
        observation(
            entry_id="r7-forecast:b",
            revision_id=REVISION_B,
            probability="0.35",
            realized=False,
        ),
        observation(
            entry_id="r7-forecast:a",
            revision_id=REVISION_A,
            probability="0.65",
            realized=True,
        ),
    )


def make_historical_analogy() -> HistoricalAnalogyStudyEvidence:
    """Create a full PIT-manifest-bound historical analogy graph."""

    policy_record = make_policy_record()
    candidate_as_of = datetime.fromisoformat("2020-02-01T00:00:00+00:00")
    feature_available_at = candidate_as_of - timedelta(days=2)
    feature_vintage_at = candidate_as_of - timedelta(days=1)
    manifest_feature = PointInTimeManifestFeature(
        feature_key="growth_zscore",
        source_version="macro-vintage.v1",
        available_at=feature_available_at,
        vintage_at=feature_vintage_at,
        content_hash="a" * 64,
    )
    candidate_manifest = PointInTimeManifestReference.create(
        manifest_id="pit-analogy:candidate-2020",
        manifest_version="pit-manifest.v1",
        as_of=candidate_as_of,
        manifest_hash="b" * 64,
        features=(manifest_feature,),
    )
    candidate = HistoricalAnalogyCandidateEvidence.create(
        candidate_id="analogy-window:2020",
        candidate_version="historical-candidate.v1",
        window_start=candidate_as_of - timedelta(days=31),
        window_end=candidate_as_of - timedelta(days=1),
        decision_cutoff=candidate_as_of,
        allowed_release_lag=timedelta(days=1),
        pit_manifest=candidate_manifest,
        feature_definition_version="analogy-features.v1",
        features=(
            PointInTimeFeatureValue(
                feature_key="growth_zscore",
                value=Decimal("-1.25"),
                unit="zscore",
                source_version="macro-vintage.v1",
                available_at=feature_available_at,
                vintage_at=feature_vintage_at,
            ),
        ),
        similarity_score=Decimal("0.82"),
        evidence_refs=("pit://analogy-window:2020",),
    )
    query_manifest = PointInTimeManifestReference.create(
        manifest_id="pit-analogy:query",
        manifest_version="pit-manifest.v1",
        as_of=EVALUATED_AT - timedelta(days=1),
        manifest_hash="c" * 64,
    )
    return HistoricalAnalogyStudyEvidence.create(
        study_version="historical-analogy-study.v1",
        scope=policy_record.scope,
        query_manifest=query_manifest,
        feature_definition_version="analogy-features.v1",
        candidates=(candidate,),
        generated_at=EVALUATED_AT - timedelta(hours=1),
        valid_until=EVALUATED_AT + timedelta(days=10),
        evidence_refs=("research://r7-analogy-run:1",),
    )


def make_path_study() -> ScenarioPathStudyEvidence:
    """Create complete typed shock, conditional, and transition evidence."""

    policy_record = make_policy_record()
    scope = policy_record.scope
    manifest = PointInTimeManifestReference.create(
        manifest_id="pit-path:1",
        manifest_version="pit-manifest.v1",
        as_of=EVALUATED_AT - timedelta(days=2),
        manifest_hash="d" * 64,
    )
    shocks = tuple(
        MultiPeriodShockEvidence(
            period_index=period,
            scenario_revision_id=REVISION_A if period % 2 else REVISION_B,
            period_start=EVALUATED_AT - timedelta(days=20 - period * 2),
            period_end=EVALUATED_AT - timedelta(days=19 - period * 2),
            shock_key=f"macro_shock_{period}",
            magnitude=Decimal(str(period)) / Decimal("10"),
            unit="zscore",
            source_version="path-shock-spec.v1",
        )
        for period in range(1, scope.path_horizon_periods + 1)
    )
    conditional = tuple(
        ConditionalProbabilityEvidence(
            condition_key="growth_down",
            target_scenario_revision_id=target,
            probability=Decimal("0.60") if target == REVISION_A else Decimal("0.40"),
            observation_count=20,
            source_version="path-study.v1",
            sample_definition_version="path-sample.v1",
            pit_manifest_id=manifest.manifest_id,
            pit_manifest_version=manifest.manifest_version,
            pit_manifest_hash=manifest.manifest_hash,
            period_index=period,
        )
        for period in range(1, scope.path_horizon_periods + 1)
        for target in scope.scenario_revision_ids
    )
    transition = tuple(
        TransitionProbabilityEvidence(
            from_scenario_revision_id=initial,
            to_scenario_revision_id=target,
            horizon_periods=period,
            probability=(Decimal("0.70") if initial == target else Decimal("0.30")),
            observation_count=20,
            source_version="path-study.v1",
            sample_definition_version="path-sample.v1",
            pit_manifest_id=manifest.manifest_id,
            pit_manifest_version=manifest.manifest_version,
            pit_manifest_hash=manifest.manifest_hash,
        )
        for initial in scope.path_initial_state_revision_ids
        for period in range(1, scope.path_horizon_periods + 1)
        for target in scope.scenario_revision_ids
    )
    return ScenarioPathStudyEvidence.create(
        study_version="scenario-path-study.v1",
        scope=scope,
        pit_manifest=manifest,
        shocks=shocks,
        conditional_probabilities=conditional,
        transition_probabilities=transition,
        generated_at=EVALUATED_AT - timedelta(hours=2),
        valid_until=EVALUATED_AT + timedelta(days=10),
        evidence_refs=("research://r7-path-run:1",),
        probability_sum_tolerance=policy_record.policy.probability_sum_tolerance,
    )


def make_evidence_graph() -> R7ResearchEvidenceGraph:
    """Create a canonical complete R7 owner evidence graph."""

    policy_record = make_policy_record()
    return R7ResearchEvidenceGraph.create(
        scope_content_hash=policy_record.scope.content_hash,
        evaluated_at=EVALUATED_AT,
        forecast_observations=make_forecast_observations(),
        historical_analogy=make_historical_analogy(),
        path_study=make_path_study(),
    )


def make_result() -> PersistedR7ResearchResult:
    """Create one deterministic complete result bundle without database writes."""

    return materialize_persisted_r7_research_result(
        result_id="r7-result:scenario-probability:1",
        result_version="r7-result.v1",
        policy_record=make_policy_record(),
        evidence_graph=make_evidence_graph(),
        evaluated_at=EVALUATED_AT,
        recorded_at=RESULT_RECORDED_AT,
    )


__all__ = [
    "EVALUATED_AT",
    "RESULT_RECORDED_AT",
    "make_evidence_graph",
    "make_forecast_observations",
    "make_historical_analogy",
    "make_path_study",
    "make_policy_record",
    "make_result",
]
