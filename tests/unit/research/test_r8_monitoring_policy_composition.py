"""Public isolation for the Research-owned R8 monitoring policy registry."""

from inspect import signature

import pytest

from apps.research.application.r8_monitoring_policy_registry import (
    R8MonitoringPolicyRegistryUnavailable,
    RegisterR8MonitoringPolicyCommand,
)
from apps.research.r8_governed_optimization_monitoring_composition import (
    _build_django_r8_phase_a_b_runtime,
)
from apps.research.r8_monitoring_policy_composition import (
    DjangoR8MonitoringPolicyRegistryRuntime,
    build_django_r8_monitoring_policy_registry_runtime,
)
from tests.unit.research.test_r8_monitoring_policy_registry import _command


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


def test_public_policy_registry_is_using_only_readable_and_mutation_inert() -> None:
    """Production composition retains an exact reader but no append authority."""

    assert tuple(signature(build_django_r8_monitoring_policy_registry_runtime).parameters) == (
        "using",
    )
    runtime = build_django_r8_monitoring_policy_registry_runtime()
    assert isinstance(runtime, DjangoR8MonitoringPolicyRegistryRuntime)
    assert type(runtime.register).__slots__ == ()
    graph = _walk_graph(runtime)
    assert not any(
        any(hasattr(item, name) for name in ("_store", "_clock", "_token")) for item in graph
    )

    with pytest.raises(R8MonitoringPolicyRegistryUnavailable, match="unavailable"):
        runtime.register.execute(_command())

    command = _command()
    object.__setattr__(command, "policy_id", "")
    object.__setattr__(command, "__post_init__", lambda: None)
    with pytest.raises(R8MonitoringPolicyRegistryUnavailable, match="malformed"):
        runtime.register.execute(command)


def test_public_policy_registry_rejects_command_subclasses() -> None:
    """Subclass validators cannot cross the public registration boundary."""

    class _CommandSubclass(RegisterR8MonitoringPolicyCommand):
        pass

    value = _command()
    command = _CommandSubclass(value.policy_id, value.policy_version)
    runtime = build_django_r8_monitoring_policy_registry_runtime()
    with pytest.raises(R8MonitoringPolicyRegistryUnavailable, match="malformed"):
        runtime.register.execute(command)


def test_private_phase_a_b_composition_has_exact_reads_but_no_writer() -> None:
    """The private complete read graph blocks on Promotions and cannot persist Phase B."""

    runtime = _build_django_r8_phase_a_b_runtime()
    graph = _walk_graph(runtime)
    assert type(runtime.register).__slots__ == ()
    assert not any(
        any(hasattr(item, name) for name in ("_writer", "_store", "_token")) for item in graph
    )
