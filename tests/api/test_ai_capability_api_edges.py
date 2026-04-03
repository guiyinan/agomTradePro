from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.contrib.auth.models import User
from rest_framework.test import APIClient


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def staff_user(db):
    return User.objects.create_user(username="ai_cap_staff", password="test123", is_staff=True)


@pytest.fixture
def regular_user(db):
    return User.objects.create_user(username="ai_cap_regular", password="test123", is_staff=False)


@pytest.mark.django_db
def test_ai_capability_sync_requires_staff(api_client, regular_user):
    api_client.force_authenticate(user=regular_user)

    response = api_client.post("/api/ai-capability/sync/", {"sync_type": "full"}, format="json")

    assert response.status_code == 403
    assert response.json()["error"] == "Admin privileges required"


@pytest.mark.django_db
def test_ai_capability_stats_contract(api_client, regular_user):
    api_client.force_authenticate(user=regular_user)

    with patch(
        "apps.ai_capability.interface.api_views.GetCatalogStatsUseCase.execute",
        return_value={
            "total": 10,
            "enabled": 8,
            "disabled": 2,
            "by_source": {"builtin": 4},
            "by_route_group": {"builtin": 4},
        },
    ):
        response = api_client.get("/api/ai-capability/stats/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 10
    assert payload["enabled"] == 8
    assert payload["by_source"]["builtin"] == 4


@pytest.mark.django_db
def test_ai_capability_route_enriches_context_before_use_case(api_client, staff_user):
    api_client.force_authenticate(user=staff_user)

    captured = {}

    def _fake_execute(request_dto):
        captured["dto"] = request_dto
        return SimpleNamespace(
            to_dict=lambda: {
                "decision": "chat",
                "selected_capability_key": None,
                "confidence": 0.5,
                "candidate_capabilities": [],
                "requires_confirmation": False,
                "reply": "ok",
                "session_id": "sess-1",
                "metadata": {"provider": "router"},
                "answer_chain": {},
            }
        )

    with patch(
        "apps.ai_capability.interface.api_views._get_mcp_enabled",
        return_value=True,
    ), patch(
        "apps.ai_capability.interface.api_views.RouteMessageUseCase.execute",
        side_effect=_fake_execute,
    ):
        response = api_client.post(
            "/api/ai-capability/route/",
            {
                "message": "系统状态",
                "entrypoint": "terminal",
                "context": {"history": []},
            },
            format="json",
        )

    assert response.status_code == 200
    dto = captured["dto"]
    assert dto.context["user_id"] == staff_user.id
    assert dto.context["user_is_admin"] is True
    assert dto.context["mcp_enabled"] is True
    assert dto.context["answer_chain_enabled"] is False


@pytest.mark.django_db
def test_ai_capability_web_chat_masks_answer_chain_for_non_admin(api_client, regular_user):
    api_client.force_authenticate(user=regular_user)

    with patch(
        "apps.ai_capability.application.facade.CapabilityRoutingFacade.route",
        return_value={
            "reply": "ok",
            "session_id": "sess-web",
            "metadata": {"provider": "capability-router", "model": "router", "tokens": 10},
            "answer_chain": {
                "label": "Chain",
                "visibility": "public",
                "steps": [
                    {
                        "title": "Select capability",
                        "summary": "选择 system status",
                        "source": "router",
                        "technical_details": {"score": 0.9},
                    }
                ],
            },
            "requires_confirmation": False,
        },
    ):
        response = api_client.post(
            "/api/chat/web/",
            {"message": "系统状态", "context": {}},
            format="json",
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["metadata"]["answer_chain"]["visibility"] == "masked"
    assert "technical_details" not in payload["metadata"]["answer_chain"]["steps"][0]
