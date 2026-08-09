"""Django composition root for persisted research-only R6 monitoring."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from apps.research.application.state_model_monitoring import (
    ActiveR6QualificationEvidence,
    ActiveR6QualificationProvider,
    EvaluateR6Monitoring,
    EvaluateR6MonitoringCommand,
    R6MonitoringClock,
    R6MonitoringPeriodCalendarProvider,
    R6MonitoringPolicyProvider,
    R6MonitoringRawFactProvider,
    R6MonitoringUnavailable,
)
from apps.research.application.state_model_monitoring_persistence import (
    AuditR6MonitoringAssessments,
    GetExactR6MonitoringAssessment,
    R6MonitoringPersistedAssessment,
    R6MonitoringPersistenceUnavailable,
    RegisterR6MonitoringAssessment,
    RegisterR6MonitoringAssessmentCommand,
)
from apps.research.domain.state_model_monitoring import (
    R6MonitoringObservation,
    R6MonitoringPeriodCalendar,
    R6MonitoringPolicy,
)
from apps.research.domain.state_model_qualification_lifecycle import R6QualificationRef
from apps.research.infrastructure.state_model_monitoring_models import (
    _require_active_r6_monitoring_uow,
)
from apps.research.infrastructure.state_model_monitoring_repository import (
    DjangoR6MonitoringClock,
    DjangoR6MonitoringRepository,
    _DjangoR6MonitoringStore,
)


def _owner_uow_key(
    source: (
        ActiveR6QualificationProvider
        | R6MonitoringPolicyProvider
        | R6MonitoringPeriodCalendarProvider
        | R6MonitoringRawFactProvider
    ),
) -> str:
    try:
        candidate = source.unit_of_work_key
    except (AttributeError, TypeError) as error:
        raise ValueError("R6 monitoring owner unit_of_work_key is required") from error
    if not isinstance(candidate, str) or not candidate.strip():
        raise ValueError("R6 monitoring owner unit_of_work_key is invalid")
    return candidate


class _ActiveQualificationGuard:
    def __init__(self, source: ActiveR6QualificationProvider) -> None:
        self._source = source

    @property
    def unit_of_work_key(self) -> str:
        """Delegate the owner's explicit transaction identity."""

        return self._source.unit_of_work_key

    def get_exact_active(
        self,
        *,
        qualification_ref: R6QualificationRef,
        as_of: datetime,
    ) -> ActiveR6QualificationEvidence | None:
        _require_active_r6_monitoring_uow()
        return self._source.get_exact_active(
            qualification_ref=qualification_ref,
            as_of=as_of,
        )


class _PolicyGuard:
    def __init__(self, source: R6MonitoringPolicyProvider) -> None:
        self._source = source

    @property
    def unit_of_work_key(self) -> str:
        """Delegate the owner's explicit transaction identity."""

        return self._source.unit_of_work_key

    def get_exact(
        self,
        *,
        policy_id: str,
        policy_version: str,
        expected_policy_hash: str,
        qualification_ref: R6QualificationRef,
        as_of: datetime,
    ) -> R6MonitoringPolicy | None:
        _require_active_r6_monitoring_uow()
        return self._source.get_exact(
            policy_id=policy_id,
            policy_version=policy_version,
            expected_policy_hash=expected_policy_hash,
            qualification_ref=qualification_ref,
            as_of=as_of,
        )


class _PeriodCalendarGuard:
    def __init__(self, source: R6MonitoringPeriodCalendarProvider) -> None:
        self._source = source

    @property
    def unit_of_work_key(self) -> str:
        """Delegate the owner's explicit transaction identity."""

        return self._source.unit_of_work_key

    def get_exact(
        self,
        *,
        source_owner: str,
        calendar_id: str,
        calendar_version: str,
        expected_calendar_hash: str,
        as_of: datetime,
    ) -> R6MonitoringPeriodCalendar | None:
        _require_active_r6_monitoring_uow()
        return self._source.get_exact(
            source_owner=source_owner,
            calendar_id=calendar_id,
            calendar_version=calendar_version,
            expected_calendar_hash=expected_calendar_hash,
            as_of=as_of,
        )


class _RawFactGuard:
    def __init__(self, source: R6MonitoringRawFactProvider) -> None:
        self._source = source

    @property
    def unit_of_work_key(self) -> str:
        """Delegate the owner's explicit transaction identity."""

        return self._source.unit_of_work_key

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
        _require_active_r6_monitoring_uow()
        return self._source.list_exact(
            qualification_ref=qualification_ref,
            policy_id=policy_id,
            policy_version=policy_version,
            expected_policy_hash=expected_policy_hash,
            period_calendar_id=period_calendar_id,
            period_calendar_version=period_calendar_version,
            period_calendar_hash=period_calendar_hash,
            as_of=as_of,
        )


