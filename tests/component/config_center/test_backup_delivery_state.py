from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from apps.config_center.domain.backup_delivery import BackupDeliveryState
from apps.config_center.infrastructure.models import SystemSettingsModel
from apps.config_center.infrastructure.repositories import ConfigCenterSettingsRepository
from apps.config_center.models import BackupDeliveryStateModel


@pytest.mark.django_db(transaction=True)
def test_backup_state_writes_new_owner_only() -> None:
    settings_obj = SystemSettingsModel.get_settings()
    legacy_expiry = datetime.now(UTC) + timedelta(days=9)
    settings_obj.backup_download_token_digest = "legacy-digest"
    settings_obj.backup_download_token_expires_at = legacy_expiry
    settings_obj.save(
        update_fields=[
            "backup_download_token_digest",
            "backup_download_token_expires_at",
            "updated_at",
        ]
    )

    repository = ConfigCenterSettingsRepository()
    next_expiry = datetime.now(UTC) + timedelta(days=2)
    repository.set_backup_delivery_state(
        BackupDeliveryState(
            last_sent_at=datetime.now(UTC),
            download_token_digest="typed-digest",
            download_token_expires_at=next_expiry,
        )
    )

    state = BackupDeliveryStateModel._default_manager.get(pk=1)
    settings_obj.refresh_from_db()
    assert state.download_token_digest == "typed-digest"
    assert settings_obj.backup_download_token_digest == "legacy-digest"
    assert repository.get_backup_delivery_state().download_token_digest == "typed-digest"


@pytest.mark.django_db(transaction=True)
def test_backup_state_does_not_fall_back_to_legacy_before_first_write() -> None:
    settings_obj = SystemSettingsModel.get_settings()
    settings_obj.backup_download_token_digest = "legacy-digest"
    settings_obj.save(update_fields=["backup_download_token_digest", "updated_at"])

    state = ConfigCenterSettingsRepository().get_backup_delivery_state()

    assert state.download_token_digest == ""
    assert not BackupDeliveryStateModel._default_manager.filter(pk=1).exists()
