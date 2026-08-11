"""TDD contracts for canonical Research-owned R4 monitoring registries."""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import fields
from datetime import datetime

import pytest

from apps.research.application.r4_promotion_monitoring_owner_registry import (
    R4MonitoringOwnerRegistryUnavailable,
    RegisterR4MonitoringCalendar,
    RegisterR4MonitoringCalendarCommand,
    RegisterR4MonitoringPolicy,
    RegisterR4MonitoringPolicyCommand,
)
from apps.research.domain.r4_promotion_monitoring_owner_registry import (
    R4MonitoringCalendarDefinition,
    R4MonitoringOwnerRecordKind,
    R4MonitoringOwnerSourceReceipt,
    R4MonitoringPolicyDefinition,
)
from tests.unit.research.r4_promotion_monitoring_factories import (
    monitoring_calendar,
    monitoring_policy,
)


class _Provider:
    unit_of_work_key = "django:default"

    def __init__(self, value: object) -> None:
        self.value = value
        self.calls = 0

    def get_exact(self, **kwargs: object) -> object:
        self.calls += 1
        return self.value


class _Store:
    unit_of_work_key = "django:default"

    def __init__(self) -> None:
        self.policy = None
        self.calendar = None

    def atomic(self) -> nullcontext[None]:
        return nullcontext()

    def append_policy(self, policy: object, **lineage: object) -> object:
        self.policy = policy
        return policy

    def append_calendar(self, calendar: object, **lineage: object) -> object:
        self.calendar = calendar
        return calendar


class _Clock:
    unit_of_work_key = "django:default"

    def __init__(self, value: datetime) -> None:
        self.value = value

    def now(self) -> datetime:
        return self.value


class _ThrowingClock(_Clock):
    def now(self) -> datetime:
        raise RuntimeError("clock unavailable")


class _ThrowingProvider(_Provider):
    def get_exact(self, **kwargs: object) -> object:
        raise RuntimeError("provider unavailable")


def _receipt(
    *,
    record_kind: R4MonitoringOwnerRecordKind,
    definition_hash: str,
    now: datetime,
) -> R4MonitoringOwnerSourceReceipt:
    return R4MonitoringOwnerSourceReceipt.create(
        record_kind=record_kind,
        source_owner="research",
        source_receipt_id=f"receipt-{record_kind.value}",
        source_receipt_version="receipt.v1",
        definition_hash=definition_hash,
        available_at=now,
        valid_until=monitoring_policy().active_until,
    )


def test_registration_commands_are_id_only() -> None:
    assert {item.name for item in fields(RegisterR4MonitoringPolicyCommand)} == {
        "policy_id",
        "policy_version",
        "source_receipt_id",
        "source_receipt_version",
        "as_of",
    }
    assert {item.name for item in fields(RegisterR4MonitoringCalendarCommand)} == {
        "calendar_id",
        "calendar_version",
        "source_receipt_id",
        "source_receipt_version",
        "as_of",
    }


def test_policy_registration_double_reads_definition_and_source() -> None:
    original = monitoring_policy()
    definition = R4MonitoringPolicyDefinition.from_policy(original)
    definition_provider = _Provider(definition)
    source_provider = _Provider(
        _receipt(
            record_kind=R4MonitoringOwnerRecordKind.POLICY,
            definition_hash=definition.content_hash,
            now=original.recorded_at,
        )
    )
    store = _Store()
    service = RegisterR4MonitoringPolicy(
        definition_provider=definition_provider,
        source_provider=source_provider,
        store=store,
        clock=_Clock(original.recorded_at),
    )

    result = service.execute(
        RegisterR4MonitoringPolicyCommand(
            policy_id=original.policy_id,
            policy_version=original.policy_version,
            source_receipt_id="receipt-policy",
            source_receipt_version="receipt.v1",
            as_of=original.recorded_at,
        )
    )

    assert result == original
    assert definition_provider.calls == 2
    assert source_provider.calls == 2
    assert store.policy == original


