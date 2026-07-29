"""API contracts for staff semantic-key governance."""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from apps.ai_capability.infrastructure.models import (
    CapabilityCatalogModel,
    CapabilitySemanticAuditModel,
    CapabilitySemanticOverrideModel,
)

BASE_URL = "/api/ai-capabilities/semantic-governance/"


def _create_catalog(
    capability_key: str,
    semantic_key: str,
    *,
    source_type: str = "api",
) -> CapabilityCatalogModel:
    """Create a minimal synchronized catalog row with source evidence."""

    return CapabilityCatalogModel.objects.create(
        capability_key=capability_key,
        source_type=source_type,
        source_ref=capability_key,
        name=capability_key,
        summary=capability_key,
        semantic_key=semantic_key,
        collected_semantic_key=semantic_key,
    )


@pytest.fixture
def staff_client(django_user_model) -> APIClient:
    """Return a session-authenticated staff client."""

    CapabilityCatalogModel.objects.all().delete()
    user = django_user_model.objects.create_user(
        username="semantic-staff",
        is_staff=True,
    )
    client = APIClient()
    client.force_authenticate(user=user)
    client.user = user
    return client


@pytest.mark.django_db
def test_semantic_governance_requires_authentication_and_staff(
    django_user_model,
) -> None:
    """Anonymous users receive 401 and ordinary users receive 403."""

    anonymous = APIClient().get(BASE_URL)
    ordinary_user = django_user_model.objects.create_user(username="semantic-user")
    ordinary_client = APIClient()
    ordinary_client.force_authenticate(user=ordinary_user)
    forbidden = ordinary_client.get(BASE_URL)

    assert anonymous.status_code == 401
    assert forbidden.status_code == 403
    assert anonymous["Content-Type"].startswith("application/json")
    assert forbidden["Content-Type"].startswith("application/json")


@pytest.mark.django_db
def test_semantic_governance_inspection_contract(staff_client) -> None:
    """Staff inspection returns missing, conflict, and orphan groups."""

    _create_catalog("api.shared", "semantic.shared")
    _create_catalog("mcp.shared", "semantic.shared", source_type="mcp_tool")
    _create_catalog("api.missing", "")
    CapabilitySemanticOverrideModel.objects.create(
        capability_key="removed.capability",
        semantic_key="semantic.orphan",
        reason="Orphan retained for operator review",
        updated_by=staff_client.user,
    )

    response = staff_client.get(BASE_URL)

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    assert response.json() == {
        "missing_capability_keys": ["api.missing"],
        "conflicts": {
            "semantic.shared": ["api.shared", "mcp.shared"],
        },
        "orphaned_override_keys": ["removed.capability"],
    }


@pytest.mark.django_db
def test_semantic_preview_rejects_unknown_fields_and_performs_zero_writes(
    staff_client,
) -> None:
    """Strict input validation and preview cannot mutate governance tables."""

    _create_catalog("mcp.shared", "semantic.shared", source_type="mcp_tool")
    payload = {
        "idempotency_key": "semantic-api-preview",
        "reason": "Separate duplicate semantics",
        "corrections": [
            {
                "capability_key": "mcp.shared",
                "action": "set",
                "semantic_key": "semantic.mcp_shared",
            }
        ],
    }
    invalid = staff_client.post(
        f"{BASE_URL}preview/",
        {**payload, "unexpected": True},
        format="json",
    )
    response = staff_client.post(
        f"{BASE_URL}preview/",
        payload,
        format="json",
    )

    assert invalid.status_code == 400
    assert response.status_code == 200
    assert response.json()["batch_id"] is None
    assert response.json()["corrections"][0]["new_effective_value"] == ("semantic.mcp_shared")
    assert CapabilitySemanticOverrideModel.objects.count() == 0
    assert CapabilitySemanticAuditModel.objects.count() == 0


@pytest.mark.django_db
def test_tui_single_semantic_preview_and_apply_use_flat_contract(staff_client) -> None:
    """TUI adapters accept one flat correction and preserve idempotent evidence."""

    _create_catalog("api.tui-target", "semantic.collected")
    payload = {
        "idempotency_key": "semantic-tui-single",
        "reason": "Correct one routed semantic from the TUI",
        "capability_key": "api.tui-target",
        "action": "set",
        "semantic_key": "semantic.tui_corrected",
    }

    preview = staff_client.post(
        f"{BASE_URL}single-preview/",
        payload,
        format="json",
    )
    applied = staff_client.post(
        f"{BASE_URL}single-apply/",
        payload,
        format="json",
    )

    assert preview.status_code == 200
    assert preview.json()["batch_id"] is None
    assert applied.status_code == 200
    assert applied.json()["corrections"][0]["new_effective_value"] == ("semantic.tui_corrected")
    assert (
        CapabilitySemanticOverrideModel.objects.get(capability_key="api.tui-target").semantic_key
        == "semantic.tui_corrected"
    )


@pytest.mark.django_db
def test_semantic_apply_is_idempotent_and_conflicts_on_payload_change(
    staff_client,
) -> None:
    """Matching retries replay prior evidence and changed payloads return 409."""

    _create_catalog("api.target", "semantic.collected")
    payload = {
        "idempotency_key": "semantic-api-apply",
        "reason": "Correct routed semantic",
        "corrections": [
            {
                "capability_key": "api.target",
                "action": "set",
                "semantic_key": "semantic.corrected",
            }
        ],
    }

    first = staff_client.post(f"{BASE_URL}apply/", payload, format="json")
    replay = staff_client.post(f"{BASE_URL}apply/", payload, format="json")
    conflict = staff_client.post(
        f"{BASE_URL}apply/",
        {
            **payload,
            "reason": "Changed authorization reason",
        },
        format="json",
    )

    assert first.status_code == 200
    assert first.json()["replayed"] is False
    assert replay.status_code == 200
    assert replay.json()["replayed"] is True
    assert replay.json()["batch_id"] == first.json()["batch_id"]
    assert replay.json()["corrections"] == first.json()["corrections"]
    assert conflict.status_code == 409
    assert (
        CapabilitySemanticOverrideModel.objects.get(capability_key="api.target").semantic_key
        == "semantic.corrected"
    )
    assert CapabilitySemanticAuditModel.objects.count() == 1


@pytest.mark.django_db
def test_semantic_remove_and_audit_contract(staff_client) -> None:
    """Remove restores collected projection and immutable audit remains listed."""

    _create_catalog("api.target", "semantic.collected")
    CapabilitySemanticOverrideModel.objects.create(
        capability_key="api.target",
        semantic_key="semantic.corrected",
        reason="Earlier correction",
        updated_by=staff_client.user,
    )
    response = staff_client.post(
        f"{BASE_URL}apply/",
        {
            "idempotency_key": "semantic-api-remove",
            "reason": "Restore collected semantic",
            "corrections": [
                {
                    "capability_key": "api.target",
                    "action": "remove",
                }
            ],
        },
        format="json",
    )
    audit = staff_client.get(
        f"{BASE_URL}audit/",
        {"capability_key": "api.target", "limit": 25},
    )

    assert response.status_code == 200
    assert response.json()["corrections"][0]["new_effective_value"] == ("semantic.collected")
    assert (
        CapabilitySemanticOverrideModel.objects.get(capability_key="api.target").is_active is False
    )
    assert audit.status_code == 200
    assert audit.json()["count"] == 1
    assert audit.json()["results"][0]["action"] == "remove"
