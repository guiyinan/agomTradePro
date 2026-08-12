"""ID/as-of-only orchestration for research-only R6 monitoring."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from hashlib import sha256
from typing import Protocol

from apps.research.domain.state_model_monitoring import (
    R6MonitoringAssessment,
    R6MonitoringObservation,
    R6MonitoringPeriodCalendar,
    R6MonitoringPolicy,
    evaluate_r6_monitoring,
    r6_monitoring_observation_hash,
    r6_monitoring_period_calendar_hash,
    r6_monitoring_policy_hash,
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


def _require_hash(value: object, field_name: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdefABCDEF" for character in value)
    ):
        raise ValueError(f"{field_name} must be a SHA-256 digest")


class _UnitOfWorkProvider(Protocol):
    @property
    def unit_of_work_key(self) -> str:
        """Return an explicit transaction boundary identity."""


def _provider_uow_key(provider: _UnitOfWorkProvider, label: str) -> str:
    try:
        key = provider.unit_of_work_key
    except (AttributeError, TypeError) as error:
        raise ValueError(f"{label}.unit_of_work_key is required") from error
    if not isinstance(key, str) or not key.strip():
        raise ValueError(f"{label}.unit_of_work_key must be non-blank")
    return key


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _require_policy_hash_contract(policy: R6MonitoringPolicy) -> None:
    _require_hash(policy.content_hash, "R6MonitoringPolicy.content_hash")
    _require_hash(
        policy.qualification_ref.assessment_hash,
        "R6MonitoringPolicy.qualification_ref.assessment_hash",
    )
    _require_hash(
        policy.expected_label_set_hash,
        "R6MonitoringPolicy.expected_label_set_hash",
    )
    _require_hash(
        policy.expected_pit_manifest_hash,
        "R6MonitoringPolicy.expected_pit_manifest_hash",
    )
    _require_hash(
        policy.expected_period_calendar_hash,
        "R6MonitoringPolicy.expected_period_calendar_hash",
    )


def _require_calendar_hash_contract(calendar: R6MonitoringPeriodCalendar) -> None:
    _require_hash(calendar.content_hash, "R6MonitoringPeriodCalendar.content_hash")
    for entry in calendar.entries:
        _require_hash(entry.period_id, "R6MonitoringPeriodEntry.period_id")


def _require_observation_hash_contract(observation: R6MonitoringObservation) -> None:
    for value, field_name in (
        (observation.content_hash, "content_hash"),
        (observation.observation_period_id, "observation_period_id"),
        (observation.period_calendar_hash, "period_calendar_hash"),
        (observation.qualification_ref.assessment_hash, "qualification_ref.assessment_hash"),
        (observation.policy_hash, "policy_hash"),
        (observation.pit_manifest_hash, "pit_manifest_hash"),
        (observation.observed_label_set_hash, "observed_label_set_hash"),
    ):
        _require_hash(value, f"R6MonitoringObservation.{field_name}")


class R6MonitoringUnavailable(RuntimeError):
    """A trusted clock or canonical owner could not answer exactly."""


class R6MonitoringClock(Protocol):
    """Trusted server clock used to reject caller-selected future cutoffs."""

    def now(self) -> datetime:
        """Return one timezone-aware authoritative timestamp."""


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
    content_hash: str = field(init=False)

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
        object.__setattr__(self, "content_hash", _active_qualification_evidence_hash(self))


def _active_qualification_evidence_hash(evidence: ActiveR6QualificationEvidence) -> str:
    _require_aware(evidence.assessed_at, "ActiveR6QualificationEvidence.assessed_at")
    _require_aware(evidence.known_at, "ActiveR6QualificationEvidence.known_at")
    encoded = json.dumps(
        {
            "schema": "r6-monitoring-active-qualification.v1",
            "qualification_ref": {
                "assessment_id": evidence.qualification_ref.assessment_id,
                "assessment_hash": evidence.qualification_ref.assessment_hash.lower(),
            },
            "candidate_id": evidence.candidate_id,
            "candidate_version": evidence.candidate_version,
            "assessed_at": _utc_text(evidence.assessed_at),
            "known_at": _utc_text(evidence.known_at),
            "research_only": evidence.research_only,
            "must_not_use_for_decision": evidence.must_not_use_for_decision,
            "must_not_replace_regime": evidence.must_not_replace_regime,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


class ActiveR6QualificationProvider(Protocol):
    """Read one exact active qualification through its canonical owner."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the explicit canonical-owner transaction identity."""

    def get_exact_active(
        self,
        *,
        qualification_ref: R6QualificationRef,
        as_of: datetime,
    ) -> ActiveR6QualificationEvidence | None:
        """Return an exact active internal qualification or explicit absence."""


