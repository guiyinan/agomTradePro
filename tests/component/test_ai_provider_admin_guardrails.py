import pytest
from django.contrib import admin

from apps.ai_provider.infrastructure.repositories import AIProviderRepository
from apps.ai_provider.interface.admin import AIProviderConfigAdmin
from apps.ai_provider.models import AIProviderConfig
from shared.infrastructure.crypto import FieldEncryptionService


def test_provider_admin_does_not_expose_plaintext_api_key_field():
    model_admin = admin.site._registry[AIProviderConfig]
    field_names = {
        field_name for _title, options in model_admin.fieldsets for field_name in options["fields"]
    }

    assert isinstance(model_admin, AIProviderConfigAdmin)
    assert "api_key" not in field_names
    assert "api_key_encrypted" not in field_names
    assert "masked_api_key" in field_names
    assert "masked_api_key" in model_admin.readonly_fields


@pytest.mark.django_db
def test_provider_admin_mask_does_not_disclose_key_suffix(settings):
    settings.AGOMTRADEPRO_ENCRYPTION_KEY = FieldEncryptionService.generate_key()
    provider = AIProviderRepository().create(
        name="admin-mask",
        provider_type="custom",
        base_url="https://example.invalid/v1",
        api_key="sk-sensitive-suffix-1234",
        default_model="gpt-4o-mini",
    )
    model_admin = admin.site._registry[AIProviderConfig]

    masked = model_admin.masked_api_key(provider)

    assert masked == "****"
    assert "1234" not in masked
    provider.refresh_from_db()
    assert provider.api_key == ""
    assert provider.api_key_encrypted
