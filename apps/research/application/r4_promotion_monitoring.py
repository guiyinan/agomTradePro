"""ID/as-of-only orchestration for R4 post-promotion monitoring."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from apps.research.domain.r4_promotion_decision import (
    R4PromotionDecision,
    r4_promotion_decision_hash,
)
from apps.research.domain.r4_promotion_evidence import (
    R4PromotionR3AttestationEvidence,
    r4_promotion_r3_attestation_evidence_hash,
)
from apps.research.domain.r4_promotion_lifecycle import R4PromotionDecisionIdentity
from apps.research.domain.r4_promotion_monitoring import (
    R4MonitoringAssessment,
    R4MonitoringObservation,
    R4MonitoringPeriodCalendar,
    R4MonitoringPolicy,
    evaluate_r4_promotion_monitoring,
    r4_monitoring_observation_hash,
    r4_monitoring_period_calendar_hash,
    r4_monitoring_policy_hash,
)
from apps.research.domain.r4_promotion_record_seal import (
    R4PromotionPortfolioRecordSeal,
    r4_promotion_portfolio_record_seal_hash,
)
from apps.research.domain.r4_promotion_scope_policy import r4_promotion_policy_hash
from apps.research.domain.r4_promotion_trial import r4_promotion_trial_seal_hash


def _require_token(value: object, field_name: str) -> None:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > 192
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{field_name} must be a bounded non-blank token")


def _require_hash(value: object, field_name: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdefABCDEF" for character in value)
    ):
        raise ValueError(f"{field_name} must be a SHA-256 digest")


def _require_aware(value: object, field_name: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


class R4MonitoringUnavailable(RuntimeError):
    """A trusted clock, UoW, or canonical owner could not answer exactly."""


class R4MonitoringClock(Protocol):
    """Trusted server clock for rejecting caller-selected future cutoffs."""

    def now(self) -> datetime:
        """Return one authoritative timezone-aware timestamp."""


class R4MonitoringUnitOfWork(Protocol):
    """One explicit read transaction shared by every owner provider."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the stable transaction identity."""

    def atomic(self) -> AbstractContextManager[None]:
        """Open the exact read transaction used by all providers."""


class _UnitOfWorkBound(Protocol):
    @property
    def unit_of_work_key(self) -> str:
        """Return the stable transaction identity."""


class R4MonitoringActiveDecisionProvider(_UnitOfWorkBound, Protocol):
    """Resolve one exact active R4 decision by immutable identity."""

    def get_exact_active(
        self,
        *,
        active_decision: R4PromotionDecisionIdentity,
        as_of: datetime,
    ) -> R4PromotionDecision | None:
        """Return the exact active decision or explicit absence."""


class R4MonitoringPolicyProvider(_UnitOfWorkBound, Protocol):
    """Read one exact Research-owned monitoring policy."""

    def get_exact(
        self,
        *,
        policy_id: str,
        policy_version: str,
        expected_policy_hash: str,
        active_decision: R4PromotionDecisionIdentity,
        as_of: datetime,
    ) -> R4MonitoringPolicy | None:
        """Return the exact policy known at ``as_of`` or explicit absence."""


class R4MonitoringPortfolioResultProvider(_UnitOfWorkBound, Protocol):
    """Read the exact Portfolio result sealed by the active decision."""

    def get_exact(
        self,
        *,
        record_id: str,
        record_version: str,
        expected_record_hash: str,
        as_of: datetime,
    ) -> R4PromotionPortfolioRecordSeal | None:
        """Return the exact Portfolio projection or explicit absence."""


class R4MonitoringR3AttestationProvider(_UnitOfWorkBound, Protocol):
    """Read the exact live R3 attestation used by the active decision."""

    def get_exact(
        self,
        *,
        artifact_id: str,
        artifact_version: str,
        artifact_content_hash: str,
        decision_id: str,
        decision_version: str,
        decision_content_hash: str,
        expected_attestation_hash: str,
        as_of: datetime,
    ) -> R4PromotionR3AttestationEvidence | None:
        """Return the exact current R3 projection or explicit absence."""


class R4MonitoringPeriodCalendarProvider(_UnitOfWorkBound, Protocol):
    """Read the owner-recorded canonical monitoring calendar."""

    def get_exact(
        self,
        *,
        source_owner: str,
        calendar_id: str,
        calendar_version: str,
        expected_calendar_hash: str,
        as_of: datetime,
    ) -> R4MonitoringPeriodCalendar | None:
        """Return the exact calendar known at ``as_of`` or explicit absence."""


