"""Capability-isolation tests for the public source-definition runtime."""

from __future__ import annotations

from inspect import signature

import pytest

from apps.signal.application.forecast_realization_source_definition import (
    ForecastRealizationSourceDefinitionUnavailable,
    RegisterForecastRealizationSourceDefinitionCommand,
)
from apps.signal.forecast_realization_source_definition_composition import (
    DjangoForecastRealizationSourceDefinitionRuntime,
    build_django_forecast_realization_source_definition_runtime,
)


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


def test_public_definition_builder_is_using_only_and_has_no_write_capability() -> None:
    """Production exposes an inert facade and a read-only exact query only."""

    assert tuple(
        signature(build_django_forecast_realization_source_definition_runtime).parameters
    ) == ("using",)
    runtime = build_django_forecast_realization_source_definition_runtime()

    assert isinstance(runtime, DjangoForecastRealizationSourceDefinitionRuntime)
    assert type(runtime.register).__slots__ == ()
    graph = _walk_graph(runtime)
    forbidden_names = ("Provider", "Clock", "Writer", "Token", "Store")
    assert not any(any(name in type(item).__name__ for name in forbidden_names) for item in graph)
    assert not any(
        any(
            hasattr(item, attribute)
            for attribute in ("_provider", "_clock", "_writer", "_token", "_store")
        )
        for item in graph
    )


def test_public_definition_registration_is_inert_and_class_bound() -> None:
    """Valid and validator-bypassed commands both stop at the public facade."""

    runtime = build_django_forecast_realization_source_definition_runtime()
    command = RegisterForecastRealizationSourceDefinitionCommand(
        owner_record_id="realization-manifest-1",
        owner_record_version="manifest.v1",
    )
    with pytest.raises(ForecastRealizationSourceDefinitionUnavailable, match="unavailable"):
        runtime.register.execute(command)

    object.__setattr__(command, "owner_record_id", "")
    object.__setattr__(command, "__post_init__", lambda: None)
    with pytest.raises(ForecastRealizationSourceDefinitionUnavailable, match="malformed"):
        runtime.register.execute(command)
    with pytest.raises(ForecastRealizationSourceDefinitionUnavailable, match="malformed"):
        runtime.register.execute(object())  # type: ignore[arg-type]
