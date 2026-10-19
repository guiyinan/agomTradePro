"""Adapt fixed automatic-caller clocks without passing datetime subclasses."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, tzinfo
from types import ModuleType

import django.utils.timezone as django_timezone
import pytest

import apps.config_center.application.runtime_config as runtime_config_application
import apps.config_center.application.runtime_public as runtime_public_application
import apps.config_center.domain.runtime_config as runtime_config_domain
import apps.data_center.infrastructure.provider_response_capture as provider_response_capture
import apps.data_center.infrastructure.tushare_client as tushare_client
import apps.simulated_trading.execution_current_reference_composition as current_reference_composition
from tests.component.data_center import (
    test_formal_exchange_calendar_publication_repository as calendar_source_fixture,
)
from tests.support import ash03_auto_calendar_fixture

_KNOWLEDGE_AT = datetime(2026, 10, 16, 1, 59, 50, tzinfo=UTC)


def freeze_auto_uow_fixture_clocks_native(monkeypatch: pytest.MonkeyPatch) -> datetime:
    """Freeze fixture writes while keeping ``datetime.now`` results exact-typed.

    The frozen calendar helper owns the list of runtime clock seams. This adapter
    changes only its temporary ``datetime`` subclass factory so strict Domain
    constructors continue to receive the standard-library ``datetime`` type.
    """

    monkeypatch.setattr(
        ash03_auto_calendar_fixture,
        "_datetime_class_at",
        _datetime_class_at_native,
    )
    frozen_at = ash03_auto_calendar_fixture.freeze_auto_uow_fixture_clocks(monkeypatch)
    monkeypatch.setattr(
        provider_response_capture, "datetime", _datetime_class_at_native(_KNOWLEDGE_AT)
    )
    monkeypatch.setattr(runtime_config_domain, "datetime", _runtime_knowledge_clock())
    if frozen_at != _KNOWLEDGE_AT or type(frozen_at) is not datetime:
        raise AssertionError("fixture knowledge clock must be the exact native datetime")
    if runtime_public_application.datetime is not datetime:
        raise AssertionError("runtime public cutoff checks must retain the native datetime class")
    return frozen_at


def advance_auto_uow_fixture_clocks(
    monkeypatch: pytest.MonkeyPatch,
    *,
    as_of: datetime,
) -> None:
    """Advance every current clock seam to the exact execution cutoff.

    Fixture evidence is persisted first at its historical knowledge times. The
    caller then runs at ``as_of`` so a publication timestamp later than setup
    cannot be used before it exists.
    """

    advance_auto_uow_fixture_read_clock(monkeypatch, as_of=as_of)
    fixed_datetime = _datetime_class_at_native(as_of)

    for module in _direct_datetime_modules():
        monkeypatch.setattr(module, "datetime", fixed_datetime)
    if runtime_public_application.datetime is not datetime:
        raise AssertionError("runtime public cutoff checks must retain the native datetime class")
    if any(
        type(module.datetime.now(UTC)) is not datetime or module.datetime.now(UTC) != as_of
        for module in _direct_datetime_modules()
    ):
        raise AssertionError("runtime direct clocks must return the exact native cutoff")


def advance_auto_uow_fixture_read_clock(
    monkeypatch: pytest.MonkeyPatch, *, as_of: datetime
) -> None:
    """Advance audit and execution reads while prerequisite write clocks stay bounded."""

    if type(as_of) is not datetime or as_of.utcoffset() != timedelta(0):
        raise TypeError("execution cutoff must be an exact aware UTC datetime")

    def current_time() -> datetime:
        """Return the native datetime cutoff for Django's clock seam."""

        return as_of

    def current_server_clock(
        _clock: current_reference_composition._ServerUTCClock,
    ) -> datetime:
        """Return the same cutoff through the production settlement clock."""

        return as_of

    monkeypatch.setattr(django_timezone, "now", current_time)
    monkeypatch.setattr(
        current_reference_composition._ServerUTCClock,
        "now",
        current_server_clock,
    )
    if runtime_public_application.datetime is not datetime:
        raise AssertionError("runtime public cutoff checks must retain the native datetime class")
    if type(django_timezone.now()) is not datetime or django_timezone.now() != as_of:
        raise AssertionError("Django execution clock must return the exact native cutoff")
    if current_reference_composition._ServerUTCClock().now() != as_of:
        raise AssertionError("settlement execution clock must equal the explicit cutoff")


def _runtime_knowledge_clock() -> type[datetime]:
    """Give distinct runtime snapshots increasing native times before publication."""

    tick = 0

    class _RuntimeKnowledgeDateTime(datetime):
        @classmethod
        def now(cls, tz: tzinfo | None = None) -> datetime:
            """Advance by one microsecond without reaching the publication cutoff."""

            nonlocal tick
            tick += 1
            value = _KNOWLEDGE_AT + timedelta(microseconds=tick)
            if value >= _KNOWLEDGE_AT + timedelta(seconds=1):
                raise AssertionError("runtime fixture clock exceeded its knowledge window")
            return value.replace(tzinfo=None) if tz is None else value.astimezone(tz)

    return _RuntimeKnowledgeDateTime


def _direct_datetime_modules() -> tuple[ModuleType, ...]:
    """Return only direct timestamp aliases patched by the frozen helper."""

    return (
        runtime_config_application,
        runtime_config_domain,
        provider_response_capture,
        tushare_client,
        calendar_source_fixture,
    )


def _datetime_class_at_native(value: datetime) -> type[datetime]:
    """Build a clock class whose ``now`` returns a standard-library value."""

    class _FixedDateTime(datetime):
        @classmethod
        def now(cls, tz: tzinfo | None = None) -> datetime:
            """Return ``value`` converted to the requested timezone as base type."""

            selected = value.replace(tzinfo=None) if tz is None else value.astimezone(tz)
            return datetime(
                selected.year,
                selected.month,
                selected.day,
                selected.hour,
                selected.minute,
                selected.second,
                selected.microsecond,
                tzinfo=selected.tzinfo,
                fold=selected.fold,
            )

    return _FixedDateTime


__all__ = [
    "advance_auto_uow_fixture_clocks",
    "advance_auto_uow_fixture_read_clock",
    "freeze_auto_uow_fixture_clocks_native",
]
