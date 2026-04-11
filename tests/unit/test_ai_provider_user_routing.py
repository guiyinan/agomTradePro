import pytest
from django.contrib.auth import get_user_model

from apps.ai_provider.infrastructure.client_factory import AIClientFactory
from apps.ai_provider.infrastructure.models import AIProviderConfig, AIUsageLog, AIUserFallbackQuota
from apps.ai_provider.infrastructure.repositories import AIUsageRepository


class _FakeAdapter:
    def __init__(
        self,
        *,
        base_url,
        api_key,
        default_model="gpt-4o-mini",
        api_mode=None,
        fallback_enabled=None,
    ):
        self.base_url = base_url
        self.default_model = default_model

    def chat_completion(
        self,
        messages,
        model=None,
        temperature=0.7,
        max_tokens=None,
        stream=False,
        tools=None,
        tool_choice=None,
        response_format=None,
    ):
        resolved_model = model or self.default_model
        if "personal-fail" in self.base_url:
            return {
                "content": None,
                "model": resolved_model,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "finish_reason": None,
                "response_time_ms": 12,
                "status": "error",
                "error_message": "personal provider failed",
                "estimated_cost": 0.0,
                "provider_used": "fake",
                "request_type": "chat",
                "api_mode_used": "chat_only",
                "fallback_used": False,
                "tool_calls": None,
            }
        return {
            "content": "ok",
            "model": resolved_model,
            "prompt_tokens": 10,
            "completion_tokens": 20,
            "total_tokens": 30,
            "finish_reason": "stop",
            "response_time_ms": 25,
            "status": "success",
            "error_message": None,
            "estimated_cost": 0.25,
            "provider_used": "fake",
            "request_type": "chat",
            "api_mode_used": "chat_only",
            "fallback_used": False,
            "tool_calls": None,
        }


@pytest.fixture
def user(db):
    return get_user_model().objects.create_user(
        username="quota-user",
        password="testpass123",
        email="quota-user@example.com",
    )


def _create_provider(*, name, scope, base_url, owner_user=None, priority=1):
    return AIProviderConfig.objects.create(
        name=name,
        scope=scope,
        owner_user=owner_user,
        provider_type="openai",
        is_active=True,
        priority=priority,
        base_url=base_url,
        api_key="sk-test",
        default_model="gpt-4o-mini",
    )


@pytest.mark.django_db
def test_personal_provider_is_chosen_before_system(monkeypatch, user):
    monkeypatch.setattr("apps.ai_provider.infrastructure.client_factory.OpenAICompatibleAdapter", _FakeAdapter)
    personal = _create_provider(
        name="personal-main",
        scope="user",
        owner_user=user,
        base_url="https://personal-success.example.invalid/v1",
        priority=1,
    )
    _create_provider(
        name="system-main",
        scope="system",
        base_url="https://system-success.example.invalid/v1",
        priority=10,
    )
    AIUserFallbackQuota.objects.create(user=user, daily_limit=10, monthly_limit=100, is_active=True)

    result = AIClientFactory().get_client(user=user).chat_completion(
        messages=[{"role": "user", "content": "hello"}],
    )

    assert result["status"] == "success"
    assert result["provider_used"] == personal.name
    assert result["provider_scope"] == "personal"
    assert result["quota_charged"] is False
    log = AIUsageLog.objects.latest("id")
    assert log.provider_id == personal.id
    assert log.provider_scope == "personal"
    assert log.quota_charged is False


@pytest.mark.django_db
def test_personal_failure_falls_back_to_system_when_quota_allows(monkeypatch, user):
    monkeypatch.setattr("apps.ai_provider.infrastructure.client_factory.OpenAICompatibleAdapter", _FakeAdapter)
    _create_provider(
        name="personal-main",
        scope="user",
        owner_user=user,
        base_url="https://personal-fail.example.invalid/v1",
        priority=1,
    )
    system = _create_provider(
        name="system-main",
        scope="system",
        base_url="https://system-success.example.invalid/v1",
        priority=10,
    )
    AIUserFallbackQuota.objects.create(user=user, daily_limit=10, monthly_limit=100, is_active=True)

    result = AIClientFactory().get_client(user=user).chat_completion(
        messages=[{"role": "user", "content": "hello"}],
    )

    assert result["status"] == "success"
    assert result["provider_used"] == system.name
    assert result["provider_scope"] == "system_fallback"
    assert result["quota_charged"] is True
    success_log = AIUsageLog.objects.filter(status="success").latest("id")
    assert success_log.provider_id == system.id
    assert success_log.provider_scope == "system_fallback"
    assert success_log.quota_charged is True


@pytest.mark.django_db
def test_exhausted_quota_blocks_system_fallback(monkeypatch, user):
    monkeypatch.setattr("apps.ai_provider.infrastructure.client_factory.OpenAICompatibleAdapter", _FakeAdapter)
    personal = _create_provider(
        name="personal-main",
        scope="user",
        owner_user=user,
        base_url="https://personal-fail.example.invalid/v1",
        priority=1,
    )
    system = _create_provider(
        name="system-main",
        scope="system",
        base_url="https://system-success.example.invalid/v1",
        priority=10,
    )
    AIUserFallbackQuota.objects.create(user=user, daily_limit=1, monthly_limit=100, is_active=True)
    AIUsageLog.objects.create(
        provider=system,
        user=user,
        provider_scope="system_fallback",
        quota_charged=True,
        model="gpt-4o-mini",
        request_type="chat",
        prompt_tokens=10,
        completion_tokens=20,
        total_tokens=30,
        estimated_cost=1,
        response_time_ms=25,
        status="success",
        error_message="",
        request_metadata={},
    )

    result = AIClientFactory().get_client(user=user).chat_completion(
        messages=[{"role": "user", "content": "hello"}],
    )

    assert result["status"] == "error"
    assert "quota exhausted" in result["error_message"].lower()
    assert AIUsageLog.objects.filter(provider=system, status="success").count() == 1
    assert AIUsageLog.objects.filter(provider=personal).count() == 1


@pytest.mark.django_db
def test_personal_success_does_not_consume_fallback_quota(monkeypatch, user):
    monkeypatch.setattr("apps.ai_provider.infrastructure.client_factory.OpenAICompatibleAdapter", _FakeAdapter)
    _create_provider(
        name="personal-main",
        scope="user",
        owner_user=user,
        base_url="https://personal-success.example.invalid/v1",
        priority=1,
    )
    AIUserFallbackQuota.objects.create(user=user, daily_limit=10, monthly_limit=100, is_active=True)

    AIClientFactory().get_client(user=user).chat_completion(
        messages=[{"role": "user", "content": "hello"}],
    )

    usage_repo = AIUsageRepository()
    assert usage_repo.get_user_fallback_daily_spend(user, AIUsageLog.objects.latest("id").created_at.date()) == 0.0
