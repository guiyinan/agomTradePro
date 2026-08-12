"""Capability isolation tests for production R4 monitoring composition."""

from __future__ import annotations

from dataclasses import fields
from datetime import timedelta
from inspect import signature

import pytest

from apps.research.application.r4_promotion_monitoring import (
    EvaluateR4PromotionMonitoringCommand,
)
from apps.research.application.r4_promotion_monitoring_persistence import (
    AuditR4MonitoringAssessmentsCommand,
    R4MonitoringPersistenceUnavailable,
)
from apps.research.domain.r4_promotion_lifecycle import R4PromotionDecisionIdentity
from apps.research.infrastructure.r4_promotion_monitoring_models import (
    R4MonitoringAssessmentLedgerModel,
    R4MonitoringObservationLedgerModel,
)
from apps.research.infrastructure.r4_promotion_monitoring_repository import (
    _DjangoR4MonitoringStore,
)
from apps.research.r4_promotion_monitoring_composition import (
    DjangoCanonicalR4MonitoringRuntime,
    DjangoR4MonitoringRuntime,
    _build_django_canonical_r4_monitoring_test_runtime,
    build_django_canonical_r4_monitoring_runtime,
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


class _EmptyActivePromotionProvider:
    def get_active(self, scope_ref: object, *, as_of: object) -> None:
        return None


class _UnusedPortfolioQuery:
    unit_of_work_key = "django:default"

    def get_exact(self, **kwargs: object) -> None:
        raise AssertionError("Portfolio must not be read after active-owner absence")


class _UnusedR3Provider:
    def get_exact(self, **kwargs: object) -> None:
        raise AssertionError("R3 must not be read after active-owner absence")


@pytest.mark.django_db
def test_public_canonical_composition_is_inert_and_accepts_only_database_alias() -> None:
    assert tuple(signature(build_django_canonical_r4_monitoring_runtime).parameters) == ("using",)
    runtime = build_django_canonical_r4_monitoring_runtime()

    assert isinstance(runtime, DjangoCanonicalR4MonitoringRuntime)
    graph = _walk_graph(runtime)
    assert not any(isinstance(item, _DjangoR4MonitoringStore) for item in graph)
    assert not any(hasattr(item, "append_evidence") for item in graph)
    assert not any(hasattr(item, "_token") for item in graph)
    with pytest.raises(R4MonitoringPersistenceUnavailable, match="providers are unavailable"):
        runtime.register.execute(_command())
    assert R4MonitoringObservationLedgerModel._default_manager.count() == 0
    assert R4MonitoringAssessmentLedgerModel._default_manager.count() == 0


@pytest.mark.django_db
def test_private_canonical_test_runtime_empty_owner_graph_is_zero_write() -> None:
    runtime = _build_django_canonical_r4_monitoring_test_runtime(
        active_promotion_provider=_EmptyActivePromotionProvider(),
        portfolio_query=_UnusedPortfolioQuery(),
        current_r3_provider=_UnusedR3Provider(),
    )

    with pytest.raises(R4MonitoringPersistenceUnavailable, match="owner graph"):
        runtime.register.execute(_command())
    assert R4MonitoringObservationLedgerModel._default_manager.count() == 0
    assert R4MonitoringAssessmentLedgerModel._default_manager.count() == 0
