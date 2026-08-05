"""Typed factories shared by R7 reminder unit and component tests."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from apps.research.domain.scenario_probability_contracts import (
    ForecastLedgerOutcomeObservation,
    ScenarioInvalidationEvidence,
    ScenarioProbabilityResearchPolicy,
    ScenarioResearchScope,
)
from apps.research.domain.scenario_research_evidence import (
    ConditionalProbabilityEvidence,
    MultiPeriodShockEvidence,
    PointInTimeManifestReference,
    ScenarioPathStudyEvidence,
    TransitionProbabilityEvidence,
)
from apps.research.domain.scenario_review_intent import (
    ReviewReminderIntent,
    build_review_reminder_intent,
)
from apps.signal.domain.forecast_scenario_evidence import ScenarioForecastBinding

NOW = datetime(2026, 8, 5, 12, tzinfo=UTC)
SET_REVISION = UUID("00000000-0000-0000-0000-000000000100")
REVISION_A = UUID("00000000-0000-0000-0000-000000000001")
REVISION_B = UUID("00000000-0000-0000-0000-000000000002")


def make_policy() -> ScenarioProbabilityResearchPolicy:
    """Build the exact research policy used by reminder tests."""

    return ScenarioProbabilityResearchPolicy.create(
        policy_version="scenario-calibration-policy.v1",
        activated_at=NOW - timedelta(days=30),
        valid_until=NOW + timedelta(days=30),
        sample_window_start=NOW - timedelta(days=30),
        sample_window_end=NOW,
        forecast_horizon=timedelta(days=10),
        censoring_lag=timedelta(days=7),
        censoring_rule_version="scenario-censoring.v1",
        minimum_forecasts_per_revision=1,
        minimum_resolved_outcomes_per_revision=1,
        minimum_outcome_coverage=Decimal("1"),
        minimum_binary_class_observations=1,
        minimum_multiclass_groups=1,
        minimum_multiclass_class_observations=1,
        maximum_outcome_evidence_age=timedelta(days=365),
        calibration_bin_edges=(Decimal("0"), Decimal("1")),
        probability_sum_tolerance=Decimal("0.000001"),
        minimum_historical_analogies=1,
        minimum_path_probability_observations=1,
        path_horizon_periods=2,
        require_all_path_initial_states=False,
        maximum_research_evidence_age=timedelta(days=90),
        invalidation_review_delay=timedelta(days=2),
        approved_by="research-owner",
    )


def make_observation() -> ForecastLedgerOutcomeObservation:
    """Build one exact invalidated forecast observation."""

    invalidation = ScenarioInvalidationEvidence.create(
        evidence_version="scenario-invalidation.v1",
        scenario_revision_id=REVISION_A,
        scenario_set_revision_id=SET_REVISION,
        invalidated_at=NOW - timedelta(hours=1),
        invalidation_rule_version="scenario-rule.v3",
        pit_manifest_id="pit-invalidation-v1",
        evidence_refs=("evidence://scenario-invalidated",),
    )
    published_at = NOW - timedelta(days=5)
    return ForecastLedgerOutcomeObservation.create(
        observation_version="ledger-observation.v1",
        entry_id="forecast-r7-1",
        forecast_group_id="forecast-group-r7",
        binding=ScenarioForecastBinding.from_values(
            scenario_revision_id=REVISION_A,
            scenario_set_revision_id=SET_REVISION,
            subjective_probability="0.4",
            subjective_probability_source_version="committee-v1",
        ),
        pit_manifest_id="pit-forecast-r7",
        pit_manifest_version="pit-manifest.v1",
        pit_manifest_hash=hashlib.sha256(b"pit-forecast-r7").hexdigest(),
        censoring_rule_version="scenario-censoring.v1",
        published_at=published_at,
        horizon_end=published_at + timedelta(days=10),
        scenario_realized=None,
        outcome_recorded_at=None,
        outcome_evidence_valid_until=None,
        invalidation=invalidation,
    )


def make_review_intent() -> ReviewReminderIntent:
    """Build a deterministic forecast-bound human-review intent."""

    policy = make_policy()
    intent = build_review_reminder_intent(
        observation=make_observation(),
        policy=policy,
        evaluated_at=NOW,
    )
    return intent


def make_path_study(
    *,
    generated_at: datetime | None = None,
    valid_until: datetime | None = None,
    scenario_set_revision_id: UUID | None = SET_REVISION,
) -> ScenarioPathStudyEvidence:
    """Build complete two-period typed conditional and transition evidence."""

    scope = ScenarioResearchScope.create(
        scope_version="scenario-scope.v1",
        scenario_set_revision_id=scenario_set_revision_id,
        scenario_revision_ids=(REVISION_A, REVISION_B),
        forecast_horizon=timedelta(days=10),
        censoring_rule_version="scenario-censoring.v1",
        path_horizon_periods=2,
        path_initial_state_revision_ids=(REVISION_A, REVISION_B),
    )
    manifest = PointInTimeManifestReference.create(
        manifest_id="pit-path-r7",
        manifest_version="pit-manifest.v1",
        as_of=NOW - timedelta(days=2),
        manifest_hash="d" * 64,
        features=(),
    )
    probabilities = {
        (REVISION_A, REVISION_A): Decimal("0.70"),
        (REVISION_A, REVISION_B): Decimal("0.30"),
        (REVISION_B, REVISION_A): Decimal("0.40"),
        (REVISION_B, REVISION_B): Decimal("0.60"),
    }
    return ScenarioPathStudyEvidence.create(
        study_version="scenario-path-study.v1",
        scope=scope,
        pit_manifest=manifest,
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
        conditional_probabilities=tuple(
            ConditionalProbabilityEvidence(
                condition_key="growth_down",
                target_scenario_revision_id=target,
                probability=(Decimal("0.60") if target == REVISION_A else Decimal("0.40")),
                observation_count=20,
                source_version="path-study.v1",
                sample_definition_version="path-sample.v1",
                pit_manifest_id="pit-path-r7",
                pit_manifest_version="pit-manifest.v1",
                pit_manifest_hash="d" * 64,
                period_index=period_index,
            )
            for period_index in (1, 2)
            for target in (REVISION_A, REVISION_B)
        ),
        transition_probabilities=tuple(
            TransitionProbabilityEvidence(
                from_revision,
                to_revision,
                period_index,
                probabilities[(from_revision, to_revision)],
                20,
                "path-study.v1",
                "path-sample.v1",
                "pit-path-r7",
                "pit-manifest.v1",
                "d" * 64,
            )
            for period_index in (1, 2)
            for from_revision in (REVISION_A, REVISION_B)
            for to_revision in (REVISION_A, REVISION_B)
        ),
        generated_at=generated_at or NOW - timedelta(hours=2),
        valid_until=valid_until or NOW + timedelta(days=10),
        evidence_refs=("research://path-run-r7",),
        probability_sum_tolerance=Decimal("0.000001"),
    )
