"""Identity-only orchestration for R7 post-promotion monitoring."""

from __future__ import annotations

from contextlib import AbstractContextManager
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256
from typing import Protocol

from apps.research.domain.r7_post_promotion_monitoring import (
    R7ForecastRealizationFact,
    R7ForecastRealizationOwnerRecord,
    R7PostPromotionMonitoringAssessment,
    evaluate_r7_post_promotion_monitoring,
)
from apps.research.domain.r7_post_promotion_monitoring_contracts import (
    R7LifecycleStreamOwnerEvidence,
    R7MonitoringActiveResult,
    R7MonitoringPeriodCalendar,
    R7MonitoringPeriodEntry,
)
from apps.research.domain.r7_research_result_lifecycle import R7ResultLifecycleEvent
from apps.research.domain.r7_research_result_persistence import PersistedR7ResearchResult

_POLICY_VERSION = "r7-post-promotion-monitoring-policy.v1"


class R7PostPromotionMonitoringUnavailable(RuntimeError):
    """A trusted clock, UoW, or exact authoritative owner is unavailable."""


class R7MonitoringClock(Protocol):
    """Trusted server clock sharing the owner transaction identity."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the exact database/snapshot identity."""

    def now(self) -> datetime:
        """Return one timezone-aware server timestamp."""


class R7MonitoringUnitOfWork(Protocol):
    """Shared transaction boundary for all R7 monitoring owner reads."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the exact database/snapshot identity."""

    def atomic(self) -> AbstractContextManager[None]:
        """Open the shared atomic owner-read transaction."""


class _UnitOfWorkBound(Protocol):
    @property
    def unit_of_work_key(self) -> str:
        """Return the exact database/snapshot identity."""


