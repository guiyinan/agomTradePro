"""Immutable approval and persistence seals for R7 sample policies."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from apps.research.domain.scenario_probability_contracts import (
    ScenarioProbabilityResearchPolicy,
    ScenarioResearchScope,
)
from apps.research.domain.scenario_research_hashing import (
    hash_components,
    require_sha256,
    require_token,
)


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def validate_r7_sample_policy_scope_coherence(
    *,
    scope: ScenarioResearchScope,
    policy: ScenarioProbabilityResearchPolicy,
) -> None:
    """Reject a signed policy whose duplicated scope semantics disagree."""

    if scope.forecast_horizon != policy.forecast_horizon:
        raise ValueError("R7 scope and policy forecast_horizon mismatch")
    if scope.censoring_rule_version != policy.censoring_rule_version:
        raise ValueError("R7 scope and policy censoring_rule_version mismatch")
    if scope.path_horizon_periods != policy.path_horizon_periods:
        raise ValueError("R7 scope and policy path_horizon_periods mismatch")
    if policy.require_all_path_initial_states and set(scope.path_initial_state_revision_ids) != set(
        scope.scenario_revision_ids
    ):
        raise ValueError("R7 policy requires every scope revision as a path initial state")


def r7_sample_policy_definition_hash(
    *,
    scope: ScenarioResearchScope,
    policy: ScenarioProbabilityResearchPolicy,
) -> str:
    """Hash every policy threshold except the externally supplied approver."""

    validate_r7_sample_policy_scope_coherence(scope=scope, policy=policy)

    return hash_components(
        "r7-sample-policy-definition.v1",
        scope.content_hash,
        policy.policy_version,
        policy.activated_at.isoformat(),
        policy.valid_until.isoformat(),
        policy.sample_window_start.isoformat(),
        policy.sample_window_end.isoformat(),
        str(policy.forecast_horizon.total_seconds()),
        str(policy.censoring_lag.total_seconds()),
        policy.censoring_rule_version,
        str(policy.minimum_forecasts_per_revision),
        str(policy.minimum_resolved_outcomes_per_revision),
        str(policy.minimum_outcome_coverage),
        str(policy.minimum_binary_class_observations),
        str(policy.minimum_multiclass_groups),
        str(policy.minimum_multiclass_class_observations),
        str(policy.maximum_outcome_evidence_age.total_seconds()),
        *(str(edge) for edge in policy.calibration_bin_edges),
        str(policy.probability_sum_tolerance),
        str(policy.minimum_historical_analogies),
        str(policy.minimum_path_probability_observations),
        str(policy.path_horizon_periods),
        str(policy.require_all_path_initial_states),
        str(policy.maximum_research_evidence_age.total_seconds()),
        str(policy.invalidation_review_delay.total_seconds()),
    )


def materialize_r7_sample_policy(
    *,
    policy: ScenarioProbabilityResearchPolicy,
    approved_by: str,
) -> ScenarioProbabilityResearchPolicy:
    """Rebuild a policy with the approver asserted by exact owner evidence."""

    return ScenarioProbabilityResearchPolicy.create(
        policy_version=policy.policy_version,
        activated_at=policy.activated_at,
        valid_until=policy.valid_until,
        sample_window_start=policy.sample_window_start,
        sample_window_end=policy.sample_window_end,
        forecast_horizon=policy.forecast_horizon,
        censoring_lag=policy.censoring_lag,
        censoring_rule_version=policy.censoring_rule_version,
        minimum_forecasts_per_revision=policy.minimum_forecasts_per_revision,
        minimum_resolved_outcomes_per_revision=(policy.minimum_resolved_outcomes_per_revision),
        minimum_outcome_coverage=policy.minimum_outcome_coverage,
        minimum_binary_class_observations=policy.minimum_binary_class_observations,
        minimum_multiclass_groups=policy.minimum_multiclass_groups,
        minimum_multiclass_class_observations=(policy.minimum_multiclass_class_observations),
        maximum_outcome_evidence_age=policy.maximum_outcome_evidence_age,
        calibration_bin_edges=policy.calibration_bin_edges,
        probability_sum_tolerance=policy.probability_sum_tolerance,
        minimum_historical_analogies=policy.minimum_historical_analogies,
        minimum_path_probability_observations=(policy.minimum_path_probability_observations),
        path_horizon_periods=policy.path_horizon_periods,
        require_all_path_initial_states=policy.require_all_path_initial_states,
        maximum_research_evidence_age=policy.maximum_research_evidence_age,
        invalidation_review_delay=policy.invalidation_review_delay,
        approved_by=approved_by,
    )


@dataclass(frozen=True)
class R7SamplePolicyAuthorization:
    """Exact external-owner authorization for one policy definition."""

    owner: str
    capability: str
    purpose: str
    authorization_id: str
    authorization_version: str
    owner_record_id: str
    owner_record_version: str
    owner_record_hash: str
    policy_id: str
    policy_version: str
    scope_content_hash: str
    policy_definition_hash: str
    approved_by: str
    issued_at: datetime
    valid_until: datetime
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        authorization_id: str,
        authorization_version: str,
        owner_record_id: str,
        owner_record_version: str,
        owner_record_hash: str,
        policy_id: str,
        policy_version: str,
        scope_content_hash: str,
        policy_definition_hash: str,
        approved_by: str,
        issued_at: datetime,
        valid_until: datetime,
    ) -> R7SamplePolicyAuthorization:
        """Create a content-addressed external authorization receipt."""

        digest = hash_components(
            "r7-sample-policy-authorization.v1",
            "scenario_governance",
            "r7",
            "scenario_probability_sample_policy",
            authorization_id,
            authorization_version,
            owner_record_id,
            owner_record_version,
            owner_record_hash,
            policy_id,
            policy_version,
            scope_content_hash,
            policy_definition_hash,
            approved_by,
            issued_at.isoformat(),
            valid_until.isoformat(),
        )
        return cls(
            owner="scenario_governance",
            capability="r7",
            purpose="scenario_probability_sample_policy",
            authorization_id=authorization_id,
            authorization_version=authorization_version,
            owner_record_id=owner_record_id,
            owner_record_version=owner_record_version,
            owner_record_hash=owner_record_hash,
            policy_id=policy_id,
            policy_version=policy_version,
            scope_content_hash=scope_content_hash,
            policy_definition_hash=policy_definition_hash,
            approved_by=approved_by,
            issued_at=issued_at,
            valid_until=valid_until,
            content_hash=digest,
        )

    def __post_init__(self) -> None:
        """Reject forged identity, clocks, owner record, or content hash."""

        for field_name, value in (
            ("owner", self.owner),
            ("capability", self.capability),
            ("purpose", self.purpose),
            ("authorization_id", self.authorization_id),
            ("authorization_version", self.authorization_version),
            ("owner_record_id", self.owner_record_id),
            ("owner_record_version", self.owner_record_version),
            ("policy_id", self.policy_id),
            ("policy_version", self.policy_version),
            ("approved_by", self.approved_by),
        ):
            require_token(value, field_name, maximum=192)
        if (
            self.owner != "scenario_governance"
            or self.capability != "r7"
            or self.purpose != "scenario_probability_sample_policy"
        ):
            raise ValueError("R7 sample policy authorization authority is invalid")
        for field_name, value in (
            ("owner_record_hash", self.owner_record_hash),
            ("scope_content_hash", self.scope_content_hash),
            ("policy_definition_hash", self.policy_definition_hash),
            ("content_hash", self.content_hash),
        ):
            require_sha256(value, field_name)
        _require_aware(self.issued_at, "issued_at")
        _require_aware(self.valid_until, "valid_until")
        if self.valid_until <= self.issued_at:
            raise ValueError("authorization valid_until must follow issued_at")
        expected = hash_components(
            "r7-sample-policy-authorization.v1",
            self.owner,
            self.capability,
            self.purpose,
            self.authorization_id,
            self.authorization_version,
            self.owner_record_id,
            self.owner_record_version,
            self.owner_record_hash,
            self.policy_id,
            self.policy_version,
            self.scope_content_hash,
            self.policy_definition_hash,
            self.approved_by,
            self.issued_at.isoformat(),
            self.valid_until.isoformat(),
        )
        if self.content_hash != expected:
            raise ValueError("R7 sample policy authorization content_hash mismatch")


@dataclass(frozen=True)
class PersistedR7SamplePolicy:
    """Research-owned immutable policy plus exact approval receipt."""

    policy_id: str
    policy_version: str
    scope: ScenarioResearchScope
    policy: ScenarioProbabilityResearchPolicy
    authorization: R7SamplePolicyAuthorization
    recorded_at: datetime
    research_only: bool
    must_not_use_for_decision: bool
    must_not_execute: bool
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        policy_id: str,
        policy_version: str,
        scope: ScenarioResearchScope,
        policy_definition: ScenarioProbabilityResearchPolicy,
        authorization: R7SamplePolicyAuthorization,
        recorded_at: datetime,
    ) -> PersistedR7SamplePolicy:
        """Seal one approved policy using the authoritative receipt clock."""

        validate_r7_sample_policy_scope_coherence(
            scope=scope,
            policy=policy_definition,
        )

        definition_hash = r7_sample_policy_definition_hash(
            scope=scope,
            policy=policy_definition,
        )
        if (
            authorization.policy_id != policy_id
            or authorization.policy_version != policy_version
            or authorization.scope_content_hash != scope.content_hash
            or authorization.policy_definition_hash != definition_hash
        ):
            raise ValueError("R7 sample policy authorization substitution")
        materialized = materialize_r7_sample_policy(
            policy=policy_definition,
            approved_by=authorization.approved_by,
        )
        digest = hash_components(
            "r7-persisted-sample-policy.v1",
            policy_id,
            policy_version,
            scope.content_hash,
            materialized.content_hash,
            authorization.content_hash,
            recorded_at.isoformat(),
            "True",
            "True",
            "True",
        )
        return cls(
            policy_id=policy_id,
            policy_version=policy_version,
            scope=scope,
            policy=materialized,
            authorization=authorization,
            recorded_at=recorded_at,
            research_only=True,
            must_not_use_for_decision=True,
            must_not_execute=True,
            content_hash=digest,
        )

    def __post_init__(self) -> None:
        """Validate identity, pre-registration, authority, and safety flags."""

        require_token(self.policy_id, "policy_id", maximum=192)
        require_token(self.policy_version, "policy_version", maximum=192)
        require_sha256(self.content_hash, "content_hash")
        _require_aware(self.recorded_at, "recorded_at")
        validate_r7_sample_policy_scope_coherence(
            scope=self.scope,
            policy=self.policy,
        )
        if self.policy.policy_version != self.policy_version:
            raise ValueError("persisted R7 policy version mismatch")
        definition_hash = r7_sample_policy_definition_hash(
            scope=self.scope,
            policy=self.policy,
        )
        if (
            self.authorization.policy_id != self.policy_id
            or self.authorization.policy_version != self.policy_version
            or self.authorization.scope_content_hash != self.scope.content_hash
            or self.authorization.policy_definition_hash != definition_hash
            or self.authorization.approved_by != self.policy.approved_by
        ):
            raise ValueError("persisted R7 policy approval graph mismatch")
        if not (self.authorization.issued_at <= self.recorded_at < self.authorization.valid_until):
            raise ValueError("R7 policy was recorded outside authorization validity")
        if self.recorded_at > self.policy.activated_at:
            raise ValueError("R7 sample policy must be pre-registered before activation")
        if (
            not self.research_only
            or not self.must_not_use_for_decision
            or not self.must_not_execute
        ):
            raise ValueError("persisted R7 sample policy must remain research-only")
        expected = hash_components(
            "r7-persisted-sample-policy.v1",
            self.policy_id,
            self.policy_version,
            self.scope.content_hash,
            self.policy.content_hash,
            self.authorization.content_hash,
            self.recorded_at.isoformat(),
            "True",
            "True",
            "True",
        )
        if self.content_hash != expected:
            raise ValueError("persisted R7 sample policy content_hash mismatch")


__all__ = [
    "PersistedR7SamplePolicy",
    "R7SamplePolicyAuthorization",
    "materialize_r7_sample_policy",
    "r7_sample_policy_definition_hash",
    "validate_r7_sample_policy_scope_coherence",
]
