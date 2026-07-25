import pytest
from django.contrib.auth import get_user_model

from apps.ai_provider.infrastructure.client_factory import AIClientFactory
from apps.ai_provider.infrastructure.models import AIProviderConfig, AIUsageLog, AIUserFallbackQuota
from apps.ai_provider.infrastructure.repositories import AIUsageRepository
from shared.infrastructure.crypto import FieldEncryptionService


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
        self.api_key = api_key
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
    monkeypatch.setattr(
        "apps.ai_provider.infrastructure.client_factory.OpenAICompatibleAdapter", _FakeAdapter
    )
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

    result = (
        AIClientFactory()
        .get_client(user=user)
        .chat_completion(
            messages=[{"role": "user", "content": "hello"}],
        )
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
    monkeypatch.setattr(
        "apps.ai_provider.infrastructure.client_factory.OpenAICompatibleAdapter", _FakeAdapter
    )
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

    result = (
        AIClientFactory()
        .get_client(user=user)
        .chat_completion(
            messages=[{"role": "user", "content": "hello"}],
        )
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
def test_adapter_exception_is_logged_and_next_provider_takes_over(monkeypatch, user, caplog):
    class _RaisingAdapter(_FakeAdapter):
        def chat_completion(self, *args, **kwargs):
            if "personal-raises" in self.base_url:
                raise TimeoutError("credential-bearing upstream detail")
            return super().chat_completion(*args, **kwargs)

    monkeypatch.setattr(
        "apps.ai_provider.infrastructure.client_factory.OpenAICompatibleAdapter",
        _RaisingAdapter,
    )
    personal = _create_provider(
        name="personal-raising",
        scope="user",
        owner_user=user,
        base_url="https://personal-raises.example.invalid/v1",
        priority=1,
    )
    system = _create_provider(
        name="system-main",
        scope="system",
        base_url="https://system-success.example.invalid/v1",
        priority=10,
    )
    AIUserFallbackQuota.objects.create(user=user, daily_limit=10, monthly_limit=100, is_active=True)

    result = (
        AIClientFactory()
        .get_client(user=user)
        .chat_completion(
            messages=[{"role": "user", "content": "hello"}],
        )
    )

    assert result["status"] == "success"
    assert result["provider_used"] == system.name
    failed_log = AIUsageLog.objects.get(provider=personal)
    assert failed_log.status == "error"
    assert "TimeoutError" in failed_log.error_message
    assert "credential-bearing upstream detail" not in failed_log.error_message
    assert "credential-bearing upstream detail" not in caplog.text


@pytest.mark.django_db
def test_cached_scoped_client_rebuilds_adapter_after_provider_rotation(monkeypatch):
    observed_connections = []

    class _ObservedAdapter(_FakeAdapter):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            observed_connections.append((self.base_url, self.api_key))

    monkeypatch.setattr(
        "apps.ai_provider.infrastructure.client_factory.OpenAICompatibleAdapter",
        _ObservedAdapter,
    )
    provider = _create_provider(
        name="system-main",
        scope="system",
        base_url="https://system-old.example.invalid/v1",
    )
    client = AIClientFactory().get_client()

    first = client.chat_completion(messages=[{"role": "user", "content": "first"}])
    AIProviderConfig.objects.filter(pk=provider.pk).update(
        base_url="https://system-new.example.invalid/v1",
        api_key="sk-rotated",
        api_key_encrypted="",
    )
    second = client.chat_completion(messages=[{"role": "user", "content": "second"}])

    assert first["status"] == second["status"] == "success"
    assert observed_connections == [
        ("https://system-old.example.invalid/v1", "sk-test"),
        ("https://system-new.example.invalid/v1", "sk-rotated"),
    ]


@pytest.mark.django_db
def test_invalid_explicit_user_id_does_not_fall_through_to_system_provider():
    _create_provider(
        name="system-main",
        scope="system",
        base_url="https://system-success.example.invalid/v1",
    )

    with pytest.raises(ValueError, match="Unknown user reference"):
        AIClientFactory().get_client(user=999999999)


@pytest.mark.django_db
def test_personal_provider_budget_is_enforced_before_system_fallback(monkeypatch, user):
    monkeypatch.setattr(
        "apps.ai_provider.infrastructure.client_factory.OpenAICompatibleAdapter",
        _FakeAdapter,
    )
    personal = _create_provider(
        name="personal-main",
        scope="user",
        owner_user=user,
        base_url="https://personal-success.example.invalid/v1",
    )
    personal.daily_budget_limit = 0
    personal.save(update_fields=["daily_budget_limit"])
    system = _create_provider(
        name="system-main",
        scope="system",
        base_url="https://system-success.example.invalid/v1",
        priority=10,
    )
    AIUserFallbackQuota.objects.create(user=user, daily_limit=10, monthly_limit=100, is_active=True)

    result = (
        AIClientFactory()
        .get_client(user=user)
        .chat_completion(
            messages=[{"role": "user", "content": "hello"}],
        )
    )

    assert result["status"] == "success"
    assert result["provider_used"] == system.name
    assert not AIUsageLog.objects.filter(provider=personal).exists()


@pytest.mark.django_db
def test_exhausted_quota_blocks_system_fallback(monkeypatch, user):
    monkeypatch.setattr(
        "apps.ai_provider.infrastructure.client_factory.OpenAICompatibleAdapter", _FakeAdapter
    )
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

    result = (
        AIClientFactory()
        .get_client(user=user)
        .chat_completion(
            messages=[{"role": "user", "content": "hello"}],
        )
    )

    assert result["status"] == "error"
    assert "quota exhausted" in result["error_message"].lower()
    assert AIUsageLog.objects.filter(provider=system, status="success").count() == 1
    assert AIUsageLog.objects.filter(provider=personal).count() == 1


@pytest.mark.django_db
def test_personal_success_does_not_consume_fallback_quota(monkeypatch, user):
    monkeypatch.setattr(
        "apps.ai_provider.infrastructure.client_factory.OpenAICompatibleAdapter", _FakeAdapter
    )
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
    assert (
        usage_repo.get_user_fallback_daily_spend(
            user, AIUsageLog.objects.latest("id").created_at.date()
        )
        == 0.0
    )


@pytest.mark.django_db
def test_system_routing_skips_provider_with_unusable_credentials(monkeypatch, settings):
    class _StrictAdapter(_FakeAdapter):
        def __init__(self, *, api_key, **kwargs):
            if not api_key:
                raise AssertionError(
                    "adapter should not be built for provider without usable credentials"
                )
            super().__init__(api_key=api_key, **kwargs)

    settings.AGOMTRADEPRO_ENCRYPTION_KEY = FieldEncryptionService.generate_key()
    wrong_service = FieldEncryptionService(FieldEncryptionService.generate_key())
    monkeypatch.setattr(
        "apps.ai_provider.infrastructure.client_factory.OpenAICompatibleAdapter", _StrictAdapter
    )

    AIProviderConfig.objects.create(
        name="system-invalid",
        scope="system",
        provider_type="openai",
        is_active=True,
        priority=1,
        base_url="https://system-invalid.example.invalid/v1",
        api_key="",
        api_key_encrypted=wrong_service.encrypt("sk-invalid-for-current-key"),
        default_model="gpt-4o-mini",
    )
    system = _create_provider(
        name="system-main",
        scope="system",
        base_url="https://system-success.example.invalid/v1",
        priority=10,
    )

    result = (
        AIClientFactory()
        .get_client()
        .chat_completion(
            messages=[{"role": "user", "content": "hello"}],
        )
    )

    assert result["status"] == "success"
    assert result["provider_used"] == system.name
    assert result["provider_scope"] == "system_global"