@dataclass(frozen=True)
class R7PostPromotionMonitoringPolicy:
    """Content-addressed monitoring policy selecting no caller-owned outcomes."""

    policy_id: str
    policy_version: str
    result_id: str
    result_version: str
    result_hash: str
    lifecycle_attestation_id: str
    lifecycle_attestation_version: str
    lifecycle_attestation_hash: str
    calendar_id: str
    calendar_version: str
    calendar_hash: str
    period_id: str
    period_version: str
    period_hash: str
    maximum_subjective_brier_score: Decimal
    maximum_model_brier_score: Decimal
    minimum_forecast_outcome_coverage: Decimal
    recorded_at: datetime
    valid_until: datetime
    automatic_retirement: bool
    research_only: bool
    must_not_use_for_decision: bool
    must_not_execute: bool
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        policy_id: str,
        result_id: str,
        result_version: str,
        result_hash: str,
        lifecycle_attestation_id: str,
        lifecycle_attestation_version: str,
        lifecycle_attestation_hash: str,
        calendar_id: str,
        calendar_version: str,
        calendar_hash: str,
        period_id: str,
        period_version: str,
        period_hash: str,
        maximum_subjective_brier_score: Decimal,
        maximum_model_brier_score: Decimal,
        minimum_forecast_outcome_coverage: Decimal,
        recorded_at: datetime,
        valid_until: datetime,
    ) -> R7PostPromotionMonitoringPolicy:
        """Seal an explicitly preregistered result, calendar member, and rule set."""

        values = (
            policy_id,
            _POLICY_VERSION,
            result_id,
            result_version,
            result_hash.lower(),
            lifecycle_attestation_id,
            lifecycle_attestation_version,
            lifecycle_attestation_hash.lower(),
            calendar_id,
            calendar_version,
            calendar_hash.lower(),
            period_id,
            period_version,
            period_hash.lower(),
            maximum_subjective_brier_score,
            maximum_model_brier_score,
            minimum_forecast_outcome_coverage,
            recorded_at,
            valid_until,
            False,
            True,
            True,
            True,
        )
        return cls(*values, _policy_hash(*values))

    def __post_init__(self) -> None:
        for label, token_value in (
            ("policy_id", self.policy_id),
            ("result_id", self.result_id),
            ("result_version", self.result_version),
            ("lifecycle_attestation_id", self.lifecycle_attestation_id),
            ("lifecycle_attestation_version", self.lifecycle_attestation_version),
            ("calendar_id", self.calendar_id),
            ("calendar_version", self.calendar_version),
            ("period_id", self.period_id),
            ("period_version", self.period_version),
        ):
            _require_token(token_value, f"R7 monitoring policy {label}")
        if self.policy_version != _POLICY_VERSION:
            raise ValueError("R7 monitoring policy version is unsupported")
        for label, hash_value in (
            ("result_hash", self.result_hash),
            ("lifecycle_attestation_hash", self.lifecycle_attestation_hash),
            ("calendar_hash", self.calendar_hash),
            ("period_hash", self.period_hash),
            ("content_hash", self.content_hash),
        ):
            _require_hash(hash_value, f"R7 monitoring policy {label}")
        for label, threshold in (
            ("maximum subjective Brier", self.maximum_subjective_brier_score),
            ("maximum model Brier", self.maximum_model_brier_score),
            ("minimum forecast outcome coverage", self.minimum_forecast_outcome_coverage),
        ):
            if (
                type(threshold) is not Decimal
                or not threshold.is_finite()
                or not Decimal("0") <= threshold <= Decimal("1")
            ):
                raise ValueError(f"R7 monitoring policy {label} is invalid")
        _require_aware(self.recorded_at, "R7 monitoring policy recorded_at")
        _require_aware(self.valid_until, "R7 monitoring policy valid_until")
        if self.recorded_at >= self.valid_until:
            raise ValueError("R7 monitoring policy validity is empty")
        if (
            self.automatic_retirement is not False
            or self.research_only is not True
            or self.must_not_use_for_decision is not True
            or self.must_not_execute is not True
        ):
            raise ValueError("R7 monitoring policy must remain research-only")
        if self.content_hash != r7_monitoring_policy_hash(self):
            raise ValueError("R7 monitoring policy content hash mismatch")

    def validated_copy(self) -> R7PostPromotionMonitoringPolicy:
        """Rebuild and revalidate the complete policy seal."""

        self.__post_init__()
        return R7PostPromotionMonitoringPolicy(
            **{field: getattr(self, field) for field in self.__dataclass_fields__}
        )


def r7_monitoring_policy_hash(value: R7PostPromotionMonitoringPolicy) -> str:
    """Recompute the canonical monitoring-policy content seal."""

    return _policy_hash(
        value.policy_id,
        value.policy_version,
        value.result_id,
        value.result_version,
        value.result_hash,
        value.lifecycle_attestation_id,
        value.lifecycle_attestation_version,
        value.lifecycle_attestation_hash,
        value.calendar_id,
        value.calendar_version,
        value.calendar_hash,
        value.period_id,
        value.period_version,
        value.period_hash,
        value.maximum_subjective_brier_score,
        value.maximum_model_brier_score,
        value.minimum_forecast_outcome_coverage,
        value.recorded_at,
        value.valid_until,
        value.automatic_retirement,
        value.research_only,
        value.must_not_use_for_decision,
        value.must_not_execute,
    )


