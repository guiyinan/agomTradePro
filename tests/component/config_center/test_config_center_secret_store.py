from __future__ import annotations

import pytest
from django.test import override_settings

from apps.config_center.infrastructure.secret_store import (
    ConfigCenterSecretStore,
    ConfigCenterSecretUnavailable,
)
from apps.config_center.models import ConfigCenterSecretModel


@pytest.mark.django_db(transaction=True)
@override_settings(AGOMTRADEPRO_ENCRYPTION_KEY="config-center-test-key")
def test_config_center_secret_store_encrypts_and_resolves_without_plaintext_row() -> None:
    store = ConfigCenterSecretStore()
    secret_ref = "config_center.backup.archive_password"

    status = store.persist(secret_ref, "archive-secret")

    record = ConfigCenterSecretModel._default_manager.get(secret_ref=secret_ref)
    assert status.present is True
    assert record.encrypted_value
    assert "archive-secret" not in record.encrypted_value
    assert store.resolve(secret_ref) == "archive-secret"

    cleared = store.persist(secret_ref, "")
    assert cleared.present is False
    assert not ConfigCenterSecretModel._default_manager.filter(secret_ref=secret_ref).exists()


@pytest.mark.django_db(transaction=True)
@override_settings(AGOMTRADEPRO_ENCRYPTION_KEY="")
def test_config_center_secret_store_fails_closed_for_new_secret_without_key() -> None:
    with pytest.raises(ConfigCenterSecretUnavailable):
        ConfigCenterSecretStore().persist(
            "config_center.backup.smtp_password",
            "smtp-secret",
        )
