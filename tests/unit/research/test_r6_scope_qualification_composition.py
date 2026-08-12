"""Public capability isolation for the R6 scope-qualification registry."""

from inspect import signature

import pytest

from apps.research.application.r6_scope_qualification_registry import (
    R6ScopeQualificationRegistryUnavailable,
    RegisterR6ScopeQualificationBindingCommand,
)
from apps.research.r6_scope_qualification_composition import (
    DjangoR6ScopeQualificationRegistryRuntime,
    build_django_r6_scope_qualification_registry_runtime,
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


def test_public_registry_is_using_only_readable_and_registration_inert() -> None:
    assert tuple(signature(build_django_r6_scope_qualification_registry_runtime).parameters) == (
        "using",
    )
    runtime = build_django_r6_scope_qualification_registry_runtime()
    assert type(runtime) is DjangoR6ScopeQualificationRegistryRuntime
    assert type(runtime.register).__slots__ == ()
    graph = _walk_graph(runtime)
    assert not any(
        any(hasattr(item, name) for name in ("append", "_store", "_clock", "_token"))
        for item in graph
    )
    with pytest.raises(R6ScopeQualificationRegistryUnavailable, match="unavailable"):
        runtime.register.execute(RegisterR6ScopeQualificationBindingCommand("binding-1", "v1"))


def test_public_registry_live_validates_exact_command_class() -> None:
    command = RegisterR6ScopeQualificationBindingCommand("binding-1", "v1")
    object.__setattr__(command, "binding_id", "")
    object.__setattr__(command, "__post_init__", lambda: None)
    runtime = build_django_r6_scope_qualification_registry_runtime()
    with pytest.raises(R6ScopeQualificationRegistryUnavailable, match="malformed"):
        runtime.register.execute(command)

    class _Subclass(RegisterR6ScopeQualificationBindingCommand):
        pass

    with pytest.raises(R6ScopeQualificationRegistryUnavailable, match="malformed"):
        runtime.register.execute(_Subclass("binding-1", "v1"))