class R4MonitoringRawFactProvider(_UnitOfWorkBound, Protocol):
    """Read canonical post-promotion facts without caller-provided values."""

    def list_exact(
        self,
        *,
        active_decision: R4PromotionDecisionIdentity,
        policy_id: str,
        policy_version: str,
        expected_policy_hash: str,
        calendar_id: str,
        calendar_version: str,
        expected_calendar_hash: str,
        as_of: datetime,
    ) -> tuple[R4MonitoringObservation, ...]:
        """Return the bounded facts required by the exact policy and calendar."""


@dataclass(frozen=True)
class EvaluateR4PromotionMonitoringCommand:
    """Identity/cutoff-only command; it accepts no thresholds or raw values."""

    active_decision: R4PromotionDecisionIdentity
    policy_id: str
    policy_version: str
    expected_policy_hash: str
    as_of: datetime

    def __post_init__(self) -> None:
        _require_decision_identity_hashes(self.active_decision)
        _require_token(self.policy_id, "EvaluateR4PromotionMonitoringCommand.policy_id")
        _require_token(
            self.policy_version,
            "EvaluateR4PromotionMonitoringCommand.policy_version",
        )
        _require_hash(
            self.expected_policy_hash,
            "EvaluateR4PromotionMonitoringCommand.expected_policy_hash",
        )
        _require_aware(self.as_of, "EvaluateR4PromotionMonitoringCommand.as_of")


@dataclass(frozen=True)
class R4MonitoringEvaluationEvidence:
    """Exact owner graph used for one locally recomputed assessment."""

    active_decision: R4PromotionDecision | None
    portfolio_result: R4PromotionPortfolioRecordSeal | None
    current_r3_attestation: R4PromotionR3AttestationEvidence | None
    policy: R4MonitoringPolicy | None
    period_calendar: R4MonitoringPeriodCalendar | None
    observations: tuple[R4MonitoringObservation, ...]
    assessment: R4MonitoringAssessment


