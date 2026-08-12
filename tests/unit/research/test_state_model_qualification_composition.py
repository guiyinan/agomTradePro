"""Production capability tests for persisted R6 qualification research."""

from __future__ import annotations

from dataclasses import fields
from datetime import UTC, datetime
from inspect import Parameter, signature

import pytest

from apps.research.application.state_model_qualification_lifecycle import (
    ApplyR6QualificationLifecycleCommand,
    R6QualificationAuthorizationRef,
)
from apps.research.application.state_model_qualification_persistence import (
    R6QualificationUnavailable,
    RegisterR6QualificationAssessmentCommand,
)
from apps.research.domain.state_model_qualification_lifecycle import (
    R6QualificationLifecycleAction,
    R6QualificationRef,
)
from apps.research.infrastructure.state_model_qualification_repository import (
    DjangoR6QualificationReadRepository,
    _DjangoR6QualificationStore,
)
from apps.research.state_model_qualification_composition import (
    DjangoR6QualificationRuntime,
    UnavailableR6QualificationLifecycleFacade,
    UnavailableR6QualificationMonitorFacade,
    UnavailableR6QualificationRegisterFacade,
    build_django_r6_qualification_runtime,
)

NOW = datetime(2026, 8, 12, tzinfo=UTC)


def _walk_runtime_graph(runtime: object) -> tuple[object, ...]:
    pending = [runtime]
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


def _lifecycle_command() -> ApplyR6QualificationLifecycleCommand:
    return ApplyR6QualificationLifecycleCommand(
        qualification_ref=R6QualificationRef("qualification:r6", "a" * 64),
        action=R6QualificationLifecycleAction.PROMOTE,
        authorization_ref=R6QualificationAuthorizationRef("authorization:r6", "v1"),
    )


def test_public_builder_is_using_only_and_runtime_retains_exact_reads_only() -> None:
    runtime = build_django_r6_qualification_runtime()

    parameters = signature(build_django_r6_qualification_runtime).parameters
    assert tuple(parameters) == ("using",)
    assert parameters["using"].kind is Parameter.KEYWORD_ONLY
    assert isinstance(runtime, DjangoR6QualificationRuntime)
    assert not hasattr(runtime, "__dict__")
    assert {item.name for item in fields(runtime)} == {
        "register",
        "get_exact",
        "monitor",
        "apply_lifecycle",
        "get_active",
    }
    assert isinstance(runtime.register, UnavailableR6QualificationRegisterFacade)
    assert isinstance(runtime.monitor, UnavailableR6QualificationMonitorFacade)
    assert isinstance(runtime.apply_lifecycle, UnavailableR6QualificationLifecycleFacade)
    assert type(runtime.register).__slots__ == ()
    assert type(runtime.monitor).__slots__ == ()
    assert type(runtime.apply_lifecycle).__slots__ == ()
    assert runtime.register.execute.__func__.__closure__ is None
    assert runtime.monitor.execute.__func__.__closure__ is None
    assert runtime.apply_lifecycle.execute.__func__.__closure__ is None

    graph = _walk_runtime_graph(runtime)
    assert any(isinstance(item, DjangoR6QualificationReadRepository) for item in graph)
    assert not any(isinstance(item, _DjangoR6QualificationStore) for item in graph)
    for item in graph:
        for attribute in (
            "_token",
            "_clock",
            "_writer",
            "append_assessment",
            "append_lifecycle_event",
            "atomic",
            "server_now",
        ):
            assert not hasattr(item, attribute)


def test_public_mutation_monitor_and_lifecycle_facades_revalidate_and_fail_closed() -> None:
    runtime = build_django_r6_qualification_runtime()
    registration = RegisterR6QualificationAssessmentCommand(
        study_id="study:r6",
        assessed_at=NOW,
    )

    with pytest.raises(R6QualificationUnavailable, match="owner providers are unavailable"):
        runtime.register.execute(registration)
    object.__setattr__(registration, "assessed_at", object())
    with pytest.raises(R6QualificationUnavailable, match="command is malformed"):
        runtime.register.execute(registration)

    with pytest.raises(R6QualificationUnavailable, match="monitor is unavailable"):
        runtime.monitor.execute(as_of=NOW, cursor=None, limit=1)
    with pytest.raises(R6QualificationUnavailable, match="request is malformed"):
        runtime.monitor.execute(as_of=NOW, cursor=None, limit=True)

    lifecycle = _lifecycle_command()
    with pytest.raises(R6QualificationUnavailable, match="owner providers are unavailable"):
        runtime.apply_lifecycle.execute(lifecycle)
    object.__setattr__(lifecycle, "action", object())
    with pytest.raises(R6QualificationUnavailable, match="command is malformed"):
        runtime.apply_lifecycle.execute(lifecycle)
