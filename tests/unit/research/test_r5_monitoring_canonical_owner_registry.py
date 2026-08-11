from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta

import pytest

from apps.research.application.r5_monitoring_owner_registry import (
    R5MonitoringOwnerRegistryUnavailable,
    RegisterR5MonitoringCalendar,
    RegisterR5MonitoringCalendarCommand,
    RegisterR5MonitoringPolicy,
    RegisterR5MonitoringPolicyCommand,
)
from apps.research.domain.r5_monitoring_owner_registry import (
    R5MonitoringCalendarDefinition,
    R5MonitoringOwnerRecordKind,
    R5MonitoringOwnerSourceReceipt,
    R5MonitoringPolicyDefinition,
)
from tests.unit.research.test_r5_relative_value_monitoring import (
    BASE,
    _calendar,
    _policy,
)


@dataclass
class _DefinitionProvider:
    value: object
    unit_of_work_key: str = "django:default"
    calls: int = 0

    def get_exact(
        self,
        *,
        owner_id: str,
        owner_version: str,
        as_of: datetime,
    ) -> object:
        del owner_id, owner_version, as_of
        self.calls += 1
        return self.value


@dataclass
class _SourceProvider:
    value: R5MonitoringOwnerSourceReceipt
    unit_of_work_key: str = "django:default"
    calls: int = 0

    def get_exact(
        self,
        *,
        record_kind: R5MonitoringOwnerRecordKind,
        owner_id: str,
        owner_version: str,
        definition_hash: str,
        as_of: datetime,
    ) -> R5MonitoringOwnerSourceReceipt:
        del record_kind, owner_id, owner_version, definition_hash, as_of
        self.calls += 1
        return self.value


class _Store:
    unit_of_work_key = "django:default"

    def __init__(self) -> None:
        self.policy_values: list[object] = []
        self.calendar_values: list[object] = []
        self.atomic_entries = 0

    @contextmanager
    def atomic(self) -> Iterator[None]:
        self.atomic_entries += 1
        yield

    def append_policy(
        self,
        *,
        definition: R5MonitoringPolicyDefinition,
        source: R5MonitoringOwnerSourceReceipt,
        ledger_recorded_at: datetime,
    ) -> object:
        del source, ledger_recorded_at
        self.policy_values.append(definition.policy)
        return definition.policy

    def append_calendar(
        self,
        *,
        definition: R5MonitoringCalendarDefinition,
        source: R5MonitoringOwnerSourceReceipt,
        ledger_recorded_at: datetime,
    ) -> object:
        del source, ledger_recorded_at
        self.calendar_values.append(definition.calendar)
        return definition.calendar


@dataclass
class _Clock:
    current: datetime
    unit_of_work_key: str = "django:default"
    calls: int = 0

    def now(self) -> datetime:
        self.calls += 1
        return self.current


class _ThrowingClock(_Clock):
    def now(self) -> datetime:
        raise RuntimeError("clock failed")


def _source(
    *,
    kind: R5MonitoringOwnerRecordKind,
    owner_id: str,
    owner_version: str,
    definition_hash: str,
) -> R5MonitoringOwnerSourceReceipt:
    return R5MonitoringOwnerSourceReceipt.create(
        record_kind=kind,
        source_owner="research",
        source_receipt_id=f"source:{owner_id}",
        source_receipt_version="v1",
        owner_id=owner_id,
        owner_version=owner_version,
        definition_hash=definition_hash,
        available_at=BASE - timedelta(minutes=1),
        valid_until=BASE + timedelta(days=4),
    )


