"""Contracts for Broker-owned R8 reconciliation monitoring receipts."""

from contextlib import nullcontext
from dataclasses import fields
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from apps.broker_execution.application.r8_monitoring_reconciliation_registry import (
    R8BrokerMonitoringRegistryUnavailable,
    RegisterR8BrokerMonitoringPeriod,
    RegisterR8BrokerMonitoringPeriodCommand,
)
from apps.broker_execution.domain.r8_monitoring_reconciliation import (
    R8BrokerMonitoringMetricKey,
    R8BrokerMonitoringMetricRawFact,
    R8BrokerMonitoringPeriodReceipt,
    R8BrokerReconciliationDefinition,
    R8BrokerReconciliationMember,
    R8BrokerReconciliationMemberKind,
    R8BrokerReconciliationSourceReceipt,
)
from apps.broker_execution.infrastructure.r8_monitoring_reconciliation_codec import (
    R8BrokerMonitoringCodecError,
    decode_r8_broker_monitoring_period_receipt,
    decode_r8_broker_reconciliation_definition,
    decode_r8_broker_reconciliation_source_receipt,
    encode_r8_broker_monitoring_period_receipt,
    encode_r8_broker_reconciliation_definition,
    encode_r8_broker_reconciliation_source_receipt,
)

NOW = datetime(2026, 1, 15, 8, tzinfo=UTC)
PERIOD_START = NOW - timedelta(days=8)
PERIOD_END = NOW - timedelta(days=1)


def _members() -> tuple[R8BrokerReconciliationMember, ...]:
    return (
        R8BrokerReconciliationMember.create(
            member_id="broker-fill-manifest:period-1",
            member_version="broker-fill-manifest.v1",
            member_kind=R8BrokerReconciliationMemberKind.FILL_MANIFEST,
            content_hash="1" * 64,
            observed_at=PERIOD_END - timedelta(hours=2),
            available_at=PERIOD_END + timedelta(minutes=30),
        ),
        R8BrokerReconciliationMember.create(
            member_id="portfolio-transition-plan:1",
            member_version="portfolio-transition-plan.v1",
            member_kind=R8BrokerReconciliationMemberKind.ORDER_PLAN_BINDING,
            content_hash="7" * 64,
            observed_at=PERIOD_END - timedelta(hours=1),
            available_at=PERIOD_END + timedelta(minutes=45),
        ),
        R8BrokerReconciliationMember.create(
            member_id="broker-reconciliation-manifest:period-1",
            member_version="broker-reconciliation-manifest.v1",
            member_kind=R8BrokerReconciliationMemberKind.RECONCILIATION_MANIFEST,
            content_hash="3" * 64,
            observed_at=PERIOD_END,
            available_at=PERIOD_END + timedelta(hours=1),
        ),
    )


def _facts() -> tuple[R8BrokerMonitoringMetricRawFact, ...]:
    members = _members()
    return (
        R8BrokerMonitoringMetricRawFact.create(
            metric_key=R8BrokerMonitoringMetricKey.TOTAL_COST_RATE,
            numerator_name="actual_total_cost_amount",
            numerator=Decimal("12.50"),
            denominator_name="executed_notional",
            denominator=Decimal("10000"),
            source_member_hashes=(members[0].content_hash,),
        ),
        R8BrokerMonitoringMetricRawFact.create(
            metric_key=R8BrokerMonitoringMetricKey.ADVERSE_SLIPPAGE_RATE,
            numerator_name="adverse_slippage_amount",
            numerator=Decimal("5"),
            denominator_name="executed_notional",
            denominator=Decimal("10000"),
            source_member_hashes=(members[0].content_hash, members[1].content_hash),
        ),
        R8BrokerMonitoringMetricRawFact.create(
            metric_key=R8BrokerMonitoringMetricKey.RECONCILIATION_BREAK_RATE,
            numerator_name="reconciliation_break_count",
            numerator=Decimal("2"),
            denominator_name="reconciliation_comparison_count",
            denominator=Decimal("200"),
            source_member_hashes=(members[2].content_hash,),
        ),
    )


def _definition() -> R8BrokerReconciliationDefinition:
    return R8BrokerReconciliationDefinition.create(
        result_id="governed-optimization-result:1",
        result_hash="4" * 64,
        portfolio_receipt_id="governed-optimization-receipt:1",
        portfolio_receipt_version="governed-optimization-input-receipt.v1",
        portfolio_receipt_hash="5" * 64,
        calendar_id="r8-monitoring-calendar:weekly:v1",
        calendar_version="r8-monitoring-calendar.v1",
        calendar_hash="6" * 64,
        period_id="r8-monitoring-calendar:weekly:v1:period:1",
        period_start_at=PERIOD_START,
        period_end_at=PERIOD_END,
        planning_reference_id="portfolio-transition-plan:1",
        planning_reference_version="portfolio-transition-plan.v1",
        planning_reference_hash="7" * 64,
        reconciliation_manifest_id="broker-reconciliation-manifest:period-1",
        reconciliation_manifest_version="broker-reconciliation-manifest.v1",
        reconciliation_manifest_hash="3" * 64,
        members=_members(),
        metric_facts=_facts(),
        valid_until=NOW + timedelta(days=30),
        evidence_ref="broker:r8-monitoring-reconciliation:period-1",
    )


def _source() -> R8BrokerReconciliationSourceReceipt:
    definition = _definition()
    return R8BrokerReconciliationSourceReceipt.create(
        source_receipt_id="broker-r8-reconciliation-source:period-1",
        source_receipt_version="broker-r8-reconciliation-source.v1",
        definition_hash=definition.content_hash,
        available_at=definition.available_at,
        valid_until=definition.valid_until,
        evidence_ref="broker:r8-monitoring-reconciliation-source:period-1",
    )


