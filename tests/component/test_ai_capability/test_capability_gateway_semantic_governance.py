"""Operator-page and Admin tests for semantic governance."""

from __future__ import annotations

import pytest
from django.contrib import admin

from apps.ai_capability.infrastructure.models import (
    CapabilityCatalogModel,
    CapabilitySemanticAuditModel,
    CapabilitySemanticOverrideModel,
)


def _create_user(django_user_model, username: str, *, is_staff: bool):
    """Create an approved account user for Gateway rendering."""

    user = django_user_model.objects.create_user(
        username=username,
        password="test123",
        is_staff=is_staff,
        is_superuser=is_staff,
    )
    profile = user.account_profile
    profile.approval_status = "approved"
    profile.rbac_role = "admin" if is_staff else "read_only"
    profile.mcp_enabled = is_staff
    profile.save(
        update_fields=[
            "approval_status",
            "rbac_role",
            "mcp_enabled",
            "updated_at",
        ]
    )
    return user


@pytest.mark.django_db
def test_gateway_hides_semantic_governance_from_regular_users(
    client,
    django_user_model,
) -> None:
    """Ordinary users never receive operator controls or audit data."""

    user = _create_user(
        django_user_model,
        "semantic-page-user",
        is_staff=False,
    )
    client.force_login(user)

    response = client.get("/settings/capability-gateway/")
    content = response.content.decode("utf-8")

    assert response.status_code == 200
    assert "semanticGovernancePanel" not in content
    assert "语义键治理" not in content


@pytest.mark.django_db
def test_gateway_staff_page_renders_semantic_issues_and_audit(
    client,
    django_user_model,
) -> None:
    """Staff see missing/conflict/orphan issues and immutable audit evidence."""

    staff = _create_user(
        django_user_model,
        "semantic-page-staff",
        is_staff=True,
    )
    CapabilityCatalogModel.objects.all().delete()
    for capability_key, semantic_key in [
        ("api.shared", "semantic.shared"),
        ("mcp.shared", "semantic.shared"),
        ("api.missing", ""),
    ]:
        CapabilityCatalogModel.objects.create(
            capability_key=capability_key,
            source_type="api",
            source_ref=capability_key,
            name=capability_key,
            summary=capability_key,
            semantic_key=semantic_key,
            collected_semantic_key=semantic_key,
        )
    CapabilitySemanticOverrideModel.objects.create(
        capability_key="removed.capability",
        semantic_key="semantic.orphan",
        reason="Retained orphan",
        updated_by=staff,
    )
    CapabilitySemanticAuditModel.objects.create(
        idempotency_key="semantic-page-audit",
        capability_key="api.shared",
        action="set",
        old_collected_value="semantic.shared",
        old_effective_value="semantic.shared",
        new_effective_value="semantic.corrected",
        reason="Page audit evidence",
        operator=staff,
        request_fingerprint="c" * 64,
    )
    client.force_login(staff)

    response = client.get("/settings/capability-gateway/")
    content = response.content.decode("utf-8")

    assert response.status_code == 200
    assert 'id="semanticGovernancePanel"' in content
    assert "语义键治理" in content
    assert "api.missing" in content
    assert "semantic.shared" in content
    assert "removed.capability" in content
    assert "Page audit evidence" in content
    assert "预览修正" in content
    assert "应用修正" in content


@pytest.mark.django_db
def test_semantic_governance_admin_registration_is_read_only_for_audit() -> None:
    """Admin exposes current overrides and immutable audit history."""

    assert admin.site.is_registered(CapabilitySemanticOverrideModel)
    assert admin.site.is_registered(CapabilitySemanticAuditModel)
    audit_admin = admin.site._registry[CapabilitySemanticAuditModel]
    assert audit_admin.has_add_permission(None) is False
    assert audit_admin.has_change_permission(None) is False
    assert audit_admin.has_delete_permission(None) is False