class R6MonitoringPolicyProvider(Protocol):
    """Read one exact versioned monitoring policy from Research ownership."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the explicit canonical-owner transaction identity."""

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

    @property
    def unit_of_work_key(self) -> str:
        """Return the explicit canonical-owner transaction identity."""

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

    @property
    def unit_of_work_key(self) -> str:
        """Return the explicit canonical-owner transaction identity."""

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


@dataclass(frozen=True)
class R6MonitoringEvaluationEvidence:
    """Exact owner graph used for one recomputed monitoring assessment."""

    active_qualification: ActiveR6QualificationEvidence | None
    policy: R6MonitoringPolicy | None
    period_calendar: R6MonitoringPeriodCalendar | None
    observations: tuple[R6MonitoringObservation, ...]
    assessment: R6MonitoringAssessment


class EvaluateR6Monitoring:
    """Re-read exact owners and recompute an internal retirement-review result."""

    def __init__(
        self,
        *,
        active_qualification_provider: ActiveR6QualificationProvider,
        policy_provider: R6MonitoringPolicyProvider,
        period_calendar_provider: R6MonitoringPeriodCalendarProvider,
        raw_fact_provider: R6MonitoringRawFactProvider,
        clock: R6MonitoringClock,
    ) -> None:
        owner_keys = {
            _provider_uow_key(
                active_qualification_provider,
                "active_qualification_provider",
            ),
            _provider_uow_key(policy_provider, "policy_provider"),
            _provider_uow_key(period_calendar_provider, "period_calendar_provider"),
            _provider_uow_key(raw_fact_provider, "raw_fact_provider"),
        }
        if len(owner_keys) != 1:
            raise ValueError("R6 monitoring owners use different units of work")
        self._active_qualification_provider = active_qualification_provider
        self._policy_provider = policy_provider
        self._period_calendar_provider = period_calendar_provider
        self._raw_fact_provider = raw_fact_provider
        self._clock = clock

    def execute(self, command: EvaluateR6MonitoringCommand) -> R6MonitoringAssessment:
        """Evaluate exact evidence without lifecycle, current, or execution side effects."""

        return self.execute_evidence(command).assessment

    def execute_evidence(
        self,
        command: EvaluateR6MonitoringCommand,
    ) -> R6MonitoringEvaluationEvidence:
        """Return the exact owner graph and its locally recomputed assessment."""

        try:
            server_now = self._clock.now()
        except Exception as error:
            raise R6MonitoringUnavailable("trusted R6 monitoring clock is unavailable") from error
        try:
            _require_aware(server_now, "R6MonitoringClock.now")
        except (AttributeError, TypeError, ValueError) as error:
            raise R6MonitoringUnavailable("trusted R6 monitoring clock is invalid") from error
        if command.as_of > server_now:
            raise R6MonitoringUnavailable("future R6 monitoring as_of is forbidden")

        try:
            active = self._active_qualification_provider.get_exact_active(
                qualification_ref=command.qualification_ref,
                as_of=command.as_of,
            )
            if active is not None:
                if type(active) is not ActiveR6QualificationEvidence:
                    raise TypeError("active qualification owner returned an invalid type")
                _require_hash(
                    active.content_hash,
                    "ActiveR6QualificationEvidence.content_hash",
                )
                _require_hash(
                    active.qualification_ref.assessment_hash,
                    "ActiveR6QualificationEvidence.qualification_ref.assessment_hash",
                )
                active_projection_sealed = (
                    active.content_hash.lower()
                    == _active_qualification_evidence_hash(active).lower()
                )
                active_qualification_ref = active.qualification_ref
                qualification_assessed_at = active.assessed_at
                qualification_known_at = active.known_at
                qualification_content_hash = active.qualification_ref.assessment_hash
        except Exception as error:
            raise R6MonitoringUnavailable("active R6 qualification owner is unavailable") from error
        if active is None:
            assessment = evaluate_r6_monitoring(
                qualification_ref=command.qualification_ref,
                qualification_content_hash=None,
                qualification_assessed_at=None,
                qualification_known_at=None,
                requested_policy_id=command.policy_id,
                requested_policy_version=command.policy_version,
                expected_policy_hash=command.expected_policy_hash,
                policy=None,
                period_calendar=None,
                observations=(),
                evaluated_at=command.as_of,
            )
            return R6MonitoringEvaluationEvidence(None, None, None, (), assessment)
        if (
            not active_projection_sealed
            or active_qualification_ref != command.qualification_ref
            or qualification_known_at > command.as_of
        ):
            assessment = evaluate_r6_monitoring(
                qualification_ref=command.qualification_ref,
                qualification_content_hash="0" * 64,
                qualification_assessed_at=qualification_assessed_at,
                qualification_known_at=qualification_known_at,
                requested_policy_id=command.policy_id,
                requested_policy_version=command.policy_version,
                expected_policy_hash=command.expected_policy_hash,
                policy=None,
                period_calendar=None,
                observations=(),
                evaluated_at=command.as_of,
            )
            return R6MonitoringEvaluationEvidence(active, None, None, (), assessment)
        try:
            policy = self._policy_provider.get_exact(
                policy_id=command.policy_id,
                policy_version=command.policy_version,
                expected_policy_hash=command.expected_policy_hash,
                qualification_ref=command.qualification_ref,
                as_of=command.as_of,
            )
            if policy is not None:
                if type(policy) is not R6MonitoringPolicy:
                    raise TypeError("policy owner returned an invalid type")
                _require_policy_hash_contract(policy)
                r6_monitoring_policy_hash(policy)
                period_calendar_owner = policy.expected_period_calendar_owner
                period_calendar_id = policy.expected_period_calendar_id
                period_calendar_version = policy.expected_period_calendar_version
                period_calendar_hash = policy.expected_period_calendar_hash
        except Exception as error:
            raise R6MonitoringUnavailable("R6 monitoring policy owner is unavailable") from error
        if policy is None:
            assessment = evaluate_r6_monitoring(
                qualification_ref=command.qualification_ref,
                qualification_content_hash=qualification_content_hash,
                qualification_assessed_at=qualification_assessed_at,
                qualification_known_at=qualification_known_at,
                requested_policy_id=command.policy_id,
                requested_policy_version=command.policy_version,
                expected_policy_hash=command.expected_policy_hash,
                policy=None,
                period_calendar=None,
                observations=(),
                evaluated_at=command.as_of,
            )
            return R6MonitoringEvaluationEvidence(active, None, None, (), assessment)
        try:
            period_calendar = self._period_calendar_provider.get_exact(
                source_owner=period_calendar_owner,
                calendar_id=period_calendar_id,
                calendar_version=period_calendar_version,
                expected_calendar_hash=period_calendar_hash,
                as_of=command.as_of,
            )
            if period_calendar is not None:
                if type(period_calendar) is not R6MonitoringPeriodCalendar:
                    raise TypeError("period calendar owner returned an invalid type")
                _require_calendar_hash_contract(period_calendar)
                r6_monitoring_period_calendar_hash(period_calendar)
        except Exception as error:
            raise R6MonitoringUnavailable(
                "R6 monitoring period calendar owner is unavailable"
            ) from error
        if period_calendar is None:
            assessment = evaluate_r6_monitoring(
                qualification_ref=command.qualification_ref,
                qualification_content_hash=qualification_content_hash,
                qualification_assessed_at=qualification_assessed_at,
                qualification_known_at=qualification_known_at,
                requested_policy_id=command.policy_id,
                requested_policy_version=command.policy_version,
                expected_policy_hash=command.expected_policy_hash,
                policy=policy,
                period_calendar=None,
                observations=(),
                evaluated_at=command.as_of,
            )
            return R6MonitoringEvaluationEvidence(
                active,
                policy,
                None,
                (),
                assessment,
            )
        try:
            observations = self._raw_fact_provider.list_exact(
                qualification_ref=command.qualification_ref,
                policy_id=command.policy_id,
                policy_version=command.policy_version,
                expected_policy_hash=command.expected_policy_hash,
                period_calendar_id=period_calendar_id,
                period_calendar_version=period_calendar_version,
                period_calendar_hash=period_calendar_hash,
                as_of=command.as_of,
            )
            if not isinstance(observations, tuple) or any(
                type(item) is not R6MonitoringObservation for item in observations
            ):
                raise TypeError("raw-fact owner returned an invalid type")
            for observation in observations:
                _require_observation_hash_contract(observation)
                r6_monitoring_observation_hash(observation)
        except Exception as error:
            raise R6MonitoringUnavailable("R6 monitoring raw-fact owner is unavailable") from error
        assessment = evaluate_r6_monitoring(
            qualification_ref=command.qualification_ref,
            qualification_content_hash=qualification_content_hash,
            qualification_assessed_at=qualification_assessed_at,
            qualification_known_at=qualification_known_at,
            requested_policy_id=command.policy_id,
            requested_policy_version=command.policy_version,
            expected_policy_hash=command.expected_policy_hash,
            policy=policy,
            period_calendar=period_calendar,
            observations=observations,
            evaluated_at=command.as_of,
        )
        return R6MonitoringEvaluationEvidence(
            active,
            policy,
            period_calendar,
            observations,
            assessment,
        )


__all__ = [
    "ActiveR6QualificationEvidence",
    "ActiveR6QualificationProvider",
    "EvaluateR6Monitoring",
    "EvaluateR6MonitoringCommand",
    "R6MonitoringClock",
    "R6MonitoringPolicyProvider",
    "R6MonitoringEvaluationEvidence",
    "R6MonitoringPeriodCalendarProvider",
    "R6MonitoringRawFactProvider",
    "R6MonitoringUnavailable",
]
