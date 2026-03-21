import pytest

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
