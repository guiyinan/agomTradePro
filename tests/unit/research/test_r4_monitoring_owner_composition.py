"""Composition tests for Research-owned R4 monitoring policy/calendar ledgers."""

from __future__ import annotations

from datetime import datetime

import pytest

from apps.research.application.r4_promotion_monitoring_owner_registry import (
    R4MonitoringOwnerRegistryUnavailable,
    RegisterR4MonitoringCalendarCommand,
    RegisterR4MonitoringPolicyCommand,
)
from apps.research.domain.r4_promotion_monitoring_owner_registry import (
    R4MonitoringCalendarDefinition,
    R4MonitoringOwnerRecordKind,
    R4MonitoringOwnerSourceReceipt,
    R4MonitoringPolicyDefinition,
)
from apps.research.infrastructure.r4_promotion_monitoring_owner_models import (
    R4MonitoringCalendarLedgerModel,
    R4MonitoringPolicyLedgerModel,
)
from apps.research.r4_promotion_monitoring_owner_composition import (
    _build_django_r4_monitoring_owner_registration_runtime,
    build_django_r4_monitoring_owner_registry_runtime,
)
from tests.unit.research.r4_promotion_monitoring_factories import (
    monitoring_calendar,
    monitoring_policy,
)


class _ExactProvider:
    unit_of_work_key = "django:default"

    def __init__(self, value: object) -> None:
        self.value = value

    def get_exact(self, **kwargs: object) -> object:
        return self.value


class _Clock:
    unit_of_work_key = "django:default"

    def __init__(self, value: datetime) -> None:
        self.value = value

    def now(self) -> datetime:
        return self.value


def _source(
    *,
    kind: R4MonitoringOwnerRecordKind,
    definition_hash: str,
    now: datetime,
) -> R4MonitoringOwnerSourceReceipt:
    return R4MonitoringOwnerSourceReceipt.create(
        record_kind=kind,
        source_owner="research",
        source_receipt_id=f"source-{kind.value}",
        source_receipt_version="source.v1",
        definition_hash=definition_hash,
        available_at=now,
        valid_until=monitoring_policy().active_until,
    )


@pytest.mark.django_db
def test_public_registry_mutations_are_inert_and_have_no_store_capability() -> None:
    runtime = build_django_r4_monitoring_owner_registry_runtime()
    policy = monitoring_policy()
    calendar = monitoring_calendar()

    with pytest.raises(R4MonitoringOwnerRegistryUnavailable, match="source provider"):
        runtime.register_policy.execute(
            RegisterR4MonitoringPolicyCommand(
                policy.policy_id,
                policy.policy_version,
                "source-policy",
                "source.v1",
                policy.recorded_at,
            )
        )
    with pytest.raises(R4MonitoringOwnerRegistryUnavailable, match="source provider"):
        runtime.register_calendar.execute(
            RegisterR4MonitoringCalendarCommand(
                calendar.calendar_id,
                calendar.calendar_version,
                "source-calendar",
                "source.v1",
                calendar.recorded_at,
            )
        )

    assert R4MonitoringPolicyLedgerModel._default_manager.count() == 0
    assert R4MonitoringCalendarLedgerModel._default_manager.count() == 0
    graph = vars(runtime)
    assert all(not hasattr(value, "append_policy") for value in graph.values())
    assert all(not hasattr(value, "append_calendar") for value in graph.values())
    assert all(not hasattr(value, "_token") for value in graph.values())


@pytest.mark.django_db
def test_private_test_composition_builds_and_restores_owner_records() -> None:
    policy = monitoring_policy()
    calendar = monitoring_calendar()
    policy_definition = R4MonitoringPolicyDefinition.from_policy(policy)
    calendar_definition = R4MonitoringCalendarDefinition.from_calendar(calendar)
    runtime = _build_django_r4_monitoring_owner_registration_runtime(
        policy_definition_provider=_ExactProvider(policy_definition),
        calendar_definition_provider=_ExactProvider(calendar_definition),
        policy_source_provider=_ExactProvider(
            _source(
                kind=R4MonitoringOwnerRecordKind.POLICY,
                definition_hash=policy_definition.content_hash,
                now=policy.recorded_at,
            )
        ),
        calendar_source_provider=_ExactProvider(
            _source(
                kind=R4MonitoringOwnerRecordKind.CALENDAR,
                definition_hash=calendar_definition.content_hash,
                now=calendar.recorded_at,
            )
        ),
        clock=_Clock(policy.recorded_at),
    )

    stored_policy = runtime.register_policy.execute(
        RegisterR4MonitoringPolicyCommand(
            policy.policy_id,
            policy.policy_version,
            "source-policy",
            "source.v1",
            policy.recorded_at,
        )
    )
    stored_calendar = runtime.register_calendar.execute(
        RegisterR4MonitoringCalendarCommand(
            calendar.calendar_id,
            calendar.calendar_version,
            "source-calendar",
            "source.v1",
            calendar.recorded_at,
        )
    )

    assert (
        runtime.policy_provider.get_exact(
            policy_id=policy.policy_id,
            policy_version=policy.policy_version,
            expected_policy_hash=policy.content_hash,
            active_decision=policy.active_decision,
            as_of=policy.recorded_at,
        )
        == stored_policy
    )
    assert (
        runtime.calendar_provider.get_exact(
            source_owner=calendar.source_owner,
            calendar_id=calendar.calendar_id,
            calendar_version=calendar.calendar_version,
            expected_calendar_hash=calendar.content_hash,
            as_of=calendar.recorded_at,
        )
        == stored_calendar
    )
