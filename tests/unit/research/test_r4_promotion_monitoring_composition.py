"""Capability isolation tests for production R4 monitoring composition."""

from __future__ import annotations

from dataclasses import fields
from datetime import timedelta

import pytest

from apps.research.application.r4_promotion_monitoring import (
    EvaluateR4PromotionMonitoringCommand,
)
from apps.research.application.r4_promotion_monitoring_persistence import (
    AuditR4MonitoringAssessmentsCommand,
    R4MonitoringPersistenceUnavailable,
)
from apps.research.domain.r4_promotion_lifecycle import R4PromotionDecisionIdentity
from apps.research.infrastructure.r4_promotion_monitoring_repository import (
    _DjangoR4MonitoringStore,
)
from apps.research.r4_promotion_monitoring_composition import (
    DjangoR4MonitoringRuntime,
    build_django_r4_monitoring_runtime,
)
from tests.unit.research.r4_promotion_monitoring_factories import (
    monitoring_calendar,
    monitoring_decision,
    monitoring_policy,
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


def _command() -> EvaluateR4PromotionMonitoringCommand:
    decision = monitoring_decision()
    calendar = monitoring_calendar(decision)
    policy = monitoring_policy(decision, calendar)
    return EvaluateR4PromotionMonitoringCommand(
        active_decision=R4PromotionDecisionIdentity.from_decision(decision),
        policy_id=policy.policy_id,
        policy_version=policy.policy_version,
        expected_policy_hash=policy.content_hash,
        as_of=calendar.valid_from + timedelta(hours=2, minutes=30),
    )


def test_public_runtime_has_no_store_token_or_append_capability() -> None:
    runtime = build_django_r4_monitoring_runtime()

    assert isinstance(runtime, DjangoR4MonitoringRuntime)
    assert {item.name for item in fields(runtime)} == {"register", "get_exact", "audit"}
    graph = _walk_graph(runtime)
    assert not any(isinstance(item, _DjangoR4MonitoringStore) for item in graph)
    assert not any(hasattr(item, "append_evidence") for item in graph)
    assert not any(hasattr(item, "_token") for item in graph)
    assert type(runtime.register).__slots__ == ()
    assert type(runtime.audit).__slots__ == ()


def test_production_write_surfaces_are_inert_and_revalidate_commands() -> None:
    runtime = build_django_r4_monitoring_runtime()
    command = _command()
    with pytest.raises(R4MonitoringPersistenceUnavailable, match="providers are unavailable"):
        runtime.register.execute(command)

    object.__setattr__(command, "as_of", object())
    with pytest.raises(R4MonitoringPersistenceUnavailable, match="malformed"):
        runtime.register.execute(command)

    audit = AuditR4MonitoringAssessmentsCommand(
        as_of=monitoring_calendar().valid_from,
        limit=1,
    )
    with pytest.raises(R4MonitoringPersistenceUnavailable, match="snapshot writer"):
        runtime.audit.execute(audit)
