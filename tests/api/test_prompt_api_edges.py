from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.ai_provider.infrastructure.models import AIProviderConfig
from apps.prompt.infrastructure.models import ChainConfigORM, PromptTemplateORM


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


@pytest.fixture
def staff_user(db):
    return get_user_model().objects.create_user(
        username="prompt_staff",
        password="testpass123",
        email="prompt-staff@example.com",
        is_staff=True,
    )


@pytest.fixture
def staff_client(api_client, staff_user):
    api_client.force_authenticate(user=staff_user)
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
def test_prompt_template_list_contract_returns_active_templates_only(authenticated_client):
    PromptTemplateORM.objects.create(
        name="Macro Weekly Brief",
        category="report",
        version="1.2",
        template_content="Summarize macro regime for {{date}}.",
        system_prompt="Focus on regime and policy.",
        placeholders=[{"name": "date", "type": "simple", "required": True}],
        temperature=0.3,
        max_tokens=1200,
        description="Weekly macro brief template",
        is_active=True,
    )
    PromptTemplateORM.objects.create(
        name="Inactive Template",
        category="analysis",
        version="0.9",
        template_content="Should not be listed.",
        system_prompt="",
        placeholders=[],
        temperature=0.5,
        max_tokens=300,
        description="Inactive template",
        is_active=False,
    )

    response = authenticated_client.get("/api/prompt/templates/")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    payload = response.json()
    assert payload["count"] == 1
    assert payload["next"] is None
    assert payload["previous"] is None
    assert len(payload["results"]) == 1
    assert payload["results"][0]["name"] == "Macro Weekly Brief"
    assert payload["results"][0]["category"] == "report"
    assert payload["results"][0]["version"] == "1.2"
    assert payload["results"][0]["template_content"] == "Summarize macro regime for {{date}}."
    assert payload["results"][0]["is_active"] is True
    assert payload["results"][0]["placeholders"][0]["name"] == "date"
    assert payload["results"][0]["placeholders"][0]["type"] == "simple"


@pytest.mark.django_db
def test_prompt_template_create_requires_staff(authenticated_client):
    response = authenticated_client.post(
        "/api/prompt/templates/",
        {
            "name": "Restricted Template",
            "category": "analysis",
            "template_content": "Analyze {{asset_code}}.",
        },
        format="json",
    )

    assert response.status_code == 403


@pytest.mark.django_db
def test_prompt_template_create_rejects_unauthenticated_client(api_client):
    response = api_client.post(
        "/api/prompt/templates/",
        {
            "name": "Unauthenticated Template",
            "category": "analysis",
            "template_content": "Analyze {{asset_code}}.",
        },
        format="json",
    )

    assert response.status_code in {401, 403}


@pytest.mark.django_db
def test_prompt_template_create_returns_stable_contract_for_staff(staff_client):
    response = staff_client.post(
        "/api/prompt/templates/",
        {
            "name": "Governed Analysis Template",
            "category": "analysis",
            "version": "1.0",
            "template_content": "Analyze {{asset_code}}.",
            "system_prompt": "Use persisted investment facts only.",
            "placeholders": [
                {
                    "name": "asset_code",
                    "type": "simple",
                    "description": "Target asset code",
                    "required": True,
                }
            ],
            "temperature": 0.2,
            "max_tokens": 800,
            "description": "Governed prompt template",
            "is_active": True,
        },
        format="json",
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["name"] == "Governed Analysis Template"
    assert payload["category"] == "analysis"
    assert payload["placeholders"][0]["name"] == "asset_code"
    assert PromptTemplateORM.objects.filter(
        name="Governed Analysis Template",
        is_active=True,
    ).exists()


@pytest.mark.django_db
def test_prompt_template_create_rejects_inactive_duplicate_name(staff_client):
    PromptTemplateORM.objects.create(
        name="Reserved Template",
        category="analysis",
        version="1.0",
        template_content="Inactive content.",
        placeholders=[],
        is_active=False,
    )

    response = staff_client.post(
        "/api/prompt/templates/",
        {
            "name": "Reserved Template",
            "category": "analysis",
            "template_content": "Replacement content.",
        },
        format="json",
    )

    assert response.status_code == 400
    assert "模板名称已存在" in str(response.json())


@pytest.mark.django_db
def test_prompt_template_staff_lookup_can_include_inactive_exact_name(staff_client):
    PromptTemplateORM.objects.create(
        name="Inactive Preview Template",
        category="report",
        version="1.0",
        template_content="Inactive content.",
        placeholders=[],
        is_active=False,
    )

    response = staff_client.get(
        "/api/prompt/templates/",
        {
            "name": "Inactive Preview Template",
            "include_inactive": "true",
        },
    )

    assert response.status_code == 200
    assert response.json()["count"] == 1
    assert response.json()["results"][0]["name"] == "Inactive Preview Template"
    assert response.json()["results"][0]["is_active"] is False


@pytest.mark.django_db
def test_prompt_chain_list_contract_returns_active_chains_only(authenticated_client):
    ChainConfigORM.objects.create(
        name="Macro Review Flow",
        category="analysis",
        description="Chain for macro review",
        steps=[
            {
                "step_id": "step-1",
                "template_id": "9",
                "step_name": "Collect Context",
                "order": 1,
                "input_mapping": {"date": "today"},
                "output_parser": "",
                "parallel_group": "",
                "enable_tool_calling": False,
                "available_tools": [],
            }
        ],
        execution_mode="serial",
        aggregate_step=None,
        is_active=True,
    )
    ChainConfigORM.objects.create(
        name="Inactive Chain",
        category="report",
        description="Should not be listed",
        steps=[],
        execution_mode="parallel",
        aggregate_step=None,
        is_active=False,
    )

    response = authenticated_client.get("/api/prompt/chains/")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    payload = response.json()
    assert payload["count"] == 1
    assert payload["next"] is None
    assert payload["previous"] is None
    assert len(payload["results"]) == 1
    assert payload["results"][0]["name"] == "Macro Review Flow"
    assert payload["results"][0]["category"] == "analysis"
    assert payload["results"][0]["execution_mode"] == "serial"
    assert payload["results"][0]["is_active"] is True
    assert payload["results"][0]["steps"][0]["step_id"] == "step-1"
    assert payload["results"][0]["steps"][0]["step_name"] == "Collect Context"


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


@pytest.mark.django_db
def test_prompt_chat_providers_embeds_models_for_initial_selector(authenticated_client):
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

    response = authenticated_client.get("/api/prompt/chat/providers")

    assert response.status_code == 200
    assert response.json()["providers"][0]["models"] == [
        "gpt-4.1",
        "gpt-4.1-mini",
    ]