def _policy_hash(
    policy_id: str,
    policy_version: str,
    result_id: str,
    result_version: str,
    result_hash: str,
    lifecycle_attestation_id: str,
    lifecycle_attestation_version: str,
    lifecycle_attestation_hash: str,
    calendar_id: str,
    calendar_version: str,
    calendar_hash: str,
    period_id: str,
    period_version: str,
    period_hash: str,
    maximum_subjective_brier_score: Decimal,
    maximum_model_brier_score: Decimal,
    minimum_forecast_outcome_coverage: Decimal,
    recorded_at: datetime,
    valid_until: datetime,
    automatic_retirement: bool,
    research_only: bool,
    must_not_use_for_decision: bool,
    must_not_execute: bool,
) -> str:
    values = (
        policy_version,
        policy_id,
        result_id,
        result_version,
        result_hash.lower(),
        lifecycle_attestation_id,
        lifecycle_attestation_version,
        lifecycle_attestation_hash.lower(),
        calendar_id,
        calendar_version,
        calendar_hash.lower(),
        period_id,
        period_version,
        period_hash.lower(),
        format(maximum_subjective_brier_score, "f"),
        format(maximum_model_brier_score, "f"),
        format(minimum_forecast_outcome_coverage, "f"),
        _utc_text(recorded_at),
        _utc_text(valid_until),
        _bool_text(automatic_retirement),
        _bool_text(research_only),
        _bool_text(must_not_use_for_decision),
        _bool_text(must_not_execute),
    )
    return sha256("\x00".join(values).encode()).hexdigest()


class R7MonitoringPolicyProvider(_UnitOfWorkBound, Protocol):
    """Research owner port for one exact monitoring policy."""

    def get_exact(
        self,
        *,
        policy_id: str,
        policy_version: str,
        expected_policy_hash: str,
        as_of: datetime,
    ) -> R7PostPromotionMonitoringPolicy | None:
        """Return the exact content-addressed policy at the PIT cutoff."""


@dataclass(frozen=True)
class R7MonitoringActiveOwnerGraph:
    """Complete result and lifecycle sources used to mint an active projection."""

    result: PersistedR7ResearchResult
    lifecycle_stream: tuple[R7ResultLifecycleEvent, ...]
    lifecycle_owner_evidence: R7LifecycleStreamOwnerEvidence

    def validated_copy(self) -> R7MonitoringActiveOwnerGraph:
        """Deep-copy sources and replay their exact promoted lifecycle."""

        copied = deepcopy(self)
        if type(copied.result) is not PersistedR7ResearchResult:
            raise TypeError("R7 monitoring result owner object is invalid")
        copied.result.__post_init__()
        if type(copied.lifecycle_stream) is not tuple or not copied.lifecycle_stream:
            raise ValueError("R7 monitoring lifecycle stream is incomplete")
        if any(type(item) is not R7ResultLifecycleEvent for item in copied.lifecycle_stream):
            raise TypeError("R7 monitoring lifecycle stream contains an invalid event")
        if type(copied.lifecycle_owner_evidence) is not R7LifecycleStreamOwnerEvidence:
            raise TypeError("R7 monitoring lifecycle attestation is invalid")
        R7MonitoringActiveResult.from_owner_graph(
            result=copied.result,
            lifecycle_stream=copied.lifecycle_stream,
            lifecycle_owner_evidence=copied.lifecycle_owner_evidence,
        )
        return copied

    def active_result(self) -> R7MonitoringActiveResult:
        """Mint a live active projection from the validated source graph."""

        graph = self.validated_copy()
        return R7MonitoringActiveResult.from_owner_graph(
            result=graph.result,
            lifecycle_stream=graph.lifecycle_stream,
            lifecycle_owner_evidence=graph.lifecycle_owner_evidence,
        )


class R7MonitoringActiveOwnerGraphProvider(_UnitOfWorkBound, Protocol):
    """Research result/lifecycle owner port."""

    def get_exact(
        self,
        *,
        result_id: str,
        result_version: str,
        expected_result_hash: str,
        lifecycle_attestation_id: str,
        lifecycle_attestation_version: str,
        expected_lifecycle_attestation_hash: str,
        as_of: datetime,
    ) -> R7MonitoringActiveOwnerGraph | None:
        """Return complete sources for one exact active result."""


class R7MonitoringCalendarProvider(_UnitOfWorkBound, Protocol):
    """Canonical complete monitoring-calendar owner port."""

    def get_exact(
        self,
        *,
        calendar_id: str,
        calendar_version: str,
        expected_calendar_hash: str,
        as_of: datetime,
    ) -> R7MonitoringPeriodCalendar | None:
        """Return one exact complete calendar."""


