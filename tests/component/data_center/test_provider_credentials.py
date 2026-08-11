"""Config Center-owned Data Center provider credential tests."""

from __future__ import annotations

import pytest
from django.contrib.admin import AdminSite
from django.test import RequestFactory, override_settings

from apps.config_center.application.repository_provider import (
    get_config_center_secret_repository,
)
from apps.config_center.models import ConfigCenterSecretModel
from apps.data_center.domain.entities import ProviderConfig
from apps.data_center.infrastructure.models import ProviderConfigModel
from apps.data_center.infrastructure.provider_credentials import (
    ProviderCredentialEncryptionUnavailable,
    ProviderCredentialStore,
    api_key_ref_for_provider,
    api_secret_ref_for_provider,
    credential_ref_for_provider,
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
def test_repository_writes_credentials_only_to_config_center_owner() -> None:
    saved = ProviderConfigRepository().save(_provider_config(api_key="token-value"))

    model = ProviderConfigModel.objects.get(pk=saved.id)
    assert "api_key" not in {field.name for field in model._meta.fields}
    assert "api_secret" not in {field.name for field in model._meta.fields}
    key_row = ConfigCenterSecretModel._default_manager.get(
        secret_ref=api_key_ref_for_provider(int(saved.id))
    )
    secret_row = ConfigCenterSecretModel._default_manager.get(
        secret_ref=api_secret_ref_for_provider(int(saved.id))
    )
    assert key_row.encrypted_value.startswith("encrypted:v1:")
    assert secret_row.encrypted_value.startswith("encrypted:v1:")
    assert saved.credential_ref == credential_ref_for_provider(int(saved.id))

    loaded = ProviderConfigRepository().get_by_id(int(saved.id))
    assert loaded is not None
    assert loaded.api_key == "token-value"
    assert loaded.api_secret == "secret-value"


@pytest.mark.django_db
@override_settings(AGOMTRADEPRO_ENCRYPTION_KEY="")
def test_new_credential_write_fails_closed_without_encryption_key(monkeypatch) -> None:
    monkeypatch.setattr(get_config_center_secret_repository(), "_crypto", None)
    with pytest.raises(ProviderCredentialEncryptionUnavailable):
        ProviderConfigRepository().save(_provider_config(api_key="new-token"))
    assert ProviderConfigModel._default_manager.count() == 0
    assert ConfigCenterSecretModel._default_manager.count() == 0


@pytest.mark.django_db
def test_metadata_update_does_not_delete_config_center_credentials_without_key() -> None:
    with override_settings(AGOMTRADEPRO_ENCRYPTION_KEY="provider-credential-test-key"):
        saved = ProviderConfigRepository().save(_provider_config(api_key="token-value"))

    with override_settings(AGOMTRADEPRO_ENCRYPTION_KEY=""):
        ProviderConfigRepository().save(_provider_config(provider_id=int(saved.id), api_key=""))

    assert ConfigCenterSecretModel._default_manager.filter(
        secret_ref=api_key_ref_for_provider(int(saved.id))
    ).exists()


@pytest.mark.django_db
@override_settings(AGOMTRADEPRO_ENCRYPTION_KEY="provider-credential-test-key")
def test_provider_credential_status_never_returns_secret_values() -> None:
    provider = ProviderConfigModel.objects.create(
        name="status-provider-secret-test",
        source_type="tushare",
    )
    ProviderCredentialStore().persist(provider, api_key="secret-token", api_secret=None)

    status = ProviderCredentialStore().status(provider)
    assert status.has_api_key is True
    assert status.credential_ref == credential_ref_for_provider(int(provider.pk))
    assert "secret-token" not in str(status)


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

    assert ConfigCenterSecretModel._default_manager.filter(
        secret_ref=api_key_ref_for_provider(int(obj.pk))
    ).exists()
    assert ConfigCenterSecretModel._default_manager.filter(
        secret_ref=api_secret_ref_for_provider(int(obj.pk))
    ).exists()
