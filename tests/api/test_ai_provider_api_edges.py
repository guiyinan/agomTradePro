import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.ai_provider.infrastructure.models import AIProviderConfig, AIUserFallbackQuota


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def auth_user(db):
    return get_user_model().objects.create_user(
        username="ai_provider_user",
        password="testpass123",
        email="ai-provider@example.com",
    )


@pytest.fixture
def admin_user(db):
    return get_user_model().objects.create_superuser(
        username="ai_provider_admin",
        password="testpass123",
        email="ai-provider-admin@example.com",
    )


@pytest.fixture
def authenticated_client(api_client, auth_user):
    api_client.force_authenticate(user=auth_user)
    return api_client


@pytest.fixture
def admin_client(admin_user):
    client = APIClient()
    client.force_authenticate(user=admin_user)
    return client


@pytest.mark.django_db
def test_ai_provider_api_root_contract(authenticated_client):
    response = authenticated_client.get("/api/ai/")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    payload = response.json()
    assert payload["endpoints"]["providers"] == "/api/ai/providers/"
    assert payload["endpoints"]["logs"] == "/api/ai/logs/"
    assert payload["endpoints"]["me_providers"] == "/api/ai/me/providers/"
    assert payload["endpoints"]["me_quota"] == "/api/ai/me/quota/current/"


@pytest.mark.django_db
def test_ai_provider_logs_reject_invalid_provider_filter(admin_client):
    response = admin_client.get("/api/ai/logs/?provider=bad")

    assert response.status_code == 400
    assert response.json()["error"] == "provider 必须是整数"


@pytest.mark.django_db
def test_ai_provider_list_requires_authentication(api_client):
    response = api_client.get("/api/ai/providers/")

    assert response.status_code in {401, 403}


@pytest.mark.django_db
def test_ai_provider_system_list_requires_admin(authenticated_client):
    response = authenticated_client.get("/api/ai/providers/")

    assert response.status_code == 403


@pytest.mark.django_db
def test_ai_provider_test_connection_missing_provider_returns_404(admin_client):
    response = admin_client.post("/api/ai/providers/999999/test-connection/")

    assert response.status_code == 404
    assert "not found" in response.json()["error"].lower()


@pytest.mark.django_db
def test_user_can_list_own_personal_providers(authenticated_client, auth_user):
    AIProviderConfig.objects.create(
        name="personal-main",
        scope="user",
        owner_user=auth_user,
        provider_type="openai",
        is_active=True,
        priority=1,
        base_url="https://example.invalid/user",
        api_key="sk-user",
        default_model="gpt-4o-mini",
    )
    AIProviderConfig.objects.create(
        name="system-main",
        scope="system",
        provider_type="openai",
        is_active=True,
        priority=10,
        base_url="https://example.invalid/system",
        api_key="sk-system",
        default_model="gpt-4o-mini",
    )

    response = authenticated_client.get("/api/ai/me/providers/")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["name"] == "personal-main"
    assert payload[0]["scope"] == "user"
    assert payload[0]["today_requests"] == 0
    assert payload[0]["today_cost"] == 0.0
    assert payload[0]["month_requests"] == 0
    assert payload[0]["month_cost"] == 0.0


@pytest.mark.django_db
def test_admin_system_provider_list_includes_usage_fields(admin_client):
    AIProviderConfig.objects.create(
        name="system-main",
        scope="system",
        provider_type="openai",
        is_active=True,
        priority=10,
        base_url="https://example.invalid/system",
        api_key="sk-system",
        default_model="gpt-4o-mini",
    )

    response = admin_client.get("/api/ai/providers/")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["name"] == "system-main"
    assert payload[0]["scope"] == "system"
    assert payload[0]["today_requests"] == 0
    assert payload[0]["today_cost"] == 0.0
    assert payload[0]["month_requests"] == 0
    assert payload[0]["month_cost"] == 0.0