class R7MonitoringRealizationProvider(_UnitOfWorkBound, Protocol):
    """Forecast Ledger owner port for a period-complete realization record."""

    def get_exact(
        self,
        *,
        result_id: str,
        result_version: str,
        expected_result_hash: str,
        period_id: str,
        period_version: str,
        expected_period_hash: str,
        as_of: datetime,
    ) -> R7ForecastRealizationOwnerRecord | None:
        """Return the authoritative exact PIT owner record for one period."""


@dataclass(frozen=True)
class EvaluateR7PostPromotionMonitoringCommand:
    """Caller-safe selector containing policy identity and an exact PIT cutoff only."""

    policy_id: str
    policy_version: str
    expected_policy_hash: str
    as_of: datetime

    def __post_init__(self) -> None:
        _require_token(self.policy_id, "R7 monitoring command policy_id")
        _require_token(self.policy_version, "R7 monitoring command policy_version")
        _require_hash(self.expected_policy_hash, "R7 monitoring command policy hash")
        _require_aware(self.as_of, "R7 monitoring command as_of")


@dataclass(frozen=True)
class R7MonitoringEvaluationEvidence:
    """Complete authoritative source graph and locally replayable assessment."""

    policy: R7PostPromotionMonitoringPolicy
    active_owner_graph: R7MonitoringActiveOwnerGraph
    active: R7MonitoringActiveResult
    calendar: R7MonitoringPeriodCalendar
    period: R7MonitoringPeriodEntry
    realization_owner_record: R7ForecastRealizationOwnerRecord
    realization: R7ForecastRealizationFact
    assessment: R7PostPromotionMonitoringAssessment

    def validated_copy(self) -> R7MonitoringEvaluationEvidence:
        """Rebuild nested owner evidence and replay the Domain assessment."""

        policy = self.policy.validated_copy()
        owner_graph = self.active_owner_graph.validated_copy()
        active = owner_graph.active_result()
        calendar = deepcopy(self.calendar)
        calendar.__post_init__()
        period = deepcopy(self.period)
        calendar.require_exact_member(period)
        owner_record = self.realization_owner_record.validated_copy()
        realization = R7ForecastRealizationFact.from_owner_record(
            period=period,
            owner_record=owner_record,
        )
        assessment = evaluate_r7_post_promotion_monitoring(
            active=active,
            calendar=calendar,
            period=period,
            realization=realization,
            evaluated_at=self.assessment.evaluated_at,
            maximum_subjective_brier_score=policy.maximum_subjective_brier_score,
            maximum_model_brier_score=policy.maximum_model_brier_score,
            minimum_forecast_outcome_coverage=policy.minimum_forecast_outcome_coverage,
        )
        rebuilt = R7MonitoringEvaluationEvidence(
            policy=policy,
            active_owner_graph=owner_graph,
            active=active,
            calendar=calendar,
            period=period,
            realization_owner_record=owner_record,
            realization=realization,
            assessment=assessment,
        )
        if rebuilt != self:
            raise ValueError("R7 monitoring evidence differs after full replay")
        return rebuilt


@dataclass(frozen=True)
class _OwnerGraph:
    policy: R7PostPromotionMonitoringPolicy
    active_owner_graph: R7MonitoringActiveOwnerGraph
    active: R7MonitoringActiveResult
    calendar: R7MonitoringPeriodCalendar
    period: R7MonitoringPeriodEntry
    realization_owner_record: R7ForecastRealizationOwnerRecord
    realization: R7ForecastRealizationFact