def _command() -> RegisterR8BrokerMonitoringPeriodCommand:
    definition = _definition()
    source = _source()
    return RegisterR8BrokerMonitoringPeriodCommand(
        definition_id=definition.definition_id,
        definition_version=definition.definition_version,
        source_receipt_id=source.source_receipt_id,
        source_receipt_version=source.source_receipt_version,
        as_of=NOW,
    )


def test_command_is_identity_and_cutoff_only() -> None:
    """Callers cannot submit raw ratios, source members, or owner clocks."""

    assert tuple(item.name for item in fields(RegisterR8BrokerMonitoringPeriodCommand)) == (
        "definition_id",
        "definition_version",
        "source_receipt_id",
        "source_receipt_version",
        "as_of",
    )


def test_definition_seals_exact_raw_numerators_denominators_identity_and_clocks() -> None:
    """All three Broker metrics retain raw components and canonical evidence members."""

    definition = _definition()

    assert tuple(item.metric_key for item in definition.metric_facts) == tuple(
        R8BrokerMonitoringMetricKey
    )
    assert tuple(item.value for item in definition.metric_facts) == (
        Decimal("0.00125"),
        Decimal("0.0005"),
        Decimal("0.01"),
    )
    assert definition.observed_at == PERIOD_END
    assert definition.available_at == PERIOD_END + timedelta(hours=1)
    assert definition.reconciliation_manifest_hash == definition.members[-1].content_hash


def test_receipt_uses_only_trusted_owner_clock_and_preserves_source_clocks() -> None:
    """The owner ledger clock cannot replace member observation/availability clocks."""

    receipt = R8BrokerMonitoringPeriodReceipt.record(
        definition=_definition(),
        source_receipt=_source(),
        owner_recorded_at=NOW,
    )

    assert receipt.owner == "broker_execution"
    assert receipt.recorded_at == NOW
    assert receipt.observed_at == PERIOD_END
    assert receipt.available_at == PERIOD_END + timedelta(hours=1)


def test_strict_codec_round_trips_complete_graph_and_rejects_surplus_keys() -> None:
    """Persisted payloads cannot omit raw inputs or smuggle aggregate values."""

    definition = _definition()
    source = _source()
    receipt = R8BrokerMonitoringPeriodReceipt.record(
        definition=definition,
        source_receipt=source,
        owner_recorded_at=NOW,
    )
    definition_payload = encode_r8_broker_reconciliation_definition(definition)
    source_payload = encode_r8_broker_reconciliation_source_receipt(source)
    receipt_payload = encode_r8_broker_monitoring_period_receipt(receipt)

    assert decode_r8_broker_reconciliation_definition(definition_payload) == definition
    assert decode_r8_broker_reconciliation_source_receipt(source_payload) == source
    assert decode_r8_broker_monitoring_period_receipt(receipt_payload) == receipt

    forged = dict(definition_payload)
    forged["total_cost_rate"] = "0"
    with pytest.raises(R8BrokerMonitoringCodecError, match="keys"):
        decode_r8_broker_reconciliation_definition(forged)

    missing = dict(receipt_payload)
    del missing["source_receipt"]
    with pytest.raises(R8BrokerMonitoringCodecError, match="keys"):
        decode_r8_broker_monitoring_period_receipt(missing)


class _Provider:
    unit_of_work_key = "django:default"

    def __init__(self, value: object) -> None:
        self.value = value
        self.calls = 0

    def get_exact(self, **selectors: object) -> object:
        del selectors
        self.calls += 1
        return self.value


class _Store:
    unit_of_work_key = "django:default"

    def __init__(self) -> None:
        self.calls = 0

    def atomic(self):  # type: ignore[no-untyped-def]
        return nullcontext()

    def append(
        self,
        receipt: R8BrokerMonitoringPeriodReceipt,
        *,
        definition: R8BrokerReconciliationDefinition,
        source_receipt: R8BrokerReconciliationSourceReceipt,
    ) -> R8BrokerMonitoringPeriodReceipt:
        assert definition == _definition()
        assert source_receipt == _source()
        self.calls += 1
        return receipt


class _Clock:
    unit_of_work_key = "django:default"

    def now(self) -> datetime:
        return NOW


def _use_case(
    definition: object,
    source: object,
) -> tuple[RegisterR8BrokerMonitoringPeriod, _Store]:
    store = _Store()
    return (
        RegisterR8BrokerMonitoringPeriod(
            definition_provider=_Provider(definition),
            source_provider=_Provider(source),
            store=store,
            clock=_Clock(),
        ),
        store,
    )


def test_registration_double_reads_exact_sources_and_uses_trusted_clock() -> None:
    """Stable source owners produce one server-clocked append."""

    use_case, store = _use_case(_definition(), _source())

    receipt = use_case.execute(_command())

    assert receipt.recorded_at == NOW
    assert store.calls == 1


def test_missing_source_and_mutated_command_are_zero_write() -> None:
    """Absence and validator bypass stop before any append."""

    use_case, store = _use_case(_definition(), None)
    with pytest.raises(R8BrokerMonitoringRegistryUnavailable, match="source"):
        use_case.execute(_command())

    command = _command()
    object.__setattr__(command, "definition_id", "")
    object.__setattr__(command, "__post_init__", lambda: None)
    with pytest.raises(R8BrokerMonitoringRegistryUnavailable, match="command"):
        use_case.execute(command)
    assert store.calls == 0