def test_policy_registration_double_reads_definition_and_source_in_shared_uow() -> None:
    policy = _policy()
    definition = R5MonitoringPolicyDefinition.from_policy(policy)
    definition_provider = _DefinitionProvider(definition)
    source_provider = _SourceProvider(
        _source(
            kind=R5MonitoringOwnerRecordKind.POLICY,
            owner_id=policy.policy_id,
            owner_version=policy.policy_version,
            definition_hash=definition.content_hash,
        )
    )
    store = _Store()
    clock = _Clock(BASE)
    service = RegisterR5MonitoringPolicy(
        definition_provider=definition_provider,
        source_provider=source_provider,
        store=store,
        clock=clock,
    )

    result = service.execute(
        RegisterR5MonitoringPolicyCommand(
            policy_id=policy.policy_id,
            policy_version=policy.policy_version,
        )
    )

    assert result == policy
    assert definition_provider.calls == 2
    assert source_provider.calls == 2
    assert clock.calls == 1
    assert store.atomic_entries == 1
    assert store.policy_values == [policy]


def test_calendar_registration_is_id_only_and_double_read() -> None:
    calendar = _calendar()
    definition = R5MonitoringCalendarDefinition.from_calendar(calendar)
    definition_provider = _DefinitionProvider(definition)
    source_provider = _SourceProvider(
        _source(
            kind=R5MonitoringOwnerRecordKind.CALENDAR,
            owner_id=calendar.owner.owner_id,
            owner_version=calendar.owner.owner_version,
            definition_hash=definition.content_hash,
        )
    )
    store = _Store()
    clock = _Clock(BASE)

    result = RegisterR5MonitoringCalendar(
        definition_provider=definition_provider,
        source_provider=source_provider,
        store=store,
        clock=clock,
    ).execute(
        RegisterR5MonitoringCalendarCommand(
            calendar_id=calendar.owner.owner_id,
            calendar_version=calendar.owner.owner_version,
        )
    )

    assert result == calendar
    assert definition_provider.calls == 2
    assert source_provider.calls == 2
    assert store.calendar_values == [calendar]
    assert tuple(RegisterR5MonitoringCalendarCommand.__dataclass_fields__) == (
        "calendar_id",
        "calendar_version",
    )


def test_registry_clock_mismatch_drift_throw_and_owner_replacement_are_zero_write() -> None:
    policy = _policy()
    definition = R5MonitoringPolicyDefinition.from_policy(policy)
    source = _source(
        kind=R5MonitoringOwnerRecordKind.POLICY,
        owner_id=policy.policy_id,
        owner_version=policy.policy_version,
        definition_hash=definition.content_hash,
    )
    mismatch_clock = _Clock(BASE, unit_of_work_key="django:other")
    with pytest.raises(R5MonitoringOwnerRegistryUnavailable, match="unit of work"):
        RegisterR5MonitoringPolicy(
            definition_provider=_DefinitionProvider(definition),
            source_provider=_SourceProvider(source),
            store=_Store(),
            clock=mismatch_clock,
        )

    store = _Store()
    clock = _Clock(BASE)
    service = RegisterR5MonitoringPolicy(
        definition_provider=_DefinitionProvider(definition),
        source_provider=_SourceProvider(source),
        store=store,
        clock=clock,
    )
    command = RegisterR5MonitoringPolicyCommand(policy.policy_id, policy.policy_version)
    clock.unit_of_work_key = "django:other"
    with pytest.raises(R5MonitoringOwnerRegistryUnavailable, match="unit of work"):
        service.execute(command)
    assert store.policy_values == []

    clock.unit_of_work_key = "django:default"
    object.__setattr__(service, "_definition_provider", _DefinitionProvider(definition))
    with pytest.raises(R5MonitoringOwnerRegistryUnavailable, match="replaced"):
        service.execute(command)
    assert store.policy_values == []

    throwing_store = _Store()
    throwing = RegisterR5MonitoringPolicy(
        definition_provider=_DefinitionProvider(definition),
        source_provider=_SourceProvider(source),
        store=throwing_store,
        clock=_ThrowingClock(BASE),
    )
    with pytest.raises(R5MonitoringOwnerRegistryUnavailable, match="unavailable"):
        throwing.execute(command)
    assert throwing_store.policy_values == []