def test_calendar_registration_double_reads_definition_and_source() -> None:
    original = monitoring_calendar()
    definition = R4MonitoringCalendarDefinition.from_calendar(original)
    definition_provider = _Provider(definition)
    source_provider = _Provider(
        _receipt(
            record_kind=R4MonitoringOwnerRecordKind.CALENDAR,
            definition_hash=definition.content_hash,
            now=original.recorded_at,
        )
    )
    store = _Store()
    service = RegisterR4MonitoringCalendar(
        definition_provider=definition_provider,
        source_provider=source_provider,
        store=store,
        clock=_Clock(original.recorded_at),
    )

    result = service.execute(
        RegisterR4MonitoringCalendarCommand(
            calendar_id=original.calendar_id,
            calendar_version=original.calendar_version,
            source_receipt_id="receipt-calendar",
            source_receipt_version="receipt.v1",
            as_of=original.recorded_at,
        )
    )

    assert result == original
    assert definition_provider.calls == 2
    assert source_provider.calls == 2
    assert store.calendar == original


def test_owner_uow_mismatch_is_rejected_before_reads() -> None:
    definition = R4MonitoringPolicyDefinition.from_policy(monitoring_policy())
    source = _Provider(None)
    source.unit_of_work_key = "django:other"

    with pytest.raises(R4MonitoringOwnerRegistryUnavailable, match="unit of work"):
        RegisterR4MonitoringPolicy(
            definition_provider=_Provider(definition),
            source_provider=source,
            store=_Store(),
            clock=_Clock(monitoring_policy().recorded_at),
        )


def test_policy_clock_uow_mismatch_is_rejected_before_reads() -> None:
    definition = R4MonitoringPolicyDefinition.from_policy(monitoring_policy())
    clock = _Clock(monitoring_policy().recorded_at)
    clock.unit_of_work_key = "django:other"

    with pytest.raises(R4MonitoringOwnerRegistryUnavailable, match="unit of work"):
        RegisterR4MonitoringPolicy(
            definition_provider=_Provider(definition),
            source_provider=_Provider(None),
            store=_Store(),
            clock=clock,
        )


def test_policy_clock_drift_and_owner_replacement_fail_before_write() -> None:
    original = monitoring_policy()
    definition = R4MonitoringPolicyDefinition.from_policy(original)
    source = _receipt(
        record_kind=R4MonitoringOwnerRecordKind.POLICY,
        definition_hash=definition.content_hash,
        now=original.recorded_at,
    )
    clock = _Clock(original.recorded_at)
    store = _Store()
    service = RegisterR4MonitoringPolicy(
        definition_provider=_Provider(definition),
        source_provider=_Provider(source),
        store=store,
        clock=clock,
    )
    clock.unit_of_work_key = "django:other"
    with pytest.raises(R4MonitoringOwnerRegistryUnavailable, match="unit of work"):
        service.execute(
            RegisterR4MonitoringPolicyCommand(
                original.policy_id,
                original.policy_version,
                "receipt-policy",
                "receipt.v1",
                original.recorded_at,
            )
        )
    assert store.policy is None

    clock.unit_of_work_key = "django:default"
    object.__setattr__(service, "_definition_provider", _Provider(definition))
    with pytest.raises(R4MonitoringOwnerRegistryUnavailable, match="replaced"):
        service.execute(
            RegisterR4MonitoringPolicyCommand(
                original.policy_id,
                original.policy_version,
                "receipt-policy",
                "receipt.v1",
                original.recorded_at,
            )
        )
    assert store.policy is None


def test_calendar_throwing_clock_and_provider_are_unavailable_zero_write() -> None:
    original = monitoring_calendar()
    definition = R4MonitoringCalendarDefinition.from_calendar(original)
    source = _receipt(
        record_kind=R4MonitoringOwnerRecordKind.CALENDAR,
        definition_hash=definition.content_hash,
        now=original.recorded_at,
    )
    command = RegisterR4MonitoringCalendarCommand(
        original.calendar_id,
        original.calendar_version,
        "receipt-calendar",
        "receipt.v1",
        original.recorded_at,
    )
    store = _Store()
    throwing_clock = RegisterR4MonitoringCalendar(
        definition_provider=_Provider(definition),
        source_provider=_Provider(source),
        store=store,
        clock=_ThrowingClock(original.recorded_at),
    )
    with pytest.raises(R4MonitoringOwnerRegistryUnavailable, match="unavailable"):
        throwing_clock.execute(command)
    assert store.calendar is None

    throwing_provider = RegisterR4MonitoringCalendar(
        definition_provider=_ThrowingProvider(definition),
        source_provider=_Provider(source),
        store=store,
        clock=_Clock(original.recorded_at),
    )
    with pytest.raises(R4MonitoringOwnerRegistryUnavailable, match="unavailable"):
        throwing_provider.execute(command)
    assert store.calendar is None
