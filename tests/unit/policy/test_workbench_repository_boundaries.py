from datetime import date
from unittest.mock import patch

import pytest
from django.contrib.auth.models import User

from apps.policy.infrastructure.models import GateActionAuditLog, PolicyAuditQueue, PolicyLog
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


@pytest.mark.django_db
def test_review_policy_item_requires_assignment_and_writes_audit_log() -> None:
    assigned_reviewer = User._default_manager.create_user(
        username="assigned_policy_reviewer",
        is_staff=True,
    )
    other_reviewer = User._default_manager.create_user(
        username="other_policy_reviewer",
        is_staff=True,
    )
    event = _pending_event("Assigned review")
    PolicyAuditQueue._default_manager.create(
        policy_log=event,
        priority="high",
        assigned_to=assigned_reviewer,
    )
    repository = WorkbenchRepository()

    denied = repository.review_policy_item(
        policy_log_id=event.id,
        approved=True,
        reviewer_id=other_reviewer.id,
    )
    event.refresh_from_db()
    assert denied is None
    assert event.audit_status == "pending_review"

    reviewed = repository.review_policy_item(
        policy_log_id=event.id,
        approved=False,
        reviewer_id=assigned_reviewer.id,
        notes="Evidence is insufficient",
    )
    event.refresh_from_db()

    assert reviewed == {"id": event.id, "audit_status": "rejected"}
    assert event.audit_status == "rejected"
    assert not PolicyAuditQueue._default_manager.filter(policy_log=event).exists()
    audit_log = GateActionAuditLog._default_manager.get(event=event)
    assert audit_log.action == "reject"
    assert audit_log.operator_id == assigned_reviewer.id
    assert audit_log.before_state["audit_status"] == "pending_review"
    assert audit_log.after_state["audit_status"] == "rejected"


@pytest.mark.django_db
def test_review_policy_item_rolls_back_when_audit_log_fails() -> None:
    reviewer = User._default_manager.create_user(
        username="atomic_policy_reviewer",
        is_staff=True,
    )
    event = _pending_event("Atomic legacy review")
    PolicyAuditQueue._default_manager.create(
        policy_log=event,
        assigned_to=reviewer,
    )
    repository = WorkbenchRepository()

    with (
        patch.object(
            repository,
            "_create_audit_log",
            side_effect=RuntimeError("audit storage unavailable"),
        ),
        pytest.raises(RuntimeError, match="audit storage unavailable"),
    ):
        repository.review_policy_item(
            policy_log_id=event.id,
            approved=True,
            reviewer_id=reviewer.id,
        )

    event.refresh_from_db()
    assert event.audit_status == "pending_review"
    assert PolicyAuditQueue._default_manager.filter(policy_log=event).exists()


def test_ingestion_config_rejects_unknown_fields_before_database_access() -> None:
    repository = WorkbenchRepository()

    with pytest.raises(ValueError, match="unsupported ingestion config fields"):
        repository.update_ingestion_config(save="shadow method")
