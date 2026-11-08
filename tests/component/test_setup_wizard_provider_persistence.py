"""Setup-wizard credential persistence and provider-readiness contracts."""

import pytest

from apps.ai_provider.infrastructure.models import AIProviderConfig
from apps.ai_provider.infrastructure.repositories import AIProviderRepository
from apps.setup_wizard.application.use_cases import SetupAIProviderUseCase
from apps.setup_wizard.domain.entities import AIProviderConfigDTO
from apps.setup_wizard.infrastructure.repositories import (
    AIProviderRepository as SetupAIProviderRepository,
)
from shared.infrastructure.crypto import FieldEncryptionService


@pytest.mark.django_db
def test_setup_wizard_persists_encrypted_key_and_keeps_readiness_available(settings) -> None:
    settings.AGOMTRADEPRO_ENCRYPTION_KEY = FieldEncryptionService.generate_key()
    plaintext = "sk-ref06-setup-wizard-credential"
    config = AIProviderConfigDTO(
        name="ref06-setup-wizard-provider",
        provider_type="openai",
        base_url="https://example.invalid/v1",
        api_key=plaintext,
        default_model="gpt-4o-mini",
    )

    result = SetupAIProviderUseCase().execute(config)

    assert result.success is True
    provider = AIProviderConfig.objects.get(name=config.name)
    assert "api_key" not in {field.name for field in AIProviderConfig._meta.local_concrete_fields}
    assert provider.api_key_encrypted.startswith(FieldEncryptionService.PREFIX)
    assert AIProviderRepository().get_api_key(provider) == plaintext
    assert SetupAIProviderRepository().has_active_provider() is True