class EvaluateR4PromotionMonitoring:
    """Re-read every exact owner inside one UoW and recompute monitoring."""

    def __init__(
        self,
        *,
        active_decision_provider: R4MonitoringActiveDecisionProvider,
        policy_provider: R4MonitoringPolicyProvider,
        portfolio_result_provider: R4MonitoringPortfolioResultProvider,
        r3_attestation_provider: R4MonitoringR3AttestationProvider,
        period_calendar_provider: R4MonitoringPeriodCalendarProvider,
        raw_fact_provider: R4MonitoringRawFactProvider,
        unit_of_work: R4MonitoringUnitOfWork,
        clock: R4MonitoringClock,
    ) -> None:
        self._active_decision_provider = active_decision_provider
        self._policy_provider = policy_provider
        self._portfolio_result_provider = portfolio_result_provider
        self._r3_attestation_provider = r3_attestation_provider
        self._period_calendar_provider = period_calendar_provider
        self._raw_fact_provider = raw_fact_provider
        self._unit_of_work = unit_of_work
        self._clock = clock
        try:
            keys = self._current_uow_keys()
        except Exception as error:
            raise R4MonitoringUnavailable("R4 monitoring UoW identity is unavailable") from error
        if len(keys) != 1:
            raise R4MonitoringUnavailable("R4 monitoring owners use different units of work")
        self._expected_uow_key = next(iter(keys))

    @property
    def unit_of_work_key(self) -> str:
        """Return the live shared owner transaction identity."""

        self._require_unchanged_uow()
        return self._expected_uow_key

    def execute(
        self,
        command: EvaluateR4PromotionMonitoringCommand,
    ) -> R4MonitoringAssessment:
        """Return only the research assessment, with no lifecycle side effect."""

        return self.execute_evidence(command).assessment

    def execute_evidence(
        self,
        command: EvaluateR4PromotionMonitoringCommand,
    ) -> R4MonitoringEvaluationEvidence:
        """Return the exact owner graph and locally recomputed assessment."""

        try:
            _require_command_contract(command)
        except Exception as error:
            raise R4MonitoringUnavailable("R4 monitoring command is invalid") from error
        try:
            server_now = self._clock.now()
            _require_aware(server_now, "R4MonitoringClock.now")
        except Exception as error:
            raise R4MonitoringUnavailable("trusted R4 monitoring clock is unavailable") from error
        if command.as_of > server_now:
            raise R4MonitoringUnavailable("future R4 monitoring as_of is forbidden")
        self._require_unchanged_uow()
        try:
            with self._unit_of_work.atomic():
                self._require_unchanged_uow()
                return self._execute_atomic(command)
        except R4MonitoringUnavailable:
            raise
        except Exception as error:
            raise R4MonitoringUnavailable("R4 monitoring owner graph is unavailable") from error

    def _execute_atomic(
        self,
        command: EvaluateR4PromotionMonitoringCommand,
    ) -> R4MonitoringEvaluationEvidence:
        active = self._active_decision_provider.get_exact_active(
            active_decision=command.active_decision,
            as_of=command.as_of,
        )
        if active is not None:
            if type(active) is not R4PromotionDecision:
                raise TypeError("active decision owner returned an invalid type")
            _require_decision_hash_contract(active)
        if active is None:
            return self._evaluate(
                command=command,
                active=None,
                portfolio=None,
                r3=None,
                policy=None,
                calendar=None,
                observations=(),
            )

        record = active.trial.portfolio_record
        portfolio = self._portfolio_result_provider.get_exact(
            record_id=record.record_id,
            record_version=record.record_version,
            expected_record_hash=record.record_hash,
            as_of=command.as_of,
        )
        if portfolio is not None:
            if type(portfolio) is not R4PromotionPortfolioRecordSeal:
                raise TypeError("Portfolio owner returned an invalid type")
            _require_portfolio_hash_contract(portfolio)

        expected_r3 = active.trial.current_r3_attestation
        r3 = self._r3_attestation_provider.get_exact(
            artifact_id=expected_r3.artifact_id,
            artifact_version=expected_r3.artifact_version,
            artifact_content_hash=expected_r3.artifact_content_hash,
            decision_id=expected_r3.decision_id,
            decision_version=expected_r3.decision_version,
            decision_content_hash=expected_r3.decision_content_hash,
            expected_attestation_hash=expected_r3.attestation_hash,
            as_of=command.as_of,
        )
        if r3 is not None:
            if type(r3) is not R4PromotionR3AttestationEvidence:
                raise TypeError("R3 owner returned an invalid type")
            _require_r3_hash_contract(r3)

        policy = self._policy_provider.get_exact(
            policy_id=command.policy_id,
            policy_version=command.policy_version,
            expected_policy_hash=command.expected_policy_hash,
            active_decision=command.active_decision,
            as_of=command.as_of,
        )
        if policy is not None:
            if type(policy) is not R4MonitoringPolicy:
                raise TypeError("monitoring policy owner returned an invalid type")
            _require_monitoring_policy_hash_contract(policy)
        if policy is None:
            return self._evaluate(
                command=command,
                active=active,
                portfolio=portfolio,
                r3=r3,
                policy=None,
                calendar=None,
                observations=(),
            )

        calendar = self._period_calendar_provider.get_exact(
            source_owner=policy.expected_period_calendar_owner,
            calendar_id=policy.expected_period_calendar_id,
            calendar_version=policy.expected_period_calendar_version,
            expected_calendar_hash=policy.expected_period_calendar_hash,
            as_of=command.as_of,
        )
        if calendar is not None:
            if type(calendar) is not R4MonitoringPeriodCalendar:
                raise TypeError("period calendar owner returned an invalid type")
            _require_calendar_hash_contract(calendar)
        if calendar is None:
            return self._evaluate(
                command=command,
                active=active,
                portfolio=portfolio,
                r3=r3,
                policy=policy,
                calendar=None,
                observations=(),
            )

        observations = self._raw_fact_provider.list_exact(
            active_decision=command.active_decision,
            policy_id=policy.policy_id,
            policy_version=policy.policy_version,
            expected_policy_hash=policy.content_hash,
            calendar_id=calendar.calendar_id,
            calendar_version=calendar.calendar_version,
            expected_calendar_hash=calendar.content_hash,
            as_of=command.as_of,
        )
        if not isinstance(observations, tuple) or any(
            type(item) is not R4MonitoringObservation for item in observations
        ):
            raise TypeError("raw-fact owner returned an invalid type")
        for observation in observations:
            _require_observation_hash_contract(observation)
        self._require_unchanged_uow()
        return self._evaluate(
            command=command,
            active=active,
            portfolio=portfolio,
            r3=r3,
            policy=policy,
            calendar=calendar,
            observations=observations,
        )

    def _evaluate(
        self,
        *,
        command: EvaluateR4PromotionMonitoringCommand,
        active: R4PromotionDecision | None,
        portfolio: R4PromotionPortfolioRecordSeal | None,
        r3: R4PromotionR3AttestationEvidence | None,
        policy: R4MonitoringPolicy | None,
        calendar: R4MonitoringPeriodCalendar | None,
        observations: tuple[R4MonitoringObservation, ...],
    ) -> R4MonitoringEvaluationEvidence:
        self._require_unchanged_uow()
        assessment = evaluate_r4_promotion_monitoring(
            requested_active_decision=command.active_decision,
            requested_policy_id=command.policy_id,
            requested_policy_version=command.policy_version,
            expected_policy_hash=command.expected_policy_hash,
            active_decision=active,
            portfolio_result=portfolio,
            current_r3_attestation=r3,
            policy=policy,
            period_calendar=calendar,
            observations=observations,
            evaluated_at=command.as_of,
        )
        return R4MonitoringEvaluationEvidence(
            active_decision=active,
            portfolio_result=portfolio,
            current_r3_attestation=r3,
            policy=policy,
            period_calendar=calendar,
            observations=observations,
            assessment=assessment,
        )

    def _current_uow_keys(self) -> set[str]:
        return {
            _provider_uow_key(self._active_decision_provider, "active_decision_provider"),
            _provider_uow_key(self._policy_provider, "policy_provider"),
            _provider_uow_key(self._portfolio_result_provider, "portfolio_result_provider"),
            _provider_uow_key(self._r3_attestation_provider, "r3_attestation_provider"),
            _provider_uow_key(self._period_calendar_provider, "period_calendar_provider"),
            _provider_uow_key(self._raw_fact_provider, "raw_fact_provider"),
            _provider_uow_key(self._unit_of_work, "unit_of_work"),
        }

    def _require_unchanged_uow(self) -> None:
        try:
            keys = self._current_uow_keys()
        except Exception as error:
            raise R4MonitoringUnavailable("R4 monitoring UoW identity is unavailable") from error
        if keys != {self._expected_uow_key}:
            raise R4MonitoringUnavailable("R4 monitoring UoW identity changed")