class EvaluateR7PostPromotionMonitoring:
    """Double-read all canonical owners and derive a research-only assessment."""

    def __init__(
        self,
        *,
        policy_provider: R7MonitoringPolicyProvider,
        active_owner_graph_provider: R7MonitoringActiveOwnerGraphProvider,
        calendar_provider: R7MonitoringCalendarProvider,
        realization_provider: R7MonitoringRealizationProvider,
        clock: R7MonitoringClock,
        unit_of_work: R7MonitoringUnitOfWork,
    ) -> None:
        self._policy_provider = policy_provider
        self._active_owner_graph_provider = active_owner_graph_provider
        self._calendar_provider = calendar_provider
        self._realization_provider = realization_provider
        self._clock = clock
        self._unit_of_work = unit_of_work
        try:
            keys = self._current_uow_keys()
        except Exception as error:
            raise R7PostPromotionMonitoringUnavailable(
                "R7 monitoring UoW identity is unavailable"
            ) from error
        if len(set(keys)) != 1:
            raise R7PostPromotionMonitoringUnavailable("R7 monitoring owners use different UoWs")
        self._expected_uow_key = keys[0]

    @property
    def unit_of_work_key(self) -> str:
        """Return the live shared owner transaction identity."""

        self._require_unchanged_uow()
        return self._expected_uow_key

    def execute(
        self,
        command: EvaluateR7PostPromotionMonitoringCommand,
    ) -> R7PostPromotionMonitoringAssessment:
        """Return only the derived assessment, without persistence effects."""

        return self.execute_evidence(command).assessment

    def execute_evidence(
        self,
        command: EvaluateR7PostPromotionMonitoringCommand,
    ) -> R7MonitoringEvaluationEvidence:
        """Return a double-read, fully replayable owner evidence graph."""

        try:
            if type(command) is not EvaluateR7PostPromotionMonitoringCommand:
                raise TypeError("R7 monitoring command type differs")
            command.__post_init__()
            server_now = self._clock.now()
            _require_aware(server_now, "R7 monitoring trusted server clock")
            if command.as_of > server_now:
                raise ValueError("R7 monitoring command uses a future as_of")
            self._require_unchanged_uow()
            with self._unit_of_work.atomic():
                self._require_unchanged_uow()
                first = self._read_owner_graph(command)
                first_assessment = self._evaluate(first, command.as_of)
                self._require_unchanged_uow()
                second = self._read_owner_graph(command)
                second_assessment = self._evaluate(second, command.as_of)
                self._require_unchanged_uow()
                if first != second or first_assessment != second_assessment:
                    raise ValueError("R7 monitoring owner graph changed during evaluation")
                return R7MonitoringEvaluationEvidence(
                    policy=second.policy,
                    active_owner_graph=second.active_owner_graph,
                    active=second.active,
                    calendar=second.calendar,
                    period=second.period,
                    realization_owner_record=second.realization_owner_record,
                    realization=second.realization,
                    assessment=second_assessment,
                ).validated_copy()
        except R7PostPromotionMonitoringUnavailable:
            raise
        except Exception as error:
            raise R7PostPromotionMonitoringUnavailable(
                "R7 monitoring authoritative owner graph is unavailable"
            ) from error

    def _read_owner_graph(
        self,
        command: EvaluateR7PostPromotionMonitoringCommand,
    ) -> _OwnerGraph:
        policy = _copy_policy(
            self._policy_provider.get_exact(
                policy_id=command.policy_id,
                policy_version=command.policy_version,
                expected_policy_hash=command.expected_policy_hash,
                as_of=command.as_of,
            )
        )
        if policy is None or (
            policy.policy_id,
            policy.policy_version,
            policy.content_hash,
        ) != (
            command.policy_id,
            command.policy_version,
            command.expected_policy_hash,
        ):
            raise ValueError("R7 monitoring policy identity was replaced")
        if not policy.recorded_at <= command.as_of < policy.valid_until:
            raise ValueError("R7 monitoring policy is future or expired")
        owner_graph = _copy_active_owner_graph(
            self._active_owner_graph_provider.get_exact(
                result_id=policy.result_id,
                result_version=policy.result_version,
                expected_result_hash=policy.result_hash,
                lifecycle_attestation_id=policy.lifecycle_attestation_id,
                lifecycle_attestation_version=policy.lifecycle_attestation_version,
                expected_lifecycle_attestation_hash=policy.lifecycle_attestation_hash,
                as_of=command.as_of,
            )
        )
        if owner_graph is None:
            raise ValueError("R7 monitoring active owner graph is missing")
        active = owner_graph.active_result()
        if (
            active.result_id,
            active.result_version,
            active.result_hash,
            active.lifecycle_attestation_id,
            active.lifecycle_attestation_version,
            active.lifecycle_attestation_hash,
        ) != (
            policy.result_id,
            policy.result_version,
            policy.result_hash,
            policy.lifecycle_attestation_id,
            policy.lifecycle_attestation_version,
            policy.lifecycle_attestation_hash,
        ):
            raise ValueError("R7 monitoring active result was replaced")
        if not active.lifecycle_recorded_at <= command.as_of < active.lifecycle_valid_until:
            raise ValueError("R7 monitoring active result is future or expired")
        calendar = _copy_calendar(
            self._calendar_provider.get_exact(
                calendar_id=policy.calendar_id,
                calendar_version=policy.calendar_version,
                expected_calendar_hash=policy.calendar_hash,
                as_of=command.as_of,
            )
        )
        if calendar is None or (
            calendar.calendar_id,
            calendar.calendar_version,
            calendar.content_hash,
        ) != (policy.calendar_id, policy.calendar_version, policy.calendar_hash):
            raise ValueError("R7 monitoring calendar was replaced")
        matches = tuple(
            item
            for item in calendar.periods
            if (
                item.period_id,
                item.period_version,
                item.content_hash,
            )
            == (policy.period_id, policy.period_version, policy.period_hash)
        )
        if len(matches) != 1:
            raise ValueError("R7 monitoring policy period is not an exact calendar member")
        period = deepcopy(matches[0])
        calendar.require_exact_member(period)
        if policy.recorded_at > period.period_start or period.period_end > command.as_of:
            raise ValueError("R7 monitoring policy or period chronology is invalid")
        owner_record = _copy_owner_record(
            self._realization_provider.get_exact(
                result_id=policy.result_id,
                result_version=policy.result_version,
                expected_result_hash=policy.result_hash,
                period_id=period.period_id,
                period_version=period.period_version,
                expected_period_hash=period.content_hash,
                as_of=command.as_of,
            )
        )
        if owner_record is None:
            raise ValueError("R7 monitoring realization owner record is missing")
        if (
            owner_record.period_id,
            owner_record.period_hash,
        ) != (period.period_id, period.content_hash):
            raise ValueError("R7 monitoring realization owner period was replaced")
        if not (
            owner_record.recorded_at <= owner_record.pit_as_of <= command.as_of
            and command.as_of < owner_record.valid_until
        ):
            raise ValueError("R7 monitoring realization owner is future or expired")
        realization = R7ForecastRealizationFact.from_owner_record(
            period=period,
            owner_record=owner_record,
        )
        return _OwnerGraph(
            policy=policy,
            active_owner_graph=owner_graph,
            active=active,
            calendar=calendar,
            period=period,
            realization_owner_record=owner_record,
            realization=realization,
        )

    @staticmethod
    def _evaluate(
        graph: _OwnerGraph,
        evaluated_at: datetime,
    ) -> R7PostPromotionMonitoringAssessment:
        return evaluate_r7_post_promotion_monitoring(
            active=graph.active,
            calendar=graph.calendar,
            period=graph.period,
            realization=graph.realization,
            evaluated_at=evaluated_at,
            maximum_subjective_brier_score=(graph.policy.maximum_subjective_brier_score),
            maximum_model_brier_score=graph.policy.maximum_model_brier_score,
            minimum_forecast_outcome_coverage=(graph.policy.minimum_forecast_outcome_coverage),
        )

    def _current_uow_keys(self) -> tuple[str, ...]:
        values: tuple[object, ...] = (
            self._policy_provider.unit_of_work_key,
            self._active_owner_graph_provider.unit_of_work_key,
            self._calendar_provider.unit_of_work_key,
            self._realization_provider.unit_of_work_key,
            self._clock.unit_of_work_key,
            self._unit_of_work.unit_of_work_key,
        )
        return tuple(_exact_uow_key(value) for value in values)

    def _require_unchanged_uow(self) -> None:
        try:
            keys = self._current_uow_keys()
        except Exception as error:
            raise R7PostPromotionMonitoringUnavailable(
                "R7 monitoring UoW identity is unavailable"
            ) from error
        if any(value != self._expected_uow_key for value in keys):
            raise R7PostPromotionMonitoringUnavailable("R7 monitoring UoW identity changed")


