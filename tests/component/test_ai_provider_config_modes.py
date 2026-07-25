import pytest
from django.contrib.auth import get_user_model

from apps.ai_provider.application.use_cases import (
    CreateProviderUseCase,
    UpdateProviderUseCase,
)
from apps.ai_provider.application.use_cases import (
    TestProviderConnectionUseCase as ProviderConnectionUseCase,
)
from apps.ai_provider.infrastructure.models import AIProviderConfig
from apps.ai_provider.interface.serializers import AIProviderConfigCreateSerializer


@pytest.mark.django_db
def test_ai_provider_config_mode_defaults():
    provider = AIProviderConfig.objects.create(
        name="openai-defaults",
        provider_type="openai",
        is_active=True,
        priority=10,
        base_url="https://api.openai.com/v1",
        api_key="sk-test",
        default_model="gpt-4o-mini",
    )

    assert provider.api_mode == "dual"
    assert provider.fallback_enabled is True


@pytest.mark.django_db
def test_create_provider_use_case_validates_api_mode():
    use_case = CreateProviderUseCase()

    with pytest.raises(ValueError):
        use_case.execute(
            name="bad-mode",
            provider_type="openai",
            base_url="https://api.openai.com/v1",
            api_key="sk-test",
            default_model="gpt-4o-mini",
            api_mode="invalid_mode",
        )


@pytest.mark.django_db
def test_update_provider_use_case_validates_api_mode():
    provider = AIProviderConfig.objects.create(
        name="openai-update-mode",
        provider_type="openai",
        is_active=True,
        priority=10,
        base_url="https://api.openai.com/v1",
        api_key="sk-test",
        default_model="gpt-4o-mini",
    )
    use_case = UpdateProviderUseCase()

    with pytest.raises(ValueError):
        use_case.execute(provider.id, api_mode="invalid_mode")


@pytest.mark.django_db
def test_ai_provider_create_serializer_accepts_new_fields():
    serializer = AIProviderConfigCreateSerializer(
        data={
            "name": "openai-dual",
            "provider_type": "openai",
            "is_active": True,
            "priority": 5,
            "base_url": "https://api.openai.com/v1",
            "api_key": "sk-test",
            "default_model": "gpt-4o-mini",
            "api_mode": "responses_only",
            "fallback_enabled": False,
            "extra_config": {"timeout": 30},
            "description": "test",
        }
    )

    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["api_mode"] == "responses_only"
    assert serializer.validated_data["fallback_enabled"] is False


@pytest.mark.django_db
def test_system_management_scope_cannot_mutate_personal_provider():
    owner = get_user_model().objects.create_user(username="personal-owner")
    provider = AIProviderConfig.objects.create(
        name="personal-only",
        scope="user",
        owner_user=owner,
        provider_type="openai",
        is_active=True,
        priority=10,
        base_url="https://personal.example.invalid/v1",
        api_key="sk-test",
        default_model="gpt-4o-mini",
    )

    with pytest.raises(ValueError, match="not found"):
        UpdateProviderUseCase().execute(provider.id, name="admin-cross-scope")

    provider.refresh_from_db()
    assert provider.name == "personal-only"


@pytest.mark.django_db
def test_personal_management_scope_cannot_access_system_provider(monkeypatch):
    user = get_user_model().objects.create_user(username="personal-caller")
    provider = AIProviderConfig.objects.create(
        name="system-only",
        scope="system",
        provider_type="openai",
        is_active=True,
        priority=10,
        base_url="https://system.example.invalid/v1",
        api_key="sk-test",
        default_model="gpt-4o-mini",
    )
    builder_called = False

    def _unexpected_builder(**kwargs):
        nonlocal builder_called
        builder_called = True
        raise AssertionError("connection adapter must not be built across scopes")

    monkeypatch.setattr(
        "apps.ai_provider.application.use_cases.build_openai_compatible_adapter",
        _unexpected_builder,
    )

    with pytest.raises(ValueError, match="not found"):
        ProviderConnectionUseCase().execute(provider.id, actor_user=user)

    assert builder_called is False
