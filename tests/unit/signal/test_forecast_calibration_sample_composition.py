"""Capability-isolation tests for the public calibration owner runtime."""

from __future__ import annotations

from inspect import signature

import pytest

from apps.signal.application.forecast_calibration_sample import (
    ForecastCalibrationSampleUnavailable,
    RegisterForecastCalibrationSampleDefinitionCommand,
    RegisterForecastCalibrationSampleReceiptCommand,
)
from apps.signal.forecast_calibration_sample_composition import (
    DjangoForecastCalibrationSampleRuntime,
    build_django_forecast_calibration_sample_runtime,
)
from tests.unit.signal.test_forecast_calibration_sample import NOW


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


def test_public_builder_is_using_only_and_carries_no_mutation_capability() -> None:
    """Production exposes inert registration facades and one read-only query."""

    assert tuple(signature(build_django_forecast_calibration_sample_runtime).parameters) == (
        "using",
    )
    runtime = build_django_forecast_calibration_sample_runtime()

    assert isinstance(runtime, DjangoForecastCalibrationSampleRuntime)
    assert type(runtime.register_definition).__slots__ == ()
    assert type(runtime.register_receipt).__slots__ == ()
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
    assert not any(
        hasattr(item, "append_definition") or hasattr(item, "append_receipt") for item in graph
    )


def test_public_registration_is_inert_for_valid_and_malformed_commands() -> None:
    """No production caller can obtain the private append capability."""

    runtime = build_django_forecast_calibration_sample_runtime()
    definition = RegisterForecastCalibrationSampleDefinitionCommand(
        sample_id="calibration-sample-1",
        sample_version="sample.v1",
        as_of=NOW,
    )
    receipt = RegisterForecastCalibrationSampleReceiptCommand(
        sample_id="calibration-sample-1",
        sample_version="sample.v1",
        as_of=NOW,
    )
    with pytest.raises(ForecastCalibrationSampleUnavailable, match="unavailable"):
        runtime.register_definition.execute(definition)
    with pytest.raises(ForecastCalibrationSampleUnavailable, match="unavailable"):
        runtime.register_receipt.execute(receipt)

    object.__setattr__(definition, "sample_id", "")
    object.__setattr__(definition, "__post_init__", lambda: None)
    object.__setattr__(receipt, "as_of", NOW.replace(tzinfo=None))
    object.__setattr__(receipt, "__post_init__", lambda: None)
    with pytest.raises(ForecastCalibrationSampleUnavailable, match="malformed"):
        runtime.register_definition.execute(definition)
    with pytest.raises(ForecastCalibrationSampleUnavailable, match="malformed"):
        runtime.register_receipt.execute(receipt)
    with pytest.raises(ForecastCalibrationSampleUnavailable, match="malformed"):
        runtime.register_definition.execute(object())  # type: ignore[arg-type]
