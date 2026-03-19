"""API and use-case regression tests for AI capability routing."""

from unittest.mock import patch

import pytest
from django.contrib.auth.models import User
from rest_framework.test import APIClient

from apps.ai_capability.application.dtos import RouteRequestDTO
from apps.ai_capability.application.use_cases import RouteMessageUseCase, SyncCapabilitiesUseCase
from apps.ai_capability.infrastructure.models import CapabilityCatalogModel


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def staff_user(db):
    return User.objects.create_user(
        username="cap_staff",
        password="test123",
        is_staff=True,
    )


@pytest.fixture
def regular_user(db):
    return User.objects.create_user(
        username="cap_regular",
        password="test123",
        is_staff=False,
    )


@pytest.fixture
def write_capability(db):
    return CapabilityCatalogModel.objects.create(
        capability_key="api.post.api.runtime.reset",
        source_type="api",
        source_ref="POST api/runtime/reset/",
        name="Runtime Reset",
        summary="Reset runtime state",
        description="Reset runtime state for the system",
        route_group="write_api",
        category="runtime",
        execution_target={"type": "api", "method": "POST", "path": "api/runtime/reset/"},
        risk_level="high",
        requires_confirmation=True,
        enabled_for_routing=True,
        enabled_for_terminal=True,
        enabled_for_chat=False,
        enabled_for_agent=True,
        visibility="internal",
        auto_collected=True,
        review_status="auto",
    )


@pytest.mark.django_db
def test_non_admin_capability_detail_hides_technical_fields(api_client, regular_user, write_capability):
    api_client.force_authenticate(user=regular_user)

    response = api_client.get(f"/api/ai-capability/capabilities/{write_capability.capability_key}/")

    assert response.status_code == 200
    data = response.json()
    assert "source_ref" not in data
    assert "execution_target" not in data
    assert data["capability_key"] == write_capability.capability_key


@pytest.mark.django_db
def test_sync_capabilities_disables_missing_source_entries():
    CapabilityCatalogModel.objects.create(
        capability_key="api.get.api.legacy.status",
        source_type="api",
        source_ref="GET api/legacy/status/",
        name="Legacy Status",
        summary="Legacy endpoint",
        route_group="read_api",
        category="legacy",
        execution_target={"type": "api", "method": "GET", "path": "api/legacy/status/"},
        enabled_for_routing=True,
    )

    use_case = SyncCapabilitiesUseCase()
    with patch.object(SyncCapabilitiesUseCase, "_sync_apis", return_value=[]):
        result = use_case.execute(sync_type="incremental", source="api")

    assert result.disabled_count == 1
    assert CapabilityCatalogModel.objects.get(
        capability_key="api.get.api.legacy.status"
    ).enabled_for_routing is False


@pytest.mark.django_db
def test_route_message_requires_confirmation_for_write_capability(write_capability, regular_user):
    use_case = RouteMessageUseCase()

    response = use_case.execute(
        RouteRequestDTO(
            message="请帮我 reset runtime state",
            entrypoint="terminal",
            context={
                "user_id": regular_user.id,
                "user_is_admin": False,
                "mcp_enabled": True,
                "answer_chain_enabled": True,
            },
        )
    )

    assert response.decision == "ask_confirmation"
    assert response.selected_capability_key == write_capability.capability_key
    assert response.requires_confirmation is True


@pytest.mark.django_db
def test_non_admin_answer_chain_masks_technical_fields(write_capability, regular_user):
    use_case = RouteMessageUseCase()

    response = use_case.execute(
        RouteRequestDTO(
            message="runtime reset",
            entrypoint="terminal",
            context={
                "user_id": regular_user.id,
                "user_is_admin": False,
                "mcp_enabled": True,
                "answer_chain_enabled": True,
            },
        )
    )

    assert response.answer_chain["visibility"] == "masked"
    steps = response.answer_chain["steps"]
    assert all("technical_details" not in step for step in steps)
    assert write_capability.capability_key not in steps[1]["summary"]
    assert write_capability.name in steps[1]["summary"]
