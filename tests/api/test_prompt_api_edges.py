from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.ai_provider.infrastructure.models import AIProviderConfig


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def auth_user(db):
    return get_user_model().objects.create_user(
        username="prompt_user",
        password="testpass123",
        email="prompt@example.com",
    )


@pytest.fixture
def authenticated_client(api_client, auth_user):
    api_client.force_authenticate(user=auth_user)
    return api_client


@pytest.mark.django_db
def test_prompt_api_root_contract(authenticated_client):
    response = authenticated_client.get("/api/prompt/")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    payload = response.json()
    assert payload["endpoints"]["templates"] == "/api/prompt/templates/"
    assert payload["endpoints"]["chat"] == "/api/prompt/chat"


@pytest.mark.django_db
def test_prompt_chat_returns_502_when_provider_returns_error_status(authenticated_client):
    with patch("apps.prompt.interface.views.generate_chat_completion") as mock_completion:
        mock_completion.return_value = {
            "status": "error",
            "error_message": "provider unavailable",
        }
        response = authenticated_client.post(
            "/api/prompt/chat",
            {"message": "hello", "provider_name": "openai-main", "model": "gpt-4.1"},
            format="json",
        )

    assert response.status_code == 502
    assert response.json()["error"] == "provider unavailable"


@pytest.mark.django_db
def test_prompt_chat_models_uses_supported_models_from_extra_config(authenticated_client):
    AIProviderConfig.objects.create(
        name="openai-main",
        provider_type="openai",
        is_active=True,
        priority=1,
        base_url="https://api.openai.com/v1",
        api_key="test-key",
        default_model="gpt-4.1",
        extra_config={"supported_models": ["gpt-4.1", "gpt-4.1-mini"]},
    )

    response = authenticated_client.get("/api/prompt/chat/models?provider=openai-main")

    assert response.status_code == 200
    assert response.json()["models"] == ["gpt-4.1", "gpt-4.1-mini"]
