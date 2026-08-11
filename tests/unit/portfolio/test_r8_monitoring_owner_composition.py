"""Public isolation and empty-state tests for R8 monitoring owner composition."""

from datetime import UTC, datetime
from inspect import signature

import pytest

from apps.portfolio.application.r8_monitoring_calendar_registry import (
    R8MonitoringCalendarRegistryUnavailable,
    RegisterR8MonitoringCalendarCommand,
)
from apps.portfolio.r8_monitoring_owner_composition import (
    DjangoR8MonitoringOwnerRuntime,
    build_django_r8_monitoring_owner_runtime,
)

NOW = datetime(2026, 1, 1, 8, tzinfo=UTC)


def _walk_graph(root: object) -> tuple[object, ...]:
    pending = [root]
    visited: set[int] = set()
    values: list[object] = []
    while pending:
        current = pending.pop()
        if id(current) in visited:
            continue
        visited.add(id(current))
        values.append(current)
        state = getattr(current, "__dict__", None)
        if isinstance(state, dict):
            pending.extend(state.values())
        for owner in type(current).__mro__:
            slots = owner.__dict__.get("__slots__", ())
            if isinstance(slots, str):
                slots = (slots,)
            for slot in slots:
                if slot in {"__dict__", "__weakref__"}:
                    continue
                try:
                    pending.append(object.__getattribute__(current, slot))
                except AttributeError:
                    continue
    return tuple(values)


def test_public_owner_builder_is_using_only_and_has_no_write_capability() -> None:
    """The public graph may read owner rows but retains no store/writer/token."""

    assert tuple(signature(build_django_r8_monitoring_owner_runtime).parameters) == ("using",)
    runtime = build_django_r8_monitoring_owner_runtime()

    assert isinstance(runtime, DjangoR8MonitoringOwnerRuntime)
    assert type(runtime.register_calendar).__slots__ == ()
    graph = _walk_graph(runtime)
    assert not any(
        any(name in type(item).__name__ for name in ("Store", "Writer", "RegistrationRuntime"))
        for item in graph
    )
    assert not any(
        any(hasattr(item, attribute) for attribute in ("_store", "_writer", "_token"))
        for item in graph
    )


def test_public_calendar_registration_is_inert_for_valid_and_mutated_commands() -> None:
    """Production calendar mutation always stops before registry access."""

    runtime = build_django_r8_monitoring_owner_runtime()
    command = RegisterR8MonitoringCalendarCommand(
        calendar_id="r8-monitoring-calendar:weekly:v1",
        calendar_version="r8-monitoring-calendar.v1",
        source_receipt_id="r8-monitoring-calendar-source:weekly:v1",
        source_receipt_version="r8-monitoring-calendar-source.v1",
        as_of=NOW,
    )
    with pytest.raises(R8MonitoringCalendarRegistryUnavailable, match="unavailable"):
        runtime.register_calendar.execute(command)

    object.__setattr__(command, "calendar_id", "")
    object.__setattr__(command, "__post_init__", lambda: None)
    with pytest.raises(R8MonitoringCalendarRegistryUnavailable, match="malformed"):
        runtime.register_calendar.execute(command)