def _copy_policy(value: object) -> R7PostPromotionMonitoringPolicy | None:
    if value is None:
        return None
    if type(value) is not R7PostPromotionMonitoringPolicy:
        raise TypeError("R7 monitoring policy provider returned an invalid object")
    copied = value.validated_copy()
    if copied != value:
        raise ValueError("R7 monitoring policy provider substituted an object")
    return copied


def _copy_active_owner_graph(value: object) -> R7MonitoringActiveOwnerGraph | None:
    if value is None:
        return None
    if type(value) is not R7MonitoringActiveOwnerGraph:
        raise TypeError("R7 monitoring active owner provider returned an invalid object")
    copied = value.validated_copy()
    if copied != value:
        raise ValueError("R7 monitoring active owner graph was substituted")
    return copied


def _copy_calendar(value: object) -> R7MonitoringPeriodCalendar | None:
    if value is None:
        return None
    if type(value) is not R7MonitoringPeriodCalendar:
        raise TypeError("R7 monitoring calendar provider returned an invalid object")
    copied = deepcopy(value)
    copied.__post_init__()
    if copied != value:
        raise ValueError("R7 monitoring calendar provider substituted an object")
    return copied


def _copy_owner_record(value: object) -> R7ForecastRealizationOwnerRecord | None:
    if value is None:
        return None
    if type(value) is not R7ForecastRealizationOwnerRecord:
        raise TypeError("R7 realization provider returned an invalid owner object")
    copied = value.validated_copy()
    if copied != value:
        raise ValueError("R7 realization provider substituted an owner record")
    return copied


