"""Reusable values for approved R7 sample policy tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from apps.research.application.r7_sample_policy import R7SamplePolicyRegistrationDraft
from apps.research.domain.r7_sample_policy import (
    R7SamplePolicyAuthorization,
    r7_sample_policy_definition_hash,
)
from apps.research.domain.scenario_probability_contracts import (
    ScenarioProbabilityResearchPolicy,
    ScenarioResearchScope,
)

RECORDED_AT = datetime(2026, 8, 7, 10, 0, tzinfo=UTC)
ACTIVATED_AT = RECORDED_AT + timedelta(hours=1)
VALID_UNTIL = ACTIVATED_AT + timedelta(days=30)
REVISION_A = UUID("00000000-0000-0000-0000-000000000701")
REVISION_B = UUID("00000000-0000-0000-0000-000000000702")
SET_REVISION = UUID("00000000-0000-0000-0000-000000000700")


def make_scope(
    *,
    forecast_horizon: timedelta = timedelta(days=90),
    censoring_rule_version: str = "scenario-censoring.v1",
    path_horizon_periods: int = 3,
    path_initial_state_revision_ids: tuple[UUID, ...] = (REVISION_B, REVISION_A),
) -> ScenarioResearchScope:
    """Create one exact two-revision research scope."""

    return ScenarioResearchScope.create(
        scope_version="r7-scope.v1",
        scenario_set_revision_id=SET_REVISION,
        scenario_revision_ids=(REVISION_B, REVISION_A),
        forecast_horizon=forecast_horizon,
        censoring_rule_version=censoring_rule_version,
        path_horizon_periods=path_horizon_periods,
        path_initial_state_revision_ids=path_initial_state_revision_ids,
    )


def make_policy_definition(
    *,
    policy_version: str = "r7-sample-policy.v1",
    approved_by: str = "caller-self-attestation",
    minimum_historical_analogies: int = 5,
    forecast_horizon: timedelta = timedelta(days=90),
    censoring_rule_version: str = "scenario-censoring.v1",
    path_horizon_periods: int = 3,
    require_all_path_initial_states: bool = True,
) -> ScenarioProbabilityResearchPolicy:
    """Create a complete policy definition with a deliberately untrusted approver."""

    return ScenarioProbabilityResearchPolicy.create(
        policy_version=policy_version,
        activated_at=ACTIVATED_AT,
        valid_until=VALID_UNTIL,
        sample_window_start=datetime(2024, 1, 1, tzinfo=UTC),
        sample_window_end=datetime(2025, 12, 31, tzinfo=UTC),
        forecast_horizon=forecast_horizon,
        censoring_lag=timedelta(days=7),
        censoring_rule_version=censoring_rule_version,
        minimum_forecasts_per_revision=20,
        minimum_resolved_outcomes_per_revision=15,
        minimum_outcome_coverage=Decimal("0.75"),
        minimum_binary_class_observations=10,
        minimum_multiclass_groups=8,
        minimum_multiclass_class_observations=6,
        maximum_outcome_evidence_age=timedelta(days=120),
        calibration_bin_edges=(
            Decimal("0"),
            Decimal("0.25"),
            Decimal("0.5"),
            Decimal("0.75"),
            Decimal("1"),
        ),
        probability_sum_tolerance=Decimal("0.000001"),
        minimum_historical_analogies=minimum_historical_analogies,
        minimum_path_probability_observations=12,
        path_horizon_periods=path_horizon_periods,
        require_all_path_initial_states=require_all_path_initial_states,
        maximum_research_evidence_age=timedelta(days=30),
        invalidation_review_delay=timedelta(days=2),
        approved_by=approved_by,
    )


def make_draft(
    *,
    policy_id: str = "r7-policy:scenario-probability",
    policy_version: str = "r7-sample-policy.v1",
) -> R7SamplePolicyRegistrationDraft:
    """Create one exact trusted policy-definition record."""

    return R7SamplePolicyRegistrationDraft(
        policy_id=policy_id,
        policy_version=policy_version,
        scope=make_scope(),
        policy_definition=make_policy_definition(policy_version=policy_version),
    )


def make_authorization(
    draft: R7SamplePolicyRegistrationDraft | None = None,
    *,
    authorization_id: str = "r7-auth:scenario-probability",
    authorization_version: str = "authorization.v1",
    approved_by: str = "research-governance-owner",
) -> R7SamplePolicyAuthorization:
    """Create exact external-owner evidence for the supplied definition."""

    value = draft or make_draft()
    return R7SamplePolicyAuthorization.create(
        authorization_id=authorization_id,
        authorization_version=authorization_version,
        owner_record_id="governance-approval:r7-policy",
        owner_record_version="owner-record.v1",
        owner_record_hash="a" * 64,
        policy_id=value.policy_id,
        policy_version=value.policy_version,
        scope_content_hash=value.scope.content_hash,
        policy_definition_hash=r7_sample_policy_definition_hash(
            scope=value.scope,
            policy=value.policy_definition,
        ),
        approved_by=approved_by,
        issued_at=RECORDED_AT - timedelta(hours=1),
        valid_until=RECORDED_AT + timedelta(days=1),
    )


__all__ = [
    "ACTIVATED_AT",
    "RECORDED_AT",
    "VALID_UNTIL",
    "make_authorization",
    "make_draft",
    "make_policy_definition",
    "make_scope",
]