@pytest.mark.django_db
def test_user_quota_current_contract(authenticated_client, auth_user):
    AIUserFallbackQuota.objects.create(
        user=auth_user,
        daily_limit=10,
        monthly_limit=100,
        is_active=True,
        admin_note="default quota",
    )

    response = authenticated_client.get("/api/ai/me/quota/current/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["user_id"] == auth_user.id
    assert payload["daily_limit"] == 10.0
    assert payload["monthly_limit"] == 100.0
    assert payload["daily_spent"] == 0.0
    assert payload["monthly_spent"] == 0.0


@pytest.mark.django_db
def test_admin_can_update_one_user_quota(admin_client, auth_user):
    response = admin_client.patch(
        f"/api/ai/admin/quotas/{auth_user.id}/",
        {
            "daily_limit": "5.00",
            "monthly_limit": "50.00",
            "is_active": True,
            "admin_note": "manually assigned",
        },
        format="json",
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["user_id"] == auth_user.id
    assert payload["daily_limit"] == 5.0
    assert payload["monthly_limit"] == 50.0


@pytest.mark.django_db
def test_admin_partial_quota_update_preserves_unspecified_fields(admin_client, auth_user):
    AIUserFallbackQuota.objects.create(
        user=auth_user,
        daily_limit=4,
        monthly_limit=40,
        is_active=False,
        admin_note="keep me",
    )

    response = admin_client.patch(
        f"/api/ai/admin/quotas/{auth_user.id}/",
        {
            "daily_limit": "6.00",
        },
        format="json",
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["daily_limit"] == 6.0
    assert payload["monthly_limit"] == 40.0
    assert payload["is_active"] is False
    assert payload["admin_note"] == "keep me"


@pytest.mark.django_db
def test_system_provider_put_update_preserves_unspecified_fields(admin_client):
    provider = AIProviderConfig.objects.create(
        name="system-main",
        scope="system",
        provider_type="openai",
        is_active=True,
        priority=10,
        base_url="https://example.invalid/system",
        api_key="sk-system",
        default_model="gpt-4o-mini",
        api_mode="chat_only",
        fallback_enabled=False,
        extra_config={"timeout": 99},
    )

    response = admin_client.put(
        f"/api/ai/providers/{provider.id}/",
        {
            "name": "system-main",
            "provider_type": "openai",
            "base_url": "https://example.invalid/system-updated",
            "default_model": "gpt-4.1-mini",
            "priority": 2,
            "is_active": True,
        },
        format="json",
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["api_mode"] == "chat_only"
    assert payload["fallback_enabled"] is False
    assert payload["extra_config"] == {"timeout": 99}


@pytest.mark.django_db
def test_personal_provider_put_update_preserves_unspecified_fields(authenticated_client, auth_user):
    provider = AIProviderConfig.objects.create(
        name="personal-main",
        scope="user",
        owner_user=auth_user,
        provider_type="openai",
        is_active=True,
        priority=10,
        base_url="https://example.invalid/personal",
        api_key="sk-user",
        default_model="gpt-4o-mini",
        api_mode="responses_only",
        fallback_enabled=False,
        extra_config={"temperature": 0.3},
    )

    response = authenticated_client.put(
        f"/api/ai/me/providers/{provider.id}/",
        {
            "name": "personal-main",
            "provider_type": "openai",
            "base_url": "https://example.invalid/personal-updated",
            "default_model": "gpt-4.1-mini",
            "priority": 3,
            "is_active": True,
        },
        format="json",
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["api_mode"] == "responses_only"
    assert payload["fallback_enabled"] is False
    assert payload["extra_config"] == {"temperature": 0.3}


@pytest.mark.django_db
def test_ai_provider_test_connection_success_contract(admin_client, monkeypatch):
    class _HealthyAdapter:
        def __init__(self, *args, **kwargs):
            pass

        def is_available(self):
            return True

    monkeypatch.setattr(
        "apps.ai_provider.application.use_cases.OpenAICompatibleAdapter", _HealthyAdapter
    )
    provider = AIProviderConfig.objects.create(
        name="system-main",
        scope="system",
        provider_type="openai",
        is_active=True,
        priority=10,
        base_url="https://example.invalid/system",
        api_key="sk-system",
        default_model="gpt-4o-mini",
    )

    response = admin_client.post(f"/api/ai/providers/{provider.id}/test-connection/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "success"
    assert payload["provider"] == "system-main"
    assert "message" in payload


@pytest.mark.django_db
def test_admin_can_batch_apply_quota(admin_client, auth_user):
    response = admin_client.post(
        "/api/ai/admin/quotas/batch_apply/",
        {
            "daily_limit": "3.00",
            "monthly_limit": "30.00",
            "overwrite_existing": False,
            "is_active": True,
            "admin_note": "batch default",
        },
        format="json",
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["processed_users"] >= 1
    assert payload["created_count"] >= 1


@pytest.mark.django_db
def test_user_cannot_access_admin_quotas(authenticated_client):
    response = authenticated_client.get("/api/ai/admin/quotas/")

    assert response.status_code == 403