def _require_token(value: object, label: str) -> None:
    if (
        type(value) is not str
        or not value.strip()
        or len(value) > 300
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{label} must be an exact bounded token")


def _require_hash(value: object, label: str) -> None:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{label} must be lowercase SHA-256")


def _require_aware(value: object, label: str) -> None:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")


def _exact_uow_key(value: object) -> str:
    if type(value) is not str or not value.strip() or len(value) > 192:
        raise TypeError("R7 monitoring UoW key must be an exact non-blank string")
    return value


def _utc_text(value: datetime) -> str:
    _require_aware(value, "R7 monitoring hash datetime")
    return value.astimezone(UTC).isoformat()


def _bool_text(value: bool) -> str:
    if type(value) is not bool:
        raise TypeError("R7 monitoring hash flag must be an exact bool")
    return "true" if value else "false"


__all__ = [
    "EvaluateR7PostPromotionMonitoring",
    "EvaluateR7PostPromotionMonitoringCommand",
    "R7MonitoringActiveOwnerGraph",
    "R7MonitoringActiveOwnerGraphProvider",
    "R7MonitoringCalendarProvider",
    "R7MonitoringClock",
    "R7MonitoringEvaluationEvidence",
    "R7MonitoringPolicyProvider",
    "R7MonitoringRealizationProvider",
    "R7MonitoringUnitOfWork",
    "R7PostPromotionMonitoringPolicy",
    "R7PostPromotionMonitoringUnavailable",
    "r7_monitoring_policy_hash",
]
