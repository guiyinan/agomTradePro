"""Public isolation tests for Broker R8 monitoring owner composition."""

from datetime import UTC, datetime
from inspect import signature

import pytest

from apps.broker_execution.application.r8_monitoring_reconciliation_registry import (
    R8BrokerMonitoringRegistryUnavailable,
    RegisterR8BrokerMonitoringPeriodCommand,
)
from apps.broker_execution.infrastructure import (
    r8_monitoring_reconciliation_repository as r8_repository,
)
from apps.broker_execution.r8_monitoring_reconciliation_composition import (
    DjangoR8BrokerMonitoringOwnerRuntime,
    build_django_r8_broker_monitoring_owner_runtime,
    build_django_r8_broker_monitoring_receipt_provider,
)

NOW = datetime(2026, 1, 15, 8, tzinfo=UTC)


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


def _command() -> RegisterR8BrokerMonitoringPeriodCommand:
    return RegisterR8BrokerMonitoringPeriodCommand(
        definition_id="broker-r8-reconciliation-definition:0123456789abcdef01234567",
        definition_version="broker-r8-reconciliation-definition.v1",
        source_receipt_id="broker-r8-reconciliation-source:period-1",
        source_receipt_version="broker-r8-reconciliation-source.v1",
        as_of=NOW,
    )


def test_public_builders_are_using_only_and_retain_no_write_capability() -> None:
    """Production graphs expose exact reads but no provider injection/store/token."""

    assert tuple(signature(build_django_r8_broker_monitoring_owner_runtime).parameters) == (
        "using",
    )
    assert tuple(signature(build_django_r8_broker_monitoring_receipt_provider).parameters) == (
        "using",
    )
    assert "DjangoR8BrokerMonitoringUnitOfWork" not in r8_repository.__all__
    assert "DjangoR8BrokerMonitoringRegistryClock" not in r8_repository.__all__
    runtime = build_django_r8_broker_monitoring_owner_runtime()

    assert isinstance(runtime, DjangoR8BrokerMonitoringOwnerRuntime)
    assert type(runtime.register_period).__slots__ == ()
    graph = _walk_graph(runtime)
    assert not any(
        any(name in type(item).__name__ for name in ("Store", "Writer", "RegistrationRuntime"))
        for item in graph
    )
    assert not any(
        any(hasattr(item, attribute) for attribute in ("_store", "_writer", "_token"))
        for item in graph
    )


def test_public_registration_is_inert_for_valid_and_mutated_commands() -> None:
    """Production mutation stops before registry access for every command."""

    runtime = build_django_r8_broker_monitoring_owner_runtime()
    command = _command()
    with pytest.raises(R8BrokerMonitoringRegistryUnavailable, match="unavailable"):
        runtime.register_period.execute(command)

    object.__setattr__(command, "definition_id", "")
    object.__setattr__(command, "__post_init__", lambda: None)
    with pytest.raises(R8BrokerMonitoringRegistryUnavailable, match="malformed"):
        runtime.register_period.execute(command)
