from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from inspect import signature

import pytest

from apps.research.application.r5_research_control_preflight import (
    EvaluateR5ResearchControlPreflight,
    EvaluateR5ResearchControlPreflightCommand,
    R5ResearchControlBlockerCode,
    R5ResearchControlMonitoringEvidence,
    R5ResearchControlPreflightStatus,
    R5ResearchControlUnavailable,
)
from apps.research.domain.r5_relative_value_monitoring import (
    R5MonitoringAssessmentStatus,
)
from apps.research.domain.r5_relative_value_monitoring_contracts import (
    R5MonitoringActiveLifecycle,
    R5MonitoringFixedIncomeEvidence,
)
from apps.research.r5_research_control_composition import (
    build_django_r5_research_control_runtime,
)

NOW = datetime(2026, 8, 11, 8, tzinfo=UTC)
HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
HASH_D = "d" * 64
HASH_E = "e" * 64
HASH_F = "f" * 64


def _active(*, decision_hash: str = HASH_B) -> R5MonitoringActiveLifecycle:
    return R5MonitoringActiveLifecycle.create(
        scope_id="r5-scope",
        scope_hash=HASH_A,
        decision_id="r5-decision",
        decision_version="v1",
        decision_hash=decision_hash,
        trial_id="r5-trial",
        trial_hash=HASH_C,
        fixed_income_owner_seal_hashes=(HASH_D,),
        stream_id="r5-stream",
        latest_event_id="r5-event",
        latest_event_hash=HASH_E,
        promoted_at=NOW - timedelta(days=3),
        recorded_at=NOW - timedelta(days=3) + timedelta(minutes=1),
        valid_until=NOW + timedelta(days=10),
    )


def _fixed_income() -> R5MonitoringFixedIncomeEvidence:
    return R5MonitoringFixedIncomeEvidence.create(
        result_id="r5-result",
        result_version="v1",
        result_hash=HASH_F,
        owner_seal_id="r5-owner-seal",
        owner_seal_version="v1",
        owner_seal_hash=HASH_D,
        recorded_at=NOW - timedelta(days=4),
    )


def _monitoring(
    *,
    status: R5MonitoringAssessmentStatus = R5MonitoringAssessmentStatus.HEALTHY,
    active: R5MonitoringActiveLifecycle | None = None,
) -> R5ResearchControlMonitoringEvidence:
    return R5ResearchControlMonitoringEvidence.create(
        assessment_id="r5-monitoring-assessment",
        assessment_hash=HASH_A,
        active_lifecycle=active or _active(),
        fixed_income=_fixed_income(),
        latest_period_id=HASH_B,
        latest_period_end=NOW - timedelta(hours=2),
        evaluated_at=NOW - timedelta(hours=1),
        ledger_recorded_at=NOW - timedelta(minutes=30),
        status=status,
    )


class _UnitOfWork:
    unit_of_work_key = "django:default"

    def __init__(self) -> None:
        self.atomic_entries = 0

    @contextmanager
    def atomic(self) -> Iterator[None]:
        self.atomic_entries += 1
        yield

    def server_now(self) -> datetime:
        return NOW


class _ActiveProvider:
    unit_of_work_key = "django:default"

    def __init__(
        self,
        values: tuple[R5MonitoringActiveLifecycle | None, ...],
    ) -> None:
        self.values = values
        self.calls = 0

    def get_active(
        self,
        *,
        scope_id: str,
        as_of: datetime,
    ) -> R5MonitoringActiveLifecycle | None:
        assert scope_id == "r5-scope"
        assert as_of == NOW
        value = self.values[min(self.calls, len(self.values) - 1)]
        self.calls += 1
        return value


class _MonitoringProvider:
    unit_of_work_key = "django:default"

    def __init__(
        self,
        values: tuple[R5ResearchControlMonitoringEvidence | None, ...],
    ) -> None:
        self.values = values
        self.calls = 0

    def get_latest_complete(
        self,
        *,
        active_lifecycle: R5MonitoringActiveLifecycle,
        as_of: datetime,
    ) -> R5ResearchControlMonitoringEvidence | None:
        assert active_lifecycle.scope_id == "r5-scope"
        assert as_of == NOW
        value = self.values[min(self.calls, len(self.values) - 1)]
        self.calls += 1
        return value


class _FixedIncomeProvider:
    unit_of_work_key = "django:default"

    def __init__(
        self,
        values: tuple[R5MonitoringFixedIncomeEvidence | None, ...],
    ) -> None:
        self.values = values
        self.calls = 0

    def get_exact(
        self,
        *,
        evidence: R5MonitoringFixedIncomeEvidence,
        as_of: datetime,
    ) -> R5MonitoringFixedIncomeEvidence | None:
        assert evidence == _fixed_income()
        assert as_of == NOW
        value = self.values[min(self.calls, len(self.values) - 1)]
        self.calls += 1
        return value


def _service(
    *,
    active_values: tuple[R5MonitoringActiveLifecycle | None, ...] | None = None,
    monitoring_values: tuple[R5ResearchControlMonitoringEvidence | None, ...] | None = None,
    fixed_income_values: tuple[R5MonitoringFixedIncomeEvidence | None, ...] | None = None,
) -> tuple[
    EvaluateR5ResearchControlPreflight,
    _ActiveProvider,
    _MonitoringProvider,
    _FixedIncomeProvider,
    _UnitOfWork,
]:
    active = _ActiveProvider(active_values or (_active(), _active()))
    monitoring = _MonitoringProvider(monitoring_values or (_monitoring(), _monitoring()))
    fixed_income = _FixedIncomeProvider(fixed_income_values or (_fixed_income(), _fixed_income()))
    uow = _UnitOfWork()
    return (
        EvaluateR5ResearchControlPreflight(
            active_lifecycle_provider=active,
            monitoring_provider=monitoring,
            fixed_income_provider=fixed_income,
            unit_of_work=uow,
        ),
        active,
        monitoring,
        fixed_income,
        uow,
    )


