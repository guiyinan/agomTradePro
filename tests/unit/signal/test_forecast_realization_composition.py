"""Capability-isolation tests for the public Signal realization runtime."""

from __future__ import annotations

from inspect import signature

import pytest

from apps.signal.application.forecast_realization_owner import (
    AppendForecastRealizationManifestCommand,
    ForecastRealizationOwnerUnavailable,
)
from apps.signal.forecast_realization_composition import (
    DjangoForecastRealizationOwnerRuntime,
    build_django_forecast_realization_owner_runtime,
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


def test_public_builder_is_using_only_and_object_graph_has_no_write_owner() -> None:
    """Production cannot retain an injected provider, clock, store, writer, or token."""

    assert tuple(signature(build_django_forecast_realization_owner_runtime).parameters) == (
        "using",
    )
    runtime = build_django_forecast_realization_owner_runtime()

    assert isinstance(runtime, DjangoForecastRealizationOwnerRuntime)
    assert type(runtime.append).__slots__ == ()
    graph = _walk_graph(runtime)
    forbidden_names = ("Provider", "Clock", "Store", "Writer", "Token")
    assert not any(any(name in type(item).__name__ for name in forbidden_names) for item in graph)
    assert not any(
        any(
            hasattr(item, attribute)
            for attribute in ("_provider", "_clock", "_store", "_writer", "_token")
        )
        for item in graph
    )


def test_public_append_is_inert_and_class_bound_revalidates_commands() -> None:
    """Both valid and mutated commands stop before any append capability exists."""

    runtime = build_django_forecast_realization_owner_runtime()
    command = AppendForecastRealizationManifestCommand(
        owner_record_id="manifest-1",
        owner_record_version="manifest.v1",
    )
    with pytest.raises(ForecastRealizationOwnerUnavailable, match="provider.*unavailable"):
        runtime.append.execute(command)

    object.__setattr__(command, "owner_record_id", "")
    object.__setattr__(command, "__post_init__", lambda: None)
    with pytest.raises(ForecastRealizationOwnerUnavailable, match="malformed"):
        runtime.append.execute(command)

    with pytest.raises(ForecastRealizationOwnerUnavailable, match="malformed"):
        runtime.append.execute(object())  # type: ignore[arg-type]
