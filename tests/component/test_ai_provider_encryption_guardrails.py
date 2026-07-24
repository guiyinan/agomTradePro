import pytest

from apps.ai_provider.infrastructure.models import AIProviderConfig
from apps.ai_provider.infrastructure.repositories import AIProviderRepository
from apps.ai_provider.interface.serializers import AIProviderConfigSerializer
from shared.infrastructure.crypto import FieldEncryptionService


@pytest.mark.django_db
def test_repository_rejects_api_key_write_without_encryption_key(settings):
    settings.AGOMTRADEPRO_ENCRYPTION_KEY = ""
    repo = AIProviderRepository()

    with pytest.raises(ValueError, match="AGOMTRADEPRO_ENCRYPTION_KEY"):
        repo.create(
            name="guardrail-no-key",
            provider_type="custom",
            base_url="https://example.invalid/v1",
            api_key="sk-plain-should-not-write",
            default_model="gpt-4o-mini",
            api_mode="dual",
            fallback_enabled=True,
        )


@pytest.mark.django_db
def test_serializer_masks_only_last_four_characters(settings):
    key = FieldEncryptionService.generate_key()
    settings.AGOMTRADEPRO_ENCRYPTION_KEY = key
    repo = AIProviderRepository()

    provider = repo.create(
        name="guardrail-mask",
        provider_type="custom",
        base_url="https://example.invalid/v1",
        api_key="sk-abcdefghijklmn1234",
        default_model="gpt-4o-mini",
        api_mode="dual",
        fallback_enabled=True,
    )

    data = AIProviderConfigSerializer(provider).data
    assert data["api_key"] == "****1234"


@pytest.mark.django_db
def test_repository_returns_empty_for_invalid_encrypted_api_key(settings):
    settings.AGOMTRADEPRO_ENCRYPTION_KEY = FieldEncryptionService.generate_key()
    repo = AIProviderRepository()
    wrong_service = FieldEncryptionService(FieldEncryptionService.generate_key())

    provider = AIProviderConfig.objects.create(
        name="guardrail-invalid-encrypted",
        provider_type="custom",
        base_url="https://example.invalid/v1",
        api_key="",
        api_key_encrypted=wrong_service.encrypt("sk-invalid-for-current-key"),
        default_model="gpt-4o-mini",
        api_mode="dual",
        fallback_enabled=True,
    )

    assert repo.get_api_key(provider) == ""


@pytest.mark.django_db
def test_repository_filters_out_unusable_active_system_providers(settings):
    settings.AGOMTRADEPRO_ENCRYPTION_KEY = FieldEncryptionService.generate_key()
    repo = AIProviderRepository()
    wrong_service = FieldEncryptionService(FieldEncryptionService.generate_key())

    AIProviderConfig.objects.create(
        name="guardrail-invalid-system-provider",
        provider_type="custom",
        base_url="https://invalid.example.invalid/v1",
        api_key="",
        api_key_encrypted=wrong_service.encrypt("sk-invalid-for-current-key"),
        default_model="gpt-4o-mini",
        api_mode="dual",
        fallback_enabled=True,
        is_active=True,
        priority=1,
    )
    valid = repo.create(
        name="guardrail-valid-system-provider",
        provider_type="custom",
        base_url="https://valid.example.invalid/v1",
        api_key="sk-valid",
        default_model="gpt-4o-mini",
        api_mode="dual",
        fallback_enabled=True,
        is_active=True,
        priority=2,
    )

    providers = repo.get_active_configured_system_providers()

    assert [provider.id for provider in providers] == [valid.id]
