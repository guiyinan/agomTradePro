from datetime import date
from unittest.mock import patch

import pytest
from django.contrib.auth.models import User

from apps.policy.infrastructure.models import PolicyAuditQueue, PolicyLog
from apps.policy.infrastructure.workbench_repositories import WorkbenchRepository


def _pending_event(title: str) -> PolicyLog:
    return PolicyLog._default_manager.create(
        event_date=date(2026, 7, 25),
        level="P1",
        title=title,
        description=f"Detailed description for {title}.",
        evidence_url="https://example.com/policy/workbench",
        audit_status="pending_review",
    )


@pytest.mark.django_db
def test_audit_queue_applies_priority_before_limit() -> None:
    auditor = User._default_manager.create_user(
        username="policy_auditor",
        is_staff=True,
    )
    low = _pending_event("Low priority")
    urgent = _pending_event("Urgent priority")
    PolicyAuditQueue._default_manager.create(
        policy_log=low,
        priority="low",
        assigned_to=auditor,
    )
    PolicyAuditQueue._default_manager.create(
        policy_log=urgent,
        priority="urgent",
        assigned_to=auditor,
    )

    rows = WorkbenchRepository().list_audit_queue_items(
        assigned_user_id=auditor.id,
        limit=1,
    )

    assert [row["id"] for row in rows] == [urgent.id]


@pytest.mark.django_db
def test_event_state_rolls_back_when_audit_log_write_fails() -> None:
    reviewer = User._default_manager.create_user(
        username="policy_reviewer",
        is_staff=True,
    )
    event = _pending_event("Atomic approval")
    repository = WorkbenchRepository()

    with (
        patch.object(
            repository,
            "_create_audit_log",
            side_effect=RuntimeError("audit storage unavailable"),
        ),
        pytest.raises(RuntimeError, match="audit storage unavailable"),
    ):
        repository.approve_event(event.id, reviewer.id)

    event.refresh_from_db()
    assert event.audit_status == "pending_review"
    assert event.gate_effective is False


def test_ingestion_config_rejects_unknown_fields_before_database_access() -> None:
    repository = WorkbenchRepository()

    with pytest.raises(ValueError, match="unsupported ingestion config fields"):
        repository.update_ingestion_config(save="shadow method")
