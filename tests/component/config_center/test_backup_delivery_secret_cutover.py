from __future__ import annotations

import pytest
from django.test import override_settings

from apps.account.infrastructure.backup_delivery_projection import (
    get_backup_delivery_settings,
)
from apps.config_center.application.public import (
    get_backup_delivery_runtime_payload,
    update_backup_delivery_settings,
)
from apps.config_center.domain.backup_delivery import (
    BACKUP_ARCHIVE_PASSWORD_SECRET_REF,
    BACKUP_SMTP_PASSWORD_SECRET_REF,
)
from apps.config_center.models import ConfigCenterSecretModel


@pytest.mark.django_db(transaction=True)
@override_settings(AGOMTRADEPRO_ENCRYPTION_KEY="backup-cutover-test-key")
def test_backup_policy_update_uses_config_center_secret_owner() -> None:
    update_backup_delivery_settings(
        {
            "backup_enabled": False,
            "backup_archive_password": "archive-secret",
            "backup_smtp_password": "smtp-secret",
        },
        actor="component-test",
    )

    payload = get_backup_delivery_runtime_payload()
    assert payload["backup_archive_password_ref"] == BACKUP_ARCHIVE_PASSWORD_SECRET_REF
    assert payload["backup_smtp_password_ref"] == BACKUP_SMTP_PASSWORD_SECRET_REF
    assert payload["policy_source"] == "config_center_runtime_profile"
    rows = list(ConfigCenterSecretModel._default_manager.values("secret_ref", "encrypted_value"))
    assert {str(row["secret_ref"]) for row in rows} >= {
        BACKUP_ARCHIVE_PASSWORD_SECRET_REF,
        BACKUP_SMTP_PASSWORD_SECRET_REF,
    }
    assert all(
        "archive-secret" not in str(row["encrypted_value"])
        and "smtp-secret" not in str(row["encrypted_value"])
        for row in rows
    )
    projected = get_backup_delivery_settings()
    assert projected.get_backup_password() == "archive-secret"
    assert projected.get_backup_smtp_password() == "smtp-secret"
