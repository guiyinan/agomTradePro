"""Component coverage for Broker-owned R8 monitoring reconciliation receipts."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.db import connection, transaction

from apps.broker_execution.application.r8_monitoring_reconciliation_registry import (
    R8BrokerMonitoringRegistryUnavailable,
)
from apps.broker_execution.domain.r8_monitoring_reconciliation import (
    R8BrokerReconciliationSourceReceipt,
)
from apps.broker_execution.infrastructure.r8_monitoring_reconciliation_models import (
    R8BrokerMonitoringPeriodReceiptModel,
)
from apps.broker_execution.infrastructure.r8_monitoring_reconciliation_repository import (
    R8BrokerMonitoringRegistryConflict,
    R8BrokerMonitoringRegistryCorruption,
)
from apps.broker_execution.r8_monitoring_reconciliation_composition import (
    _build_django_r8_broker_monitoring_test_runtime,
    build_django_r8_broker_monitoring_owner_runtime,
)
from apps.portfolio.domain.governed_optimization_monitoring_metrics import (
    MonitoringMetricKey,
    MonitoringSourceOwner,
)
from apps.portfolio.infrastructure.r8_broker_monitoring_feedback_adapter import (
    DjangoR8BrokerMonitoringFeedbackAdapter,
)
from tests.unit.broker_execution.test_r8_monitoring_reconciliation_registry import (
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


def _registration_runtime(
    *,
    definition_provider: object | None = None,
    source_provider: object | None = None,
):
    return _build_django_r8_broker_monitoring_test_runtime(
        definition_provider=definition_provider or _Provider(_definition()),
        source_provider=source_provider or _Provider(_source()),
        clock=_Clock(),
    )


@pytest.mark.django_db(transaction=True)
def test_period_receipt_round_trip_winner_exact_pit_and_portfolio_projection() -> None:
    """One owner receipt replays exactly and projects only the three sealed ratios."""

    runtime = _registration_runtime()
    receipt = runtime.register_period.execute(_command())

    assert runtime.register_period.execute(_command()) == receipt
    assert R8BrokerMonitoringPeriodReceiptModel._default_manager.count() == 1
    assert (
        runtime.receipt_provider.get_exact(
            receipt_id=receipt.receipt_id,
            receipt_version=receipt.receipt_version,
            expected_receipt_hash=receipt.content_hash,
            as_of=NOW,
        )
        == receipt
    )
    assert (
        runtime.receipt_provider.get_exact(
            receipt_id=receipt.receipt_id,
            receipt_version=receipt.receipt_version,
            expected_receipt_hash=receipt.content_hash,
            as_of=NOW - timedelta(microseconds=1),
        )
        is None
    )

    definition = receipt.definition
    projected = DjangoR8BrokerMonitoringFeedbackAdapter().list_exact(
        result_id=definition.result_id,
        result_hash=definition.result_hash,
        receipt_id=definition.portfolio_receipt_id,
        receipt_hash=definition.portfolio_receipt_hash,
        calendar_id=definition.calendar_id,
        calendar_hash=definition.calendar_hash,
        period_ids=(definition.period_id,),
        as_of=NOW,
    )
    assert len(projected) == 1
    evidence = projected[0]
    assert evidence.owner is MonitoringSourceOwner.BROKER_EXECUTION
    assert tuple(item.metric_key for item in evidence.metric_payload) == (
        MonitoringMetricKey.TOTAL_COST_RATE,
        MonitoringMetricKey.ADVERSE_SLIPPAGE_RATE,
        MonitoringMetricKey.RECONCILIATION_BREAK_RATE,
    )
    assert tuple(item.value for item in evidence.metric_payload) == tuple(
        item.value for item in definition.metric_facts
    )
    assert evidence.observed_at == definition.observed_at
    assert evidence.available_at == receipt.recorded_at


@pytest.mark.django_db(transaction=True)
def test_period_receipt_missing_drift_fork_and_outer_rollback_are_zero_write() -> None:
    """Absent, changing, conflicting, and rolled-back owner graphs fail closed."""

    missing = _registration_runtime(source_provider=_Provider(None))
    with pytest.raises(R8BrokerMonitoringRegistryUnavailable, match="source"):
        missing.register_period.execute(_command())
    assert R8BrokerMonitoringPeriodReceiptModel._default_manager.count() == 0

    mutated_source = _source()
    object.__setattr__(mutated_source, "evidence_ref", "broker:mutated")
    object.__setattr__(mutated_source, "__post_init__", lambda: None)
    drift = _registration_runtime(source_provider=_DriftingProvider(_source(), mutated_source))
    with pytest.raises(R8BrokerMonitoringRegistryUnavailable):
        drift.register_period.execute(_command())
    assert R8BrokerMonitoringPeriodReceiptModel._default_manager.count() == 0

    with pytest.raises(RuntimeError, match="outer rollback"):
        with transaction.atomic():
            _registration_runtime().register_period.execute(_command())
            assert R8BrokerMonitoringPeriodReceiptModel._default_manager.count() == 1
            raise RuntimeError("outer rollback")
    assert R8BrokerMonitoringPeriodReceiptModel._default_manager.count() == 0

    _registration_runtime().register_period.execute(_command())
    source = _source()
    fork_source = R8BrokerReconciliationSourceReceipt.create(
        source_receipt_id=source.source_receipt_id,
        source_receipt_version=source.source_receipt_version,
        definition_hash=source.definition_hash,
        available_at=source.available_at,
        valid_until=source.valid_until,
        evidence_ref="broker:r8-monitoring-reconciliation-source:fork",
    )
    fork = _registration_runtime(source_provider=_Provider(fork_source))
    with pytest.raises(R8BrokerMonitoringRegistryUnavailable) as raised:
        fork.register_period.execute(_command())
    assert isinstance(raised.value.__cause__, R8BrokerMonitoringRegistryConflict)
    assert R8BrokerMonitoringPeriodReceiptModel._default_manager.count() == 1


@pytest.mark.django_db(transaction=True)
def test_period_receipt_append_only_guards_and_raw_tamper_detection() -> None:
    """All ORM mutation paths fail and raw header changes break strict replay."""

    runtime = _registration_runtime()
    receipt = runtime.register_period.execute(_command())
    row = R8BrokerMonitoringPeriodReceiptModel._default_manager.get()

    with pytest.raises(ValidationError):
        row.save()
    with pytest.raises(ValidationError):
        row.save_base(force_update=True)
    with pytest.raises(ValidationError):
        row.delete()
    with pytest.raises(ValidationError):
        R8BrokerMonitoringPeriodReceiptModel._default_manager.update(total_cost_amount=0)
    with pytest.raises(ValidationError):
        R8BrokerMonitoringPeriodReceiptModel._default_manager.all().delete()
    with pytest.raises(ValidationError):
        R8BrokerMonitoringPeriodReceiptModel._default_manager.bulk_create([])
    with pytest.raises(ValidationError):
        R8BrokerMonitoringPeriodReceiptModel._default_manager.get_or_create(receipt_id="forbidden")
    with pytest.raises(ValidationError):
        R8BrokerMonitoringPeriodReceiptModel(receipt_id="forbidden").save(force_insert=True)

    table = connection.ops.quote_name(R8BrokerMonitoringPeriodReceiptModel._meta.db_table)
    with connection.cursor() as cursor:
        cursor.execute(
            f"UPDATE {table} SET planning_reference_id = %s WHERE receipt_id = %s",
            ["portfolio-transition-plan:tampered", receipt.receipt_id],
        )
    with pytest.raises(R8BrokerMonitoringRegistryCorruption, match="headers"):
        runtime.receipt_provider.get_exact(
            receipt_id=receipt.receipt_id,
            receipt_version=receipt.receipt_version,
            expected_receipt_hash=receipt.content_hash,
            as_of=NOW,
        )


@pytest.mark.django_db(transaction=True)
def test_public_mutation_is_inert_and_empty_feedback_stays_absent() -> None:
    """Empty production state supplies no synthetic Broker feedback and writes nothing."""

    public = build_django_r8_broker_monitoring_owner_runtime()
    with pytest.raises(R8BrokerMonitoringRegistryUnavailable):
        public.register_period.execute(_command())
    assert R8BrokerMonitoringPeriodReceiptModel._default_manager.count() == 0

    definition = _definition()
    assert (
        DjangoR8BrokerMonitoringFeedbackAdapter().list_exact(
            result_id=definition.result_id,
            result_hash=definition.result_hash,
            receipt_id=definition.portfolio_receipt_id,
            receipt_hash=definition.portfolio_receipt_hash,
            calendar_id=definition.calendar_id,
            calendar_hash=definition.calendar_hash,
            period_ids=(definition.period_id,),
            as_of=NOW,
        )
        == ()
    )
    assert R8BrokerMonitoringPeriodReceiptModel._default_manager.count() == 0