def _provider_uow_key(provider: _UnitOfWorkBound, label: str) -> str:
    try:
        key = provider.unit_of_work_key
    except Exception as error:
        raise ValueError(f"{label}.unit_of_work_key is required") from error
    if not isinstance(key, str) or not key.strip():
        raise ValueError(f"{label}.unit_of_work_key must be non-blank")
    return key


def _require_command_contract(command: EvaluateR4PromotionMonitoringCommand) -> None:
    if type(command) is not EvaluateR4PromotionMonitoringCommand:
        raise ValueError("R4 monitoring command type is invalid")
    _require_decision_identity_hashes(command.active_decision)
    rebuilt = EvaluateR4PromotionMonitoringCommand(
        active_decision=command.active_decision,
        policy_id=command.policy_id,
        policy_version=command.policy_version,
        expected_policy_hash=command.expected_policy_hash,
        as_of=command.as_of,
    )
    if rebuilt != command:
        raise ValueError("R4 monitoring command failed live validation")


def _require_decision_identity_hashes(identity: R4PromotionDecisionIdentity) -> None:
    if type(identity) is not R4PromotionDecisionIdentity:
        raise ValueError("R4 monitoring active decision identity is invalid")
    for value, field_name in (
        (identity.content_hash, "content_hash"),
        (identity.scope.content_hash, "scope.content_hash"),
        (identity.trial_content_hash, "trial_content_hash"),
        (identity.portfolio_record_hash, "portfolio_record_hash"),
        (identity.policy_content_hash, "policy_content_hash"),
        (identity.current_r3_content_hash, "current_r3_content_hash"),
    ):
        _require_hash(value, f"R4PromotionDecisionIdentity.{field_name}")