def _command() -> EvaluateR5ResearchControlPreflightCommand:
    return EvaluateR5ResearchControlPreflightCommand(
        scope_id="r5-scope",
        as_of=NOW,
    )


def test_preflight_double_reads_exact_owners_and_only_allows_manual_review() -> None:
    service, active, monitoring, fixed_income, uow = _service()

    result = service.execute(_command())

    assert result.status is R5ResearchControlPreflightStatus.ELIGIBLE_FOR_MANUAL_CONSUMER_REVIEW
    assert result.blocker_codes == ()
    assert result.active_lifecycle_hash == _active().content_hash
    assert result.monitoring_assessment_hash == HASH_A
    assert result.fixed_income_owner_seal_hash == HASH_D
    assert result.research_only is True
    assert result.must_not_publish_current is True
    assert result.must_not_use_for_decision is True
    assert result.must_not_execute is True
    assert (active.calls, monitoring.calls, fixed_income.calls) == (2, 2, 2)
    assert uow.atomic_entries == 1


@pytest.mark.parametrize(
    ("monitoring_status", "expected_blocker"),
    (
        (
            R5MonitoringAssessmentStatus.BREACHED,
            R5ResearchControlBlockerCode.LATEST_MONITORING_BREACHED,
        ),
        (
            R5MonitoringAssessmentStatus.RETIREMENT_REVIEW_REQUIRED,
            R5ResearchControlBlockerCode.LATEST_MONITORING_REQUIRES_RETIREMENT_REVIEW,
        ),
    ),
)
def test_latest_nonhealthy_assessment_blocks_instead_of_allowing_cherry_pick(
    monitoring_status: R5MonitoringAssessmentStatus,
    expected_blocker: R5ResearchControlBlockerCode,
) -> None:
    latest = _monitoring(status=monitoring_status)
    service, _, _, _, _ = _service(monitoring_values=(latest, latest))

    result = service.execute(_command())

    assert result.status is R5ResearchControlPreflightStatus.BLOCKED
    assert result.blocker_codes == (expected_blocker,)


def test_missing_or_drifting_owner_graph_is_stably_blocked() -> None:
    missing_service, _, missing_monitoring, missing_fixed_income, _ = _service(
        active_values=(None, None),
    )
    missing = missing_service.execute(_command())
    assert missing.status is R5ResearchControlPreflightStatus.BLOCKED
    assert missing.blocker_codes == (R5ResearchControlBlockerCode.ACTIVE_LIFECYCLE_UNAVAILABLE,)
    assert missing_monitoring.calls == 0
    assert missing_fixed_income.calls == 0

    changed = _active(decision_hash=HASH_F)
    drift_service, _, _, _, _ = _service(active_values=(_active(), changed))
    drift = drift_service.execute(_command())
    assert drift.status is R5ResearchControlPreflightStatus.BLOCKED
    assert drift.blocker_codes == (
        R5ResearchControlBlockerCode.OWNER_GRAPH_CHANGED_DURING_PREFLIGHT,
    )


def test_preflight_rejects_malformed_command_and_mismatched_uow_without_reads() -> None:
    service, active, monitoring, fixed_income, _ = _service()
    forged = object.__new__(EvaluateR5ResearchControlPreflightCommand)
    object.__setattr__(forged, "scope_id", "")
    object.__setattr__(forged, "as_of", NOW)

    with pytest.raises(R5ResearchControlUnavailable, match="command"):
        service.execute(forged)
    assert (active.calls, monitoring.calls, fixed_income.calls) == (0, 0, 0)

    mismatched = _FixedIncomeProvider((_fixed_income(),))
    mismatched.unit_of_work_key = "django:other"
    with pytest.raises(R5ResearchControlUnavailable, match="unit of work"):
        EvaluateR5ResearchControlPreflight(
            active_lifecycle_provider=active,
            monitoring_provider=monitoring,
            fixed_income_provider=mismatched,
            unit_of_work=_UnitOfWork(),
        )


def test_command_exposes_no_assessment_or_health_selector() -> None:
    assert tuple(EvaluateR5ResearchControlPreflightCommand.__dataclass_fields__) == (
        "scope_id",
        "as_of",
    )


def test_public_composition_accepts_no_owner_injection_and_is_fail_closed() -> None:
    from apps.research.infrastructure.r5_research_control_active_query import (
        DjangoR5ResearchControlActiveLifecycleProvider,
    )

    assert tuple(signature(build_django_r5_research_control_runtime).parameters) == ("using",)
    runtime = build_django_r5_research_control_runtime()
    assert tuple(runtime.__dataclass_fields__) == ("preflight",)
    assert type(runtime.preflight._active_lifecycle_provider) is (
        DjangoR5ResearchControlActiveLifecycleProvider
    )
    assert not hasattr(runtime, "register")
    assert not hasattr(runtime, "publish_current")
    assert not hasattr(runtime, "decide")
    assert not hasattr(runtime, "execute")
