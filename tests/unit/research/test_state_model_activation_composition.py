"""Composition boundary tests for research-only R6 activation Phase B."""

from __future__ import annotations

from dataclasses import fields
from datetime import UTC, datetime

import pytest

from apps.research.application.state_model_activation import (
    ApplyR6Activation,
    ApplyR6ActivationCommand,
    R6ActivationUnavailable,
)
from apps.research.application.state_model_activation_persistence import (
    AuditR6ActivationEventsCommand,
)
from apps.research.domain.state_model_activation import (
    R6ActivationAction,
    R6ActivationApprovalRef,
    R6ActivationAuthorizationRef,
    R6ActivationScopeRef,
)
from apps.research.infrastructure.state_model_activation_repository import (
    _DjangoR6ActivationStore,
)
from apps.research.state_model_activation_composition import (
    DjangoR6ActivationRuntime,
    build_django_r6_activation_runtime,
)

NOW = datetime(2026, 8, 9, tzinfo=UTC)


def _scope() -> R6ActivationScopeRef:
    return R6ActivationScopeRef("scope:r6", "r6-activation-scope.v1", "a" * 64)


def _command() -> ApplyR6ActivationCommand:
    return ApplyR6ActivationCommand(
        scope_ref=_scope(),
        action=R6ActivationAction.ACTIVATE,
        subject=R6ActivationApprovalRef(
            "approval:r6",
            "r6-activation-approval.v1",
            "b" * 64,
        ),
        rollback_target=None,
        authorization_ref=R6ActivationAuthorizationRef(
            "authorization:r6",
            "r6-activation-authorization.v1",
        ),
    )


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


def test_activation_runtime_exposes_only_inert_write_facades_and_safe_reads() -> None:
    runtime = build_django_r6_activation_runtime()

    assert isinstance(runtime, DjangoR6ActivationRuntime)
    assert {item.name for item in fields(runtime)} == {
        "apply",
        "get_active",
        "get_exact_authorization",
        "get_exact_event",
        "audit",
    }
    graph = _walk_runtime_graph(runtime)
    assert not any(isinstance(item, ApplyR6Activation) for item in graph)
    assert not any(isinstance(item, _DjangoR6ActivationStore) for item in graph)
    assert not any(hasattr(item, "append_event") for item in graph)
    assert not any(hasattr(item, "_token") for item in graph)
    assert type(runtime.apply).__slots__ == ()
    assert type(runtime.get_active).__slots__ == ()
    assert type(runtime.audit).__slots__ == ()


def test_activation_production_mutation_surfaces_fail_closed_without_state() -> None:
    runtime = build_django_r6_activation_runtime()

    with pytest.raises(R6ActivationUnavailable, match="owner providers are unavailable"):
        runtime.apply.execute(_command())
    assert runtime.get_active.get_active(scope_ref=_scope(), as_of=NOW) is None
    with pytest.raises(R6ActivationUnavailable, match="snapshot writer is unavailable"):
        runtime.audit.execute(AuditR6ActivationEventsCommand(as_of=NOW, limit=1))


def test_activation_production_facades_revalidate_mutated_commands() -> None:
    runtime = build_django_r6_activation_runtime()
    command = _command()
    object.__setattr__(command, "action", object())

    with pytest.raises(R6ActivationUnavailable, match="command is malformed"):
        runtime.apply.execute(command)

    audit = AuditR6ActivationEventsCommand(as_of=NOW, limit=1)
    object.__setattr__(audit, "limit", 1.5)
    with pytest.raises(R6ActivationUnavailable, match="audit query is malformed"):
        runtime.audit.execute(audit)