def _require_decision_hash_contract(decision: R4PromotionDecision) -> None:
    _require_hash(decision.content_hash, "R4PromotionDecision.content_hash")
    _require_hash(decision.policy.content_hash, "R4PromotionPolicy.content_hash")
    _require_hash(decision.trial.content_hash, "R4PromotionTrialSeal.content_hash")
    _require_portfolio_hash_contract(decision.trial.portfolio_record)
    _require_r3_hash_contract(decision.trial.current_r3_attestation)
    r4_promotion_decision_hash(decision)
    r4_promotion_policy_hash(decision.policy)
    r4_promotion_trial_seal_hash(decision.trial)


def _require_portfolio_hash_contract(record: R4PromotionPortfolioRecordSeal) -> None:
    for value, field_name in (
        (record.record_hash, "record_hash"),
        (record.content_hash, "content_hash"),
        (record.study_content_hash, "study_content_hash"),
        (record.artifact_hash, "artifact_hash"),
    ):
        _require_hash(value, f"R4PromotionPortfolioRecordSeal.{field_name}")
    r4_promotion_portfolio_record_seal_hash(record)


def _require_r3_hash_contract(evidence: R4PromotionR3AttestationEvidence) -> None:
    for value, field_name in (
        (evidence.artifact_content_hash, "artifact_content_hash"),
        (evidence.decision_content_hash, "decision_content_hash"),
        (evidence.attestation_hash, "attestation_hash"),
        (evidence.content_hash, "content_hash"),
    ):
        _require_hash(value, f"R4PromotionR3AttestationEvidence.{field_name}")
    r4_promotion_r3_attestation_evidence_hash(evidence)


def _require_monitoring_policy_hash_contract(policy: R4MonitoringPolicy) -> None:
    _require_hash(policy.content_hash, "R4MonitoringPolicy.content_hash")
    _require_hash(policy.expected_pit_manifest_hash, "expected_pit_manifest_hash")
    _require_hash(policy.expected_label_set_hash, "expected_label_set_hash")
    _require_hash(policy.expected_data_schema_hash, "expected_data_schema_hash")
    _require_hash(policy.expected_period_calendar_hash, "expected_period_calendar_hash")
    validated = policy.validated_copy()
    if validated != policy:
        raise ValueError("R4 monitoring policy failed live validation")
    recomputed = r4_monitoring_policy_hash(validated)
    if policy.content_hash.lower() != recomputed.lower():
        raise ValueError("R4 monitoring policy seal is invalid")


def _require_calendar_hash_contract(calendar: R4MonitoringPeriodCalendar) -> None:
    _require_hash(calendar.content_hash, "R4MonitoringPeriodCalendar.content_hash")
    for entry in calendar.entries:
        _require_hash(entry.period_id, "R4MonitoringPeriodEntry.period_id")
    r4_monitoring_period_calendar_hash(calendar)


def _require_observation_hash_contract(observation: R4MonitoringObservation) -> None:
    for value, field_name in (
        (observation.content_hash, "content_hash"),
        (observation.period_id, "period_id"),
        (observation.period_calendar_hash, "period_calendar_hash"),
        (observation.policy_hash, "policy_hash"),
        (observation.portfolio_record_hash, "portfolio_record_hash"),
        (observation.portfolio_record_content_hash, "portfolio_record_content_hash"),
        (observation.r3_attestation_content_hash, "r3_attestation_content_hash"),
        (observation.pit_manifest_hash, "pit_manifest_hash"),
        (observation.observed_label_set_hash, "observed_label_set_hash"),
        (observation.observed_data_schema_hash, "observed_data_schema_hash"),
    ):
        _require_hash(value, f"R4MonitoringObservation.{field_name}")
    r4_monitoring_observation_hash(observation)


__all__ = [
    "EvaluateR4PromotionMonitoring",
    "EvaluateR4PromotionMonitoringCommand",
    "R4MonitoringActiveDecisionProvider",
    "R4MonitoringClock",
    "R4MonitoringEvaluationEvidence",
    "R4MonitoringPeriodCalendarProvider",
    "R4MonitoringPolicyProvider",
    "R4MonitoringPortfolioResultProvider",
    "R4MonitoringR3AttestationProvider",
    "R4MonitoringRawFactProvider",
    "R4MonitoringUnavailable",
    "R4MonitoringUnitOfWork",
]
