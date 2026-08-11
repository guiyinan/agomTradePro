"""Contracts for the Portfolio-owned R8 monitoring calendar registry."""

from contextlib import nullcontext
from dataclasses import fields
from datetime import UTC, datetime, timedelta

import pytest

from apps.portfolio.application.r8_monitoring_calendar_registry import (
    R8MonitoringCalendarRegistryUnavailable,
    RegisterR8MonitoringCalendar,
    RegisterR8MonitoringCalendarCommand,
)
from apps.portfolio.domain.governed_optimization_monitoring import (
    GovernedOptimizationMonitoringCalendar,
    OptimizationMonitoringPeriod,
)
from apps.portfolio.domain.r8_monitoring_calendar_registry import (
    R8MonitoringCalendarDefinition,
    R8MonitoringCalendarSourceReceipt,
)
from apps.portfolio.infrastructure.r8_monitoring_calendar_codec import (
    R8MonitoringCalendarRegistryCodecError,
    decode_r8_monitoring_calendar_definition,
    decode_r8_monitoring_calendar_source_receipt,
    encode_r8_monitoring_calendar_definition,
    encode_r8_monitoring_calendar_source_receipt,
)

NOW = datetime(2026, 8, 11, 8, tzinfo=UTC)
CALENDAR_ID = "r8-monitoring-calendar:weekly:v1"
CALENDAR_VERSION = "r8-monitoring-calendar.v1"


def _periods() -> tuple[OptimizationMonitoringPeriod, ...]:
    return tuple(
        OptimizationMonitoringPeriod.create(
            calendar_id=CALENDAR_ID,
            calendar_version=CALENDAR_VERSION,
            index=index,
            start_at=NOW + timedelta(days=index),
            end_at=NOW + timedelta(days=index + 1),
        )
        for index in range(1, 4)
    )


def _definition() -> R8MonitoringCalendarDefinition:
    return R8MonitoringCalendarDefinition.create(
        calendar_id=CALENDAR_ID,
        calendar_version=CALENDAR_VERSION,
        periods=_periods(),
        available_at=NOW - timedelta(hours=1),
        valid_until=NOW + timedelta(days=30),
        evidence_ref="portfolio:r8-monitoring-calendar:weekly:v1",
    )


def _source() -> R8MonitoringCalendarSourceReceipt:
    definition = _definition()
    return R8MonitoringCalendarSourceReceipt.create(
        source_receipt_id="r8-monitoring-calendar-source:weekly:v1",
        source_receipt_version="r8-monitoring-calendar-source.v1",
        definition_hash=definition.content_hash,
        available_at=NOW - timedelta(minutes=30),
        valid_until=NOW + timedelta(days=30),
        evidence_ref="portfolio:r8-monitoring-calendar-owner:weekly:v1",
    )


def test_registration_command_is_identity_and_cutoff_only() -> None:
    """Callers cannot submit periods, a finished calendar, or owner clocks."""

    assert tuple(item.name for item in fields(RegisterR8MonitoringCalendarCommand)) == (
        "calendar_id",
        "calendar_version",
        "source_receipt_id",
        "source_receipt_version",
        "as_of",
    )


def test_definition_builds_server_clocked_portfolio_calendar() -> None:
    """Complete membership is sealed before the owner claims recorded_at."""

    calendar = _definition().build(owner_recorded_at=NOW)

    assert type(calendar) is GovernedOptimizationMonitoringCalendar
    assert calendar.owner == "portfolio"
    assert calendar.recorded_at == NOW
    assert tuple(item.index for item in calendar.periods) == (1, 2, 3)
    assert calendar.content_hash


def test_registry_codec_is_strict_and_round_trips_both_owner_inputs() -> None:
    """Missing or surplus JSON keys cannot alter a canonical definition/source."""

    definition = _definition()
    source = _source()
    definition_payload = encode_r8_monitoring_calendar_definition(definition)
    source_payload = encode_r8_monitoring_calendar_source_receipt(source)

    assert decode_r8_monitoring_calendar_definition(definition_payload) == definition
    assert decode_r8_monitoring_calendar_source_receipt(source_payload) == source

    forged = dict(definition_payload)
    forged["current"] = True
    with pytest.raises(R8MonitoringCalendarRegistryCodecError, match="keys"):
        decode_r8_monitoring_calendar_definition(forged)
    missing = dict(source_payload)
    del missing["definition_hash"]
    with pytest.raises(R8MonitoringCalendarRegistryCodecError, match="keys"):
        decode_r8_monitoring_calendar_source_receipt(missing)


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
        calendar: GovernedOptimizationMonitoringCalendar,
        *,
        definition: R8MonitoringCalendarDefinition,
        source_receipt: R8MonitoringCalendarSourceReceipt,
    ) -> GovernedOptimizationMonitoringCalendar:
        assert definition == _definition()
        assert source_receipt == _source()
        self.calls += 1
        return calendar


class _Clock:
    unit_of_work_key = "django:default"

    def now(self) -> datetime:
        return NOW


def _use_case(
    definition: object,
    source: object,
) -> tuple[RegisterR8MonitoringCalendar, _Store]:
    store = _Store()
    return (
        RegisterR8MonitoringCalendar(
            definition_provider=_Provider(definition),
            source_provider=_Provider(source),
            store=store,
            clock=_Clock(),
        ),
        store,
    )


def _command() -> RegisterR8MonitoringCalendarCommand:
    return RegisterR8MonitoringCalendarCommand(
        calendar_id=CALENDAR_ID,
        calendar_version=CALENDAR_VERSION,
        source_receipt_id="r8-monitoring-calendar-source:weekly:v1",
        source_receipt_version="r8-monitoring-calendar-source.v1",
        as_of=NOW,
    )


def test_registration_double_reads_and_builds_only_with_trusted_clock() -> None:
    """Stable exact owner inputs produce one server-clocked calendar append."""

    use_case, store = _use_case(_definition(), _source())

    calendar = use_case.execute(_command())

    assert calendar.recorded_at == NOW
    assert store.calls == 1


def test_missing_definition_and_mutated_command_are_zero_write() -> None:
    """Absence and validator bypasses stop before any registry append."""

    use_case, store = _use_case(None, _source())
    with pytest.raises(R8MonitoringCalendarRegistryUnavailable, match="definition"):
        use_case.execute(_command())

    command = _command()
    object.__setattr__(command, "calendar_id", "")
    object.__setattr__(command, "__post_init__", lambda: None)
    with pytest.raises(R8MonitoringCalendarRegistryUnavailable, match="command"):
        use_case.execute(command)
    assert store.calls == 0
