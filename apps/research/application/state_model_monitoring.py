"""ID/as-of-only orchestration for research-only R6 monitoring."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from apps.research.domain.state_model_monitoring import (
    R6MonitoringAssessment,
    R6MonitoringObservation,
    R6MonitoringPeriodCalendar,
    R6MonitoringPolicy,
    evaluate_r6_monitoring,
)
from apps.research.domain.state_model_qualification_lifecycle import R6QualificationRef


def _require_token(value: str, field_name: str) -> None:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > 192
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{field_name} must be a bounded non-blank token")


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _require_hash(value: str, field_name: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdefABCDEF" for character in value):
        raise ValueError(f"{field_name} must be a SHA-256 digest")


@dataclass(frozen=True)
class ActiveR6QualificationEvidence:
    """Canonical active projection; it remains an internal research record."""

    qualification_ref: R6QualificationRef
    candidate_id: str
    candidate_version: str
    assessed_at: datetime
    known_at: datetime
    research_only: bool
    must_not_use_for_decision: bool
    must_not_replace_regime: bool

    def __post_init__(self) -> None:
        _require_token(self.candidate_id, "ActiveR6QualificationEvidence.candidate_id")
        _require_token(
            self.candidate_version,
            "ActiveR6QualificationEvidence.candidate_version",
        )
        _require_aware(self.assessed_at, "ActiveR6QualificationEvidence.assessed_at")
        _require_aware(self.known_at, "ActiveR6QualificationEvidence.known_at")
        if self.known_at < self.assessed_at:
            raise ValueError("active R6 qualification knowledge precedes assessment")
        if not (
            self.research_only and self.must_not_use_for_decision and self.must_not_replace_regime
        ):
            raise ValueError("active R6 qualification cannot authorize production behavior")


class ActiveR6QualificationProvider(Protocol):
    """Read one exact active qualification through its canonical owner."""

    def get_exact_active(
        self,
        *,
        qualification_ref: R6QualificationRef,
        as_of: datetime,
    ) -> ActiveR6QualificationEvidence | None:
        """Return an exact active internal qualification or explicit absence."""


class R6MonitoringPolicyProvider(Protocol):
    """Read one exact versioned monitoring policy from Research ownership."""

    def get_exact(
        self,
        *,
        policy_id: str,
        policy_version: str,
        expected_policy_hash: str,
        qualification_ref: R6QualificationRef,
        as_of: datetime,
    ) -> R6MonitoringPolicy | None:
        """Return an exact policy known at ``as_of`` or explicit absence."""


class R6MonitoringRawFactProvider(Protocol):
    """Read canonical owner facts without accepting caller-provided values."""

    def list_exact(
        self,
        *,
        qualification_ref: R6QualificationRef,
        policy_id: str,
        policy_version: str,
        expected_policy_hash: str,
        period_calendar_id: str,
        period_calendar_version: str,
        period_calendar_hash: str,
        as_of: datetime,
    ) -> tuple[R6MonitoringObservation, ...]:
        """Return all bounded exact facts required by the monitoring policy."""


class R6MonitoringPeriodCalendarProvider(Protocol):
    """Read one exact owner-recorded canonical period manifest."""

    def get_exact(
        self,
        *,
        source_owner: str,
        calendar_id: str,
        calendar_version: str,
        expected_calendar_hash: str,
        as_of: datetime,
    ) -> R6MonitoringPeriodCalendar | None:
        """Return the exact calendar manifest known at ``as_of`` or absence."""


@dataclass(frozen=True)
class EvaluateR6MonitoringCommand:
    """Identity/cutoff-only command; no thresholds or metric values are accepted."""

    qualification_ref: R6QualificationRef
    policy_id: str
    policy_version: str
    expected_policy_hash: str
    as_of: datetime

    def __post_init__(self) -> None:
        _require_token(self.policy_id, "EvaluateR6MonitoringCommand.policy_id")
        _require_token(self.policy_version, "EvaluateR6MonitoringCommand.policy_version")
        _require_hash(
            self.expected_policy_hash,
            "EvaluateR6MonitoringCommand.expected_policy_hash",
        )
        _require_aware(self.as_of, "EvaluateR6MonitoringCommand.as_of")


class EvaluateR6Monitoring:
    """Re-read exact owners and recompute an internal retirement-review result."""

    def __init__(
        self,
        *,
        active_qualification_provider: ActiveR6QualificationProvider,
        policy_provider: R6MonitoringPolicyProvider,
        period_calendar_provider: R6MonitoringPeriodCalendarProvider,
        raw_fact_provider: R6MonitoringRawFactProvider,
    ) -> None:
        self._active_qualification_provider = active_qualification_provider
        self._policy_provider = policy_provider
        self._period_calendar_provider = period_calendar_provider
        self._raw_fact_provider = raw_fact_provider

    def execute(self, command: EvaluateR6MonitoringCommand) -> R6MonitoringAssessment:
        """Evaluate exact evidence without lifecycle, current, or execution side effects."""

        active = self._active_qualification_provider.get_exact_active(
            qualification_ref=command.qualification_ref,
            as_of=command.as_of,
        )
        if (
            active is None
            or active.qualification_ref != command.qualification_ref
            or active.known_at > command.as_of
        ):
            return evaluate_r6_monitoring(
                qualification_ref=command.qualification_ref,
                qualification_content_hash=None,
                requested_policy_id=command.policy_id,
                requested_policy_version=command.policy_version,
                expected_policy_hash=command.expected_policy_hash,
                policy=None,
                period_calendar=None,
                observations=(),
                evaluated_at=command.as_of,
            )
        policy = self._policy_provider.get_exact(
            policy_id=command.policy_id,
            policy_version=command.policy_version,
            expected_policy_hash=command.expected_policy_hash,
            qualification_ref=command.qualification_ref,
            as_of=command.as_of,
        )
        if policy is None:
            return evaluate_r6_monitoring(
                qualification_ref=command.qualification_ref,
                qualification_content_hash=active.qualification_ref.assessment_hash,
                requested_policy_id=command.policy_id,
                requested_policy_version=command.policy_version,
                expected_policy_hash=command.expected_policy_hash,
                policy=None,
                period_calendar=None,
                observations=(),
                evaluated_at=command.as_of,
            )
        period_calendar = self._period_calendar_provider.get_exact(
            source_owner=policy.expected_period_calendar_owner,
            calendar_id=policy.expected_period_calendar_id,
            calendar_version=policy.expected_period_calendar_version,
            expected_calendar_hash=policy.expected_period_calendar_hash,
            as_of=command.as_of,
        )
        if period_calendar is None:
            return evaluate_r6_monitoring(
                qualification_ref=command.qualification_ref,
                qualification_content_hash=active.qualification_ref.assessment_hash,
                requested_policy_id=command.policy_id,
                requested_policy_version=command.policy_version,
                expected_policy_hash=command.expected_policy_hash,
                policy=policy,
                period_calendar=None,
                observations=(),
                evaluated_at=command.as_of,
            )
        observations = self._raw_fact_provider.list_exact(
            qualification_ref=command.qualification_ref,
            policy_id=command.policy_id,
            policy_version=command.policy_version,
            expected_policy_hash=command.expected_policy_hash,
            period_calendar_id=policy.expected_period_calendar_id,
            period_calendar_version=policy.expected_period_calendar_version,
            period_calendar_hash=policy.expected_period_calendar_hash,
            as_of=command.as_of,
        )
        return evaluate_r6_monitoring(
            qualification_ref=command.qualification_ref,
            qualification_content_hash=active.qualification_ref.assessment_hash,
            requested_policy_id=command.policy_id,
            requested_policy_version=command.policy_version,
            expected_policy_hash=command.expected_policy_hash,
            policy=policy,
            period_calendar=period_calendar,
            observations=observations,
            evaluated_at=command.as_of,
        )


__all__ = [
    "ActiveR6QualificationEvidence",
    "ActiveR6QualificationProvider",
    "EvaluateR6Monitoring",
    "EvaluateR6MonitoringCommand",
    "R6MonitoringPolicyProvider",
    "R6MonitoringPeriodCalendarProvider",
    "R6MonitoringRawFactProvider",
]