class _MonitoringWriter:
    def __init__(
        self,
        *,
        store: _DjangoR6MonitoringStore,
        evaluator: EvaluateR6Monitoring,
    ) -> None:
        self._store = store
        self._evaluator = evaluator

    def register(
        self,
        command: RegisterR6MonitoringAssessmentCommand,
    ) -> R6MonitoringPersistedAssessment:
        _require_active_r6_monitoring_uow()
        if command.as_of > self._store.server_now():
            raise R6MonitoringPersistenceUnavailable(
                "future R6 monitoring registration cutoff is unavailable"
            )
        try:
            evidence = self._evaluator.execute_evidence(
                EvaluateR6MonitoringCommand(
                    qualification_ref=command.qualification_ref,
                    policy_id=command.policy_id,
                    policy_version=command.policy_version,
                    expected_policy_hash=command.expected_policy_hash,
                    as_of=command.as_of,
                )
            )
        except R6MonitoringUnavailable as error:
            raise R6MonitoringPersistenceUnavailable(str(error)) from error
        active = evidence.active_qualification
        policy = evidence.policy
        calendar = evidence.period_calendar
        if active is None or policy is None or calendar is None:
            raise R6MonitoringPersistenceUnavailable(
                "exact active qualification, policy, and calendar are required"
            )
        if (
            active.qualification_ref != command.qualification_ref
            or policy.qualification_ref != command.qualification_ref
            or policy.content_hash.lower() != command.expected_policy_hash.lower()
            or calendar.content_hash.lower() != policy.expected_period_calendar_hash.lower()
            or calendar.source_owner != policy.expected_period_calendar_owner
            or calendar.calendar_id != policy.expected_period_calendar_id
            or calendar.calendar_version != policy.expected_period_calendar_version
            or policy.recorded_at > command.as_of
            or calendar.recorded_at > command.as_of
            or not calendar.is_active_at(command.as_of)
        ):
            raise R6MonitoringPersistenceUnavailable(
                "R6 monitoring owner graph was substituted or is not PIT-valid"
            )
        return self._store.append_bundle(
            policy=policy,
            period_calendar=calendar,
            observations=evidence.observations,
            assessment=evidence.assessment,
        )


class _RegistrationClosure:
    def __init__(
        self,
        *,
        store: _DjangoR6MonitoringStore,
        writer: _MonitoringWriter,
    ) -> None:
        self._store = store
        self._writer = writer

    def register(
        self,
        command: RegisterR6MonitoringAssessmentCommand,
    ) -> R6MonitoringPersistedAssessment:
        with self._store.atomic():
            return self._writer.register(command)


@dataclass(frozen=True)
class DjangoR6MonitoringRuntime:
    """Research-only write/read/audit facades; no consumer is exposed."""

    register: RegisterR6MonitoringAssessment
    get_exact: GetExactR6MonitoringAssessment
    audit: AuditR6MonitoringAssessments


def build_django_r6_monitoring_runtime(
    *,
    active_qualification_provider: ActiveR6QualificationProvider | None,
    policy_provider: R6MonitoringPolicyProvider | None,
    period_calendar_provider: R6MonitoringPeriodCalendarProvider | None,
    raw_fact_provider: R6MonitoringRawFactProvider | None,
    using: str = "default",
    clock: R6MonitoringClock | None = None,
) -> DjangoR6MonitoringRuntime:
    """Build Phase B only when every canonical owner provider is supplied."""

    if (
        active_qualification_provider is None
        or policy_provider is None
        or period_calendar_provider is None
        or raw_fact_provider is None
    ):
        raise R6MonitoringPersistenceUnavailable(
            "canonical R6 monitoring owner providers are unavailable"
        )
    authoritative_clock = clock or DjangoR6MonitoringClock()
    repository = DjangoR6MonitoringRepository(using=using, clock=authoritative_clock)
    store = _DjangoR6MonitoringStore(using=using, clock=authoritative_clock)
    owner_sources = (
        active_qualification_provider,
        policy_provider,
        period_calendar_provider,
        raw_fact_provider,
    )
    keys = {
        store.unit_of_work_key,
        *(_owner_uow_key(source) for source in owner_sources),
    }
    if len(keys) != 1:
        raise ValueError("R6 monitoring owners and Research use different units of work")
    evaluator = EvaluateR6Monitoring(
        active_qualification_provider=_ActiveQualificationGuard(active_qualification_provider),
        policy_provider=_PolicyGuard(policy_provider),
        period_calendar_provider=_PeriodCalendarGuard(period_calendar_provider),
        raw_fact_provider=_RawFactGuard(raw_fact_provider),
        clock=authoritative_clock,
    )
    writer = _MonitoringWriter(store=store, evaluator=evaluator)
    return DjangoR6MonitoringRuntime(
        register=RegisterR6MonitoringAssessment(_RegistrationClosure(store=store, writer=writer)),
        get_exact=GetExactR6MonitoringAssessment(repository),
        audit=AuditR6MonitoringAssessments(repository),
    )


__all__ = [
    "DjangoR6MonitoringRuntime",
    "build_django_r6_monitoring_runtime",
]
