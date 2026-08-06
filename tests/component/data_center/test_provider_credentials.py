"""Provider credential owner and migration contract tests."""

from __future__ import annotations

import pytest
from django.contrib.admin import AdminSite
from django.core.management import call_command
from django.test import RequestFactory, override_settings

from apps.data_center.domain.entities import ProviderConfig
from apps.data_center.infrastructure.models import ProviderConfigModel
from apps.data_center.infrastructure.provider_credential_models import ProviderCredentialModel
from apps.data_center.infrastructure.provider_credentials import (
    ProviderCredentialEncryptionUnavailable,
    ProviderCredentialStore,
)
from apps.data_center.infrastructure.provider_state_repositories import ProviderConfigRepository
from apps.data_center.interface.admin import ProviderConfigAdmin, ProviderConfigAdminForm


def _provider_config(*, provider_id: int | None = None, api_key: str = "") -> ProviderConfig:
    return ProviderConfig(
        id=provider_id,
        name="provider-secret-test",
        source_type="tushare",
        is_active=True,
        priority=10,
        api_key=api_key,
        api_secret="secret-value" if api_key else "",
        http_url="https://proxy.example.test",
        api_endpoint="",
        extra_config={},
        description="",
    )


@pytest.mark.django_db
@override_settings(AGOMTRADEPRO_ENCRYPTION_KEY="provider-credential-test-key")
def test_repository_writes_credentials_only_to_encrypted_owner() -> None:
    saved = ProviderConfigRepository().save(_provider_config(api_key="token-value"))

    model = ProviderConfigModel.objects.get(pk=saved.id)
    credential = ProviderCredentialModel.objects.get(provider_id=saved.id)
    assert model.api_key == ""
    assert model.api_secret == ""
    assert credential.api_key_encrypted.startswith("encrypted:v1:")
    assert credential.api_secret_encrypted.startswith("encrypted:v1:")
    assert saved.credential_ref == credential.credential_ref

    loaded = ProviderConfigRepository().get_by_id(int(saved.id))
    assert loaded is not None
    assert loaded.api_key == "token-value"
    assert loaded.api_secret == "secret-value"


@pytest.mark.django_db
@override_settings(AGOMTRADEPRO_ENCRYPTION_KEY="provider-credential-test-key")
def test_legacy_plaintext_is_explicitly_migrated_and_cleared() -> None:
    legacy = ProviderConfigModel.objects.create(
        name="legacy-provider-secret-test",
        source_type="tushare",
        api_key="legacy-token",
        api_secret="legacy-secret",
    )

    loaded = ProviderConfigRepository().get_by_id(int(legacy.pk))
    assert loaded is not None
    assert loaded.api_key == "legacy-token"
    assert loaded.credential_ref == f"data_center.provider.{legacy.pk}.credentials"

    call_command("encrypt_provider_credentials")
    legacy.refresh_from_db()
    assert legacy.api_key == ""
    assert legacy.api_secret == ""
    assert ProviderCredentialModel.objects.filter(provider_id=legacy.pk).exists()


@pytest.mark.django_db
@override_settings(AGOMTRADEPRO_ENCRYPTION_KEY="")
def test_new_credential_write_fails_closed_without_encryption_key() -> None:
    with pytest.raises(ProviderCredentialEncryptionUnavailable):
        ProviderConfigRepository().save(_provider_config(api_key="new-token"))


@pytest.mark.django_db
def test_metadata_update_does_not_delete_encrypted_credentials_without_key() -> None:
    with override_settings(AGOMTRADEPRO_ENCRYPTION_KEY="provider-credential-test-key"):
        saved = ProviderConfigRepository().save(_provider_config(api_key="token-value"))

    with override_settings(AGOMTRADEPRO_ENCRYPTION_KEY=""):
        ProviderConfigRepository().save(_provider_config(provider_id=int(saved.id), api_key=""))

    assert ProviderCredentialModel.objects.filter(provider_id=saved.id).exists()


@pytest.mark.django_db
@override_settings(AGOMTRADEPRO_ENCRYPTION_KEY="provider-credential-test-key")
def test_provider_credential_status_never_returns_secret_values() -> None:
    provider = ProviderConfigModel.objects.create(
        name="status-provider-secret-test",
        source_type="tushare",
        api_key="legacy-token",
    )

    status = ProviderCredentialStore().status(provider)
    assert status.has_api_key is True
    assert status.credential_ref.endswith(f".{provider.pk}.credentials")
    assert "legacy-token" not in str(status)


@pytest.mark.django_db
@override_settings(AGOMTRADEPRO_ENCRYPTION_KEY="provider-credential-test-key")
def test_admin_save_model_uses_application_credential_port() -> None:
    form = ProviderConfigAdminForm(
        data={
            "name": "admin-provider-secret-test",
            "source_type": "tushare",
            "is_active": "on",
            "priority": "10",
            "api_key": "admin-token",
            "api_secret": "admin-secret",
            "http_url": "",
            "tushare_request_mode": "sdk_path",
            "api_endpoint": "",
            "extra_config": "{}",
            "description": "",
        }
    )
    assert form.is_valid(), form.errors
    obj = form.save(commit=False)
    request = RequestFactory().post("/admin/data-center/providers/")
    ProviderConfigAdmin(ProviderConfigModel, AdminSite()).save_model(request, obj, form, False)

    stored = ProviderConfigModel.objects.get(pk=obj.pk)
    assert stored.api_key == ""
    assert stored.api_secret == ""
    assert ProviderCredentialModel.objects.get(provider_id=obj.pk).api_key_encrypted
