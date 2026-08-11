"""Component coverage for Portfolio-owned R8 monitoring owner adapters."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from django.core.exceptions import ValidationError
from django.db import connection, transaction

from apps.portfolio.application.governed_optimization import (
    GovernedOptimizationRunBundle,
)
from apps.portfolio.application.governed_optimization_monitoring import (
    EvaluateGovernedOptimizationMonitoringCommand,
)
from apps.portfolio.application.r8_monitoring_calendar_registry import (
    R8MonitoringCalendarRegistryUnavailable,
)
from apps.portfolio.domain.governed_optimization_monitoring import (
    MonitoringAssessmentStatus,
    MonitoringBlockerCode,
)
from apps.portfolio.domain.r8_monitoring_calendar_registry import (
    R8MonitoringCalendarDefinition,
    R8MonitoringCalendarSourceReceipt,
)
from apps.portfolio.infrastructure.optimization_input_receipt_repository import (
    DjangoGovernedOptimizationInputReceiptRepository,
    DjangoGovernedOptimizationUnitOfWork,
)
from apps.portfolio.infrastructure.optimization_research_repository import (
    DjangoGovernedOptimizationResearchRepository,
    _DjangoGovernedOptimizationLifecycleStore,
)
from apps.portfolio.infrastructure.r8_monitoring_calendar_models import (
    R8MonitoringCalendarRegistryModel,
)
from apps.portfolio.infrastructure.r8_monitoring_calendar_repository import (
    R8MonitoringCalendarRegistryConflict,
    R8MonitoringCalendarRegistryCorruption,
)
from apps.portfolio.infrastructure.r8_monitoring_owner_adapters import (
    DjangoR8MonitoringActiveResultProvider,
    DjangoR8MonitoringInputReceiptProvider,
    R8MonitoringOwnerAdapterCorruption,
)
from apps.portfolio.r8_monitoring_owner_composition import (
    _build_django_r8_monitoring_calendar_registration_runtime,
    build_django_r8_monitoring_owner_runtime,
)
from tests.unit.portfolio.test_governed_optimization_monitoring import (
    AS_OF,
    _active_result,
    _receipt_and_result,
)
from tests.unit.portfolio.test_r8_monitoring_calendar_registry import (
    NOW,
    _Clock,
    _command,
    _definition,
    _Provider,
    _source,
)


class _DriftingProvider(_Provider):
    def __init__(self, first: object, second: object) -> None:
        super().__init__(first)
        self._second = second

    def get_exact(self, **selectors: object) -> object:
        del selectors
        self.calls += 1
        return self.value if self.calls == 1 else self._second


class _RepositoryClock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def now(self) -> datetime:
        return self.value


def _registration_runtime(
    *,
    definition_provider: object | None = None,
    source_provider: object | None = None,
):
    unit_of_work = DjangoGovernedOptimizationUnitOfWork()
    definition = definition_provider or _Provider(_definition())
    source = source_provider or _Provider(_source())
    clock = _Clock()
    definition.unit_of_work_key = unit_of_work.unit_of_work_key
    source.unit_of_work_key = unit_of_work.unit_of_work_key
    clock.unit_of_work_key = unit_of_work.unit_of_work_key
    return _build_django_r8_monitoring_calendar_registration_runtime(
        definition_provider=definition,
        source_provider=source,
        clock=clock,
        unit_of_work=unit_of_work,
    )


@pytest.mark.django_db(transaction=True)
def test_calendar_registry_round_trip_winner_pit_and_append_only_guards() -> None:
    """Private owner flow appends once; public reads are exact and rows immutable."""

    runtime = _registration_runtime()
    calendar = runtime.register_calendar.execute(_command())

    assert runtime.register_calendar.execute(_command()) == calendar
    assert R8MonitoringCalendarRegistryModel._default_manager.count() == 1
    assert (
        runtime.calendar_provider.get_exact(
            calendar_id=calendar.calendar_id,
            calendar_version=calendar.calendar_version,
            expected_calendar_hash=calendar.content_hash,
            as_of=NOW,
        )
        == calendar
    )
    assert (
        runtime.calendar_provider.get_exact(
            calendar_id=calendar.calendar_id,
            calendar_version=calendar.calendar_version,
            expected_calendar_hash=calendar.content_hash,
            as_of=NOW - timedelta(microseconds=1),
        )
        is None
    )
    with pytest.raises(R8MonitoringCalendarRegistryCorruption, match="substituted"):
        runtime.calendar_provider.get_exact(
            calendar_id=calendar.calendar_id,
            calendar_version=calendar.calendar_version,
            expected_calendar_hash="0" * 64,
            as_of=NOW,
        )

    row = R8MonitoringCalendarRegistryModel._default_manager.get()
    with pytest.raises(ValidationError):
        row.save()
    with pytest.raises(ValidationError):
        row.delete()
    with pytest.raises(ValidationError):
        R8MonitoringCalendarRegistryModel._default_manager.update(period_count=2)
    with pytest.raises(ValidationError):
        R8MonitoringCalendarRegistryModel._default_manager.all().delete()
    with pytest.raises(ValidationError):
        R8MonitoringCalendarRegistryModel._default_manager.bulk_create([])
    with pytest.raises(ValidationError):
        R8MonitoringCalendarRegistryModel._default_manager.get_or_create(
            calendar_id="forbidden"
        )
    with pytest.raises(ValidationError):
        R8MonitoringCalendarRegistryModel(calendar_id="forbidden").save(force_insert=True)


@pytest.mark.django_db(transaction=True)
def test_calendar_registry_blocks_missing_drift_fork_and_rolls_back() -> None:
    """Absent, changing, conflicting, and outer-rolled-back graphs write nothing."""

    missing = _registration_runtime(definition_provider=_Provider(None))
    with pytest.raises(R8MonitoringCalendarRegistryUnavailable, match="definition"):
        missing.register_calendar.execute(_command())
    assert R8MonitoringCalendarRegistryModel._default_manager.count() == 0

    changed_definition = R8MonitoringCalendarDefinition.create(
        calendar_id=_definition().calendar_id,
        calendar_version=_definition().calendar_version,
        periods=_definition().periods,
        available_at=_definition().available_at - timedelta(minutes=1),
        valid_until=_definition().valid_until,
        evidence_ref=_definition().evidence_ref,
    )
    drift = _registration_runtime(
        definition_provider=_DriftingProvider(_definition(), changed_definition)
    )
    with pytest.raises(R8MonitoringCalendarRegistryUnavailable, match="substituted"):
        drift.register_calendar.execute(_command())
    assert R8MonitoringCalendarRegistryModel._default_manager.count() == 0

    with pytest.raises(RuntimeError, match="outer rollback"):
        with transaction.atomic():
            _registration_runtime().register_calendar.execute(_command())
            assert R8MonitoringCalendarRegistryModel._default_manager.count() == 1
            raise RuntimeError("outer rollback")
    assert R8MonitoringCalendarRegistryModel._default_manager.count() == 0

    runtime = _registration_runtime()
    runtime.register_calendar.execute(_command())
    fork_source = R8MonitoringCalendarSourceReceipt.create(
        source_receipt_id=_source().source_receipt_id,
        source_receipt_version=_source().source_receipt_version,
        definition_hash=_definition().content_hash,
        available_at=_source().available_at,
        valid_until=_source().valid_until,
        evidence_ref="portfolio:r8-monitoring-calendar-owner:fork",
    )
    fork = _registration_runtime(source_provider=_Provider(fork_source))
    with pytest.raises(R8MonitoringCalendarRegistryUnavailable) as raised:
        fork.register_calendar.execute(_command())
    assert isinstance(raised.value.__cause__, R8MonitoringCalendarRegistryConflict)
    assert R8MonitoringCalendarRegistryModel._default_manager.count() == 1


@pytest.mark.django_db(transaction=True)
def test_calendar_registry_detects_persisted_header_tampering() -> None:
    """Raw database tampering cannot survive strict payload/header replay."""

    runtime = _registration_runtime()
    calendar = runtime.register_calendar.execute(_command())
    table = connection.ops.quote_name(R8MonitoringCalendarRegistryModel._meta.db_table)
    with connection.cursor() as cursor:
        cursor.execute(
            f"UPDATE {table} SET source_evidence_ref = %s WHERE content_hash = %s",
            ["portfolio:tampered", calendar.content_hash],
        )

    with pytest.raises(R8MonitoringCalendarRegistryCorruption, match="headers"):
        runtime.calendar_provider.get_exact(
            calendar_id=calendar.calendar_id,
            calendar_version=calendar.calendar_version,
            expected_calendar_hash=calendar.content_hash,
            as_of=NOW,
        )


@pytest.mark.django_db(transaction=True)
def test_active_result_and_receipt_adapters_restore_exact_portfolio_owners() -> None:
    """Narrow adapters restore exact persisted owner evidence and reject substitution."""

    receipt, result = _receipt_and_result()
    active = _active_result(result)
    unit_of_work = DjangoGovernedOptimizationUnitOfWork()
    clock = _RepositoryClock(AS_OF + timedelta(hours=1))
    receipts = DjangoGovernedOptimizationInputReceiptRepository(
        unit_of_work=unit_of_work,
        clock=clock,
    )
    with unit_of_work.atomic():
        receipts._store_verified(receipt.input_set, receipt.recorded_at)
    results = DjangoGovernedOptimizationResearchRepository(
        unit_of_work=unit_of_work,
        receipt_provider=receipts,
        clock=clock,
    )
    results.append_bundle(
        GovernedOptimizationRunBundle(
            result=result,
            lifecycle_root=active.lifecycle_events[0],
        )
    )
    lifecycle = _DjangoGovernedOptimizationLifecycleStore(results)
    with lifecycle.atomic():
        lifecycle.append_lifecycle_event(active.lifecycle_events[1])

    active_provider = DjangoR8MonitoringActiveResultProvider()
    receipt_provider = DjangoR8MonitoringInputReceiptProvider()
    assert (
        active_provider.get_exact(
            result_id=result.result_id,
            result_version=result.result_version,
            expected_result_hash=result.content_hash,
            promotion_event_id=active.promotion_event_id,
            expected_promotion_event_hash=active.promotion_event_hash,
            as_of=AS_OF,
        )
        == active
    )
    assert (
        receipt_provider.get_exact(
            receipt_id=receipt.receipt_id,
            receipt_version=receipt.receipt_version,
            expected_receipt_hash=receipt.content_hash,
            as_of=AS_OF,
        )
        == receipt
    )
    assert (
        receipt_provider.get_exact(
            receipt_id=receipt.receipt_id,
            receipt_version=receipt.receipt_version,
            expected_receipt_hash=receipt.content_hash,
            as_of=receipt.recorded_at - timedelta(microseconds=1),
        )
        is None
    )
    with pytest.raises(R8MonitoringOwnerAdapterCorruption, match="substituted"):
        active_provider.get_exact(
            result_id=result.result_id,
            result_version=result.result_version,
            expected_result_hash="0" * 64,
            promotion_event_id=active.promotion_event_id,
            expected_promotion_event_hash=active.promotion_event_hash,
            as_of=AS_OF,
        )


@pytest.mark.django_db(transaction=True)
def test_public_owner_composition_is_inert_and_empty_state_is_blocked() -> None:
    """Production wiring never mutates and missing Research policy blocks stably."""

    runtime = build_django_r8_monitoring_owner_runtime()
    with pytest.raises(R8MonitoringCalendarRegistryUnavailable):
        runtime.register_calendar.execute(_command())
    assert R8MonitoringCalendarRegistryModel._default_manager.count() == 0

    assessment = runtime.evaluate.execute(
        EvaluateGovernedOptimizationMonitoringCommand(
            policy_id="r8-monitoring-policy:weekly:v1",
            policy_version="r8-monitoring-policy.v1",
            expected_policy_hash="0" * 64,
            as_of=NOW - timedelta(days=1),
        )
    )
    assert assessment.status is MonitoringAssessmentStatus.BLOCKED
    assert assessment.blocker_codes == (MonitoringBlockerCode.POLICY_UNAVAILABLE,)
    assert R8MonitoringCalendarRegistryModel._default_manager.count() == 0
