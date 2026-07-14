"""Persistence tests for semantic-key governance models."""

from __future__ import annotations

from uuid import UUID

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.ai_capability.infrastructure.models import (
    CapabilitySemanticAuditModel,
    CapabilitySemanticOverrideModel,
)


@pytest.mark.django_db
def test_semantic_override_is_unique_per_capability(django_user_model) -> None:
    """Only one current override row can exist for a capability."""

    user = django_user_model.objects.create_user(username="semantic-operator")
    override = CapabilitySemanticOverrideModel.objects.create(
        capability_key="realtime.create.price_alert",
        semantic_key="realtime.alert.create",
        reason="Resolve catalog collision",
        updated_by=user,
    )

    assert override.is_active is True
    assert override.updated_by_id == user.pk
    assert timezone.is_aware(override.created_at)
    assert timezone.is_aware(override.updated_at)

    with pytest.raises(IntegrityError), transaction.atomic():
        CapabilitySemanticOverrideModel.objects.create(
            capability_key="realtime.create.price_alert",
            semantic_key="realtime.alert.create_v2",
            reason="Duplicate current row",
            updated_by=user,
        )


@pytest.mark.django_db
def test_semantic_audit_records_complete_append_evidence(django_user_model) -> None:
    """Audit rows retain old/new values, actor, fingerprint, and batch identity."""

    user = django_user_model.objects.create_user(username="semantic-auditor")
    audit = CapabilitySemanticAuditModel.objects.create(
        idempotency_key="semantic-batch-001",
        capability_key="realtime.create.price_alert",
        action="set",
        old_collected_value="legacy.mcp.create_price_alert",
        old_effective_value="legacy.mcp.create_price_alert",
        new_effective_value="realtime.alert.create",
        reason="Resolve catalog collision",
        operator=user,
        request_fingerprint="a" * 64,
    )

    assert isinstance(audit.batch_id, UUID)
    assert audit.operator_id == user.pk
    assert timezone.is_aware(audit.created_at)
    assert audit.old_collected_value == "legacy.mcp.create_price_alert"
    assert audit.new_effective_value == "realtime.alert.create"


@pytest.mark.django_db
def test_semantic_audit_rejects_duplicate_capability_in_idempotent_batch(
    django_user_model,
) -> None:
    """One idempotent batch records at most one operation per capability."""

    user = django_user_model.objects.create_user(username="semantic-unique")
    fields = {
        "idempotency_key": "semantic-batch-unique",
        "capability_key": "events.replay.events",
        "action": "set",
        "old_collected_value": "",
        "old_effective_value": "",
        "new_effective_value": "events.replay.events",
        "reason": "Add governed semantic key",
        "operator": user,
        "request_fingerprint": "b" * 64,
    }
    CapabilitySemanticAuditModel.objects.create(**fields)

    with pytest.raises(IntegrityError), transaction.atomic():
        CapabilitySemanticAuditModel.objects.create(**fields)
