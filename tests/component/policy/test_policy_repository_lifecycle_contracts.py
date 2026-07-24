"""Persistence round-trip contracts for policy events."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from apps.policy.application.event_use_cases import (
    DeletePolicyEventUseCase,
    GetPolicyHistoryUseCase,
    GetPolicyStatusUseCase,
    UpdatePolicyEventUseCase,
)
from apps.policy.domain.entities import PolicyEvent, PolicyLevel
from apps.policy.infrastructure.models import PolicyLog
from apps.policy.infrastructure.repositories import DjangoPolicyRepository


def _event(day: int, level: PolicyLevel, title: str) -> PolicyEvent:
    return PolicyEvent(
        event_date=date(2026, 7, day),
        level=level,
        title=title,
        description=f"Evidence-backed description for {title}",
        evidence_url=f"https://evidence.test/{title}",
    )


@pytest.mark.django_db
def test_policy_repository_crud_range_level_stats_and_safe_updates() -> None:
    """Repository preserves same-day events and supports every lifecycle query."""
    repo = DjangoPolicyRepository()
    repo.save_event(
        _event(22, PolicyLevel.P1, "guidance"),
        return_orm=True,
        gate_effective=True,
        event_type="policy",
        effective_at=datetime(2026, 7, 22, tzinfo=UTC),
    )
    second = repo.save_event(
        _event(23, PolicyLevel.P2, "intervention"),
        return_orm=True,
        gate_effective=True,
        event_type="policy",
        effective_at=datetime(2026, 7, 23, tzinfo=UTC),
    )
    same_day = repo.save_event(
        _event(23, PolicyLevel.P3, "emergency"),
        return_orm=True,
        gate_effective=False,
        event_type="hotspot",
    )
    assert repo.get_event_count() == 3
    assert repo.get_event_by_id(second.id).level == PolicyLevel.P2
    assert len(repo.get_events_by_date(date(2026, 7, 23))) == 2
    assert repo.get_event_by_date(date(2026, 7, 22)).title == "guidance"
    assert repo.get_latest_event(date(2026, 7, 23)) is not None
    assert len(repo.get_events_in_range(date(2026, 7, 22), date(2026, 7, 23))) == 3
    assert (
        len(
            repo.get_events_by_level(
                PolicyLevel.P2,
                date(2026, 7, 22),
                date(2026, 7, 24),
            )
        )
        == 1
    )
    assert repo.get_current_policy_level(date(2026, 7, 24)) == PolicyLevel.P2
    assert repo.is_intervention_active(date(2026, 7, 24)) is True
    assert repo.is_crisis_mode(date(2026, 7, 24)) is False

    stats = repo.get_policy_level_stats(date(2026, 7, 22), date(2026, 7, 24))
    assert stats["total"] == 3
    existing = repo.get_existing_for_update(
        event_id=second.id,
        event_date=date(2026, 7, 23),
    )
    assert existing == {"id": second.id, "event_date": date(2026, 7, 23)}
    updated = repo.save_event(
        _event(23, PolicyLevel.P3, "intervention-updated"),
        return_orm=True,
        _update_id=second.id,
        audit_status="approved",
    )
    assert updated.id == second.id
    assert updated.level == "P3"
    assert updated.audit_status == "approved"

    assert repo.delete_event_by_id(same_day.id) is True
    assert repo.delete_event_by_id(same_day.id) is False
    assert repo.delete_event(date(2026, 7, 22)) is True
    assert repo.delete_events_before(date(2026, 7, 24)) == 1
    assert PolicyLog.objects.count() == 0


@pytest.mark.django_db
def test_policy_event_use_cases_update_history_status_and_precise_delete() -> None:
    """Application use cases preserve precise IDs across update and delete operations."""
    repo = DjangoPolicyRepository()
    created = repo.save_event(
        _event(24, PolicyLevel.P1, "original"),
        return_orm=True,
        gate_effective=True,
        event_type="policy",
        effective_at=datetime(2026, 7, 24, tzinfo=UTC),
    )
    status = GetPolicyStatusUseCase(repo).execute(date(2026, 7, 24))
    assert status.current_level == PolicyLevel.P1
    assert status.is_intervention_active is False

    history = GetPolicyHistoryUseCase(repo).execute(
        date(2026, 7, 1),
        date(2026, 7, 31),
        PolicyLevel.P1,
    )
    assert history.total_count == 1
    assert history.level_stats["total"] == 1

    updated = UpdatePolicyEventUseCase(repo).execute(
        event_id=created.id,
        event_date=date(2026, 7, 24),
        level=PolicyLevel.P2,
        title="updated",
        description="Updated evidence-backed intervention description",
        evidence_url="https://evidence.test/updated",
    )
    assert updated.success is True
    assert updated.event.level == PolicyLevel.P2
    missing = UpdatePolicyEventUseCase(repo).execute(
        event_id=999999,
        event_date=date(2026, 7, 24),
        level=PolicyLevel.P2,
        title="missing",
        description="Missing event should not be recreated",
        evidence_url="https://evidence.test/missing",
    )
    assert missing.success is False
    assert "未找到" in missing.errors[0]

    deleted, message = DeletePolicyEventUseCase(repo).execute(event_id=created.id)
    assert deleted is True
    assert str(created.id) in message
    deleted_again, _ = DeletePolicyEventUseCase(repo).execute(event_id=created.id)
    assert deleted_again is False
    assert DeletePolicyEventUseCase(repo).execute() == (
        False,
        "必须提供 event_date 或 event_id",
    )
